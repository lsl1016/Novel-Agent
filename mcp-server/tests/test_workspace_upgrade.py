"""Book isolation, version evidence and public workspace workflows."""
import json
import sqlite3
import threading
import time

from test_web_api import seed, start_server, get, post, raw
from novel_mcp import web_api
from novel_mcp.architect_ai import interview
from novel_mcp.service import NovelService


def test_book_scopes_reads_writes_jobs_and_stream(tmp_path, monkeypatch):
    monkeypatch.setenv('NOVEL_BOOKS_DIR', str(tmp_path))
    default, _ = seed(tmp_path)
    other = NovelService(tmp_path / 'other.db')
    web_api._SERVICE_CACHE[str((tmp_path / 'other.db').resolve())] = other
    other.planning.chapter_plan_put(2, {'pov': 'hero', 'summary': '另一书'}, None,
                                   'hero', 'draft', 'ready', {'ok': True, 'errors': [], 'warnings': []})
    run = other.novel_run_start(start_chapter=2, target_chapter=3, require_semantic=False,
                               auto_plan=False, stop_on_pressure=False)['run']['run_id']
    other.runs._event(run, 'plan', 'ready', 2, {'note': '另一书的事件'})
    other.runs._open_decision(run, 2, 'author_question', '另一书的问题', {})
    entered, release = threading.Event(), threading.Event()

    def interview_job(idea, options=None):
        entered.set()
        release.wait(3)
        return {'questions': [{'question': '只属于另一书'}]}

    monkeypatch.setattr(other, 'story_architect_interview', interview_job)
    for base in start_server(tmp_path, default):
        _, out = post(base, '/api/v1/actions/chapter_draft_save?book=other',
                      {'chapter': 2, 'title': '另一本书', 'body': '隔离正文。'})
        assert out['errNo'] == 0
        assert default.writing.get_draft(2)['body'] == '草稿正文。'
        assert other.writing.get_draft(2)['body'] == '隔离正文。'
        assert get(base, '/api/v1/chapter/2/draft/1?book=other')[1]['title'] == '另一本书'
        assert get(base, '/api/v1/chapter/2/draft/1')[1]['title'] == '第二章草稿'
        assert get(base, '/api/v1/settings?book=other')[1]['book']['db'] == str(other.store.path)
        _, explicit_default = post(base, '/api/v1/actions/blueprint_update?book=',
                                   {'book': 'other', 'patch': {'title': '只修改默认书'}})
        assert explicit_default['errNo'] == 0
        assert default.blueprint_get()['blueprint']['title'] == '只修改默认书'
        assert (other.blueprint_get()['blueprint'] or {}).get('title') != '只修改默认书'
        did = other.runs.decisions(run)[0]['decision_id']
        post(base, f'/api/v1/runs/{run}/decisions/{did}/answer?book=other',
             {'answers': [{'question': '另一书的问题', 'answer': '另一书的答案'}]})
        assert other.blueprint_get()['blueprint']['author_decisions'][0]['answer'] == '另一书的答案'
        assert not (default.blueprint_get().get('blueprint') or {}).get('author_decisions')
        assert '另一书的事件' in raw(base, f'/api/v1/stream/runs/{run}?once=1&book=other')[1]
        _, job = post(base, '/api/v1/jobs/story_architect_interview?book=other', {'args': {'idea': '测试'}})
        assert entered.wait(2)
        get(base, '/api/v1/home')  # switching reads cannot retarget the job
        release.set()
        for _ in range(30):
            result = get(base, '/api/v1/jobs/' + job['job']['id'])[1]
            if result['status'] != 'running': break
            time.sleep(.02)
        assert result['status'] == 'done'
        assert result['result']['questions'][0]['question'] == '只属于另一书'
        _, unknown = post(base, '/api/v1/actions/web_home?book=other', {})
        assert unknown['errNo'] == 40401


