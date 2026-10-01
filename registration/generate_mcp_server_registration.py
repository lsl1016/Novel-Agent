#!/usr/bin/env python3
"""根据 Novel Agent 工具 schema 生成 lsl1016/mcp-server 的 batchCreate 载荷。"""
from __future__ import annotations
import argparse, copy, json
from pathlib import Path

READ_ONLY = {
    'story_get_state','narrative_thread_get','narrative_thread_search','foreshadowing_list_open',
    'belief_get','narrative_pattern_search','chapter_plan_check','continuity_check','story_pressure_check',
    'blueprint_get','story_architect_get','arc_plan_get','arc_progress_get','milestone_list',
    'thread_schedule_get','planning_get_window','chapter_plan_get','planning_pressure_check',
    'planner_context_get','novel_run_status','novel_run_decision_list','writer_context_get',
    'chapter_draft_get','chapter_review_get','chapter_revision_context_get','writing_workflow_status',
    'entity_get','entity_author_get','entity_search','entity_neighbors','entity_path_find','entity_context_get','entity_graph_stats','narrative_entity_links_get','entity_graph_check',
    'entity_retrieve_relevant','narrative_retrieve_relevant','context_compile','context_preview','context_snapshot_get','context_explain',
    'candidate_list','event_get','event_timeline','assertion_list','fact_disclosures_get','power_context_get','artifact_history_get','geography_tree_get',
}

MODEL_TOOLS = {
    'chapter_plan_generate','novel_run_step','novel_run_continue','chapter_draft_generate',
    'chapter_semantic_review','chapter_review_full','chapter_auto_revise','chapter_auto_revision_loop',
}

MEDIUM_WRITE_TOOLS = {
    'story_architect_apply','planning_rebuild_window','chapter_review_all','chapter_finalize',
    'novel_run_report','novel_run_start','novel_run_pause','novel_run_resume','novel_run_decision_submit',
}


def bounded_input_schema(name: str, schema: dict) -> dict:
    out=copy.deepcopy(schema)
    props=out.get('properties') or {}
    # 网关上游超时上限为 120 秒,务必保持控制器调用的步数有界。
    if name=='novel_run_continue' and 'max_steps' in props:
        props['max_steps']['maximum']=3
        props['max_steps']['default']=1
        props['max_steps']['description']='Gateway profile cap: at most 3 chapter steps per synchronous HTTP call; prefer 1.'
    if name=='chapter_auto_revision_loop' and 'max_rounds' in props:
        props['max_rounds']['maximum']=3
        props['max_rounds']['default']=2
        props['max_rounds']['description']='Gateway profile cap: at most 3 synchronous revision rounds; prefer 1-2.'
    return out


def timeout_ms(name: str) -> int:
    if name in MODEL_TOOLS:
        return 120000
    if name in MEDIUM_WRITE_TOOLS:
        return 30000
    return 10000 if name in READ_ONLY else 20000


def output_envelope_schema(native: dict) -> dict:
    return {
        'type':'object',
        'properties':{
            'errNo':{'type':'integer','description':'0 means success; non-zero means Novel Agent facade error.'},
            'errMsg':{'type':'string','description':'Human/model-readable facade status message.'},
            'data':native or {'type':'object'},
        },
        'required':['errNo','errMsg','data'],
        'additionalProperties':False,
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--schemas',default='../mcp-server/tool_schemas.json')
    ap.add_argument('--base-url',default='http://novel-agent:8765')
    ap.add_argument('--facade-token',default='')
    ap.add_argument('--owner',default='novel-agent')
    ap.add_argument('--biz-tag',default='novel-agent-v0.7')
    ap.add_argument('--out',default='mcp-server-batch-create.json')
    args=ap.parse_args()
    here=Path(__file__).resolve().parent
    schemas_path=(here/args.schemas).resolve() if not Path(args.schemas).is_absolute() else Path(args.schemas)
    tools=json.loads(schemas_path.read_text(encoding='utf-8'))
    base=args.base_url.rstrip('/')
    records=[]
    for t in tools:
        name=t['name']
        headers={'Accept':'application/json','Content-Type':'application/json'}
        if args.facade_token:
            headers['Authorization']=f'Bearer {args.facade_token}'
        req={'method':'POST','timeout_ms':timeout_ms(name),'headers':headers}
        rec={
            'bizTag':args.biz_tag,
            'url':f'{base}/api/agent/tools/call/{name}',
            'requestConfig':json.dumps(req,ensure_ascii=False,separators=(',',':')),
            'name':name,
            'title':t.get('title') or name,
            'description':t.get('description') or name,
            'inputSchema':json.dumps(bounded_input_schema(name,t.get('inputSchema') or {'type':'object'}),ensure_ascii=False,separators=(',',':')),
            'outputSchema':json.dumps(output_envelope_schema(t.get('outputSchema') or {'type':'object'}),ensure_ascii=False,separators=(',',':')),
            'readOnly':2 if name in READ_ONLY else 1,
            'isInternal':2,
            'status':2,
            'owner':args.owner,
        }
        records.append(rec)
    out={'tools':records}
    out_path=(here/args.out).resolve() if not Path(args.out).is_absolute() else Path(args.out)
    out_path.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'wrote {len(records)} tools -> {out_path}')

if __name__=='__main__':
    main()
