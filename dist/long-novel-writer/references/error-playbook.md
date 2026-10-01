# 错误与决策代码手册

运行时通过结构化 `error.code` / 校验 `errors[].code` / 决策 `decision_type` 报告问题。遇到失败时先在这里查语义,再修复,不要盲目重试。

## 1. 章节计划校验(`chapter_plan_save` / `chapter_plan_check`)

| code | 含义 | 修复方式 |
|---|---|---|
| `CHAPTER_GOAL_MISSING` | 结构化计划缺少 `primary_goal` | 补一句话首要目标 |
| `WORLD_TRUTH_LEAK` | 计划在 `reveal_after` 之前让某个 holder 知悉秘密事实 | 把该断言移到合法章节,或改为 `suspects` 级暗示;确需提前必须先由作者修改 World Fact 的 `reveal_after` |
| `KNOWLEDGE_WITHOUT_SUPPORT` | `assume_known=true` 但信念状态中没有支撑 | 补一次前置 `belief_update`,或去掉 `assume_known` |
| `ARC_WITHOUT_INHERITED_THREAD` | `arc_transition.is_new_arc` 但没有继承叙事线 | 在 `inherited_thread_keys` 中至少填一条既有叙事线 |
| `ARC_FORBIDDEN_REVEAL` | 揭示命中当前篇章 `forbidden_facts` | 移出本章,或由作者修改篇章约束 |
| `EARLY_PAYOFF` | 兑现早于叙事线 `target_min` | 推迟兑现,或改部分兑现;确实要提前需作者确认并调整 target |
| `TOO_MANY_THREADS_ADVANCED` | 一章推进 >3 条叙事线(warning) | 收敛到 1-3 条,其余移入 `maintain`/`sleep` |
| `SAME_CHAPTER_MYSTERY_OPEN_CLOSE` | 同章开启并解决同一谜团(warning) | 除非有意做短弧局部悬念,拆到不同章 |
| `DUE_THREAD_NOT_ADVANCED` | 有到期排期但计划未推进(warning) | 把到期叙事线加入 `advance`,或先调整 `thread_schedule` |

校验状态含义:`ready`(通过)/`warning`(有警告,可有意识接受)/`blocked`(有错误,禁止起草)。`chapter_plan_save(allow_blocked=false)` 会在 blocked 时拒绝保存。

## 2. 连续性与正文审校 findings

| code | 含义 | 修复方式 |
|---|---|---|
| `SECRET_LITERAL_IN_PROSE` | 正文出现未声明合法揭示的秘密字面值 | 删除或模糊化该表述;若为合法揭示,必须在 `declared_updates.reveals` 声明且 recipients 覆盖 reader/POV |
| `PLANNED_REVEAL_NOT_DECLARED` | 计划了揭示但草稿未声明(BLOCK) | 在 `declared_updates.reveals` 中补声明;确实没写就该改计划 |
| `PLANNED_PAYOFF_NOT_DECLARED` | 计划了兑现但草稿未声明(BLOCK) | 补 `declared_updates.payoffs`,或修订计划 |
| `PLANNED_THREAD_NOT_DECLARED` | 计划推进的叙事线在草稿中无任何声明(warn) | 通过 clues/reveals/payoffs/events 声明推进,或修订计划 |
| `WORLD_FACT_CONTRADICTION` | 声明事实与正典世界真相冲突 | 改正文/声明;绝不修改既定 World Fact 来迁就草稿 |
| `CHARACTER_STATE_JUMP` | 角色状态无过渡理由跳变(warn) | 补 `transition_reason` 或在正文中铺垫过渡 |
| `DEAD_POV_CHARACTER` | POV 角色正典已死亡(BLOCK) | 换 POV;除非计划显式 `allow_posthumous_pov` |
| `CHAPTER_PLAN_MISSING` / `CHAPTER_PLAN_BLOCKED` | 无计划/计划被阻止 | 先完成/修复 ChapterPlan |

## 3. 模型与生成

