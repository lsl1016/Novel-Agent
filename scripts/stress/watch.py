#!/usr/bin/env python3
"""实时观察长跑创作过程。

用法:
    python3 scripts/stress/watch.py [--db story-data/stress.db] [--interval 3] [--snapback 5]

行为:
* 启动时打印一次当前状态 + 最近 N 条事件(--snapback);
* 之后每 --interval 秒轮询一次数据库(只读,WAL 并发安全),流式打印新增事件:
  - 章节启动 / 规划就绪 / 草稿新版本 / 语义审校判定 / 章节入库;
* 事件时间戳若比本地时间落后超过 4 小时,视为 UTC 进程写入,展示时 +8h 修正。

只读观察,不影响正在运行的长跑。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fix_tz(ts_str: str, now: datetime) -> str:
    try:
        ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return ts_str
    if now - ts > timedelta(hours=4):  # UTC 进程写入的旧时间戳,修正展示
        ts += timedelta(hours=8)
    return ts.strftime('%H:%M:%S')


def open_ro(db_path: str) -> sqlite3.Connection:
    db = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=2000')
    return db


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--db', default=str(ROOT / 'story-data' / 'stress.db'))
    ap.add_argument('--interval', type=float, default=3.0)
    ap.add_argument('--snapback', type=int, default=5, help='启动时回放最近 N 条事件')
    ap.add_argument('--thinking', default='', help='思考捕获 JSONL 路径(NOVEL_THINKING_LOG),实时打印模型思考')
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(line_buffering=True)  # 管道/重定向下也实时输出
    except Exception:
        pass

    db = open_ro(args.db)
    run = db.execute('select run_id,status,current_chapter,last_committed_chapter,chapters_committed '
                     'from novel_runs order by created_at desc limit 1').fetchone()
    if not run:
        print('[watch] 没有找到 run 记录')
        return 1
    print(f"[watch] {args.db}  每 {args.interval}s 轮询  Ctrl-C 退出")
    print(f"[watch] run={run['run_id']} 状态={run['status']} 进行中章节={run['current_chapter']} "
          f"已提交={run['chapters_committed']}")

    snap = db.execute('select id from novel_run_events order by id desc limit 1').fetchone()
    last_event_id = (snap['id'] if snap else 0)
    snapback_from = max(0, last_event_id - args.snapback)
    # 存量草稿/审校记录标记为已见,启动后只打印新增
    seen_drafts = {(r['chapter'], r['version']) for r in
                   db.execute('select chapter,version from chapter_drafts')}
    seen_reviews = {r[0] for r in db.execute(
        "select rowid from chapter_reviews where verdict in ('WARN','BLOCK')")}
    db.close()

    # 启动回放最近几条,让观察者立刻有上下文
    db = open_ro(args.db)
    now = datetime.now()
    for r in db.execute('select * from novel_run_events where id>? and id<=? order by id',
                        (snapback_from, last_event_id)):
        print(f"{fix_tz(r['created_at'], now)}  ch{r['chapter']:<3} {r['phase']:<10} {r['status']:<12} "
              f"{(r['detail_json'] or '')[:60]}")
    db.close()

    think_offset = 0

    def stream_thinking() -> None:
        nonlocal think_offset
        if not args.thinking:
            return
        p = Path(args.thinking)
        if not p.exists():
            return
        size = p.stat().st_size
        if size < think_offset:  # 文件被轮转/清空,重新从头读
            think_offset = 0
        with p.open('r', encoding='utf-8') as fh:
            fh.seek(think_offset)
            chunk = fh.read()
            think_offset = fh.tell()
        for line in chunk.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            role = (e.get('role') or '').replace('NOVEL_', '').lower()
            t = (e.get('thinking') or '').strip()
            ts = (e.get('ts') or '')[11:19]
            print(f"{ts}  💭 {role} 思考({len(t)}字):")
            shown = t[:2000]
            for ln in shown.splitlines():
                print(f"{'':10}  {ln}")
            if len(t) > 2000:
                print(f"{'':10}  …(截断,全文见 {args.thinking})")

    while True:
        stream_thinking()
        try:
            db = open_ro(args.db)
        except sqlite3.Error as exc:
            print(f'[watch] 数据库暂时不可读: {exc}')
            time.sleep(args.interval)
            continue
        now = datetime.now()
        run = db.execute('select status,current_chapter,chapters_committed from novel_runs '
                         'order by created_at desc limit 1').fetchone()
        if run:
            cur = run['current_chapter']

            for r in db.execute('select * from novel_run_events where id>? order by id', (last_event_id,)):
                last_event_id = r['id']
                detail = (r['detail_json'] or '')[:70]
                print(f"{fix_tz(r['created_at'], now)}  ch{r['chapter']:<3} {r['phase']:<10} "
                      f"{r['status']:<12} {detail}")
                if r['phase'] == 'chapter' and r['status'] == 'committed':
                    ch = db.execute('select title,arc,pov,length(body) as n from chapters where chapter=?',
                                    (r['chapter'],)).fetchone()
                    if ch:
                        print(f"{'':10}└─ 📖 第{r['chapter']}章《{ch['title']}》入库 {ch['n']}字 "
                              f"[{ch['arc']}] pov={ch['pov']}")
                if r['phase'] == 'decision' and r['status'] == 'opened':
                    d = json.loads(r['detail_json'] or '{}')
                    if d.get('decision_type') == 'chapter_plan_blocked':
                        print(f"{'':10}└─ ⏸ 规划器提请作者决策(自动应答中)")

            # 当前章节的新草稿版本(写作者完成一版才会落库)
            for r in db.execute('select rowid,chapter,version,length(body) as n,source from chapter_drafts '
                                'where chapter=?', (cur,)):
                key = (r['chapter'], r['version'])
                if key not in seen_drafts:
                    seen_drafts.add(key)
                    print(f"{now.strftime('%H:%M:%S')}  ch{r['chapter']:<3} draft     v{r['version']} "
                          f"完成  {r['n']}字 (source={r['source']})")

            # 新的语义判定(WARN/BLOCK 才值得关注)
            for r in db.execute("select rowid as rid,chapter,verdict,substr(findings_json,1,90) as f from "
                                "chapter_reviews where verdict in ('WARN','BLOCK') order by rid"):
                if r['rid'] not in seen_reviews:
                    seen_reviews.add(r['rid'])
                    flag = '⛔ BLOCK' if r['verdict'] == 'BLOCK' else '⚠️ WARN '
                    print(f"{now.strftime('%H:%M:%S')}  ch{r['chapter']:<3} review    {flag} "
                          f"{(r['f'] or '').strip()[:80]}")

            if run['status'] not in ('running', 'needs_author_decision', 'paused'):
                print(f"[watch] run 结束: {run['status']}  已提交 {run['chapters_committed']} 章")
                db.close()
                return 0
        db.close()
        time.sleep(args.interval)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\n[watch] 退出')
        sys.exit(0)
