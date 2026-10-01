# Narrative-KG 工具指南

## 规划控制平面

- `blueprint_get` / `blueprint_update`:维护稳定的小说意图。
- `story_architect_get` / `story_architect_apply`:查看或编译长视野架构。
- `arc_plan_create` / `arc_plan_get` / `arc_progress_get`:管理篇章级意图与进度。
- `milestone_create` / `milestone_list`:按章节窗口管理目标成果。
- `thread_schedule_update` / `thread_schedule_get`:为长线叙事的生命周期阶段排期。
- `planning_rebuild_window` / `planning_get_window`:维护硬/中/软滚动计划。
- `chapter_plan_save` / `chapter_plan_get`:持久化经过校验的结构化章节计划。
- `planning_pressure_check`:发现缺失的硬窗口计划、逾期排期与里程碑积压。


## 实体图 / 世界模型

安全检索:

- `entity_get`:某一章节经读者/POV 过滤的实体快照。
- `entity_search`:按稳定键、安全名称/可见别名、类型或状态搜索。
- `entity_neighbors`:遍历可见的局部关系。
- `entity_path_find`:寻找实体之间的短可见路径。
- `entity_context_get`:为一组实体构建紧凑的安全上下文。
- `entity_graph_stats`:计数与分布。
- `narrative_entity_links_get`:查看跨层的叙事-实体链接。
- `entity_graph_check`:校验拟议的世界模型变更。

仅作者/完整检索:

- `entity_author_get`:包含隐藏别名、属性与关系。绝不将其授予仅做散文的写作者。

正典变更:

- `entity_upsert`:创建/更新正典实体身份。
- `entity_alias_add`:添加公开或秘密的别名/身份。
- `entity_attribute_set`:时序属性更新。
- `entity_relation_upsert`:时序类型化关系更新。
- `entity_relation_end`:结束一段历史关系而不删除历史。
- `narrative_entity_link`:将叙事线/谜团/情感债/事实/事件/阶段链接到实体。
- `entity_graph_import`:将通用实体节点/边导入当前故事图;先试运行。

可见性、时序与秘密状态规则见 `references/entity-graph.md`。


## 检索与上下文编译器 v0.7

- `entity_retrieve_relevant`:面向单章的确定性排序实体图检索。
- `narrative_retrieve_relevant`:确定性排序的叙事线/谜团/情感债检索。
- `context_compile`:面向 `writer`、`planner` 或 `reviewer` 的角色隔离上下文编译器。MCP 默认不持久化/只读。
- `context_preview`:不返回完整载荷的计数、排序与 token 估算。
- `context_snapshot_get`:对持久化上下文快照做作者/调试审计;不要授予仅做散文的写作者应用。
- `context_explain`:解释某个被选中的实体/叙事线/参考模式为何进入了持久化快照。

正常散文生成应优先使用 `writer_context_get`,它会调用编译器并自动持久化写作者安全的审计快照。

## 故事图

- `story_get_state`:正典章节规划前的必调工具。
- `narrative_thread_get`:查看某一条确切的长线叙事线。
- `narrative_thread_search`:查找活跃或相关叙事线。
- `mystery_create`:正式开启一个读者疑问。
- `clue_add`:记录受控的信息释放。
- `foreshadowing_list_open`:找出需要重新激活的旧铺设。
- `belief_get`:查看作者真相与持有者特定信念。
- `belief_update`:记录读者/角色知识转变。
- `emotion_debt_create`:开立一笔情感义务。
- `emotion_debt_resolve`:执行部分/全部情感兑现。
- `narrative_pattern_search`:查询只读的结构参考库。
- `chapter_plan_check`:校验临时或未保存的计划。
- `continuity_check`:校验拟议的正典事实/状态。
- `story_pressure_check`:检查叙事积压与兑现率。

自 v0.8 起 `chapter_commit` 不再是工具:正典提交的唯一入口是 `chapter_finalize`(见写作者/审校者运行时)。

## 抽取候选(A0)

- `candidate_list`:列出从已提交正文抽取的 Mention 层候选;晋升前绝不影响正典。
- `candidate_promote`:把候选显式晋升为正典实体或世界真相,并记录证据链(章节、抽取器、置信度、原文证据)。
- `candidate_reject`:以理由拒绝候选,留审计记录。

## 世界模型 V2(Phase A)

- `identity_profile_set`:一等身份档案(本名/假名/伪装/官职/称号/转世),支持保密门控与跨世接续链;安全视图自动过滤。
- `event_create`:一等事件(参与者/地点/因果链/结果/后果),按 event_key 幂等;参与者成为检索锚点。
- `event_get`:查单个事件,含因果链与直接后果。
- `event_timeline`:按参与者/章节区间查询世界事件时间线。
- `assertion_create`:记录带证据的候选断言;抽取来源不得自证 confirmed。
- `assertion_list` / `assertion_resolve`:断言查询与作者裁决(确认/否证/取代)。
- `entity_attribute_set` / `entity_relation_upsert` 新增 `cause_event_id`:状态变化可追溯到引发事件。

