"""architecture_check 跨引用校验器单测(设计稿 §12 第一行)。"""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.architecture_check import check

SEED = Path(__file__).resolve().parents[2] / 'scripts' / 'stress' / 'architecture.json'


def base():
    return {
        'blueprint': {'title': '测试书', 'protagonist': 'hero', 'tone': '冷峻'},
        'world_facts': [{'fact_key': 'f1', 'truth': '真相一', 'secrecy': 'secret', 'reveal_after': 95}],
        'entities': [{'entity_key': 'hero', 'entity_type': 'character', 'name': '主角', 'chapter': 1}],
        'threads': [{'thread_key': 't_main', 'name': '主线', 'introduced_chapter': 1, 'target_min_chapter': 1, 'target_max_chapter': 90}],
        'mysteries': [{'mystery_key': 'm1', 'name': '谜团', 'thread_key': 't_main', 'introduced_chapter': 2, 'target_min_chapter': 30, 'target_max_chapter': 80}],
        'emotion_debts': [{'debt_key': 'd1', 'thread_key': 't_main', 'name': '债', 'emotion_type': '愧疚', 'intensity': .5, 'created_chapter': 3}],
        'arcs': [
            {'arc_key': 'arc1', 'name': '一卷', 'order_no': 1, 'start_chapter': 1, 'target_end_chapter': 20, 'inherited_thread_keys': ['t_main']},
            {'arc_key': 'arc2', 'name': '二卷', 'order_no': 2, 'start_chapter': 21, 'target_end_chapter': 90, 'forbidden_facts': ['f1'], 'inherited_thread_keys': ['t_main']},
        ],
        'milestones': [{'milestone_key': 'ms1', 'arc_key': 'arc1', 'name': '门', 'min_chapter': 5, 'max_chapter': 18, 'thread_keys': ['t_main']}],
        'thread_schedule': [{'schedule_key': 's1', 'thread_key': 't_main', 'stage_type': 'Clue', 'min_chapter': 4, 'max_chapter': 8, 'purpose': '埋线'}],
        'narrative_entity_links': [{'narrative_type': 'thread', 'narrative_key': 't_main', 'entity_key': 'hero', 'role': 'protagonist', 'chapter': 1}],
    }


def codes(res, key='errors'):
    return [e['code'] for e in res[key]]


def test_golden_seed_zero_error():
    r = check(json.loads(SEED.read_text(encoding='utf-8')), {'target_total_chapters': 40})
    assert r['errors'] == [], r['errors']


def test_valid_base_has_no_errors():
    r = check(base(), {'target_total_chapters': 90})
    assert r['errors'] == []


def test_dangling_thread_arc_fact_protagonist():
    a = base()
    a['mysteries'][0]['thread_key'] = 't_ghost'
    a['arcs'][1]['inherited_thread_keys'] = ['t_ghost']
    a['arcs'][1]['forbidden_facts'] = ['f_ghost']
    a['milestones'][0]['arc_key'] = 'arc_ghost'
    a['blueprint']['protagonist'] = 'nobody'
    a['narrative_entity_links'][0]['narrative_key'] = 't_ghost'
    r = check(a)
    c = codes(r)
    assert c.count('XREF_THREAD') >= 3 and 'XREF_ARC' in c and 'XREF_FACT' in c and 'XREF_PROTAGONIST' in c


def test_window_containment():
    a = base()
    a['mysteries'][0]['target_max_chapter'] = 95   # 越出线程窗口 90
    a['milestones'][0]['max_chapter'] = 25         # 越出弧窗口 20
    a['thread_schedule'][0]['max_chapter'] = 30    # 越出首弧 20
    r = check(a)
    assert codes(r).count('WINDOW_CONTAIN') == 3


def test_reveal_order_and_debt_seedable_and_coverage():
    a = base()
    a['world_facts'][0]['reveal_after'] = 50  # 落在 forbidden 弧 [21,90] 内
    a['emotion_debts'][0]['created_chapter'] = 30  # > 首弧 20
    r = check(a, {'target_total_chapters': 200})  # 骨架只到 90 < 180
    c = codes(r)
    assert 'REVEAL_ORDER' in c and 'DEBT_SEEDABLE' in c and 'COVERAGE' in c


def test_arc_chaining_gap_and_first_arc_start():
    a = base()
    a['arcs'][1]['start_chapter'] = 30  # 前弧 20 结束,间隔 9 章 > 3
    r = check(a)
    assert 'XREF_ARC' in codes(r) and any('gap' in e['message'] for e in r['errors'])
    b = base()
    b['arcs'][0]['start_chapter'] = 3
    r2 = check(b)
    assert any(e['code'] == 'XREF_ARC' and 'chapter 1' in e['message'] for e in r2['errors'])


def test_known_keys_prevent_false_xref_on_incremental_apply():
    a = base()
    a['threads'] = []  # 本次 payload 不带线程,但库里有
    r = check(a, known={'threads': {'t_main'}})
    assert not any(e['code'] == 'XREF_THREAD' for e in r['errors'])


def test_warnings_and_callback_strip():
    a = base()
    a['blueprint'].pop('tone')
    a['thread_schedule'][0]['callback_key'] = 'stage_999'
    r = check(a, {})  # 无 tone
    w = codes(r, 'warnings')
    assert 'TONE_MISSING' in w and 'CLUE_CALLBACK' in w
    assert 'callback_key' not in a['thread_schedule'][0], '画蛇添足的 callback_key 必须被剥除'
