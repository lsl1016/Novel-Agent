#!/usr/bin/env python3
"""Phase B 长跑无人值守驱动。

用法:
    python3 scripts/stress/drive.py --db story-data/stress.db --env env/llm.env \
        [--target-chapter 40] [--max-steps 3] [--seed]

行为:
* --seed 时应用 scripts/stress/architecture.json(幂等,upsert);
* 复用 active 的 run 或新建 bounded run;
* 循环 novel_run_continue(max_steps),每步打印章节进度;
* needs_author_decision 时输出决策内容,可选 POST NOVEL_NOTIFY_URL,退出码 2;
* 结束后自动生成 metrics 报告(--report 路径,默认 story-data/stress-metrics.json)。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp-server' / 'src'))

from novel_mcp.service import NovelService  # noqa: E402
from common import load_env, answer_planner_questions  # noqa: E402


def notify(payload: dict) -> None:
    url = os.environ.get('NOVEL_NOTIFY_URL', '').strip()
    if not url:
        return
    try:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
    except Exception as exc:  # 通知失败不阻断长跑
        print(f'[notify] failed: {exc}')


def active_run(svc: NovelService) -> str | None:
    with svc.store.connect() as db:
        r = db.execute("SELECT run_id FROM novel_runs WHERE status IN ('running','paused','needs_author_decision') ORDER BY updated_at DESC LIMIT 1").fetchone()
    return r['run_id'] if r else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'story-data' / 'stress.db'))
    ap.add_argument('--env', default=str(ROOT / 'env' / 'llm.env'))
    ap.add_argument('--seed', action='store_true', help='apply stress architecture before running')
    ap.add_argument('--target-chapter', type=int, default=40)
    ap.add_argument('--max-chapters', type=int, default=50)
    ap.add_argument('--max-steps', type=int, default=3, help='chapters per continue call (gateway profile keeps <=3)')
    ap.add_argument('--max-revisions', type=int, default=3)
    ap.add_argument('--no-semantic', action='store_true')
    ap.add_argument('--no-pressure-stop', action='store_true')
    ap.add_argument('--report', default='')
    ap.add_argument('--auto-answer', action='store_true', help='planner 作者提问自动拍板进 blueprint.author_decisions 并 resume')
    args = ap.parse_args()

    load_env(Path(args.env))
    svc = NovelService(Path(args.db))

    if args.seed:
        arch = json.loads((ROOT / 'scripts' / 'stress' / 'architecture.json').read_text(encoding='utf-8'))
        check = svc.story_architect_apply(arch, dry_run=True)
        if not check['ok']:
            print('[seed] dry-run errors:', check['errors'])
            return 1
        applied = svc.story_architect_apply(arch, dry_run=False)
        print('[seed] applied:', applied['applied'])

    from novel_mcp.planner_ai import planner_model_configured
    from novel_mcp.semantic_review import semantic_reviewer_configured
    if not planner_model_configured():
        print('[config] planner model not configured — check env file')
        return 1
    if not args.no_semantic and not semantic_reviewer_configured():
        print('[config] warning: semantic reviewer not configured; pass --no-semantic or fix env')

    run_id = active_run(svc)
    if run_id:
        st = svc.novel_run_status(run_id)['run']
        print(f'[run] reusing {run_id} status={st["status"]} current_chapter={st["current_chapter"]}')
        if st['status'] == 'needs_author_decision':
            for d in svc.novel_run_decision_list(run_id):
                print('[decision pending]', d['decision_type'], '—', d['prompt'])
            notify({'type': 'novel_stress_decision', 'run_id': run_id, 'decisions': svc.novel_run_decision_list(run_id)})
            return 2
        if st['status'] == 'paused':
            svc.novel_run_resume(run_id)
    else:
        last = svc.canon.max_committed_chapter() or 0
        started = svc.novel_run_start(start_chapter=last + 1, target_chapter=args.target_chapter,
                                      max_chapters=args.max_chapters, max_revision_rounds=args.max_revisions,
                                      require_semantic=not args.no_semantic, auto_plan=True,
                                      stop_on_pressure=not args.no_pressure_stop)
        run_id = started['run']['run_id']
        print(f'[run] started {run_id} -> target chapter {args.target_chapter}')

    consecutive_blocked = 0
    while True:
        result = svc.novel_run_continue(run_id, max_steps=args.max_steps)
        st = svc.novel_run_status(run_id)['run']
        print(f'[progress] steps={result["steps"]} status={st["status"]} committed={st["chapters_committed"]} chapter={st["current_chapter"]}')
        if st['status'] == 'needs_author_decision':
            if args.auto_answer:
                handled = False
                for d in svc.novel_run_decision_list(run_id):
                    pr = (d.get('context') or {}).get('plan_result') or {}
                    qs = pr.get('author_questions') or []
                    if qs:
                        n = answer_planner_questions(svc, qs)
                        svc.novel_run_decision_submit(run_id, d['decision_id'], {'action': 'resume'})
                        print(f'[auto-answer] recorded {n} Q/A; run resumed')
                        handled = True
                    elif d['decision_type'] in ('chapter_plan_blocked', 'planner_failed') and consecutive_blocked < 3:
                        consecutive_blocked += 1
                        errs = ((pr.get('validation') or {}).get('errors') or [])[:3]
                        print(f'[auto-retry] blocked plan #{consecutive_blocked}/3 keys={sorted(pr)} errs={errs}')
                        svc.novel_run_decision_submit(run_id, d['decision_id'], {'action': 'resume'})
                        handled = True
                if handled:
                    continue
            else:
                consecutive_blocked = 0
            decisions = svc.novel_run_decision_list(run_id)
            for d in decisions:
                print('[decision]', d['decision_type'], '—', d['prompt'])
                print('  context:', json.dumps(d.get('context', {}), ensure_ascii=False)[:600])
            notify({'type': 'novel_stress_decision', 'run_id': run_id, 'decisions': decisions})
            break
        if st['status'] != 'running':
            print('[done]', st['status'], st.get('stop_reason'))
            break

    report_path = args.report or str(Path(args.db).with_name(Path(args.db).stem + '-metrics.json'))
    metrics_module = str(ROOT / 'scripts' / 'stress' / 'metrics.py')
    os.system(f'"{sys.executable}" "{metrics_module}" --db "{args.db}" --out "{report_path}"')
    print(f'[metrics] written -> {report_path}')
    return 0 if st['status'] == 'completed' else (2 if st['status'] == 'needs_author_decision' else 0)


if __name__ == '__main__':
    raise SystemExit(main())
