#!/usr/bin/env python3
"""Phase B 压测指标采集:从 Story DB 生成 KPI 报告(JSON + 控制台摘要)。

覆盖方案第 17 章 KPI 的可确定性部分:
连续性 BLOCK 率、知识泄漏、修订轮数、人工介入次数、context token 增长趋势、
线程沉睡、谜团积压、伏笔逾期、情感债逾期、章节字数。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'mcp-server' / 'src'))

from novel_mcp.service import NovelService  # noqa: E402


def slope(points: list[tuple[float, float]]) -> float | None:
    n = len(points)
    if n < 2:
        return None
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    denom = sum((x - mx) ** 2 for x, _ in points)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in points) / denom


def collect(svc: NovelService) -> dict:
    s = svc.store
    with s.connect() as db:
        chapters = [dict(r) for r in db.execute('SELECT chapter,title,pov,LENGTH(body) chars FROM chapters ORDER BY chapter').fetchall()]
        last = chapters[-1]['chapter'] if chapters else 0
        stage_max = db.execute('SELECT COALESCE(MAX(chapter),0) m FROM stages').fetchone()['m']
        last = max(last, stage_max)  # 故事前沿:未提交时以最大 stage 章为准,避免负沉睡
        drafts = [dict(r) for r in db.execute('SELECT chapter,COUNT(*) versions FROM chapter_drafts GROUP BY chapter ORDER BY chapter').fetchall()]
        reviews = [dict(r) for r in db.execute('SELECT reviewer_type,verdict,COUNT(*) n FROM chapter_reviews GROUP BY reviewer_type,verdict').fetchall()]
        decisions = [dict(r) for r in db.execute("SELECT status,COUNT(*) n FROM novel_run_decisions GROUP BY status").fetchall()]
        runs = [dict(r) for r in db.execute('SELECT run_id,status,chapters_committed FROM novel_runs ORDER BY created_at').fetchall()]
        snapshots = [dict(r) for r in db.execute('''SELECT chapter,role,estimated_tokens FROM context_snapshots
            WHERE snapshot_id IN (SELECT snapshot_id FROM context_snapshots cs WHERE role='writer' AND chapter=cs.chapter GROUP BY chapter)''').fetchall()]
        stages = [dict(r) for r in db.execute('SELECT thread_key,MAX(chapter) last_ch,COUNT(*) n FROM stages GROUP BY thread_key').fetchall()]
        mysteries = [dict(r) for r in db.execute('SELECT mystery_key,thread_key,introduced_chapter,status,resolved_chapter FROM mysteries').fetchall()]
        clues = svc.foreshadowing_list_open(last, 0, 500)
        debts = [dict(r) for r in db.execute("SELECT debt_key,created_chapter,status FROM debts").fetchall()]

    writer_tokens = sorted((r['chapter'], r['estimated_tokens']) for r in snapshots if r['role'] == 'writer')
    token_trend = slope([(float(c), float(t)) for c, t in writer_tokens]) if writer_tokens else None
    review_map = {(r['reviewer_type'], r['verdict']): r['n'] for r in reviews}
    total_reviews = sum(r['n'] for r in reviews)
    blocks = sum(n for (rt, v), n in review_map.items() if v == 'BLOCK')
    leak_blocks = sum(n for (rt, v), n in review_map.items() if v == 'BLOCK' and rt in ('knowledge_leak', 'semantic_knowledge_leak'))
    revision_rounds = {d['chapter']: d['versions'] - 1 for d in drafts}

    metrics = {
        'chapters_committed': len(chapters),
        'total_chars': sum(c['chars'] for c in chapters),
        'avg_chars_per_chapter': round(sum(c['chars'] for c in chapters) / len(chapters), 1) if chapters else 0,
        'review': {
            'total_review_records': total_reviews,
            'block_count': blocks,
            'block_rate': round(blocks / total_reviews, 4) if total_reviews else None,
            'knowledge_leak_blocks': leak_blocks,
            'by_reviewer': {f'{rt}:{v}': n for (rt, v), n in sorted(review_map.items())},
        },
        'revision_rounds': revision_rounds,
        'avg_revision_rounds': round(sum(revision_rounds.values()) / len(revision_rounds), 2) if revision_rounds else 0,
        'human_interventions': {r['status']: r['n'] for r in decisions},
        'runs': [{'run_id': r['run_id'], 'status': r['status'], 'committed': r['chapters_committed']} for r in runs],
        'context_growth': {
            'writer_tokens_by_chapter': writer_tokens,
            'tokens_per_chapter_slope': round(token_trend, 2) if token_trend is not None else None,
            'interpretation': 'slope 明显为正 => Writer 上下文随章节线性增长,需要校准预算/检索',
        },
        'threads': {
            'total': len(stages),
            'dormancy': sorted(
                ({'thread_key': st['thread_key'], 'last_stage_chapter': st['last_ch'],
                  'dormant_for': last - st['last_ch'], 'stage_count': st['n']} for st in stages),
                key=lambda x: -x['dormant_for'])[:10],
        },
        'mysteries': {
            'open': sum(1 for m in mysteries if m['status'] == 'open'),
            'resolved': sum(1 for m in mysteries if m['status'] == 'resolved'),
            'oldest_open_age': max((last - m['introduced_chapter'] for m in mysteries if m['status'] == 'open'), default=0),
        },
        'unresolved_clues': len(clues),
        'open_emotion_debts': sum(1 for d in debts if d['status'] != 'resolved'),
        'oldest_open_debt_age': max((last - d['created_chapter'] for d in debts if d['status'] != 'resolved'), default=0),
    }
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', required=True)
    ap.add_argument('--out', default='')
    args = ap.parse_args()
    svc = NovelService(Path(args.db))
    m = collect(svc)
    text = json.dumps(m, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
