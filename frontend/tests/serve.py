"""Isolated UI fixture. Never opens the user's story databases or calls an LLM."""
from pathlib import Path
import sys
import tempfile
import os

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp-server' / 'src'))
sys.path.insert(0, str(ROOT / 'mcp-server' / 'tests'))
from test_web_api import seed
from novel_mcp import runtime, web_api
from novel_mcp.service import NovelService


def make_fixture(folder, title, text):
    folder.mkdir(parents=True, exist_ok=True)
    svc, run_id = seed(folder)
    svc.blueprint_update({'title': title, 'genre': '东方幻想', 'core_promise': '找到自己的来处。'})
    svc.planning.arc_put({'arc_key': 'opening', 'name': '初入宗门', 'order_no': 1,
                         'start_chapter': 1, 'target_end_chapter': 20, 'primary_goal': '认识世界'})
    svc.chapter_draft_save(2, '未完的回声', text, parent_version=1)
    def review(chapter, version=None, semantic=True, **kwargs):
        draft = svc.writing.get_draft(chapter, version)
        svc.writing.replace_reviews(chapter, draft['version'], [
            {'reviewer_type': t, 'verdict': 'WARN' if t == 'continuity' else 'PASS',
             'findings': [{'code': 'EVIDENCE', 'message': '核对这里的人物动作',
                           'evidence': text.split('\n\n')[1], 'suggestion': '让动作衔接更自然。'}] if t == 'continuity' else []}
            for t in ('knowledge_leak', 'continuity', 'narrative', 'character')])
        return {'ok': True}
    review(2)
    svc.chapter_review_full = review
    def continue_run(run_id, max_steps=50):
        svc.runs._event(run_id, 'plan', 'ready', 2, {'note': '测试夹具已接收推进任务'})
        return {'ok': True}
    svc.novel_run_continue = continue_run
    svc.story_architect_interview = lambda **kw: {'questions': [{'question': '主角最想保护谁？', 'options': ['家人', '自己', '故乡']}]}
    svc.novel_architecture_generate = lambda **kw: {
        'architecture': {'blueprint': {'title': '回声之书', 'core_promise': '听见被遗忘的真相'},
                         'entities': [{'entity_key': 'hero', 'entity_type': 'Character', 'name': '林昭', 'chapter': 1}],
                         'arcs': [{'arc_key': 'opening', 'name': '初入宗门', 'order_no': 1,
                                   'start_chapter': 1, 'target_end_chapter': 20, 'primary_goal': '追踪回声'}]},
        'validation': {'errors': [], 'warnings': []}, 'assumptions': ['主角从故乡出发']}
    svc.runs.pause(run_id, '等待作者继续')
    return svc


with tempfile.TemporaryDirectory(prefix='novel-ui-fixture-') as directory:
    root = Path(directory)
    first = make_fixture(root / 'a', '青霜疑锋', '山门笼在晨雾里。\n\n林昭握住剑柄，向前走了一步。\n\n风从界墙另一边吹来。')
    second = make_fixture(root / 'b', '删除线之下', '雨水漫过路面。\n\n她重新打开那段被删去的记忆。\n\n陌生人的声音再次响起。')
    library = root / 'library'
    library.mkdir()
    # SQLite backup keeps WAL contents consistent without touching source fixtures.
    import sqlite3
    for name, svc in [('first', first), ('second', second)]:
        dest = sqlite3.connect(library / (name + '.db'))
        try:
            with svc.store.connect() as source:
                source.backup(dest)
        finally:
            dest.close()
    os.environ['NOVEL_BOOKS_DIR'] = str(library)
    os.environ['NOVEL_STORY_DB'] = str(library / 'first.db')
    runtime._SERVICE = first
    web_api._SERVICE_CACHE[str((library / 'first.db').resolve())] = first
    web_api._SERVICE_CACHE[str((library / 'second.db').resolve())] = second
    server = web_api.WebServer(('127.0.0.1', 8093), web_api.Handler)
    server.static_root = str(ROOT / 'frontend' / 'dist')
    print('UI fixture listening on :8093', flush=True)
    server.serve_forever()
