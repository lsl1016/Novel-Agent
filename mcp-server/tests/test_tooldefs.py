from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.tooldefs import TOOLS

def test_tools_are_stable_and_valid():
    assert len(TOOLS)==91
    names=[x['name'] for x in TOOLS]
    assert len(names)==len(set(names))
    assert names[:14]==[
      'story_get_state','narrative_thread_get','narrative_thread_search','mystery_create','clue_add','foreshadowing_list_open','belief_get','belief_update','emotion_debt_create','emotion_debt_resolve','narrative_pattern_search','chapter_plan_check','continuity_check','story_pressure_check'
    ]
    assert names[14:30]==[
      'entity_get','entity_author_get','entity_search','entity_neighbors','entity_path_find','entity_context_get','entity_graph_stats','entity_upsert','entity_alias_add','entity_attribute_set','entity_relation_upsert','entity_relation_end','narrative_entity_link','narrative_entity_links_get','entity_graph_check','entity_graph_import'
    ]
    assert names[30:36]==[
      'entity_retrieve_relevant','narrative_retrieve_relevant','context_compile','context_preview','context_snapshot_get','context_explain'
    ]
    assert names[36:52]==[
      'blueprint_get','blueprint_update','story_architect_get','story_architect_apply','arc_plan_create','arc_plan_get','arc_progress_get','milestone_create','milestone_list','thread_schedule_update','thread_schedule_get','planning_rebuild_window','planning_get_window','chapter_plan_save','chapter_plan_get','planning_pressure_check'
    ]
    assert names[52:63]==[
      'planner_context_get','chapter_plan_generate','novel_run_start','novel_run_step','novel_run_continue','novel_run_status','novel_run_pause','novel_run_resume','novel_run_report','novel_run_decision_list','novel_run_decision_submit'
    ]
    assert names[63:76]==[
      'writer_context_get','chapter_draft_generate','chapter_draft_save','chapter_draft_get','chapter_review_all','chapter_review_get','chapter_revision_context_get','writing_workflow_status','chapter_finalize',
      'chapter_semantic_review','chapter_review_full','chapter_auto_revise','chapter_auto_revision_loop'
    ]
    assert names[76:86]==[
      'candidate_list','candidate_promote','candidate_reject',
      'identity_profile_set','event_create','event_get','event_timeline',
      'assertion_create','assertion_list','assertion_resolve'
    ]
    assert names[86:]==[
      'fact_disclosure_set','fact_disclosures_get','power_context_get',
      'artifact_history_get','geography_tree_get'
    ]
    assert 'chapter_commit' not in names, 'chapter_commit must stay off the public tool face (finalize-only since v0.8)'
    assert all(x['inputSchema']['type']=='object' for x in TOOLS)
