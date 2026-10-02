"""Web 工作台 BFF(Phase D1-D3)。

同源一个进程提供(架构见 docs/phase-d-web-tech.md):

* ``GET /``              — SPA 静态文件(``--static`` 目录,未命中回退 index.html)
* ``GET /api/v1/...``    — 聚合读端点(NovelService.web_* 只读方法)
* ``GET /api/v1/stream/runs/{id}`` — SSE 运行事件流(``?once=1`` 推一拍即断,供测试)
* ``POST /api/v1/actions/{tool}``  — 快写动作透传 ``http_compat.facade_call``,
  与外部 Agent 走完全相同的权限/校验/闸门路径。BFF 自身没有第二条写路径。
* ``POST /api/v1/jobs/{tool}``     — 慢操作(LLM 分钟级)后台作业:线程执行 +
  ``GET /api/v1/jobs/{id}`` 轮询(生成/审校/修订/规划)。
* 多书:端点统一接受 ``?book=<名>``,服务实例按库路径缓存;书库默认 ``story-data/``。

鉴权复用 auth.py(``NOVEL_FACADE_TOKENS``);``viewer`` 即读者模式:
草稿/规划/压力等作者层载荷在服务端裁剪,不是前端隐藏。
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

# 端点 × 角色:viewer 只见正典与运行状态;草稿与实时流水属作者层。
READ_ROLES = {
    'home': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'runs': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'run': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'chapter': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'draft': frozenset({'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'stream': frozenset({'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    # D2/D3 作者层:含世界真相/信念矩阵/秘密边/规划,writer 与 viewer 均不可见
    'entities': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'entity': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'graph': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'board': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'timeline': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'reviews': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'plan': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'settings': frozenset({'planner', 'admin'}),
    'jobs': frozenset({'planner', 'controller', 'admin'}),
    'books': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
    'export': frozenset({'viewer', 'writer', 'reviewer', 'planner', 'controller', 'admin'}),
}

# 慢操作白名单(分钟级 LLM 调用,走作业执行器;权限仍按角色白名单)
JOB_TOOLS = frozenset({
    'novel_architecture_generate', 'story_architect_apply', 'chapter_plan_generate', 'chapter_direction_propose', 'chapter_semantic_review',
    'chapter_review_full', 'chapter_auto_revise', 'chapter_auto_revision_loop',
    'chapter_draft_generate',
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
    root = books_dir()
    default_db = os.path.abspath(os.environ.get('NOVEL_STORY_DB') or './story-data/story.db')
    if not os.path.isdir(root):
        return out
    for fn in sorted(os.listdir(root)):
        if not fn.endswith('.db') or fn.endswith(('-wal', '-shm')):
            continue
        path = os.path.join(root, fn)
        try:
            db = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
            db.row_factory = sqlite3.Row
            title = None
            try:
                r = db.execute('SELECT payload_json FROM planning_blueprint WHERE id=1').fetchone()
                if r:
                    import json as _json
                    title = (_json.loads(r['payload_json'] or '{}') or {}).get('title')
            except Exception:
                pass
            if not title:
                try:
                    title = db.execute("SELECT value FROM meta WHERE key='title'").fetchone()
                    title = title[0] if title else None
                except Exception:
                    title = None
            cnt = db.execute('SELECT COUNT(*) c, COALESCE(SUM(LENGTH(body)),0) s FROM chapters').fetchone()
            db.close()
            out.append({'name': fn, 'title': title or fn[:-3], 'chapters': cnt['c'],
                        'chars': cnt['s'], 'default': path == default_db,
                        'updated_at': time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))})
        except Exception:
            continue
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
        self.wfile.write(data)

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
        """返回 (role, status)。status=0 通过;401 未认证。

        EventSource 无法携带 Authorization 头,故 SSE 场景允许 ``?token=``
        查询参数作为等价凭证(本地工具,日志暴露面可接受)。
        """
        if not auth.auth_enabled():
            return 'admin', 0
        headers = {k.lower(): v for k, v in self.headers.items()}
        if 'authorization' not in headers:
            q = parse_qs(urlparse(self.path).query)
            if q.get('token'):
                headers['authorization'] = f'Bearer {q["token"][0]}'
        role, err = auth.resolve_role(headers)
        return role, err

    def _require_role(self, endpoint: str):
        role, err = self._role()
        if err != 0:
            self._json(401, {'error': {'code': 'UNAUTHORIZED', 'message': 'token required'}})
            return None
        if role not in READ_ROLES.get(endpoint, READ_ROLES['chapter']):
            self._json(403, {'error': {'code': 'FORBIDDEN', 'message': f'role {role} cannot read {endpoint}'}})
            return None
        return role

    def _q(self, parsed, key, default=None):
        q = parse_qs(parsed.query)
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
            if role not in ('planner', 'admin'):
                self._json(403, {'error': {'code': 'FORBIDDEN', 'message': f'role {role} cannot create books'}})
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
            if role not in ('controller', 'admin'):
                self._json(403, {'error': {'code': 'FORBIDDEN', 'message': f'role {role} cannot resolve decisions'}})
                return
            try:
                body = self._read_json()
                out = service_for(body.get('book')).web_decision_answer(m.group(1), m.group(2), body.get('answers') or [])
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
        book = body.pop('book', None) if isinstance(body, dict) else None
        if book:
            # book 作用域动作:与 facade_call 同一道 tool_allowed 闸门,
            # 仅把分发目标从默认书单例换成多书服务实例。
            role, err = self._role()
            if err != 0:
                self._json(401, {'errNo': 40101, 'errMsg': 'unauthorized', 'data': None}); return
            ok, reason = auth.tool_allowed(role, name, body)
            if not ok:
                self._json(200, {'errNo': 40301, 'errMsg': f'role {role} denied: {reason}', 'data': None}); return
            try:
                data = getattr(service_for(book), name)(**body)
                out = (200, {'errNo': 0, 'errMsg': 'success', 'data': data})
            except KeyError as e:
                out = (200, {'errNo': 40401, 'errMsg': str(e), 'data': None})
            except (TypeError, ValueError) as e:
                out = (200, {'errNo': 40001, 'errMsg': str(e), 'data': None})
            except Exception as e:
                out = (200, {'errNo': 50001, 'errMsg': str(e), 'data': None})
            self._json(out[0], out[1]); return
        status, out = facade_call(name, body, headers)  # 权限/闸门/校验全部在既有路径里
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
        tokens_cfg = bool(os.environ.get('NOVEL_FACADE_TOKENS', '').strip())
        self._json(200, {
            'book': {'db': os.environ.get('NOVEL_STORY_DB'), 'books_dir': books_dir()},
            'models': roles,
            'facade_auth': {'enabled': tokens_cfg, 'open_mode_note': '未配置 NOVEL_FACADE_TOKENS 时为本地开放模式(admin)'},
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
        ok, reason = auth.tool_allowed(role, tool, args)
        if not ok:
            self._json(403, {'error': {'code': 'FORBIDDEN', 'message': reason}})
            return
        job_id = 'job_' + uuid.uuid4().hex[:12]
        job = {'id': job_id, 'tool': tool, 'status': 'running', 'started_at': time.time(), 'result': None, 'error': None}
        with _JOB_LOCK:
            _JOBS[job_id] = job

        def run():
            try:
                svc = service_for(body.get('book'))
                fn = getattr(svc, tool)
                job['result'] = fn(**args) if isinstance(args, dict) else fn(args)
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
        if role == 'viewer':
            home = {
                'book': home['book'],
                'progress': home['progress'],
                'run': home['run'],
                'recent_chapters': [{'chapter': c['chapter'], 'title': c['title'], 'committed_at': c['committed_at']}
                                    for c in home['recent_chapters']],
            }
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
        if role == 'viewer':
            data = {'run': data['run'],
                    'chapters': [{'chapter': c['chapter'], 'title': c['title'], 'committed_at': c['committed_at']}
                                 for c in data['chapters']]}
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
        data = self._svc(parsed).web_chapter(chapter)
        if role == 'viewer':
            data = {'chapter': data['chapter'], 'canon': data['canon']}
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
