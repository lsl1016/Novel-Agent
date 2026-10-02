"""Web 工作台 BFF(Phase D1)。

同源一个进程提供(架构见 docs/phase-d-web-tech.md):

* ``GET /``              — SPA 静态文件(``--static`` 目录,未命中回退 index.html)
* ``GET /api/v1/...``    — 聚合读端点(NovelService.web_* 只读方法)
* ``GET /api/v1/stream/runs/{id}`` — SSE 运行事件流(``?once=1`` 推一拍即断,供测试)
* ``POST /api/v1/actions/{tool}``  — 写动作透传 ``http_compat.facade_call``,
  与外部 Agent 走完全相同的权限/校验/闸门路径。BFF 自身没有第二条写路径。

鉴权复用 auth.py(``NOVEL_FACADE_TOKENS``);``viewer`` 即读者模式:
草稿/规划/压力等作者层载荷在服务端裁剪,不是前端隐藏。
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from . import auth
from .http_compat import facade_call
from .runtime import service as runtime_service

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
    # D2 作者层:含世界真相/信念矩阵/秘密边,writer 与 viewer 均不可见
    'entities': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'entity': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'graph': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'board': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
    'timeline': frozenset({'reviewer', 'planner', 'controller', 'admin'}),
}


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    static_root: str | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = 'NarrativeWeb/0.1'

    def log_message(self, fmt, *args):
        pass  # 本地工具,静默访问日志;错误仍会经 send_error 呈现

    # ---- 基础设施 ----

    def _json(self, status: int, out: dict) -> None:
        data = json.dumps(out, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
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
            elif path == '/api/v1/entities':
                self._get_entities(parsed)
            elif path == '/api/v1/graph':
                self._get_graph(parsed)
            elif path == '/api/v1/board':
                self._get_board(parsed)
            elif path == '/api/v1/timeline':
                self._get_timeline(parsed)
            elif path.startswith('/api/v1/entity/'):
                self._get_entity(path, parsed)
            elif path == '/api/v1/runs':
                role = self._require_role('runs')
                if role:
                    self._json(200, {'runs': runtime_service().web_runs()})
            elif path.startswith('/api/v1/runs/'):
                self._get_run(path)
            elif path.startswith('/api/v1/chapter/'):
                self._get_chapter(path)
            elif path.startswith('/api/v1/stream/runs/'):
                self._get_stream(path)
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
                out = runtime_service().web_decision_answer(m.group(1), m.group(2), body.get('answers') or [])
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
        status, out = facade_call(name, body, headers)  # 权限/闸门/校验全部在既有路径里
        self._json(status, out)

    # ---- 端点实现 ----

    def _get_home(self, parsed):
        role = self._require_role('home')
        if not role:
            return
        q = parse_qs(parsed.query)
        chapter = int(q['chapter'][0]) if q.get('chapter') else None
        home = runtime_service().web_home(chapter)
        if role == 'viewer':
            home = {
                'book': home['book'],
                'progress': home['progress'],
                'run': home['run'],
                'recent_chapters': [{'chapter': c['chapter'], 'title': c['title'], 'committed_at': c['committed_at']}
                                    for c in home['recent_chapters']],
            }
        self._json(200, home)

    def _get_run(self, path):
        role = self._require_role('run')
        if not role:
            return
        run_id = path[len('/api/v1/runs/'):].strip('/')
        data = runtime_service().web_run(run_id)
        if role == 'viewer':
            data = {'run': data['run'],
                    'chapters': [{'chapter': c['chapter'], 'title': c['title'], 'committed_at': c['committed_at']}
                                 for c in data['chapters']]}
        self._json(200, data)

    def _q(self, parsed, key, default=None):
        q = parse_qs(parsed.query)
        return q[key][0] if q.get(key) else default

    def _get_entities(self, parsed):
        role = self._require_role('entities')
        if not role:
            return
        svc = runtime_service()
        out = svc.web_entities(chapter=self._q(parsed, 'chapter'),
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
        self._json(200, runtime_service().web_entity(key, self._q(parsed, 'chapter')))

    def _get_graph(self, parsed):
        role = self._require_role('graph')
        if not role:
            return
        self._json(200, runtime_service().web_graph(self._q(parsed, 'chapter')))

    def _get_board(self, parsed):
        role = self._require_role('board')
        if not role:
            return
        self._json(200, runtime_service().web_board(self._q(parsed, 'chapter')))

    def _get_timeline(self, parsed):
        role = self._require_role('timeline')
        if not role:
            return
        self._json(200, runtime_service().web_timeline(self._q(parsed, 'from'),
                                                       self._q(parsed, 'to'),
                                                       self._q(parsed, 'entity')))

    def _get_chapter(self, path):
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
            self._json(200, runtime_service().web_draft(chapter, version))
            return
        role = self._require_role('chapter')
        if not role:
            return
        data = runtime_service().web_chapter(chapter)
        if role == 'viewer':
            data = {'chapter': data['chapter'], 'canon': data['canon']}
        self._json(200, data)

    def _get_stream(self, path):
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
        svc = runtime_service()
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
    runtime_service()  # 触发建库/迁移,启动即暴露配置错误
    srv = WebServer((host, port), Handler)
    srv.static_root = static
    print(f'Novel Web listening on http://{host}:{port} '
          f'(api={API}, static={static or "off"}, db={os.environ.get("NOVEL_STORY_DB")})', flush=True)
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
