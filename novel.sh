#!/usr/bin/env bash
# Novel Agent 长跑写作一键入口 —— 用法: ./novel.sh <命令>
#   new "创意" [目标章数] [跑到第N章]
#              一句话开书:创意 → 架构生成(落盘 story-data/<slug>/)
#              给第三参则 --apply 并自动长跑到第 N 章(如 ./novel.sh new "创意" 300 3)
#   start [N]  启动/断点续跑长跑(默认写到第 40 章;自动开思考捕获)
#   stop       停止长跑(已提交章节无损,下次 start 自动续跑)
#   status     看进度:进程/run 状态/章数字数/最近章节
#   watch      实时观察创作过程(事件流 + 思考流,若已开启捕获)
#   log        跟随长跑驱动日志(tail -f)
#   export     导出已提交章节为 Markdown
#   book       导出并用默认编辑器打开小说
#   metrics    生成 KPI 指标报告
#   smoke      单章全链路冒烟(改配置后先跑这个)
set -euo pipefail
cd "$(dirname "$0")"

DB="story-data/stress.db"
LOG="story-data/drive.log"
PIDF="story-data/drive.pid"
THINK="story-data/thinking.jsonl"
METRICS="story-data/stress-metrics.json"

alive_pid() {
  local p=""
  if [[ -f "$PIDF" ]]; then
    p="$(cat "$PIDF" 2>/dev/null || true)"
    if [[ -n "${p// /}" ]] && ps -p "$p" >/dev/null 2>&1; then printf '%s' "$p"; return 0; fi
  fi
  p="$(pgrep -f 'scripts/stress/drive\.py' | head -n 1 || true)"
  [[ -n "$p" ]] && { printf '%s' "$p"; return 0; }
  return 1
}

cmd_start() {
  local target="${1:-40}"
  if p="$(alive_pid)"; then
    echo "长跑已在运行 (PID $p) — ./novel.sh status 看进度 | ./novel.sh watch 实时观察 | ./novel.sh stop 停止"
    exit 0
  fi
  mkdir -p story-data
  local seed=()
  [[ -f "$DB" ]] || seed=(--seed)   # 新库自动载入《青霜疑锋》种子架构
  NOVEL_THINKING_LOG="$THINK" nohup python3 scripts/stress/drive.py \
    --db "$DB" --auto-answer --target-chapter "$target" ${seed[@]+"${seed[@]}"} \
    --report "$METRICS" > "$LOG" 2>&1 &
  echo $! > "$PIDF"
  echo "已启动 (PID $!) → 目标第 ${target} 章"
  echo "  日志: $LOG (./novel.sh log)"
  echo "  思考: $THINK (./novel.sh watch 一并实时显示)"
  echo "  说明: 自动复用活跃 run,跑过的章节不会重写"
}

cmd_stop() {
  local p
  if ! p="$(alive_pid)"; then echo "没有正在运行的长跑"; exit 0; fi
  kill -INT "$p" 2>/dev/null || true
  local i=0
  while ps -p "$p" >/dev/null 2>&1 && (( i < 10 )); do sleep 1; i=$((i+1)); done
  ps -p "$p" >/dev/null 2>&1 && { kill -TERM "$p" 2>/dev/null || true; sleep 2; }
  ps -p "$p" >/dev/null 2>&1 && kill -9 "$p" 2>/dev/null || true
  rm -f "$PIDF"
  echo "已停止 (PID $p) — 已提交章节无损,./novel.sh start 即断点续跑"
}

cmd_status() {
  local p
  if p="$(alive_pid)"; then echo "进程: PID $p 运行中"; else echo "进程: 未运行(./novel.sh start 可断点续跑)"; fi
  [[ -f "$DB" ]] || { echo "数据库不存在: $DB"; exit 1; }
  python3 - "$DB" <<'PY'
import sqlite3, sys
db = sqlite3.connect(f'file:{sys.argv[1]}?mode=ro', uri=True)
db.row_factory = sqlite3.Row
run = db.execute('select run_id,status,current_chapter,last_committed_chapter,chapters_committed '
                 'from novel_runs order by created_at desc limit 1').fetchone()
if not run:
    print('数据库中没有 run 记录(先 ./novel.sh start)')
    raise SystemExit
total, chars = db.execute('select count(*), coalesce(sum(length(body)),0) from chapters').fetchone()
print(f"run:   {run['run_id']}")
print(f"状态:  {run['status']}  第 {run['current_chapter']} 章进行中  本 run 已提交 {run['chapters_committed']} 章")
print(f"全书:  已提交 {total} 章  共 {chars} 字")
for r in db.execute('select chapter,title,arc,length(body) as n from chapters order by chapter desc limit 3'):
    print(f"  最新: 第{r['chapter']}章《{r['title']}》 {r['n']}字 [{r['arc']}]")
open_d = db.execute("select count(*) from novel_run_decisions where status='open'").fetchone()[0]
print(f"待人工决策: {open_d} 条")
PY
}

cmd_watch() {
  local args=(scripts/stress/watch.py --db "$DB")
  [[ -f "$THINK" ]] && args+=(--thinking "$THINK")
  exec python3 "${args[@]}"
}

cmd_log() {
  local f="$LOG"
  if [[ ! -f "$f" ]]; then
    f="$(ls -t story-data/drive*.log 2>/dev/null | head -n 1 || true)"
  fi
  [[ -n "${f:-}" && -f "$f" ]] || { echo "还没有长跑日志(先 ./novel.sh start)"; exit 1; }
  echo "跟随: $f (Ctrl-C 退出)"
  tail -n 30 -f "$f"
}

cmd_export() {
  python3 scripts/stress/export_novel.py --db "$DB"
}

cmd_book() {
  cmd_export
  local out
  out="$(ls -t story-data/novel/*.md 2>/dev/null | head -n 1 || true)"
  [[ -n "$out" ]] && { echo "打开: $out"; open -t "$out"; }
}

cmd_metrics() {
  python3 scripts/stress/metrics.py --db "$DB" --out "$METRICS"
}

cmd_smoke() {
  python3 scripts/stress/smoke.py --auto-answer "$@"
}

cmd_new() {
  local idea="${1:-}"; shift || true
  local target="${1:-300}" run="${2:-0}"
  if [[ -z "$idea" ]]; then
    echo '用法: ./novel.sh new "一句话创意" [目标章数] [自动跑到第N章]'
    echo '示例: ./novel.sh new "修鞋匠发现每双鞋都记录着穿鞋人的秘密" 300 3'
    exit 1
  fi
  local db="story-data/idea-$(date +%Y%m%d-%H%M%S).db"
  local extra=()
  if (( run > 0 )); then extra=(--apply --run "$run"); fi
  echo "[new] 一句话开书 → $db (目标 ${target} 章${run:+, 本次跑到第 ${run} 章})"
  PYTHONPATH=mcp-server/src python3 -m novel_mcp.cli create-from-idea \
    --db "$db" --idea "$idea" --target-chapters "$target" ${extra[@]+"${extra[@]}"}
  echo "[new] 完成后: ./novel.sh start(续跑) | 产物在 story-data/<slug>/"
}

case "${1:-help}" in
  new)     shift || true; cmd_new "$@" ;;
  start)   shift || true; cmd_start "$@" ;;
  stop)    cmd_stop ;;
  status)  cmd_status ;;
  watch)   cmd_watch ;;
  log)     cmd_log ;;
  export)  cmd_export ;;
  book)    cmd_book ;;
  metrics) cmd_metrics ;;
  smoke)   shift || true; cmd_smoke "$@" ;;
  *) sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' ;;
esac
