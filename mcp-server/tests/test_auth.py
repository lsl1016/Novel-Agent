"""Public access regressions: legacy tokens cannot hide content or block tools."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.auth import auth_enabled, resolve_role, tool_allowed
from novel_mcp.tooldefs import TOOLS


def test_all_published_tools_are_public(monkeypatch):
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'writer:legacy,viewer:reader')
    monkeypatch.setenv('NOVEL_FACADE_TOKEN', 'old-admin')
    assert auth_enabled() is False
    for headers in ({}, {'Authorization': 'Bearer legacy'}, {'Authorization': 'Bearer wrong'}):
        assert resolve_role(headers) == ('admin', 0)
    for tool in TOOLS:
        assert tool_allowed('viewer', tool['name'], {}) == (True, None)


def test_public_facade_still_enforces_canonical_gate(tmp_path, monkeypatch):
    from novel_mcp import runtime
    from novel_mcp.http_compat import facade_call
    monkeypatch.setenv('NOVEL_STORY_DB', str(tmp_path / 'public.db'))
    monkeypatch.setenv('NOVEL_FACADE_TOKENS', 'writer:old-token')
    runtime._SERVICE = None
    try:
        svc = runtime.service()
        svc.entity_graph.upsert_entity('hero', 'Character', '林昭', 1)
        for headers in ({}, {'Authorization': 'Bearer wrong'}, {'Authorization': 'Bearer old-token'}):
            status, out = facade_call('entity_author_get', {'entity_key': 'hero', 'chapter': 1}, headers)
            assert status == 200 and out['errNo'] == 0 and out['data']['name'] == '林昭'
        status, out = facade_call('chapter_finalize', {'chapter': 1})
        assert out['errNo'] != 0
        assert svc.canon.max_committed_chapter() is None
        _, out = facade_call('__dict__', {})
        assert out['errNo'] == 40401
    finally:
        runtime._SERVICE = None
