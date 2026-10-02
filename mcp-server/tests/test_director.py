# -*- coding: utf-8 -*-
"""导演位(v0.11):章节前人工引导 — 指令注入/steering 暂停/计划审核,全程无 LLM。"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from novel_mcp.service import NovelService

REF = Path(__file__).resolve().parents[2] / 'reference-example'


def make(tmp):
    s = NovelService(Path(tmp) / 'd.db', REF, '/mnt/data/narrative-kg')
    s.store.upsert_thread('t1', '主线', introduced_chapter=1, target_min=1, target_max=90)
    return s


def test_directive_set_get_consume_and_context(tmp_path):
    s = make(tmp_path)
    s.chapter_directive_set(2, '本章主角必须夜探界墙')
    assert s.chapter_directive_get(2)['directive'] == '本章主角必须夜探界墙'
    s.planning.chapter_plan_put(2, {'primary_goal': 'x', 'pov': 'hero'}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    ctx = s.planner_context_get(2)
    assert ctx['author_directive'] == '本章主角必须夜探界墙'
    s.chapter_directive_consume(2)
    assert s.chapter_directive_get(2) is None
    assert s.planner_context_get(2)['author_directive'] is None
    # 清除语义
    s.chapter_directive_set(2, '')
    assert s.chapter_directive_get(2) is None


def test_steering_pause_directive_resume_plan_review(tmp_path):
    s = make(tmp_path)
    s.planning.chapter_plan_put(1, {'primary_goal': '推进', 'pov': 'hero', 'threads': {'advance': []}}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    run = s.novel_run_start(start_chapter=1, target_chapter=1, require_semantic=False,
                            auto_plan=False, stop_on_pressure=False, steering_mode=True, plan_review=True)
    rid = run['run']['run_id']
    # 第一次 step:停在 steering_point
    out = s.novel_run_step(rid)
    assert out['status'] == 'needs_author_decision' and out['decision']['decision_type'] == 'steering_point'
    # 带指令恢复 → 指令落库
    s.novel_run_decision_submit(rid, out['decision']['decision_id'], {'action': 'resume', 'directive': '第一章必须埋下黑衣人线索'})
    assert s.chapter_directive_get(1)['directive'] == '第一章必须埋下黑衣人线索'
    # 第二次 step:越过 steering,停在 plan_approval
    out2 = s.novel_run_step(rid)
    assert out2['status'] == 'needs_author_decision' and out2['decision']['decision_type'] == 'plan_approval'
    assert out2['decision']['context']['plan']['plan']['primary_goal'] == '推进'
    # 批准 → 指令销账,继续推进(draft 未存 → 走 pipeline 异常决策,证明已过两道闸)
    s.novel_run_decision_submit(rid, out2['decision']['decision_id'], {'action': 'resume'})
    assert s.chapter_directive_get(1) is None, '计划已生成并放行,指令应销账'
    out3 = s.novel_run_step(rid)
    # 无草稿 → 写作位失败决策(writer_failed/pipeline_error 均证明已越过导演两道闸)
    assert out3['status'] == 'needs_author_decision' and out3['decision']['decision_type'] in ('writer_failed', 'chapter_pipeline_error')


def test_steering_not_reopened_after_resume(tmp_path):
    s = make(tmp_path)
    s.planning.chapter_plan_put(1, {'primary_goal': '推进', 'pov': 'hero'}, None, 'hero', 'draft',
                                'ready', {'ok': True, 'errors': [], 'warnings': []})
    run = s.novel_run_start(start_chapter=1, target_chapter=1, require_semantic=False,
                            auto_plan=False, stop_on_pressure=False, steering_mode=True)
    rid = run['run']['run_id']
    out = s.novel_run_step(rid)
    assert out['decision']['decision_type'] == 'steering_point'
    s.novel_run_decision_submit(rid, out['decision']['decision_id'], {'action': 'resume', 'directive': ''})
    # 再次 step 不得重复打开 steering(已 resolved)
    out2 = s.novel_run_step(rid)
    assert out2.get('decision', {}).get('decision_type') != 'steering_point'