def test_reviews_are_bound_to_selected_version_and_keep_evidence(tmp_path):
    svc, _ = seed(tmp_path)
    svc.writing.replace_reviews(2, 1, [{'reviewer_type': 'continuity', 'verdict': 'BLOCK',
                                      'findings': [{'code': 'QUOTE', 'message': '请核对',
                                                    'evidence': '草稿正文。', 'suggestion': '保持连续性'}]}])
    svc.chapter_draft_save(2, '第二版', '修改后的正文', parent_version=1)
    with_version = svc.web_chapter(2, 1)
    assert with_version['reviewed_version'] == 1
    assert with_version['review_details'][0]['findings'][0]['evidence'] == '草稿正文。'
    assert svc.web_chapter(2)['review_details'] == []
    assert svc.web_chapter(2)['gate']['ready'] is False
    assert svc.web_reviews(1, 2)['chapters'][0]['reviews'][0]['findings'][0]['suggestion'] == '保持连续性'
    assert svc.web_reviews(1, 2)['chapters'][0]['latest_draft_version'] == 2


def test_library_scans_copied_wal_books_and_uri_characters(tmp_path, monkeypatch):
    svc, _ = seed(tmp_path)
    library = tmp_path / 'library'
    library.mkdir()
    copy = library / 'book#2.db'
    with svc.store.connect() as source:
        dest = sqlite3.connect(copy)
        source.backup(dest)
        dest.close()
    monkeypatch.setenv('NOVEL_BOOKS_DIR', str(library))
    monkeypatch.setenv('NOVEL_STORY_DB', str(copy))
    books = web_api.list_books()
    assert len(books) == 1
    assert books[0]['name'] == 'book#2.db'
    assert books[0]['default'] is True
    assert books[0]['chapters'] == 1


def test_home_counts_only_latest_active_drafts(tmp_path):
    svc, _ = seed(tmp_path)
    svc.chapter_draft_save(2, '新版本', '新的草稿', parent_version=1)
    assert svc.web_home()['inbox']['active_draft_chapters'] == 1
    assert svc.web_plan()['chapter_plans'][0]['active_draft'] == 1
    with svc.store.connect() as db:
        db.execute("UPDATE chapter_drafts SET status='committed' WHERE chapter=2 AND version=2")
    assert svc.web_home()['inbox']['active_draft_chapters'] == 0
    assert svc.web_plan()['chapter_plans'][0]['active_draft'] == 0


def test_interview_and_architecture_snapshot_are_nonmutating(tmp_path):
    svc, _ = seed(tmp_path)
    def model(system, user):
        assert json.loads(user)['idea'] == '记忆质检员'
        return {'questions': [{'question': '她最想救谁？', 'options': ['自己', '家人']}] * 7}
    result = interview('记忆质检员', {'genre': '悬疑'}, call=model)
    assert len(result['questions']) == 4
    before = svc.store.path.read_bytes()
    snapshot = svc.web_architecture()
    assert snapshot['world_facts'][0]['truth'] == '真相值'
    assert snapshot['entities'][0]['entity_key'] == 'hero'
    assert snapshot['threads'][0]['target_min_chapter'] == 10
    assert svc.store.path.read_bytes() == before


def test_duplicate_run_jobs_reuse_active_job(tmp_path, monkeypatch):
    svc, run_id = seed(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def continue_run(run_id, max_steps=5):
        calls.append(run_id)
        entered.set()
        release.wait(3)
        return {'ok': True}
    monkeypatch.setattr(svc, 'novel_run_continue', continue_run)
    for base in start_server(tmp_path, svc):
        _, a = post(base, '/api/v1/jobs/novel_run_continue', {'args': {'run_id': run_id}})
        assert entered.wait(2)
        _, b = post(base, '/api/v1/jobs/novel_run_continue', {'args': {'run_id': run_id}})
        assert a['job']['id'] == b['job']['id']
        assert calls == [run_id]
        release.set()
