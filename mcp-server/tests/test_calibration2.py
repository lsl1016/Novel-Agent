"""第二轮校准回归:伏笔销账台账入 planner 上下文 + 短章确定性 WARN。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService

REF = Path(__file__).resolve().parents[2] / 'reference-example'


def make(tmp):
    return NovelService(Path(tmp) / 's.db', REF, '/mnt/data/narrative-kg')


def test_due_foreshadowing_in_planner_context(tmp_path):
    s = make(tmp_path)
    s.planning.blueprint_update({'chapter_length_target': 2000})
    s.store.upsert_thread('t1', '主线', introduced_chapter=1, target_min=50, target_max=80)
    s.clue_add('t1', 3, '第一条线索')
    s.clue_add('t1', 5, '第二条线索')
    s.planning.chapter_plan_put(7, {'primary_goal': '推进', 'pov': 'hero'}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    ctx = s.planner_context_get(7)
    due = ctx.get('due_foreshadowing') or []
    assert len(due) == 2
    assert all(c.get('callback_key') for c in due), 'planner 必须能拿到 callback_key 才能守销账纪律'
    assert due[0]['age'] == 4  # ch3 线索在 ch7 视角下 4 章未动


def test_payoff_without_callback_warn(tmp_path):
    s = make(tmp_path)
    s.store.upsert_thread('t1', '主线', introduced_chapter=1, target_min=1, target_max=90)
    s.clue_add('t1', 3, '线索')
    r = s.chapter_plan_check(10, {'payoffs': [{'thread_key': 't1', 'content': '兑现'}]})
    assert any(w['code'] == 'PAYOFF_WITHOUT_CALLBACK' for w in r['warnings'])
    r2 = s.chapter_plan_check(10, {'payoffs': [{'thread_key': 't1', 'content': '兑现', 'callback_key': 'stage_1'}]})
    assert not any(w['code'] == 'PAYOFF_WITHOUT_CALLBACK' for w in r2['warnings'])


def test_short_chapter_warn(tmp_path):
    s = make(tmp_path)
    s.planning.blueprint_update({'chapter_length_target': 2000})
    s.store.upsert_thread('t1', '主线', introduced_chapter=1, target_min=1, target_max=90)
    s.planning.chapter_plan_put(2, {'primary_goal': '推进', 'pov': 'hero', 'threads': {'advance': []}}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    s.chapter_draft_save(2, '短章', '太短', declared_updates={})
    rev = s._review_narrative(2, s.writing.get_draft(2), s.planning.chapter_plan_get(2))
    assert any(f['code'] == 'SHORT_CHAPTER' for f in rev['findings']) and rev['verdict'] == 'WARN'
