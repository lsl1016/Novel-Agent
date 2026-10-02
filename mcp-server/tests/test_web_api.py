"""Web BFF(Phase D1)端点测试:聚合读、鉴权角色裁剪、SSE、静态托管、动作透传。"""
from pathlib import Path
import json
import sys
import threading
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp import runtime
from novel_mcp.service import NovelService
from novel_mcp.web_api import WebServer, Handler

REF = Path(__file__).resolve().parents[2] / 'reference-example'


def seed(tmp_path):
    s = NovelService(Path(tmp_path) / 'story.db', REF, '/mnt/data/narrative-kg')
    s.store.set_meta('main_goal', '验证目标')
    s.store.set_meta('current_arc', '第一卷')
    s.store.set_world_fact('sec', '真相值', 'secret', 50)
    s.store.upsert_thread('t1', '主线', introduced_chapter=1, target_min=10, target_max=20)
    r = s.chapter_commit(1, '第一章', '正文内容。', '第一卷', 'hero', '概要', {})
    assert r.get('committed')
    s.entity_upsert('hero', 'Character', '主角', 1, 'active', '描述', {}, 'author_declared')
    s.entity_upsert('sword', 'Artifact', '佩剑', 1, 'active', '描述', {}, 'author_declared')
    s.entity_relation_upsert('hero', 'OWNS', 'sword', 0, None, 'active', 'public', None, None, {}, 'author_declared')
    s.store.add_belief(fact_key='sec', holder='reader', chapter=1, stance='suspects', value='好像是秘密')
    s.clue_add('t1', 1, '第一条线索', 'reader', 0.2)
    s.planning.chapter_plan_put(2, {'pov': 'hero', 'summary': '第二章计划'}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    s.chapter_draft_save(2, '第二章草稿', '草稿正文。', '第一卷', 'hero', '概要', {}, source='external')
    run = s.novel_run_start(start_chapter=2, target_chapter=3, require_semantic=False,
                            auto_plan=False, stop_on_pressure=False)
    run_id = run['run']['run_id']
    s.runs._event(run_id, 'plan', 'ready', 2, {'note': 'seed'})
    return s, run_id


def start_server(tmp_path, svc):
    runtime._SERVICE = svc  # web_api 经 runtime 单例取服务,注入种子实例
    srv = WebServer(('127.0.0.1', 0), Handler)
    srv.static_root = str(tmp_path / 'dist')
    (tmp_path / 'dist').mkdir(exist_ok=True)
    (tmp_path / 'dist' / 'index.html').write_text('<html>spa</html>', encoding='utf-8')
    (tmp_path / 'dist' / 'app.js').write_text('console.log(1)', encoding='utf-8')
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f'http://127.0.0.1:{srv.server_address[1]}'
    finally:
        srv.shutdown()
        runtime._SERVICE = None


def get(base, path, token=None):
    req = urllib.request.Request(base + path, headers={'Authorization': f'Bearer {token}'} if token else {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))


def post(base, path, body, token=None):
    data = json.dumps(body).encode('utf-8')
    req = urllib.request.Request(base + path, data=data, method='POST',
                                 headers={'Content-Type': 'application/json',
                                          **({'Authorization': f'Bearer {token}'} if token else {})})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode('utf-8'))


def raw(base, path, token=None):
    req = urllib.request.Request(base + path, headers={'Authorization': f'Bearer {token}'} if token else {})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, resp.read().decode('utf-8')


def test_open_mode_home_chapter_actions(tmp_path):
    svc, run_id = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        st, home = get(base, '/api/v1/home')
        assert st == 200
        assert home['progress']['committed_chapters'] == 1
        assert home['inbox']['active_draft_chapters'] == 1
        assert home['pressure']['chapter'] >= 1
        assert home['run']['run_id'] == run_id
        st, ch = get(base, '/api/v1/chapter/1')
        assert st == 200 and ch['canon']['body'] == '正文内容。'
        assert ch['gate']['ready'] is False  # 第 1 章无草稿版本记录(内部提交)
        st, ch2 = get(base, '/api/v1/chapter/2')
        assert st == 200 and ch2['latest_draft_version'] == 1
        assert ch2['gate']['ready'] is False  # 审校不齐全
        st, draft = get(base, '/api/v1/chapter/2/draft/1')
        assert st == 200 and draft['body'] == '草稿正文。'
        st, runs = get(base, '/api/v1/runs')
        assert st == 200 and runs['runs'][0]['run_id'] == run_id
        st, detail = get(base, f'/api/v1/runs/{run_id}')
        assert st == 200 and detail['run']['config']['target_chapter'] == 3
        assert any(e['phase'] == 'plan' for e in detail['events'])
        st, who = get(base, '/api/v1/whoami')
        assert st == 200 and who == {'role': 'admin', 'auth_enabled': False}
        st, out = post(base, '/api/v1/actions/blueprint_get', {})
        assert st == 200 and out['errNo'] == 0


