from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService

REF = Path(__file__).resolve().parents[2] / 'reference-example'


def make(tmp_path):
    s = NovelService(tmp_path / 'story.db', REF, None)
    s.blueprint_update({'genre': '玄幻', 'core_promise': '长线身份谜题', 'protagonist': 'hero'})
    s.entity_upsert('hero', 'Character', '林渊', 1)
    s.entity_upsert('father', 'Character', '黑衣人', 1)
    s.entity_upsert('north', 'Location', '北境城', 1)
    s.entity_upsert('south', 'Location', '南荒城', 1)
    s.entity_upsert('sword', 'Artifact', '无名古剑', 1)
    s.entity_relation_upsert('hero', 'LOCATED_IN', 'north', 1, 50)
    s.entity_relation_upsert('hero', 'LOCATED_IN', 'south', 51)
    s.entity_relation_upsert('hero', 'OWNS', 'sword', 1)
    s.store.set_world_fact('father_identity', '玄冥圣君', 'secret', 500)
    s.store.add_belief(fact_key='father_identity', holder='reader', chapter=0, stance='unknown', value=None)
    s.store.add_belief(fact_key='father_identity', holder='hero', chapter=0, stance='believes', value='父亲已死')
    s.entity_alias_add('father', '玄冥圣君', 'true_identity', 'secret', 500, 'father_identity')
    s.entity_relation_upsert('father', 'PARENT_OF', 'hero', 1, secrecy='secret', reveal_after=500, fact_key='father_identity')
    s.store.upsert_thread('hero_origin', '主角身世', introduced_chapter=1, target_min=300, target_max=600)
    s.store.add_stage('hero_origin', 2, 'Clue', '黑衣人留下旧纹章', visibility='reader', strength=.2)
    s.store.add_stage('hero_origin', 5, 'Reveal', '作者层隐藏备注', visibility='private_author', strength=.8)
    s.mystery_create(mystery_key='father_mystery', name='父亲真正身份', thread_key='hero_origin', introduced_chapter=1, target_min_chapter=300, target_max_chapter=600)
    s.narrative_entity_link('thread', 'hero_origin', 'hero', 'subject', 1)
    s.narrative_entity_link('thread', 'hero_origin', 'father', 'mystery_subject', 1)
    s.narrative_entity_link('thread', 'hero_origin', 'sword', 'clue_carrier', 2)
    s.arc_plan_create({'arc_key': 'arc1', 'name': '北境篇', 'start_chapter': 1, 'target_end_chapter': 200, 'primary_goal': '调查身世', 'inherited_thread_keys': ['hero_origin'], 'forbidden_facts': ['father_identity']})
    return s


def save_plan(s, chapter):
    return s.chapter_plan_save(chapter, {
        'primary_goal': '追查黑衣人与古剑的关系',
        'arc_key': 'arc1',
        'pov': 'hero',
        'entity_keys': ['hero', 'father', 'sword'],
        'threads': {'advance': ['hero_origin'], 'maintain': [], 'sleep': []},
        'forbidden_truths': ['father_identity'],
        'clues': [{'thread_key': 'hero_origin', 'content': '古剑纹章再次出现', 'strength': .2}],
    }, 'hero', 'arc1')


def test_writer_compile_is_safe_and_relevant(tmp_path):
    s = make(tmp_path); save_plan(s, 40)
    out = s.context_compile(40, 'writer', 'hero', max_tokens=6000, persist=False)
    raw = json.dumps(out, ensure_ascii=False)
    assert '玄冥圣君' not in raw
    assert 'PARENT_OF' not in raw
    entities = out['context']['entity_context']['items']
    keys = [x['entity_key'] for x in entities]
    assert keys[0] in {'hero', 'father', 'sword'}
    assert 'hero' in keys and 'sword' in keys
    hero = next(x for x in entities if x['entity_key'] == 'hero')
    assert any(r['relation_type'] == 'LOCATED_IN' and r['target_entity_key'] == 'north' for r in hero['entity']['relations'])
    threads = out['context']['narrative_context']['items']
    assert threads and threads[0]['thread_key'] == 'hero_origin'
    serialized_stages = json.dumps(threads[0]['recent_stages'], ensure_ascii=False)
    assert '作者层隐藏备注' not in serialized_stages


def test_time_slice_changes_location(tmp_path):
    s = make(tmp_path)
    save_plan(s, 40)
    a = s.entity_retrieve_relevant(40, 'writer', 'hero')
    hero_a = next(x for x in a['items'] if x['entity_key'] == 'hero')['entity']
    assert any(r['target_entity_key'] == 'north' for r in hero_a['relations'] if r['relation_type'] == 'LOCATED_IN')
    save_plan(s, 60)
    b = s.entity_retrieve_relevant(60, 'writer', 'hero')
    hero_b = next(x for x in b['items'] if x['entity_key'] == 'hero')['entity']
    assert any(r['target_entity_key'] == 'south' for r in hero_b['relations'] if r['relation_type'] == 'LOCATED_IN')
    assert not any(r['target_entity_key'] == 'north' for r in hero_b['relations'] if r['relation_type'] == 'LOCATED_IN')


def test_planner_compile_can_see_author_truth_and_reference_structure(tmp_path):
    s = make(tmp_path); save_plan(s, 40)
    out = s.context_compile(40, 'planner', max_tokens=12000, include_reference=True, persist=False)
    raw = json.dumps(out, ensure_ascii=False)
    assert '玄冥圣君' in raw
    assert 'PARENT_OF' in raw
    refs = out['context']['reference_patterns']
    assert refs
    assert all(x.get('source') == 'REFERENCE_GRAPH_STRUCTURE_ONLY' for x in refs)


def test_context_budget_and_preview(tmp_path):
    s = make(tmp_path); save_plan(s, 40)
    for i in range(80):
        key = f'npc{i}'
        s.entity_upsert(key, 'Character', f'路人{i}', 1, description='普通路人' * 20)
        s.entity_relation_upsert('hero', 'KNOWS', key, 1)
    out = s.context_compile(40, 'writer', 'hero', max_tokens=3000, persist=False)
    assert out['budget']['estimated_tokens'] <= 3000 or out['budget']['over_budget']
    # 编译器应裁掉排名靠后的图谱噪音,而不是把所有邻居都加载进来。
    assert len(out['context']['entity_context']['items']) < 80
    preview = s.context_preview(40, 'writer', 'hero', 3000)
    assert preview['counts']['entities'] == len(out['context']['entity_context']['items'])
    assert preview['top_entities']


def test_snapshot_and_explain_are_auditable(tmp_path):
    s = make(tmp_path); save_plan(s, 40)
    out = s.context_compiler.compile(40, 'writer', 'hero', max_tokens=6000, persist=True)
    snap = s.context_snapshot_get(out['snapshot_id'])
    assert snap['payload']['snapshot_id'] == out['snapshot_id']
    trace = out['retrieval_trace']
    assert trace
    item_key = trace[0]['item_key']
    ex = s.context_explain(out['snapshot_id'], item_key)
    assert ex['explanations'][0]['reasons']


def test_writer_context_uses_compiler_snapshot(tmp_path):
    s = make(tmp_path); save_plan(s, 40)
    ctx = s.writer_context_get(40)
    assert ctx['context_snapshot_id'].startswith('ctx_40_writer_')
    assert ctx['context_budget']['max_tokens'] == 12000
    assert ctx['entity_context']['ranking']
    snap = s.context_snapshot_get(ctx['context_snapshot_id'])
    assert snap['payload']['role'] == 'writer'
