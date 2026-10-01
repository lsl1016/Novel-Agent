"""Phase A 第二批回归:双时序 per-holder 披露与专业子图视图。"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService


def make(tmp):
    s = NovelService(Path(tmp) / 'story.db')
    s.store.upsert_thread('t', '主线', introduced_chapter=1)
    s.store.set_world_fact('sword_origin', '青霜剑是上古凶兵', 'secret', 400)
    s.entity_graph.upsert_entity('hero', 'Character', '林昭', 1)
    s.entity_graph.upsert_entity('villain', 'Character', '墨离', 1)
    s.entity_graph.upsert_entity('sword', 'Artifact', '青霜剑', 1)
    s.entity_graph.upsert_entity('sect', 'Faction', '青云宗', 1)
    s.entity_graph.upsert_entity('region', 'Location', '北荒', 1)
    s.entity_graph.upsert_entity('continent', 'Location', '东洲', 1)
    s.entity_graph.add_alias('sword', '凶兵之名', alias_type='title', secrecy='secret', fact_key='sword_origin')
    return s


def test_dual_time_visibility_and_gates(tmp_path):
    s = make(tmp_path)
    # 迁移回填:reveal_after=400 → reader 披露
    ds = s.fact_disclosures_get('sword_origin')
    assert any(d['holder'] == 'reader' and d['known_from_chapter'] == 400 for d in ds)
    # 反派第 1 章就知道
    s.fact_disclosure_set('sword_origin', 'villain', 1, channel='铸剑世家内幕')

    # 第 300 章:villain 持有者可见秘密别名,reader 不可见
    s.entity_graph.upsert_relation('hero', 'MEMBER_OF', 'sect', start_chapter=1)
    safe_v = s.entity_get('sword', 300, holder='villain')
    safe_r = s.entity_get('sword', 300, holder='reader')
    assert any(a['alias'] == '凶兵之名' for a in safe_v['aliases'])
    assert not any(a['alias'] == '凶兵之名' for a in safe_r['aliases'])
    # forbidden 清单:对 reader 隐藏、对 villain 不隐藏
    fr = s.world.forbidden_facts(300, 'reader')
    fv = s.world.forbidden_facts(300, 'villain')
    assert any(x['fact_key'] == 'sword_origin' for x in fr)
    assert not any(x['fact_key'] == 'sword_origin' for x in fv)
    # 第 400 章 reader 公开
    assert not any(x['fact_key'] == 'sword_origin' for x in s.world.forbidden_facts(400, 'reader'))

    # 计划门:第 300 章向 villain 揭示合法,向 reader 揭示是 WORLD_TRUTH_LEAK
    r = s.chapter_plan_check(300, {'reveals': [{'fact_key': 'sword_origin', 'thread_key': 't_sword', 'content': '剑之来历揭示', 'recipients': ['villain']}]})
    assert r['ok']
    r = s.chapter_plan_check(300, {'reveals': [{'fact_key': 'sword_origin', 'thread_key': 't_sword', 'content': '剑之来历揭示', 'recipients': ['reader']}]})
    assert not r['ok'] and any(e['code'] == 'WORLD_TRUTH_LEAK' for e in r['errors'])
    r = s.chapter_plan_check(400, {'reveals': [{'fact_key': 'sword_origin', 'thread_key': 't_sword', 'content': '剑之来历揭示', 'recipients': ['reader']}]})
    assert r['ok']

    # 正文门只认 reader 时刻:POV=villain 也写不出真相(读者会读到正文)
    leak = s._body_secret_leak_check(300, '青霜剑是上古凶兵', 'villain', {})
    assert not leak['ok']
    leak = s._body_secret_leak_check(400, '青霜剑是上古凶兵', 'reader', {})
    assert leak['ok']
    # 覆盖:更早的 reader 披露生效
    s.fact_disclosure_set('sword_origin', 'reader', 350)
    assert s._body_secret_leak_check(350, '青霜剑是上古凶兵', 'reader', {})['ok']


def test_power_and_artifact_subgraphs(tmp_path):
    s = make(tmp_path)
    e1 = s.event_create('剑冢试炼', 5, event_key='ev_trial', participants=[{'entity_key': 'hero', 'participant_role': 'actor'}])['event']
    e2 = s.event_create('凶兵反噬', 12, event_key='ev_backlash', cause_event_key='ev_trial')['event']
    s.entity_attribute_set('hero', 'realm', '炼气', chapter=1, cause_event_id=e1['id'])
    s.entity_attribute_set('hero', 'realm', '筑基', chapter=12, cause_event_id=e2['id'])
    s.entity_attribute_set('hero', 'bloodline', '剑体', chapter=1)
    pw = s.power_context_get('hero', 12)
    assert pw['current_power_state'] == {'realm': '筑基', 'bloodline': '剑体'}
    ladder = [d for d in pw['progression_ladders'] if d['attr_key'] == 'realm']
    assert [(d['value'], d['cause_event']['event_key']) for d in ladder] == [('炼气', 'ev_trial'), ('筑基', 'ev_backlash')]

    # 法宝持有沿革:hero → 归还 → villain,每段带事件
    s.entity_relation_upsert('hero', 'OWNS', 'sword', start_chapter=5, cause_event_id=e1['id'])
    s.entity_relation_end('hero', 'OWNS', 'sword', 30)
    s.entity_relation_upsert('villain', 'OWNS', 'sword', start_chapter=30, cause_event_id=e2['id'])
    ah = s.artifact_history_get('sword')
    owns = [r for r in ah['custody_and_state'] if r['relation_type'] == 'OWNS']
    assert [(r['source_entity_key'], r['start_chapter'], r['end_chapter']) for r in owns] == [('hero', 5, 30), ('villain', 30, None)]
    assert owns[0]['cause_event']['event_key'] == 'ev_trial'


def test_geography_tree(tmp_path):
    s = make(tmp_path)
    s.fact_disclosure_set('sword_origin', 'villain', 1)
    s.entity_graph.upsert_entity('hidden_valley', 'Location', '隐谷', 1)
    s.entity_relation_upsert('sect', 'LOCATED_IN', 'region', start_chapter=0)
    s.entity_relation_upsert('region', 'LOCATED_IN', 'continent', start_chapter=0)
    s.entity_relation_upsert('hidden_valley', 'LOCATED_IN', 'region', start_chapter=0, secrecy='secret', fact_key='sword_origin')
    tree = s.geography_tree_get('continent', 100)
    keys = {n['entity_key'] for n in tree['nodes']}
    assert {'continent', 'region', 'sect'} <= keys
    assert 'hidden_valley' not in keys, 'secret location must be filtered for reader'
    tree_v = s.geography_tree_get('continent', 100, holder='villain')
    assert 'hidden_valley' in {n['entity_key'] for n in tree_v['nodes']}, 'disclosed holder sees it'
    assert tree['depth_reached'] == 2
