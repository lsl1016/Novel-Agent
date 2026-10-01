# 小说运行控制器

控制器是一个持久化的、有界的编排器,用于重复的章节事务。它不会绕过规划、审校或提交闸门。

## 状态机

`running -> paused | needs_author_decision | completed | cancelled`

每个成功的章节遵循:

`ensure plan -> draft -> review -> bounded revision -> finalize -> advance -> report/replan`

崩溃/重启安全:run、events、decisions、reports 全部持久化在 Story DB;进程死后用 `novel_run_status` 找回 current_chapter、stop_reason 与 open decisions,直接继续。

## 启动示例

```json
// novel_run_start
{
  "start_chapter": 1,
  "target_chapter": 50,
  "max_revision_rounds": 3,
  "require_semantic": true,
  "allow_warnings": true,
  "auto_plan": true,
  "stop_on_pressure": true,
  "pressure_risk_limit": 4,
  "report_every": 10,
  "hard_horizon": 5, "medium_horizon": 20, "soft_horizon": 50
}
```

推荐配置原则:

- 必须设定显式目标:`target_chapter`、`target_arc_key` 或 `max_chapters` 至少其一;
- 保持 `max_revision_rounds` 较小(默认 3;经 lsl1016 网关注册的部署被收紧为 ≤3);
- 正式写作保持 `require_semantic=true`;
- 在故事稳定之前保持 `stop_on_pressure=true`;
- 使用 `report_every` 持久化周期性检查点。

推进时以较小 `max_steps` 调 `novel_run_continue`(如 3-5);不要外层再包无限循环。

## 压力停止机制

`stop_on_pressure=true` 时,每章开始统计:叙事风险(`story_pressure_check`:mystery_backlog_high / opening_rate_exceeds_payoff_rate / stale_foreshadowing / emotion_debt_overdue)+ 规划结构性风险(`planning_pressure_check`:HARD_WINDOW_GOAL_MISSING / HARD_WINDOW_CHAPTER_PLAN_MISSING / BLOCKED_CHAPTER_PLAN / THREAD_SCHEDULE_OVERDUE / MILESTONE_OVERDUE)。风险总数 ≥ `pressure_risk_limit` 即转入 `story_pressure` 决策。阈值不是失败信号——它是让作者在剧情失衡早期介入的设计。

## 自动规划

`chapter_plan_generate` 是作者层操作。`planner_context_get` 有意包含世界真相,以便规划者能正确塑造伏笔与延迟揭示。绝不要将该上下文复用为写作者输入。

如果规划者返回 `author_questions`,停下来询问人类作者,而不是虚构持久真相——这是 Story Architect 的人工边界。

## 决策边界

`needs_author_decision` 是硬停止。完整决策类型与处理方式见 `error-playbook.md` 第 5 节。resolution 格式:

```json
{"action": "resume", "config_patch": {"pressure_risk_limit": 6}}
```

- `action`:`resume`(默认)/`pause`/`abort`;
- `config_patch` 仅接受安全配置键;存在 open 决策时 `novel_run_resume` 会被拒绝;
- 先解决根因(修计划/草稿/排期),再提交决策;绝不能通过静默覆盖被阻塞的审校来解决决策。

## 报告

`novel_run_report(run_id, persist=true)` 生成确定性阶段报告:已提交章节摘要、事件阶段计数、当前压力、open decisions、停止原因。每 `report_every` 章自动持久化一次;篇章边界与人工介入前应主动生成并检查。