def test_role_auth_and_viewer_trimming(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'viewer:vt,planner:pt')
    svc, run_id = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        try:
            get(base, '/api/v1/home')
            assert False, 'unauthenticated should 401'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        st, who = get(base, '/api/v1/whoami', token='pt')
        assert who == {'role': 'planner', 'auth_enabled': True}
        st, home = get(base, '/api/v1/home', token='vt')
        assert st == 200
        assert set(home.keys()) == {'book', 'progress', 'run', 'recent_chapters'}  # 无 arcs/pressure/inbox
        st, ch = get(base, '/api/v1/chapter/2', token='vt')
        assert st == 200 and set(ch.keys()) == {'chapter', 'canon'}
        assert ch['canon'] is None  # 未提交章对 viewer 只有无正典
        try:
            get(base, '/api/v1/chapter/2/draft/1', token='vt')
            assert False, 'viewer must not read drafts'
        except urllib.error.HTTPError as e:
            assert e.code == 403
        st, out = post(base, '/api/v1/actions/blueprint_get', {}, token='vt')
        assert st == 200 and out['errNo'] == 40301  # 工具面拒绝
        st, out = post(base, '/api/v1/actions/novel_run_status', {'run_id': run_id}, token='vt')
        assert st == 200 and out['errNo'] == 0


def test_sse_once(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'viewer:vt,planner:pt')
    svc, run_id = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        st, body = raw(base, f'/api/v1/stream/runs/{run_id}?once=1', token='pt')
        assert st == 200
        assert 'event: run_event' in body and 'event: run_status' in body
        assert '"phase": "plan"' in body or '"phase":"plan"' in body
        try:
            raw(base, f'/api/v1/stream/runs/{run_id}?once=1', token='vt')
            assert False, 'viewer must not see run stream'
        except urllib.error.HTTPError as e:
            assert e.code == 403


def test_static_spa_fallback_and_traversal(tmp_path):
    svc, _ = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        st, body = raw(base, '/some/spa/route')
        assert st == 200 and 'spa' in body  # 回退 index.html
        st, body = raw(base, '/app.js')
        assert st == 200 and body == 'console.log(1)'
        try:
            raw(base, '/../etc/passwd')
            assert False, 'path traversal must be rejected'
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404)


def test_d2_graph_board_timeline_and_roles(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'viewer:vt,writer:wt,planner:pt')
    svc, run_id = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        # 实体目录与详情
        st, ents = get(base, '/api/v1/entities', token='pt')
        assert st == 200 and ents['type_counts'].get('Character') == 1
        st, d = get(base, '/api/v1/entity/hero', token='pt')
        assert st == 200 and any(r['relation_type'] == 'OWNS' for r in d['relations'])
        # 图谱:节点含 hero/sword,公开边可见
        st, g = get(base, '/api/v1/graph', token='pt')
        assert st == 200 and {'hero', 'sword'} <= {n['key'] for n in g['nodes']}
        assert any(e['source'] == 'hero' and e['type'] == 'OWNS' and not e['secret'] for e in g['edges'])
        # 看板:信念矩阵含 sec(reader 怀疑中),线索台账 1 条未回收
        st, b = get(base, '/api/v1/board', token='pt')
        assert st == 200
        sec = next(f for f in b['belief_matrix'] if f['fact_key'] == 'sec')
        assert sec['holders']['reader']['stance'] == 'suspects'
        assert len(b['clue_ledger']) == 1 and b['clue_ledger'][0]['paid'] is False
        # 时间线窗口
        st, t = get(base, '/api/v1/timeline?from=1&to=5', token='pt')
        assert st == 200 and t['from'] == 1
        # 角色矩阵:viewer/writer 均为作者层 403
        for tok in ('vt', 'wt'):
            try:
                get(base, '/api/v1/board', token=tok)
                assert False, f'{tok} must not read board'
            except urllib.error.HTTPError as e:
                assert e.code == 403


