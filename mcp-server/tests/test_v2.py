"""Entity Graph V2 核心回归:Identity/Role、一等 Event(参与者/因果链/追溯)、
Assertion/Evidence、检索接入与门禁不变量。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService


def make(tmp):
    s = NovelService(Path(tmp) / 'story.db')
    s.store.set_meta('main_goal', '测试主线')
    s.store.upsert_thread('t_main', '主线', introduced_chapter=1)
    s.store.set_world_fact('elder_identity', '灰袍老者即掌门', 'secret', 400)
    s.entity_graph.upsert_entity('hero', 'Character', '林昭', 1)
    s.entity_graph.upsert_entity('elder', 'Character', '灰袍老者', 1)
    s.entity_graph.upsert_entity('sect', 'Faction', '青云宗', 1)
    return s


def test_identity_profiles_visibility_and_chain(tmp_path):
    s = make(tmp_path)
    s.identity_profile_set({'profile_key': 'p_name', 'entity_key': 'hero', 'kind': 'name', 'value': '林昭'})
    s.identity_profile_set({'profile_key': 'p_disguise', 'entity_key': 'hero', 'kind': 'disguise',
                            'value': '墨坊学徒', 'secrecy': 'secret', 'fact_key': 'elder_identity'})
    s.identity_profile_set({'profile_key': 'p_prev_life', 'entity_key': 'hero', 'kind': 'incarnation', 'value': '上古剑主'})
    s.identity_profile_set({'profile_key': 'p_role', 'entity_key': 'hero', 'kind': 'role', 'value': '外门弟子', 'scope_key': 'sect',
                            'start_chapter': 1, 'end_chapter': 30})
    try:
        s.identity_profile_set({'profile_key': 'p_bad', 'entity_key': 'hero', 'kind': 'throne', 'value': 'x'})
    except ValueError:
        pass
    else:
        raise AssertionError('kind must be validated')

    safe = s.entity_get('hero', 50)
    kinds = {p['kind'] for p in safe['identity_profiles']}
    assert kinds == {'name', 'incarnation'}, f'secret disguise must be filtered, got {kinds}'
    author = s.entity_author_get('hero', 50)
    assert {p['kind'] for p in author['identity_profiles']} == {'name', 'disguise', 'incarnation'}
    # chapter 切片:第 31 章起 role 窗口关闭
    assert all(p['profile_key'] != 'p_role' for p in s.entity_get('hero', 31)['identity_profiles'])
    assert any(p['profile_key'] == 'p_role' for p in s.entity_get('hero', 30)['identity_profiles'])


def test_first_class_events_chain_and_traceability(tmp_path):
    s = make(tmp_path)
    e1 = s.event_create('师父遇袭', 12, event_key='ev_ambush', location_key='sect',
                        participants=[{'entity_key': 'elder', 'participant_role': 'victim'},
                                      {'entity_key': 'hero', 'participant_role': 'witness'}],
                        outcome='长老重伤', consequence='宗门戒严')
    assert e1['ok']
    e2 = s.event_create('主角接任', 20, event_key='ev_succession', cause_event_key='ev_ambush',
                        participants=[{'entity_key': 'hero', 'participant_role': 'successor'}])
    ev = s.event_get(event_key='ev_succession')
    assert ev['cause_chain'][0]['event_key'] == 'ev_ambush'
    root = s.event_get(event_key='ev_ambush')
    assert {p['entity_key'] for p in root['participants']} == {'elder', 'hero'}
    assert [x['event_key'] for x in root['caused_events']] == ['ev_succession']

    # 状态变化挂事件:境界提升可追溯到 ev_succession
    s.entity_attribute_set('hero', 'realm', '筑基', chapter=20, cause_event_id=ev['id'])
    s.entity_relation_upsert('hero', 'MEMBER_OF', 'sect', start_chapter=20, cause_event_id=ev['id'])
    got = s.entity_author_get('hero', 20)
    assert got['attributes']['realm']['cause_event_id'] == ev['id']
    rel = [r for r in got['relations'] if r['relation_type'] == 'MEMBER_OF'][0]
    assert rel['cause_event_id'] == ev['id']
    try:
        s.entity_attribute_set('hero', 'realm', '金丹', chapter=25, cause_event_id=99999)
    except KeyError:
        pass
    else:
        raise AssertionError('ghost cause_event_id must be rejected')

    tl = s.event_timeline(entity_key='hero', from_chapter=10, to_chapter=25)
    assert [x['event_key'] for x in tl] == ['ev_ambush', 'ev_succession']
    # 幽灵参与者被外键拒绝
    try:
        s.event_create('坏事件', 21, participants=[{'entity_key': 'ghost'}])
    except KeyError:
        pass
    else:
        raise AssertionError('ghost participant must be rejected')
    # event_key 幂等重放:同名键更新而非重复插入
    s.event_create('师父遇袭(补记)', 12, event_key='ev_ambush')
    tl2 = s.event_timeline(entity_key='elder')
    assert len(tl2) == 1 and tl2[0]['name'].startswith('师父遇袭')


def test_assertion_lifecycle(tmp_path):
    s = make(tmp_path)
    a1 = s.assertion_create('elder', 'identity', '灰袍老者即掌门', chapter=15,
                            extractor='semantic_llm_v2', confidence=0.7, evidence='长老自称掌门私印')
    assert a1['truth_status'] == 'candidate'
    a2 = s.assertion_create('elder', 'identity', '灰袍老者是掌门胞弟', chapter=15, extractor='semantic_llm_v2')
    assert s.assertion_list(subject_key='elder', truth_status='candidate') and len(s.assertion_list(subject_key='elder')) == 2
    # 被取代必须给出替换目标
    try:
        s.assertion_resolve(a2['assertion_id'], 'superseded')
    except ValueError:
        pass
    else:
        raise AssertionError('supersede requires superseded_by')
    r = s.assertion_resolve(a2['assertion_id'], 'superseded', superseded_by=a1['assertion_id'])
    assert r['ok']
    sup = [x for x in s.assertion_list(subject_key='elder') if x['assertion_id'] == a2['assertion_id']][0]
    assert sup['truth_status'] == 'superseded' and sup['superseded_by'] == a1['assertion_id']
    assert s.assertion_resolve(a1['assertion_id'], 'confirmed')['ok']
    try:
        s.assertion_resolve(a1['assertion_id'], 'disproved')
    except ValueError:
        pass
    else:
        raise AssertionError('terminal assertion cannot be re-resolved')


def test_candidate_promote_records_assertion(tmp_path):
    s = make(tmp_path)
    cid = s.candidates.add(9, 'Character', '灰袍老者', {
        'node': {'id': 'n1', 'type': 'Character', 'name': '灰袍老者', 'confidence': 0.8,
                 'status': 'candidate', 'properties': {'extractor': 'semantic_llm_v2', 'evidence': '茶棚老者目击'}}})
    pr = s.candidate_promote(cid)
    rows = s.assertion_list(subject_key=pr['applied']['entity'], predicate='identity')
    assert len(rows) == 1
    a = rows[0]
    assert a['truth_status'] == 'confirmed' and a['chapter'] == 9 and a['confidence'] == 0.8
    assert a['source_span'] == f'candidate:{cid}'


def test_event_anchors_flow_into_retrieval(tmp_path):
    s = make(tmp_path)
    s.event_create('夺剑', 5, event_key='ev_sword', participants=[{'entity_key': 'elder', 'participant_role': 'guard'}])
    plan = {'primary_goal': 'x', 'entities': [], 'events': [{'event_key': 'ev_sword'}], '_planning_runtime': True}
    out = s.context_compiler.entity_retrieve_relevant(6, 'writer', 'reader', plan, limit=10)
    hit = [x for x in out['items'] if x['entity_key'] == 'elder']
    assert hit and any('planned event ev_sword' in r for r in hit[0]['reasons'])


def test_declared_events_are_rich_and_atomic(tmp_path):
    s = make(tmp_path)
    updates = {'events': [{'name': '夜探藏经阁', 'event_key': 'ev_sneak', 'chapter': 8, 'location_key': 'sect',
                           'participants': [{'entity_key': 'hero', 'participant_role': 'actor'}],
                           'outcome': '取得残页'}]}
    r = s.chapter_commit(8, '夜探', '正文。', '卷一', 'hero', '', updates, False)
    assert r['committed']
    ev = s.event_get(event_key='ev_sneak')
    assert ev['participants'][0]['entity_key'] == 'hero' and ev['outcome'] == '取得残页'
    # 重放同一 event_key 幂等
    s.chapter_commit(8, '夜探', '正文(修订)。', '卷一', 'hero', '', updates, False)
    assert len(s.event_timeline(entity_key='hero')) == 1
