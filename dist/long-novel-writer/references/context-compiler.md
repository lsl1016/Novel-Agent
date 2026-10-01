# 检索与上下文编译器 v0.7

在长篇写作中,将上下文编译器(Context Compiler)作为默认的记忆装载层。

## 角色隔离

- 规划者:`planner_context_get` / `context_compile(role=planner)` 可以看到世界真相与作者侧实体图。
- 写作者:`writer_context_get` / `context_compile(role=writer)` 必须只包含读者/POV 可见的信息。
- 审校者:语义审校使用独立的、具备作者视角的审校者上下文;返回的发现仍需做秘密脱敏。

绝不把规划者/审校者快照喂给散文写作者。

## 推荐工作流

1. 保存/校验章节计划。
2. 调用 `writer_context_get`;不要用几十个图工具手工拼装大而全的上下文。
3. 低层的 `entity_get`、`entity_neighbors`、`belief_get` 或 `narrative_thread_get` 仅用于精确补查缺失事实或调试。
4. 当 token 压力或检索质量不确定时,在生成前使用 `context_preview`。
5. 仅在作者/调试场景中使用 `context_snapshot_get` 与 `context_explain`,审计加载了什么以及为什么加载。

## 相关性

实体排序依据:章节计划引用、POV、当前位置、活跃叙事线关联、新近程度以及未解决的叙事义务。叙事线排序依据:推进/维持意图、叙事线排期、未决谜团、情感债(EmotionDebt)以及近期呼应。

图扩展刻意保持浅层:1 跳是常态;2 跳已经较弱。除非某个具体的连续性问题确有需要,否则不要请求宽泛的多跳遍历。

## 时间切片

对于第 N 章,正典检索使用 N-1 快照。未来的实体属性/关系以及未来的正典章节绝不能出现在写作者上下文中。

## token 预算

默认值与分区软上限(占该角色预算的百分比):

| 分区 | writer (12k) | planner (24k) | reviewer (20k) |
|---|---|---|---|
| chapter_plan | 10% | 8% | 10% |
| world_truth_ledger | — | 14% | 12% |
| beliefs | 10% | 8% | 10% |
| entities | 22% | 20% | 22% |
| narrative | 20% | 20% | 18% |
| recent_canon | 20% | 10% | 12% |
| character_state | 8% | — | 8% |
| planning(window/schedule/milestones) | — | 10% | — |
| reference_patterns | 5% | 10% | — |
| safety(forbidden+contract) | 5% | — | 8% |

把这些预算视为可配置的运维默认值,而不是文学规则。如果 `context_preview` 报告 `over_budget`,先缩小范围或检查为何包含了高成本条目,再考虑提高预算。

超预算时的裁剪顺序(编译器自动执行,了解它有助于诊断):参考模式 → 最旧正典章节 → 角色状态尾部 → 叙事线尾部 → 实体尾部 → 信念 → 世界真相账本尾部。**ChapterPlan、安全契约与每类至少一条最高分条目始终保留。**

## 快照与可解释性

快照 ID 形如 `ctx_{chapter}_{role}_{digest}`,内容寻址(同输入同 ID,`ON CONFLICT DO NOTHING`)。`context_explain(snapshot_id, item_key)` 返回某条目进入快照的确定性理由与分数,`item_key` 形如 `entity:hero` / `thread:THREAD_X` / `reference:<thread_key>`。

用快照回答:

- 模型在该章节被允许知道什么;
- 某个实体/叙事线为何被检索;
- 是否有秘密跨越了角色边界;
- 上下文规模是否在长程运行中持续膨胀。

## 参考模式

规划者上下文可以接收结构化的参考图模式。只使用阶段序列、跨度、模式类型、能力与指标。绝不复制源文散文或具名实体。