def test_decision_answer_route(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'viewer:vt,controller:ct')
    svc, run_id = seed(tmp_path)
    # 挂起一个作者提问决策
    svc.runs._open_decision(run_id, 3, 'author_question', '本章是否引入新角色?', {'plan_result': {'author_questions': ['本章是否引入新角色?']}})
    for base in start_server(tmp_path, svc):
        import json as _json
        body = _json.dumps({'answers': [{'question': '本章是否引入新角色?', 'answer': '不引入,用无名随从'}]}).encode()
        req = urllib.request.Request(f'{base}/api/v1/runs/{run_id}/decisions/x/answer', data=body, method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ct'})
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404  # 不存在的决策
        # 找到真实 decision_id
        st, detail = get(base, f'/api/v1/runs/{run_id}', token='ct')
        did = detail['open_decisions'][0]['decision_id']
        assert detail['open_decisions'][0]['author_questions'] == ['本章是否引入新角色?']
        req = urllib.request.Request(f'{base}/api/v1/runs/{run_id}/decisions/{did}/answer', data=body, method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ct'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read().decode('utf-8'))
        assert out['ok']
        bp = svc.blueprint_get()
        assert any(x.get('answer') == '不引入,用无名随从' for x in bp['blueprint']['author_decisions'])
        # viewer 不可作答
        req = urllib.request.Request(f'{base}/api/v1/runs/{run_id}/decisions/{did}/answer', data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer vt'})
        try:
            urllib.request.urlopen(req, timeout=10)
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403


def test_d3_endpoints_books_jobs_settings_reviews_plan(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'viewer:vt,planner:pt')
    monkeypatch.setenv('NOVEL_BOOKS_DIR', str(tmp_path / 'lib'))
    (tmp_path / 'lib').mkdir()
    svc, run_id = seed(tmp_path)
    for base in start_server(tmp_path, svc):
        # 书库:新建一本书并列出
        st, out = post(base, '/api/v1/books', {'name': 'second'}, token='pt')
        assert st == 200 and out['ok'] and out['name'] == 'second.db'
        st, books = get(base, '/api/v1/books', token='vt')
        assert st == 200 and {b['name'] for b in books['books']} >= {'second.db'}
        # 作业执行器:未在白名单的工具 404;白名单工具权限由 auth 兜底
        try:
            post(base, '/api/v1/jobs/chapter_finalize', {}, token='pt')
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 404
        # viewer 不能发作业
        try:
            post(base, '/api/v1/jobs/chapter_plan_generate', {'args': {}}, token='vt')
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403
        # 作业:对新建空书跑一个真实慢工具等价物(chapter_plan_generate 无模型会失败,
        # 但作业机制本身应返回 job id 且状态可查)
        st, out = post(base, '/api/v1/jobs/chapter_plan_generate', {'args': {'chapter': 1}, 'book': 'second'}, token='pt')
        assert st == 200 and out['ok'] and out['job']['status'] == 'running'
        jid = out['job']['id']
        import time as _t
        for _ in range(40):
            st, job = get(base, f'/api/v1/jobs/{jid}', token='pt')
            if job['status'] != 'running':
                break
            _t.sleep(0.1)
        assert job['status'] in ('done', 'failed') and job['error'] is None or job['status'] == 'failed'
        # 设置(viewer 403,planner 可见,密钥脱敏)
        try:
            get(base, '/api/v1/settings', token='vt')
            assert False
        except urllib.error.HTTPError as e:
            assert e.code == 403
        st, settings = get(base, '/api/v1/settings', token='pt')
        assert st == 200 and 'models' in settings and 'writer' in settings['models']
        # 审校聚合(空库无审校也应是 200)
        st, revs = get(base, '/api/v1/reviews?from=1&to=9', token='pt')
        assert st == 200 and isinstance(revs['chapters'], list)
        # 规划聚合
        st, plan = get(base, '/api/v1/plan', token='pt')
        assert st == 200 and isinstance(plan['chapter_plans'], list)
        # 导出
        st, body = raw(base, '/api/v1/export/novel', token='vt')
        assert st == 200 and '第一章' in body
