"""Web 工作台 BFF(Phase D1-D3)。

同源一个进程提供(架构见 docs/phase-d-web-tech.md):

* ``GET /``              — SPA 静态文件(``--static`` 目录,未命中回退 index.html)
* ``GET /api/v1/...``    — 聚合读端点(NovelService.web_* 只读方法)
* ``GET /api/v1/stream/runs/{id}`` — SSE 运行事件流(``?once=1`` 推一拍即断,供测试)
* ``POST /api/v1/actions/{tool}``  — 快写动作透传 ``http_compat.facade_call``,
  与外部 Agent 走完全相同的校验/闸门路径。BFF 自身没有第二条写路径。
* ``POST /api/v1/jobs/{tool}``     — 慢操作(LLM 分钟级)后台作业:线程执行 +
  ``GET /api/v1/jobs/{id}`` 轮询(生成/审校/修订/规划)。
* 多书:端点统一接受 ``?book=<名>``,服务实例按库路径缓存;书库默认 ``story-data/``。

工作台公开访问，无登录或用户权限；模型上下文和正典校验仍由运行时负责。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import auth
from .http_compat import facade_call
from . import runtime

API = '/api/v1'
SSE_POLL_SECONDS = 1.5

# 慢操作工具集（分钟级任务走后台执行，所有用户均可调用）
JOB_TOOLS = frozenset({
    'novel_architecture_generate', 'story_architect_apply', 'chapter_plan_generate', 'chapter_direction_propose', 'chapter_semantic_review',
    'chapter_review_full', 'chapter_auto_revise', 'chapter_auto_revision_loop',
    'chapter_draft_generate',
    'story_architect_interview',
    'novel_run_continue',
})

# 多书:db 路径 → NovelService 实例缓存(默认书仍走 runtime 单例,便于测试注入)
_SERVICE_CACHE: dict[str, object] = {}
_JOBS: dict[str, dict] = {}
_JOB_LOCK = threading.Lock()


def books_dir() -> str:
    return os.environ.get('NOVEL_BOOKS_DIR') or os.path.join(os.getcwd(), 'story-data')


def _safe_book_path(book: str) -> str:
    name = os.path.basename(book.strip())
    if not name.endswith('.db'):
        name += '.db'
    if name in ('.db',):
        raise ValueError('invalid book name')
    return os.path.abspath(os.path.join(books_dir(), name))


def service_for(book: str | None = None):
    """默认书 → runtime 单例(测试可注入);指定书 → 按路径缓存的多书实例。"""
    if not book:
        return runtime.service()
    path = _safe_book_path(book)
    if not os.path.exists(path):
        raise KeyError(f'no such book: {book}')
    svc = _SERVICE_CACHE.get(path)
    if svc is None:
        from .service import NovelService
        svc = NovelService(path)
        _SERVICE_CACHE[path] = svc
    return svc


def create_book(name: str) -> dict:
    from .service import NovelService
    path = _safe_book_path(name)
    if os.path.exists(path):
        raise ValueError(f'book already exists: {os.path.basename(path)}')
    svc = NovelService(path)  # 连接即建库/迁移
    _SERVICE_CACHE[path] = svc
    return {'name': os.path.basename(path), 'path': path}


def list_books() -> list[dict]:
    out = []
    import sqlite3
    from pathlib import Path
    root = os.path.abspath(books_dir())
    default_db = os.path.abspath(os.environ.get('NOVEL_STORY_DB') or './story-data/story.db')
    if not os.path.isdir(root):
        return out
    for fn in sorted(os.listdir(root)):
        if not fn.endswith('.db') or fn.endswith(('-wal', '-shm')):
            continue
        path = os.path.join(root, fn)
        # A copied WAL database may lack its shared-memory sidecar. SQLite cannot
        # always initialize it via mode=ro. Fall back to an existing-file-only
        # connection with SQL writes disabled; never use immutable=1 (loses WAL).
        for mode in ('ro', 'rw'):
            db = None
            try:
                db = sqlite3.connect(Path(path).as_uri() + '?mode=' + mode, uri=True)
                db.execute('PRAGMA query_only=ON')
                db.row_factory = sqlite3.Row
                title = None
                try:
                    r = db.execute('SELECT payload_json FROM planning_blueprint WHERE id=1').fetchone()
                    if r:
                        title = (json.loads(r['payload_json'] or '{}') or {}).get('title')
                except (sqlite3.Error, ValueError):
                    pass
                if not title:
                    try:
                        row = db.execute("SELECT value FROM meta WHERE key='title'").fetchone()
                        title = row[0] if row else None
                    except sqlite3.Error:
                        pass
                cnt = db.execute('SELECT COUNT(*) c, COALESCE(SUM(LENGTH(body)),0) s FROM chapters').fetchone()
                out.append({'name': fn, 'title': title or fn[:-3], 'chapters': cnt['c'],
                            'chars': cnt['s'], 'default': path == default_db,
                            'updated_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))})
                break
            except (sqlite3.Error, OSError):
                continue
            finally:
                if db is not None:
                    db.close()
    return out


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    static_root: str | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = 'NarrativeWeb/0.2'

    def log_message(self, fmt, *args):
        pass  # 本地工具,静默访问日志;错误仍会经 send_error 呈现

    # ---- 基础设施 ----

    def _json(self, status: int, out: dict, headers: dict | None = None) -> None:
        data = json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass  # Switching books intentionally cancels in-flight requests.

    def _read_json(self) -> dict:
        n = int(self.headers.get('Content-Length', '0'))
        raw = self.rfile.read(n) if n else b'{}'
        value = json.loads(raw.decode('utf-8'))
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError('request body must be a JSON object')
        return value

    def _role(self):
        return 'admin', 0

    def _require_role(self, endpoint: str):
        # Compatibility helper for existing route handlers; the workspace is public.
        return 'admin'

    def _q(self, parsed, key, default=None):
        q = parse_qs(parsed.query, keep_blank_values=True)
        return q[key][0] if q.get(key) else default

    def _svc(self, parsed):
        return service_for(self._q(parsed, 'book'))

    # ---- 路由 ----

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == '/api/v1/whoami':
                role, err = self._role()
                if err != 0:
                    self._json(401, {'error': {'code': 'UNAUTHORIZED'}})
                    return
                self._json(200, {'role': role, 'auth_enabled': auth.auth_enabled()})
            elif path == '/api/v1/home':
                self._get_home(parsed)
            elif path == '/api/v1/books':
                role = self._require_role('books')
                if role:
                    self._json(200, {'books': list_books(), 'books_dir': books_dir()})
            elif path == '/api/v1/settings':
                self._get_settings(parsed)
            elif path == '/api/v1/architecture':
                self._json(200, self._svc(parsed).web_architecture())
            elif path == '/api/v1/entities':
                self._get_entities(parsed)
            elif path == '/api/v1/graph':
                role = self._require_role('graph')
                if role:
                    self._json(200, self._svc(parsed).web_graph(self._q(parsed, 'chapter')))
            elif path == '/api/v1/board':
                role = self._require_role('board')
                if role:
                    self._json(200, self._svc(parsed).web_board(self._q(parsed, 'chapter')))
            elif path == '/api/v1/timeline':
                role = self._require_role('timeline')
                if role:
                    self._json(200, self._svc(parsed).web_timeline(self._q(parsed, 'from'),
                                                                   self._q(parsed, 'to'),
                                                                   self._q(parsed, 'entity')))
            elif path == '/api/v1/reviews':
                role = self._require_role('reviews')
                if role:
                    self._json(200, self._svc(parsed).web_reviews(self._q(parsed, 'from'), self._q(parsed, 'to')))
            elif path == '/api/v1/plan':
                role = self._require_role('plan')
                if role:
                    self._json(200, self._svc(parsed).web_plan(self._q(parsed, 'chapter')))
            elif path == '/api/v1/export/novel':
                self._export_novel(parsed)
            elif path == '/api/v1/jobs' or path.startswith('/api/v1/jobs/'):
                self._get_job(path)
            elif path.startswith('/api/v1/entity/'):
                self._get_entity(path, parsed)
            elif path == '/api/v1/runs':
                role = self._require_role('runs')
                if role:
                    self._json(200, {'runs': self._svc(parsed).web_runs()})
            elif path.startswith('/api/v1/runs/'):
                self._get_run(path, parsed)
            elif path.startswith('/api/v1/chapter/'):
                self._get_chapter(path, parsed)
            elif path.startswith('/api/v1/stream/runs/'):
                self._get_stream(path, parsed)
            elif path.startswith('/api/'):
                self._json(404, {'error': {'code': 'NOT_FOUND', 'path': path}})
            else:
                self._static(path)
        except KeyError as e:
            self._json(404, {'error': {'code': 'NOT_FOUND', 'message': str(e)}})
        except (TypeError, ValueError) as e:
            self._json(400, {'error': {'code': 'BAD_REQUEST', 'message': str(e)}})
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:  # pragma: no cover - 兜底
            self._json(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        # 新建书(开书向导的第一步)
        if path == '/api/v1/books':
            role = self._require_role('books')
            if not role:
                return
            try:
                body = self._read_json()
                out = create_book(str(body.get('name') or '').strip())
                self._json(200, {'ok': True, **out})
            except ValueError as e:
                self._json(400, {'error': {'code': 'BAD_REQUEST', 'message': str(e)}})
            except Exception as e:
                self._json(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
            return
        # 慢操作作业执行器
        if path.startswith('/api/v1/jobs/'):
            self._post_job(path)
            return
        # HITL 决策作答(BFF 专属:记录答案进蓝图再 resume,非工具面)
        m = re.match(r'^/api/v1/runs/([^/]+)/decisions/([^/]+)/answer$', path)
        if m:
            role = self._require_role('stream')
            if not role:
                return
            try:
                body = self._read_json()
                out = service_for(self._q(parsed, 'book', body.get('book'))).web_decision_answer(m.group(1), m.group(2), body.get('answers') or [])
                self._json(200, {'ok': True, 'result': out})
            except KeyError as e:
                self._json(404, {'error': {'code': 'NOT_FOUND', 'message': str(e)}})
            except (TypeError, ValueError) as e:
                self._json(400, {'error': {'code': 'BAD_REQUEST', 'message': str(e)}})
            except Exception as e:
                self._json(500, {'error': {'code': 'INTERNAL', 'message': str(e)}})
            return
        if not path.startswith('/api/v1/actions/'):
            self._json(404, {'error': {'code': 'NOT_FOUND', 'path': path}})
            return
        try:
            body = self._read_json()
        except Exception as e:
            self._json(400, {'error': {'code': 'BAD_REQUEST', 'message': str(e)}})
            return
        name = path[len('/api/v1/actions/'):].strip('/')
        headers = {k.lower(): v for k, v in self.headers.items()}
        book = self._q(parsed, 'book', body.pop('book', None))
        if book:
            # Resolve every write to the same explicit book as reads.
            try:
                from .tooldefs import TOOLS
                if name not in {t['name'] for t in TOOLS}:
                    raise KeyError(f'unknown tool: {name}')
                data = getattr(service_for(book), name)(**body)
                out = (200, {'errNo': 0, 'errMsg': 'success', 'data': data})
            except KeyError as e:
                out = (200, {'errNo': 40401, 'errMsg': str(e), 'data': None})
            except (TypeError, ValueError) as e:
                out = (200, {'errNo': 40001, 'errMsg': str(e), 'data': None})
            except Exception as e:
                out = (200, {'errNo': 50001, 'errMsg': str(e), 'data': None})
            self._json(out[0], out[1]); return
        status, out = facade_call(name, body, headers)  # 业务校验与正典闸门仍在既有路径里
        self._json(status, out)

    # ---- D3 端点 ----

    def _get_settings(self, parsed):
        role = self._require_role('settings')
        if not role:
            return
        roles = {}
        for r in ('writer', 'planner', 'reviewer', 'revision', 'architect'):
            var = 'NOVEL_ARCHITECT_' if r == 'architect' else f'NOVEL_{r.upper()}_'
            base = os.environ.get(var + 'BASE_URL', '')
            roles[r] = {
                'base_url': re.sub(r'//[^/]+', '//***', base) if base else None,
                'model': os.environ.get(var + 'MODEL') or os.environ.get('NOVEL_PLANNER_MODEL'),
                'key_set': bool(os.environ.get(var + 'API_KEY') or os.environ.get('NOVEL_PLANNER_API_KEY')),
            }
        self._json(200, {
            'book': {'db': str(self._svc(parsed).store.path), 'books_dir': books_dir()},
            'models': roles,
            'facade_auth': {'enabled': False, 'open_mode_note': '公开工作台，无需登录，全部功能可用'},
            'reference_root': os.environ.get('NOVEL_REFERENCE_ROOT'),
        })

    def _export_novel(self, parsed):
        role = self._require_role('export')
        if not role:
            return
        svc = self._svc(parsed)
        with svc.store.connect() as db:
            title_row = db.execute('SELECT payload_json FROM planning_blueprint WHERE id=1').fetchone()
        title = '未命名'
        try:
            import json as _json
            if title_row:
                title = (_json.loads(title_row['payload_json'] or '{}') or {}).get('title') or title
        except Exception:
            pass
        chapters = svc.canon.chapters_range(1, 10 ** 6)
        bodies = svc.canon.recent_chapters_with_body(10 ** 6, 10 ** 6)
        body_by_ch = {c['chapter']: c['body'] for c in bodies}
        lines = [f'# {title}', '', f'> 共 {len(chapters)} 章 · 由 Novel Agent 叙事运行时产出', '', '## 目录', '']
        for c in chapters:
            lines.append(f'- 第{c["chapter"]}章 {c["title"]}')
        lines.append('')
        for c in chapters:
            lines += [f'## 第{c["chapter"]}章 {c["title"]}', '', (body_by_ch.get(c['chapter']) or '').strip(), '']
        data = '\n'.join(lines).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/markdown; charset=utf-8')
        self.send_header('Content-Disposition', f'attachment; filename="novel.md"')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _post_job(self, path):
        tool = path[len('/api/v1/jobs/'):].strip('/')
        role = self._require_role('jobs')
        if not role:
            return
        if tool not in JOB_TOOLS:
            self._json(404, {'error': {'code': 'NOT_FOUND', 'message': f'not a job tool: {tool}'}})
            return
        try:
            body = self._read_json()
        except Exception as e:
            self._json(400, {'error': {'code': 'BAD_REQUEST', 'message': str(e)}})
            return
        args = body.get('args') or {}
        try:
            book = self._q(urlparse(self.path), 'book', body.get('book'))
            svc = service_for(book)
        except (KeyError, ValueError) as e:
            self._json(404, {'error': {'code': 'NOT_FOUND', 'message': str(e)}})
            return
        job_id = 'job_' + uuid.uuid4().hex[:12]
        book_path = str(svc.store.path.resolve())
        job = {'id': job_id, 'book': book, 'book_path': book_path, 'args': args, 'tool': tool, 'status': 'running', 'started_at': time.time(), 'result': None, 'error': None}
        with _JOB_LOCK:
            if tool == 'novel_run_continue':
                existing = next((j for j in _JOBS.values() if j['status'] == 'running' and
                                 j['tool'] == tool and j.get('book_path') == book_path and
                                 j.get('args', {}).get('run_id') == args.get('run_id')), None)
                if existing:
                    self._json(200, {'ok': True, 'job': existing})
                    return
            _JOBS[job_id] = job

        def run():
            try:
                fn = getattr(svc, tool)
                job['result'] = fn(**args) if isinstance(args, dict) else fn(args)
                if isinstance(job['result'], dict) and job['result'].get('ok') is False:
                    err = job['result'].get('error') or job['result'].get('errors') or '操作未完成'
                    raise ValueError(err.get('message', str(err)) if isinstance(err, dict) else str(err))
                job['status'] = 'done'
            except Exception as e:
                job['error'] = f'{type(e).__name__}: {e}'
                job['status'] = 'failed'

        threading.Thread(target=run, daemon=True).start()
        self._json(200, {'ok': True, 'job': job})

    def _get_job(self, path):
        role = self._require_role('jobs')
        if not role:
            return
        job_id = path[len('/api/v1/jobs/'):].strip('/')
        with _JOB_LOCK:
            job = _JOBS.get(job_id)
        if not job:
            self._json(404, {'error': {'code': 'NOT_FOUND', 'message': f'no such job: {job_id}'}})
            return
        self._json(200, job)

    # ---- 端点实现 ----

    def _get_home(self, parsed):
        role = self._require_role('home')
        if not role:
            return
        chapter = self._q(parsed, 'chapter')
        home = self._svc(parsed).web_home(chapter)
        self._json(200, home)

    def _get_entities(self, parsed):
        role = self._require_role('entities')
        if not role:
            return
        out = self._svc(parsed).web_entities(chapter=self._q(parsed, 'chapter'),
                                             q=self._q(parsed, 'q', ''),
                                             entity_type=self._q(parsed, 'type'),
                                             limit=int(self._q(parsed, 'limit', 200)))
        self._json(200, out)

    def _get_entity(self, path, parsed):
        role = self._require_role('entity')
        if not role:
            return
        key = unquote(path[len('/api/v1/entity/'):].strip('/'))
        if not key:
            raise ValueError('entity key required')
        self._json(200, self._svc(parsed).web_entity(key, self._q(parsed, 'chapter')))

    def _get_run(self, path, parsed):
        role = self._require_role('run')
        if not role:
            return
        run_id = path[len('/api/v1/runs/'):].strip('/')
        data = self._svc(parsed).web_run(run_id)
        self._json(200, data)

    def _get_chapter(self, path, parsed):
        rest = path[len('/api/v1/chapter/'):].strip('/')
        parts = [p for p in rest.split('/') if p]
        try:
            chapter = int(parts[0])
        except (ValueError, IndexError):
            raise ValueError(f'invalid chapter: {rest}')
        if len(parts) >= 3 and parts[1] == 'draft':
            role = self._require_role('draft')
            if not role:
                return
            version = int(parts[2]) if parts[2].isdigit() else None
            self._json(200, self._svc(parsed).web_draft(chapter, version))
            return
        role = self._require_role('chapter')
        if not role:
            return
        data = self._svc(parsed).web_chapter(chapter, self._q(parsed, 'version'))
        self._json(200, data)

    def _get_stream(self, path, parsed):
        role = self._require_role('stream')
        if not role:
            return
        run_id = path[len('/api/v1/stream/runs/'):].strip('/').split('?')[0]
        once = 'once=1' in (urlparse(self.path).query or '')
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        last_id = 0
        svc = self._svc(parsed)
        deadline = time.time() + 3600 if not once else time.time()
        try:
            while True:
                with svc.store.connect() as db:
                    rows = db.execute(
                        'SELECT * FROM novel_run_events WHERE run_id=? AND id>? ORDER BY id LIMIT 100',
                        (run_id, last_id)).fetchall()
                    run = db.execute(
                        'SELECT run_id,status,current_chapter,last_committed_chapter,chapters_committed,updated_at '
                        'FROM novel_runs WHERE run_id=?', (run_id,)).fetchone()
                for r in rows:
                    last_id = r['id']
                    payload = {k: r[k] for k in ('id', 'phase', 'status', 'chapter', 'created_at')}
                    try:
                        payload['detail'] = json.loads(r['detail_json'] or 'null')
                    except Exception:
                        payload['detail'] = None
                    self._sse(payload['id'], 'run_event', payload)
                self._sse(None, 'run_status', dict(run) if run else None)
                if once or time.time() > deadline:
                    return
                time.sleep(SSE_POLL_SECONDS)
        except (BrokenPipeError, ConnectionResetError):
            return

    def _sse(self, event_id, event_type, payload) -> None:
        chunk = ''
        if event_id is not None:
            chunk += f'id: {event_id}\n'
        chunk += f'event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
        self.wfile.write(chunk.encode('utf-8'))
        self.wfile.flush()

    # ---- 静态文件 ----

    def _static(self, path: str) -> None:
        root = self.server.static_root
        if not root:
            self._json(404, {'error': {'code': 'NO_STATIC_ROOT', 'hint': 'pass --static <dist dir>'}})
            return
        root_abs = os.path.abspath(root)
        rel = path.lstrip('/') or 'index.html'
        full = os.path.normpath(os.path.join(root_abs, rel))
        if full != root_abs and not full.startswith(root_abs + os.sep):
            self.send_error(403)
            return
        if not os.path.isfile(full):
            full = os.path.join(root_abs, 'index.html')  # SPA 路由回退
            if not os.path.isfile(full):
                self.send_error(404)
                return
        ctype = mimetypes.guess_type(full)[0] or 'application/octet-stream'
        data = open(full, 'rb').read()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)


def run(db=None, host='127.0.0.1', port=8080, static=None, reference_root=None, nkg_root=None) -> None:
    if db:
        os.environ['NOVEL_STORY_DB'] = db
    if reference_root:
        os.environ['NOVEL_REFERENCE_ROOT'] = reference_root
    if nkg_root:
        os.environ['NARRATIVE_KG_ROOT'] = nkg_root
    runtime.service()  # 触发建库/迁移,启动即暴露配置错误
    srv = WebServer((host, port), Handler)
    srv.static_root = static
    print(f'Novel Web listening on http://{host}:{port} '
          f'(api={API}, static={static or "off"}, db={os.environ.get("NOVEL_STORY_DB")}, '
          f'books={books_dir()})', flush=True)
    srv.serve_forever()


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog='novel-web')
    ap.add_argument('--db', default=None)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8080)
    ap.add_argument('--static', default=None)
    ap.add_argument('--reference-root', default=None)
    ap.add_argument('--narrative-kg-root', dest='nkg_root', default=None)
    a = ap.parse_args(argv)
    run(a.db, a.host, a.port, a.static, a.reference_root, a.nkg_root)


if __name__ == '__main__':
    main()
