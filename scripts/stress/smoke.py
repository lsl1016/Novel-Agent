#!/usr/bin/env python3
"""单章全链路冒烟:种子架构 -> 真实模型规划 -> 正文 -> 审校。

验证 Phase B 长跑前的完整链路(含 Anthropic 协议适配)。
    python3 scripts/stress/smoke.py [--db story-data/smoke.db] [--env env/llm.env] [--chapter 1]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp-server' / 'src'))

from novel_mcp.service import NovelService  # noqa: E402
from common import load_env, answer_planner_questions  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'story-data' / 'smoke.db'))
    ap.add_argument('--env', default=str(ROOT / 'env' / 'llm.env'))
    ap.add_argument('--chapter', type=int, default=1)
    ap.add_argument('--auto-answer', action='store_true', help='把 planner 的作者提问自动拍板进 blueprint.author_decisions 并重试一次')
    args = ap.parse_args()

    load_env(Path(args.env))
    db_path = Path(args.db)
    fresh = not db_path.exists()
    svc = NovelService(db_path)

    if fresh:
        arch = json.loads((ROOT / 'scripts' / 'stress' / 'architecture.json').read_text(encoding='utf-8'))
        t0 = time.time()
        r = svc.story_architect_apply(arch, dry_run=False)
        print(f'[seed] applied in {time.time()-t0:.1f}s:', r['applied'])

    svc.planning_rebuild_window(args.chapter, 5, 20, 50, [], True)

    t0 = time.time()
    plan_result = svc.chapter_plan_generate(args.chapter, save=True, allow_blocked=True)
    print(f'[planner] {time.time()-t0:.1f}s ok={plan_result.get("ok")} model={plan_result.get("model")}')
    if plan_result.get('needs_author_decision') and args.auto_answer:
        qs = plan_result.get('author_questions') or []
        n = answer_planner_questions(svc, qs)
        print(f'[auto-answer] recorded {n} Q/A into blueprint.author_decisions; retrying planner')
        t0 = time.time()
        plan_result = svc.chapter_plan_generate(args.chapter, save=True, allow_blocked=True)
        print(f'[planner retry] {time.time()-t0:.1f}s ok={plan_result.get("ok")}')
    if plan_result.get('needs_author_decision'):
        print('[planner] author questions:', json.dumps(plan_result.get('author_questions'), ensure_ascii=False))
        return 1
    if not plan_result.get('ok'):
        print('[planner] failed:', json.dumps(plan_result, ensure_ascii=False)[:2000])
        return 1
    plan = plan_result.get('generated_plan') or {}
    print('[plan] goal =', plan.get('primary_goal'))
    print('[plan] title =', plan.get('title'), '| pov =', plan.get('pov'))
    print('[plan] advance =', (plan.get('threads') or {}).get('advance'), '| clues =', len(plan.get('clues') or []))
    print('[plan] validation =', plan_result['chapter_plan']['validation_status'])

    t0 = time.time()
    draft_result = svc.chapter_draft_generate(args.chapter)
    draft = draft_result['draft']
    print(f'[writer] {time.time()-t0:.1f}s model={draft.get("model")} chars={len(draft["body"])} version={draft["version"]}')
    print('[writer] preflight leak ok =', draft_result['preflight']['knowledge_leak']['ok'])
    print('[writer] 开头:', draft['body'][:120].replace('\n', ' '))

    t0 = time.time()
    review = svc.chapter_review_full(args.chapter, semantic=True)
    print(f'[review] {time.time()-t0:.1f}s overall={review.get("overall_verdict")}')
    for r in review.get('reviews', []):
        codes = [f.get('code') for f in (r.get('findings') or [])][:3]
        print(f'  - {r["reviewer_type"]}: {r["verdict"]} {codes if codes else ""}')
    if review.get('error'):
        print('[review] error:', review['error'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
