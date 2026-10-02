"""Story Architect 四段生成器离线测试(stub LLM,设计稿 §12 第二行)。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.architect_ai import generate, scale_params

T = 90

S1 = {
    'blueprint': {'title': '测试书', 'genre': '测试', 'tone': '冷峻', 'core_promise': '承诺',
                  'protagonist': 'hero', 'narrative_voice': '第三', 'chapter_length_target': 2000,
                  'hard_constraints': ['真相不得早于第80章揭示']},
    'world_facts': [{'fact_key': 'f_final', 'truth': '终局真相', 'secrecy': 'secret', 'reveal_after': 88}],
    'assumptions': ['题材按都市处理'],
    'author_decisions': [{'question': '主角成长节奏?', 'answer': '前期压制'}],
}

S2 = {
    'entities': [
        {'entity_key': 'hero', 'entity_type': 'Character', 'name': '主角', 'chapter': 1, 'description': ''},
        {'entity_key': 'mentor', 'entity_type': 'Character', 'name': '师长', 'chapter': 1, 'description': ''},
        {'entity_key': 'org_a', 'entity_type': 'Faction', 'name': '势力甲', 'chapter': 1, 'description': ''},
        {'entity_key': 'city', 'entity_type': 'Location', 'name': '城', 'chapter': 1, 'description': ''},
    ],
    'identity_profiles': [{'profile_key': 'p1', 'entity_key': 'hero', 'kind': 'incarnation',
                           'value': '隐姓', 'secrecy': 'secret', 'fact_key': 'f_final', 'start_chapter': 1}],
    'entity_attributes': [{'entity_key': 'hero', 'attr_key': 'realm', 'value': '练气', 'chapter': 1}],
    'entity_relations': [{'source_entity_key': 'mentor', 'relation_type': 'MASTER_OF', 'target_entity_key': 'hero', 'start_chapter': 1}],
}

S3_BAD = {
    'threads': [{'thread_key': 't_main', 'name': '主线', 'thread_type': 'mystery', 'introduced_chapter': 1,
                 'target_min_chapter': 1, 'target_max_chapter': 85, 'main_goal': ''},
                {'thread_key': 't_bond', 'name': '羁绊', 'thread_type': 'relationship', 'introduced_chapter': 2,
                 'target_min_chapter': 2, 'target_max_chapter': 60, 'main_goal': ''}],
    'mysteries': [{'mystery_key': 'm1', 'name': '谜', 'thread_key': 't_ghost', 'introduced_chapter': 2,
                   'target_min_chapter': 30, 'target_max_chapter': 80}],
    'emotion_debts': [{'debt_key': 'd1', 'thread_key': 't_main', 'name': '债', 'emotion_type': '愧疚',
                       'intensity': 0.5, 'created_chapter': 3}],
    'narrative_entity_links': [{'narrative_type': 'thread', 'narrative_key': 't_main', 'entity_key': 'hero',
                                'role': 'protagonist', 'chapter': 1}],
}

S3 = {**S3_BAD, 'mysteries': [{**S3_BAD['mysteries'][0], 'thread_key': 't_main'}]}

S4 = {
    'arcs': [
        {'arc_key': 'arc1', 'name': '一', 'order_no': 1, 'start_chapter': 1, 'target_end_chapter': 12,
         'primary_goal': '', 'surface_conflict': '', 'forbidden_facts': [], 'inherited_thread_keys': ['t_main'],
         'exit_conditions': ['条件']},
        {'arc_key': 'arc2', 'name': '二', 'order_no': 2, 'start_chapter': 13, 'target_end_chapter': 85,
         'primary_goal': '', 'surface_conflict': '', 'forbidden_facts': ['f_final'],
         'inherited_thread_keys': ['t_main'], 'exit_conditions': ['条件']},
    ],
    'milestones': [{'milestone_key': 'ms1', 'arc_key': 'arc1', 'name': '初门', 'min_chapter': 5, 'max_chapter': 11,
                    'thread_keys': ['t_main']}],
    'thread_schedule': [{'schedule_key': 'sch1', 'thread_key': 't_main', 'stage_type': 'Clue',
                         'min_chapter': 4, 'max_chapter': 9, 'purpose': ''}],
    'replace_blueprint': False,
}


def test_scale_params_formula():
    sp = scale_params(300)
    assert sp['arc_count'] == 7 and 12 <= sp['first_arc_length'] <= 25 and 5 <= sp['thread_count'] <= 10
    assert sp['final_reveal_window'][0] == 180
    assert scale_params(20)['arc_count'] == 4  # 下限保护


def test_generate_converges_with_stage_retry():
    calls = []

    def fake_call(system, user):
        calls.append((system, user))
        if '结构设计师' in system:
            return S1
        if 'Architect(实体层)' in system:
            return S2
        if 'Architect(叙事层)' in system:
            return S3 if any('上一轮输出存在以下错误' in (u or '') for _, u in calls[:-1]) else S3_BAD
        if 'Architect(结构层)' in system:
            return S4
        return S4  # 修复轮兜底

    r = generate('一句创意', {'target_total_chapters': T}, call=fake_call)
    assert r['ok'], r['validation']['errors']
    assert r['architecture']['blueprint']['title'] == '测试书'
    # 段内重试确实发生:S3 至少被调了两次
    assert sum(1 for sysp, _ in calls if 'Architect(叙事层)' in sysp) >= 2
    # 注册表传递:author_decisions 从 S1 预置进 blueprint
    assert any(d.get('question') == '主角成长节奏?' for d in r['architecture']['blueprint'].get('author_decisions', []))
    # 假设被收集
    assert r['assumptions'] == ['题材按都市处理']


def test_repair_loop_fixes_cross_stage_error():
    """S3/S4 都各自合法,但跨段约束(债超首弧)要靠 S5 修复回路。"""
    state = {'repair_called': False}

    s3_late = {**S3, 'emotion_debts': [{**S3['emotion_debts'][0], 'created_chapter': 60}]}  # > 首弧 12

    def fake_call(system, user):
        if '结构设计师' in system:
            return S1
        if 'Architect(实体层)' in system:
            return S2
        if 'Architect(叙事层)' in system:
            return s3_late
        if 'Architect(结构层)' in system:
            return S4
        state['repair_called'] = True
        return {'emotion_debts': [{**s3_late['emotion_debts'][0], 'created_chapter': 8}]}

    r = generate('一句创意', {'target_total_chapters': T}, call=fake_call)
    assert state['repair_called'], '跨段错误必须触发修复轮'
    assert r['ok'], r['validation']['errors']
    assert r['repair_rounds'] == 1
    assert r['architecture']['emotion_debts'][0]['created_chapter'] == 8


def test_generate_then_apply_full_chain(tmp_path):
    """M3 验收核心:生成物必须能被确定性 apply 直接接受。"""
    from novel_mcp.service import NovelService
    REF = Path(__file__).resolve().parents[2] / 'reference-example'
    svc = NovelService(tmp_path / 'story.db', REF, '/mnt/data/narrative-kg')

    def fake_call(system, user):
        if '结构设计师' in system:
            return S1
        if 'Architect(实体层)' in system:
            return S2
        if 'Architect(叙事层)' in system:
            return S3
        return S4

    r = generate('一句创意', {'target_total_chapters': T}, call=fake_call)
    assert r['ok'], r['validation']['errors']
    dry = svc.story_architect_apply(r['architecture'], dry_run=True)
    assert dry['ok'], dry['errors']
    applied = svc.story_architect_apply(r['architecture'])
    assert applied['ok'], applied['errors']
    assert applied['applied']['threads'] == 2 and applied['applied']['arcs'] == 2
    st = svc.story_get_state(5)
    assert any(t['thread_key'] == 't_main' for t in st['active_threads'])
