"""App 级权限分层回归:角色矩阵、参数级守卫、令牌解析与 facade 集成。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.auth import resolve_role, tool_allowed, parse_tokens, ROLE_TOOLS  # noqa: E402
from novel_mcp.tooldefs import TOOLS  # noqa: E402
from novel_mcp.service import NovelService  # noqa: E402


def test_role_matrix_covers_all_tools():
    all_names = {t['name'] for t in TOOLS}
    planner = ROLE_TOOLS['planner']
    controller = ROLE_TOOLS['controller']
    # planner ∪ controller ∪ finalize 之外没有作者面遗漏;planner+controller 覆盖除 run 外全部
    union = planner | controller
    missing = all_names - union
    assert missing <= set(), f'tools granted to no author/controller role: {missing}'
    # 关键红线
    writer = ROLE_TOOLS['writer']
    for forbidden in ('entity_author_get', 'belief_get', 'assertion_list', 'candidate_list',
                      'power_context_get', 'artifact_history_get', 'context_snapshot_get',
                      'chapter_finalize', 'entity_upsert', 'novel_run_start',
                      'planner_context_get', 'chapter_plan_generate', 'story_architect_apply'):
        assert forbidden not in writer, f'writer app must not reach {forbidden}'
    reviewer = ROLE_TOOLS['reviewer']
    for forbidden in ('chapter_finalize', 'entity_upsert', 'novel_run_continue', 'blueprint_update'):
        assert forbidden not in reviewer
    assert 'entity_author_get' in reviewer and 'belief_get' in reviewer
    assert 'chapter_finalize' in controller and 'novel_run_continue' in controller
    assert 'planner_context_get' in ROLE_TOOLS['planner']


def test_writer_param_guards():
    ok, _ = tool_allowed('writer', 'context_compile', {'chapter': 5, 'role': 'writer'})
    assert ok
    ok, _ = tool_allowed('writer', 'context_compile', {'chapter': 5})
    assert ok
    ok, reason = tool_allowed('writer', 'context_compile', {'chapter': 5, 'role': 'planner'})
    assert not ok and 'writer-role' in reason
    ok, reason = tool_allowed('writer', 'context_snapshot_get', {'chapter': 5, 'role': 'planner'})
    assert not ok
    ok, reason = tool_allowed('reviewer', 'chapter_auto_revision_loop', {'chapter': 5, 'finalize': True})
    assert not ok and 'finalize' in reason
    ok, _ = tool_allowed('reviewer', 'chapter_auto_revision_loop', {'chapter': 5})
    assert ok
    ok, _ = tool_allowed('admin', 'context_compile', {'chapter': 5, 'role': 'planner'})
    assert ok


def test_token_resolution(monkeypatch):
    monkeypatch.delenv('NOVEL_FACADE_TOKENS', raising=False)
    monkeypatch.delenv('NOVEL_FACADE_TOKEN', raising=False)
    assert resolve_role({}) == ('admin', 0), 'no tokens configured => open local mode'
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'writer:wtok,controller:ctok,admin:atok')
    assert resolve_role({'Authorization': 'Bearer wtok'}) == ('writer', 0)
    assert resolve_role({'Authorization': 'Bearer nope'})[1] == 40101
    assert resolve_role({})[1] == 40101
    # 旧单令牌 => admin
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', '')
    monkeypatch.setenv('NOVEL_FACADE_TOKEN', 'legacy')
    assert resolve_role({'Authorization': 'Bearer legacy'}) == ('admin', 0)
    assert parse_tokens('writer:w, bad, planner: p ,unknown-role:x') == {'w': 'writer', 'p': 'planner'}


def test_facade_enforces_roles(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_STORY_DB', str(tmp_path / 'auth.db'))
    monkeypatch.delenv('NOVEL_FACADE_TOKENS', raising=False)
    monkeypatch.delenv('NOVEL_FACADE_TOKEN', raising=False)
    import novel_mcp.runtime as rt
    rt._SERVICE = None
    from novel_mcp.http_compat import facade_call
    svc = rt.service()
    svc.entity_graph.upsert_entity('hero', 'Character', '林昭', 1)

    w = {'Authorization': 'Bearer wtok'}
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'writer:wtok,admin:atok')
    status, out = facade_call('entity_author_get', {'entity_key': 'hero', 'chapter': 1}, headers=w)
    assert status == 200 and out['errNo'] == 40301
    status, out = facade_call('entity_get', {'entity_key': 'hero', 'chapter': 1}, headers=w)
    assert out['errNo'] == 0 and out['data']['name'] == '林昭'
    status, out = facade_call('context_compile', {'chapter': 1, 'role': 'planner'}, headers=w)
    assert out['errNo'] == 40301
    status, out = facade_call('entity_get', {'entity_key': 'hero', 'chapter': 1}, headers={'Authorization': 'Bearer wrong'})
    assert status == 401 and out['errNo'] == 40101
    status, out = facade_call('entity_author_get', {'entity_key': 'hero', 'chapter': 1}, headers={'Authorization': 'Bearer atok'})
    assert out['errNo'] == 0
