from __future__ import annotations
import argparse,json
from pathlib import Path
from .store import StoryStore
from .service import NovelService


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('init-story'); p.add_argument('--db',required=True); p.add_argument('--title',required=True); p.add_argument('--main-goal',default=''); p.add_argument('--current-arc',default=''); p.add_argument('--world-facts')
    p=sub.add_parser('set-meta'); p.add_argument('--db',required=True); p.add_argument('key'); p.add_argument('value')
    p=sub.add_parser('apply-architecture'); p.add_argument('--db',required=True); p.add_argument('--file',required=True); p.add_argument('--dry-run',action='store_true')
    p=sub.add_parser('planning-status'); p.add_argument('--db',required=True); p.add_argument('--chapter',type=int,required=True)
    p=sub.add_parser('rebuild-window'); p.add_argument('--db',required=True); p.add_argument('--anchor',type=int,required=True); p.add_argument('--hard',type=int,default=5); p.add_argument('--medium',type=int,default=20); p.add_argument('--soft',type=int,default=50); p.add_argument('--proposals')
    p=sub.add_parser('generate-plan'); p.add_argument('--db',required=True); p.add_argument('--chapter',type=int,required=True); p.add_argument('--model'); p.add_argument('--dry-run',action='store_true')
    p=sub.add_parser('context-preview'); p.add_argument('--db',required=True); p.add_argument('--chapter',type=int,required=True); p.add_argument('--role',choices=['writer','planner','reviewer'],default='writer'); p.add_argument('--holder'); p.add_argument('--max-tokens',type=int)
    p=sub.add_parser('context-compile'); p.add_argument('--db',required=True); p.add_argument('--chapter',type=int,required=True); p.add_argument('--role',choices=['writer','planner','reviewer'],default='writer'); p.add_argument('--holder'); p.add_argument('--max-tokens',type=int); p.add_argument('--persist',action='store_true')
    p=sub.add_parser('context-snapshot'); p.add_argument('--db',required=True); p.add_argument('--snapshot-id'); p.add_argument('--chapter',type=int); p.add_argument('--role',choices=['writer','planner','reviewer'])
    p=sub.add_parser('context-explain'); p.add_argument('--db',required=True); p.add_argument('--snapshot-id',required=True); p.add_argument('--item-key')
    p=sub.add_parser('run-start'); p.add_argument('--db',required=True); p.add_argument('--start-chapter',type=int); p.add_argument('--target-chapter',type=int); p.add_argument('--target-arc'); p.add_argument('--max-chapters',type=int); p.add_argument('--max-revisions',type=int,default=3); p.add_argument('--report-every',type=int,default=10); p.add_argument('--no-semantic',action='store_true'); p.add_argument('--no-pressure',action='store_true'); p.add_argument('--no-auto-plan',action='store_true')
    for name in ('run-step','run-status','run-resume','run-report'):
        p=sub.add_parser(name); p.add_argument('--db',required=True); p.add_argument('--run-id',required=True)
    p=sub.add_parser('run-continue'); p.add_argument('--db',required=True); p.add_argument('--run-id',required=True); p.add_argument('--max-steps',type=int,default=5)
    p=sub.add_parser('run-pause'); p.add_argument('--db',required=True); p.add_argument('--run-id',required=True); p.add_argument('--reason',default='')
    p=sub.add_parser('run-decisions'); p.add_argument('--db',required=True); p.add_argument('--run-id',required=True); p.add_argument('--status',default='open')
    p=sub.add_parser('run-decision-submit'); p.add_argument('--db',required=True); p.add_argument('--run-id',required=True); p.add_argument('--decision-id',required=True); p.add_argument('--resolution',required=True,help='JSON string or path to JSON file')
    p=sub.add_parser('web'); p.add_argument('--db',default=None); p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8080); p.add_argument('--static',default=None); p.add_argument('--reference-root',default=None); p.add_argument('--narrative-kg-root',dest='nkg_root',default=None)
    a=ap.parse_args()
    if a.cmd=='init-story':
        s=StoryStore(a.db); s.set_meta('title',a.title); s.set_meta('main_goal',a.main_goal); s.set_meta('current_arc',a.current_arc)
        if a.world_facts:
            for x in read_json(a.world_facts):s.set_world_fact(x['fact_key'],x.get('truth'),x.get('secrecy','secret'),x.get('reveal_after'),x.get('notes',''))
        NovelService(a.db)
        out={'ok':True,'db':a.db,'title':a.title}
    elif a.cmd=='set-meta':
        s=StoryStore(a.db)
        try:v=json.loads(a.value)
        except Exception:v=a.value
        s.set_meta(a.key,v); out={'ok':True,'key':a.key,'value':v}
    else:
        svc=NovelService(a.db)
        if a.cmd=='apply-architecture': out=svc.story_architect_apply(read_json(a.file),a.dry_run)
        elif a.cmd=='planning-status': out={'state':svc.story_get_state(a.chapter),'pressure':svc.planning_pressure_check(a.chapter)}
        elif a.cmd=='rebuild-window':
            props=read_json(a.proposals) if a.proposals else []
            out=svc.planning_rebuild_window(a.anchor,a.hard,a.medium,a.soft,props,True)
        elif a.cmd=='generate-plan': out=svc.chapter_plan_generate(a.chapter,model=a.model,save=not a.dry_run,allow_blocked=False)
        elif a.cmd=='context-preview': out=svc.context_preview(a.chapter,a.role,a.holder,a.max_tokens)
        elif a.cmd=='context-compile': out=svc.context_compile(a.chapter,a.role,a.holder,a.max_tokens,persist=a.persist)
        elif a.cmd=='context-snapshot': out=svc.context_snapshot_get(a.snapshot_id,a.chapter,a.role)
        elif a.cmd=='context-explain': out=svc.context_explain(a.snapshot_id,a.item_key)
        elif a.cmd=='run-start': out=svc.novel_run_start(start_chapter=a.start_chapter,target_chapter=a.target_chapter,target_arc_key=a.target_arc,max_chapters=a.max_chapters,max_revision_rounds=a.max_revisions,require_semantic=not a.no_semantic,auto_plan=not a.no_auto_plan,stop_on_pressure=not a.no_pressure,report_every=a.report_every)
        elif a.cmd=='run-step': out=svc.novel_run_step(a.run_id)
        elif a.cmd=='run-continue': out=svc.novel_run_continue(a.run_id,a.max_steps)
        elif a.cmd=='run-status': out=svc.novel_run_status(a.run_id)
        elif a.cmd=='run-pause': out=svc.novel_run_pause(a.run_id,a.reason)
        elif a.cmd=='run-resume': out=svc.novel_run_resume(a.run_id)
        elif a.cmd=='run-report': out=svc.novel_run_report(a.run_id,True)
        elif a.cmd=='run-decisions': out=svc.novel_run_decision_list(a.run_id,a.status)
        elif a.cmd=='web':
            from .web_api import run as web_run
            web_run(a.db,a.host,a.port,a.static,a.reference_root,a.nkg_root)
            return
        else:
            raw=a.resolution
            p=Path(raw)
            resolution=read_json(p) if p.exists() else json.loads(raw)
            out=svc.novel_run_decision_submit(a.run_id,a.decision_id,resolution)
    print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
