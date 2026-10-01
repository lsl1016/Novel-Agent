"""A0(可靠性地基)回归测试:迁移框架、外键、提交事务原子性、候选晋升闭环。"""
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService
from novel_mcp.store import StoryStore
from novel_mcp.schema import LATEST_VERSION, apply_migrations


def make_service(tmp):
    s = NovelService(Path(tmp) / 'story.db')
    s.store.set_meta('main_goal', '测试主线')
    s.store.upsert_thread('t_main', '主线', introduced_chapter=1)
    return s


def test_fresh_db_gets_latest_schema_version(tmp_path):
    s = make_service(tmp_path)
    with s.store.connect() as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
        cols = [r['name'] for r in db.execute('PRAGMA table_info(extraction_candidates)').fetchall()]
    assert version == LATEST_VERSION
    for col in ('resolution', 'resolved_at', 'promoted_target', 'review_note'):
        assert col in cols


def test_legacy_v07_db_upgrades_in_place(tmp_path):
    # 真实模拟 v0.7 遗留库:基线表已建、user_version=0、无 v2 列。
    import json as _json
    from novel_mcp.schema import MIGRATIONS
    db_path = Path(tmp_path) / 'story.db'
    raw = sqlite3.connect(db_path)
    raw.executescript('BEGIN;\n' + MIGRATIONS[0][2] + '\nCOMMIT;')
    raw.execute('INSERT INTO meta(key,value) VALUES(?,?)', ('main_goal', _json.dumps('测试主线', ensure_ascii=False)))
    raw.commit(); raw.close()
    s2 = NovelService(db_path)
    with s2.store.connect() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == LATEST_VERSION
        assert db.execute("SELECT value FROM meta WHERE key='main_goal'").fetchone()['value'].startswith('"测试主线"')
    assert s2.store.get_meta('main_goal') == '测试主线'


def test_foreign_keys_are_enforced(tmp_path):
    s = make_service(tmp_path)
    raised = False
    try:
        with s.store.connect() as db:
            db.execute("INSERT INTO entity_aliases(entity_key,alias) VALUES('ghost_entity','幽灵别名')")
    except sqlite3.IntegrityError:
        raised = True
    assert raised, 'declared FOREIGN KEY must be enforced on every connection'


def test_chapter_commit_is_atomic(tmp_path):
    s = make_service(tmp_path)
    # 形状合法、但应用时崩溃:alias 指向幽灵实体(形状校验放行,apply 时 KeyError)
    updates = {
        'events': [{'name': '正常事件', 'event_key': 'ev_ok'}],
        'entity_aliases': [{'entity_key': 'ghost_entity', 'alias': '幽灵别名'}],
    }
    try:
        s.chapter_commit(5, '半提交章', '正文。', '测试卷', 'hero', '', updates, False)
    except KeyError:
        pass
    else:
        raise AssertionError('expected mid-batch failure')
    assert s.canon.max_committed_chapter() is None, 'chapter row must not survive a rolled-back commit'
    with s.store.connect() as db:
        assert db.execute('SELECT COUNT(*) n FROM events').fetchone()['n'] == 0
        assert db.execute('SELECT COUNT(*) n FROM entity_aliases').fetchone()['n'] == 0


def test_candidate_promotion_lifecycle(tmp_path):
    s = make_service(tmp_path)
    s.candidates.add(7, 'Character', '灰袍老者', {
        'node': {'id': 'S2_0007_01_x', 'type': 'Character', 'name': '灰袍老者',
                 'confidence': 0.82, 'status': 'candidate',
                 'properties': {'extractor': 'semantic_llm_v2', 'evidence': '灰袍老者抬手拦下了去路'}}})
    rows = s.candidate_list(chapter=7)
    assert len(rows) == 1 and rows[0]['name'] == '灰袍老者'
    cid = rows[0]['id']

    r = s.candidate_promote(cid)
    assert r['ok'] and r['applied']['entity'].startswith('ext_character_')
    ent = s.entity_author_get(r['applied']['entity'], 7)
    assert ent['name'] == '灰袍老者' and ent['source'] == 'extraction_promote'
    ev = ent['properties']['evidence']
    assert ev['candidate_id'] == cid and ev['chapter'] == 7 and ev['confidence'] == 0.82

    assert s.candidate_list(status='candidate') == []
    promoted = s.candidate_list(status='promoted')
    assert len(promoted) == 1 and promoted[0]['promoted_target'] == r['applied']['entity']
    try:
        s.candidate_promote(cid)
    except ValueError:
        pass
    else:
        raise AssertionError('double promotion must fail')

    # 世界真相晋升路径 + 拒绝路径
    fid = s.candidates.add(9, 'Fact', '老者即宗主', {'node': {'id': 'x', 'type': 'Fact', 'name': '老者即宗主', 'confidence': 0.6, 'status': 'candidate', 'properties': {}}})
    r2 = s.candidate_promote(fid, {'kind': 'world_fact', 'fact_key': 'elder_identity', 'truth': '灰袍老者是宗主', 'reveal_after': 60})
    assert r2['applied'] == {'world_fact': 'elder_identity'}
    snap = s.belief_get('elder_identity', 10)
    assert snap['world_truth']['value'] == '灰袍老者是宗主' and snap['world_truth']['reveal_after'] == 60
    rid = s.candidates.add(11, 'Concept', '无关概念', {'node': {'id': 'y', 'type': 'Concept', 'name': '无关概念', 'confidence': 0.3, 'status': 'candidate', 'properties': {}}})
    assert s.candidate_reject(rid, reason='抽取误报')['ok']
    rejected = s.candidate_list(status='rejected')
    assert len(rejected) == 1 and rejected[0]['review_note'] == '抽取误报'


def test_migration_runner_is_idempotent(tmp_path):
    s = make_service(tmp_path)
    with s.store.connect() as db:
        apply_migrations(db)
        assert db.execute('PRAGMA user_version').fetchone()[0] == LATEST_VERSION