## 双时序与专业子图(Phase A 第二批)

- `fact_disclosure_set`:为持有者(角色或 'reader')安排 knowledge_time;per-holder 时刻取代全局 reveal_after,取最早适用时刻。
- `fact_disclosures_get`:列出已安排的披露计划。
- `power_context_get`:力量子图——境界/血脉/技能进阶阶梯(含引发事件)与传承关系。
- `artifact_history_get`:法宝子图——持有/绑定/封印/融合/觉醒完整沿革。
- `geography_tree_get`:地理子图——按可见性过滤的空间包含树。


## 写作者 / 审校者运行时

- `writer_context_get`:必需的散文安全上下文;隐藏的世界真相值已被移除。
- `chapter_draft_generate`:可选的已配置模型生成;保存非正典的带版本草稿。
- `chapter_draft_save`:把外部撰写或修订的散文持久化为带版本草稿。
- `chapter_draft_get`:查看某个确切的草稿版本。
- `chapter_review_all`:运行四个确定性审校者。
- `chapter_semantic_review`:运行四个具备作者视角的语义审校者;返回的发现中隐藏真相已脱敏。
- `chapter_review_full`:对同一确切草稿版本运行确定性 + 语义审校。
- `chapter_auto_revise`:基于当前脱敏发现创建新的修订草稿。
- `chapter_auto_revision_loop`:有界的审校/修订/复审循环,可选定稿。
- `chapter_review_get`:查看某个确切草稿版本的审校证据。
- `chapter_revision_context_get`:为修订打包当前草稿 + 发现 + 安全上下文。
- `writing_workflow_status`:查看计划/草稿/审校生命周期状态。
- `chapter_finalize`:最终审校闸门与正典提交。

不要跨版本复用审校。任何修订都会产生新的草稿版本,需要全新的确定性与语义审校。

## 作者规划者 / 小说运行控制器

- `planner_context_get`:作者层规划上下文;包含世界真相,绝非散文安全。
- `chapter_plan_generate`:已配置的规划者模型 -> 经校验的结构化章节计划。
- `novel_run_start`:创建一个持久化的、带显式目标/停止策略的有界自动推进运行。
- `novel_run_step`:最多执行一个章节事务。
- `novel_run_continue`:执行有界数量的章节事务,遇闸门提前停止。
- `novel_run_status`:查看运行状态、停止原因、决策与近期事件。
- `novel_run_pause` / `novel_run_resume`:主动的编排暂停/恢复。
- `novel_run_report`:确定性的周期/篇章检查点报告。
- `novel_run_decision_list` / `novel_run_decision_submit`:人在回路(HITL)的决策边界。

不要把 `novel_run_continue` 变成无界限循环。自动运行必须保持可中断、可审计。

## 模型端点配置

生成类工具依赖 OpenAI 兼容端点,按角色独立配置(均含可选 `*_TEMPERATURE`),未配置时逐级回退到 `NKG_LLM_*`:

| 角色 | 环境变量前缀 | 回退 | 未配置时的表现 |
|---|---|---|---|
| 规划者 | `NOVEL_PLANNER_` | `NOVEL_WRITER_*` → `NKG_LLM_*` | `chapter_plan_generate` 返回 `PLANNER_NOT_CONFIGURED` |
| 写作者 | `NOVEL_WRITER_` | `NKG_LLM_*` | `chapter_draft_generate` 抛错 |
| 语义审校 | `NOVEL_REVIEWER_` | `NOVEL_WRITER_*` | `chapter_review_full(semantic=true)` 返回 `INCOMPLETE` |
| 修订 | `NOVEL_REVISION_` | `NOVEL_WRITER_*` | `chapter_auto_revise` 抛错 |

每个前缀需要 `BASE_URL` / `API_KEY` / `MODEL` 三项。其余运行变量:`NOVEL_STORY_DB`(故事库路径)、`NOVEL_REFERENCE_ROOT`(只读参考图根目录)、`NARRATIVE_KG_ROOT`(外部抽取器可选)、`NOVEL_FACADE_TOKEN`(HTTP facade 鉴权)。

审校/生成不可用时不要静默降级:显式告知用户当前是仅确定性闸门,并保持草稿为未提交状态。

## 错误处理

所有校验错误码、审校 findings 码、提交闸门错误与 Run 决策类型的语义及修复方式见 `references/error-playbook.md`。先查根因再重试;不要用提高轮数或 BLOCK 覆盖来"解决"错误。