| code / 信号 | 含义 | 修复方式 |
|---|---|---|
| `PLANNER_NOT_CONFIGURED` | 未配置规划模型 | 设置 `NOVEL_PLANNER_*` 或 `NOVEL_WRITER_*` 环境变量(见 tools.md「模型端点配置」) |
| `SEMANTIC_REVIEWER_NOT_CONFIGURED` | 未配置语义审校模型 | 设置 `NOVEL_REVIEWER_*`;不可用时退回 `chapter_review_all` 并明确告知用户这是仅确定性结果 |
| `INVALID_PLANNER_OUTPUT` / `INVALID_REVISION` 类 | 模型输出不可解析 | 重试一次;连续失败换模型或转人工 |
| `REVISION_NO_CHANGE` | 修订模型输出与原稿相同 | 通常提示上下文不足;检查 findings 是否为空或换 revision 模型 |
| `revision_limit_reached` | 有界修订耗尽仍未 PASS | 停止,向作者呈现 history 中各版本 verdict 与 findings |
| `revision_stalled` | 无可修订项但仍 BLOCK | 检查是否 BLOCK 来自确定性审校且需要改计划而非改正文 |
| `review_incomplete` | require_semantic 但语义审校不可用 | 配置审校模型,或显式降级为仅确定性并重新走闸门 |

## 4. 提交闸门(`chapter_finalize`)

| code | 含义 | 处理 |
|---|---|---|
| `REVIEW_INCOMPLETE` | 缺少必需 reviewer(返回 `missing` 列表) | 对该版本补跑缺失的审校;不得凭旧版本的审校结果定稿 |
| `REVIEW_BLOCKED` | 综合 verdict 为 BLOCK | 修订;`override_block=true` 仅限人工明确授权且必须给 `override_reason` |
| `REVIEW_WARNINGS_REQUIRE_APPROVAL` | WARN 但 `allow_warnings=false` | 人工审查 warnings 后显式接受,或先修复 |
| `PLAN_REVALIDATION_BLOCKED` | 提交时计划重验失败 | 回到规划修复,不要绕过 |

必需 reviewer 集合:确定性四项 `knowledge_leak`/`continuity`/`narrative`/`character`;`require_semantic=true` 时追加语义四项 `semantic_knowledge_leak`/`semantic_character`/`semantic_narrative`/`semantic_pacing`。注意语义审校者缺项会被规范化为 WARN(`SEMANTIC_REVIEWER_OUTPUT_MISSING`),因此审校输出不完整不等于通过。

## 5. Run Controller 决策类型(`novel_run_decision_list`)

| decision_type | 触发 | 典型处理 |
|---|---|---|
| `story_pressure` | 叙事+规划风险数 ≥ `pressure_risk_limit` | 处理 risks(关闭谜团/排期/补计划),必要时 `config_patch` 调阈值 |
| `chapter_plan_required` | 当前章无可用计划且 `auto_plan=false` | 手工保存计划,或决策开启 auto_plan |
| `planner_failed` | 自动规划模型调用失败 | 检查模型配置;手工保存计划 |
| `chapter_plan_blocked` | 自动生成的计划被校验阻止 | 按第 1 节 code 修复后手工保存 |
| `writer_failed` | 写作模型调用失败 | 检查模型配置;或外部写作后 `chapter_draft_save` |
| `review_or_revision_blocked` | 审校/修订循环未能提交 | 按第 2/3 节处理 findings;人工修订后重走审校 |
| `finalize_failed` | 提交闸门拒绝 | 按第 4 节处理 |

`needs_author_decision` 是硬停止:先处理根因,再 `novel_run_decision_submit`,resolution 形如:

```json
{"action": "resume", "config_patch": {"pressure_risk_limit": 6}}
```

`action` 取 `resume`(默认)/`pause`/`abort`;`config_patch` 只接受安全键(target_chapter、max_chapters、max_revision_rounds、require_semantic、allow_warnings、auto_plan、stop_on_pressure、pressure_risk_limit、report_every、三个 horizon、四个 model)。存在 open 决策时 `novel_run_resume` 会被拒绝。
