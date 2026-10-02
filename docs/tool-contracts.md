# 工具契约 — v0.11

机器可读的 schema 位于 `mcp-server/src/novel_mcp/tooldefs.py`,导出到 `mcp-server/tool_schemas.json`,并通过 MCP `tools/list` 暴露。

## 工具分组 — 共 94 个

### 叙事故事图 — 14

`story_get_state`, `narrative_thread_get`, `narrative_thread_search`, `mystery_create`, `clue_add`, `foreshadowing_list_open`, `belief_get`, `belief_update`, `emotion_debt_create`, `emotion_debt_resolve`, `narrative_pattern_search`, `chapter_plan_check`, `continuity_check`, `story_pressure_check`. (`chapter_commit` removed from the tool face in v0.8; the only commit entry is `chapter_finalize`.)

### 实体图 / 世界模型 — 16(+ V2 子图 12,见下)

安全/读取工具:

`entity_get`, `entity_search`, `entity_neighbors`, `entity_path_find`, `entity_context_get`, `entity_graph_stats`, `narrative_entity_links_get`, `entity_graph_check`.

作者/完整读取:

`entity_author_get`.

变更工具:

`entity_upsert`, `entity_alias_add`, `entity_attribute_set`, `entity_relation_upsert`, `entity_relation_end`, `narrative_entity_link`, `entity_graph_import`.

### 检索与上下文编译器 — 6

`entity_retrieve_relevant`, `narrative_retrieve_relevant`, `context_compile`, `context_preview`, `context_snapshot_get`, `context_explain`.

面向模型的首选入口是 `writer_context_get` / `planner_context_get`;它们现在在内部调用上下文编译器。低层检索工具主要用于检查、调试、评估或自定义智能体。

`context_snapshot_get` 与 `context_explain` 仅限**作者/调试用途**,因为规划器/审校者快照可能包含隐藏的世界真相。

### 规划运行时 / 一句话开书 — 17

`blueprint_get`, `blueprint_update`, `story_architect_get`, `story_architect_apply`, **`novel_architecture_generate`**(v0.10,四段式生成 + 校验 + 修复回路), `arc_plan_create`, `arc_plan_get`, `arc_progress_get`, `milestone_create`, `milestone_list`, `thread_schedule_update`, `thread_schedule_get`, `planning_rebuild_window`, `planning_get_window`, `chapter_plan_save`, `chapter_plan_get`, `planning_pressure_check`.

`blueprint_get`, `blueprint_update`, `story_architect_get`, `story_architect_apply`, `arc_plan_create`, `arc_plan_get`, `arc_progress_get`, `milestone_create`, `milestone_list`, `thread_schedule_update`, `thread_schedule_get`, `planning_rebuild_window`, `planning_get_window`, `chapter_plan_save`, `chapter_plan_get`, `planning_pressure_check`.

### 作者规划器 / 导演位 / 运行控制器 — 13

`planner_context_get`, `chapter_plan_generate`, **`chapter_directive_set`** / **`chapter_direction_propose`**(v0.11 导演位:本章引导指令落库/销账;模型基于当前状态提案走向候选), `novel_run_start`(v0.11 新增 `steering_mode` / `plan_review` 配置), `novel_run_step`, `novel_run_continue`, `novel_run_status`, `novel_run_pause`, `novel_run_resume`, `novel_run_report`, `novel_run_decision_list`, `novel_run_decision_submit`.

### 写作者 / 审校者 / 自动修订 — 13

`writer_context_get`, `chapter_draft_generate`, `chapter_draft_save`, `chapter_draft_get`, `chapter_review_all`, `chapter_review_get`, `chapter_revision_context_get`, `writing_workflow_status`, `chapter_finalize`, `chapter_semantic_review`, `chapter_review_full`, `chapter_auto_revise`, `chapter_auto_revision_loop`.

`writer_context_get`, `chapter_draft_generate`, `chapter_draft_save`, `chapter_draft_get`, `chapter_review_all`, `chapter_review_get`, `chapter_revision_context_get`, `writing_workflow_status`, `chapter_finalize`.

### 抽取候选闭环 — 3(v0.8)

`candidate_list`, `candidate_promote`, `candidate_reject` — Mention → Assertion → Canon 管线;晋升必须携带证据链。

### 实体图 V2 子图 — 12(v0.10)

`identity_profile_set`(身份档案链), `event_create` / `event_get` / `event_timeline`(一等事件与因果链), `assertion_create` / `assertion_list` / `assertion_resolve`(断言生命周期), `fact_disclosure_set` / `fact_disclosures_get`(双时序披露), `power_context_get` / `artifact_history_get` / `geography_tree_get`(力量/器物/地理子图)。

## 正典边界

`Entity/Narrative Canon != Planning != Draft != Review != Run State != Context Snapshot`。

上下文快照记录某个角色在某一章被允许看到的内容;它从不修改正典。

只有成功的定稿/提交才能修改实体图或叙事图正典。

## 机密边界

- `entity_author_get`:作者一侧的完整世界模型。
- `entity_get/entity_context_get`:章节 + 读者/视角(POV)过滤。
- `context_compile(role=writer)`:按章节切片的写作者安全记忆。
- `context_compile(role=planner|reviewer)`:作者层记忆;绝不要直接喂给正文生成。
- 机密别名/属性/关系可绑定 `fact_key`,并参与信念状态(BeliefState)可见性。
- 正文写作者永远不会收到作者专属的实体细节。
- 语义审校者可以在内部检视完整的作者实体上下文。
- 导演工具(`chapter_directive_set` / `chapter_direction_propose`)属作者层:planner/controller/admin 可用,写作者与读者不可见。
- Web BFF 的写动作(`/api/v1/actions/{tool}`、慢操作 `/api/v1/jobs/{tool}`)复用同一 `tool_allowed` 闸门,支持 `book` 多书作用域。

## 版本与运行规则

每份审校都属于精确的草稿版本。修订会使先前的通过结果失效。自动推进保持有界且可中断;`needs_author_decision` 是硬停止。
