#!/usr/bin/env python3
"""把已提交章节导出为可读 Markdown。

    python3 scripts/stress/export_novel.py [--db story-data/stress.db] [--out story-data/novel]
输出 <out>/<书名>.md:目录 + 各章正文(含 POV/摘要元信息)。长跑进行中可随时重跑刷新。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(Path(__file__).resolve().parents[2] / 'story-data' / 'stress.db'))
    ap.add_argument('--out', default=str(Path(__file__).resolve().parents[2] / 'story-data' / 'novel'))
    args = ap.parse_args()

    db = sqlite3.connect(args.db); db.row_factory = sqlite3.Row
    title_row = db.execute("SELECT value FROM meta WHERE key='blueprint'").fetchone()
    book_title = '青霜疑锋'
    try:
        import json
        bp = json.loads(title_row['value']) if title_row else {}
        book_title = bp.get('title') or book_title
    except Exception:
        pass
    rows = db.execute('SELECT chapter,title,arc,pov,summary,body,committed_at FROM chapters ORDER BY chapter').fetchall()
    if not rows:
        print('还没有已提交章节'); return 1

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    lines = [f'# {book_title}', '',
             f'> 共 {len(rows)} 章 / {sum(len(r["body"]) for r in rows):,} 字 · 由 Novel Agent V0.10 长跑生成', '', '## 目录', '']
    for r in rows:
        lines.append(f'- [{r["chapter"]}. {r["title"]}](#{r["chapter"]})')
    lines.append('')
    for r in rows:
        lines += [f'## {r["chapter"]}. {r["title"]}', '']
        meta = [f'卷:{r["arc"] or "—"} · POV:{r["pov"] or "reader"} · {len(r["body"]):,}字 · 提交于 {r["committed_at"]}']
        if r['summary']:
            meta.append(f'> 摘要:{r["summary"]}')
        lines += meta + ['', r['body'], '', '---', '']
    out_file = out_dir / f'{book_title}.md'
    out_file.write_text('\n'.join(lines), encoding='utf-8')
    print(f'已导出 {len(rows)} 章 -> {out_file}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
