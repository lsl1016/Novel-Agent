---
name: long-novel-writer
description: 适用于在 Narrative-KG 故事图、实体图世界模型、检索/上下文编译器、规划、写作者/审校者与运行控制器等 MCP 工具的支撑下,对一部长篇小说进行架构设计、规划、起草、修订、续写或自动推进。维护蓝图、篇章/滚动计划、章节计划、时序实体/关系、世界—角色—读者三层知识分离、长线谜团、伏笔、情感债、连续性、按角色隔离并受 token 预算约束的上下文、审校与正典提交。只读参考图仅用于抽象叙事机制;绝不复制其散文文本、具名实体或情节事实。
---

# 长篇小说写作者

将基于 MCP 的故事图(Story Graph)视为正典长期记忆,它由两个耦合层组成:实体图(Entity Graph,世界是什么)与叙事图(Narrative Graph,故事如何揭示它)。将规划运行时(Planning Runtime)视为关于未来结构的正典作者意图。将参考图(Reference Graph)视为只读的结构性指导。

## 规划层级

使用以下层级:

`Blueprint -> Story Architecture -> Arc Plan -> Thread Schedule/Milestones -> Rolling Window -> ChapterPlan -> Validate -> Draft -> Commit -> Replan`

在初始化小说、变更篇章、为叙事线排期、重建规划视野或保存章节计划(ChapterPlan)时,阅读 `references/planning-runtime.md`。

## 小说初始化工作流

在撰写新的长篇小说之前:

1. 使用 `blueprint_get` / `blueprint_update` 创建或查看蓝图(Blueprint)。
2. 设计世界真相(World Truth,作者独有)、核心实体图(角色/势力/地点/物品/功法/境界及其关系)、长线叙事线、主要谜团、情感债(EmotionDebt)、篇章骨架、里程碑与叙事线排期。
3. 以 `dry_run=true` 运行 `story_architect_apply`。
4. 修复错误/警告,然后以 `dry_run=false` 正典化应用。
5. 使用 `planning_rebuild_window` 构建第一个滚动窗口。
6. 不要把规划中的未来揭示当作当前的读者知识或角色知识。

使用稳定键。不要仅凭散文式名称来标识长期存在的状态。

## 篇章工作流

在篇章开始时:

1. 创建或查看其 `ArcPlan`。
2. 定义 `primary_goal`、`surface_conflict`、隐藏叙事功能、允许的揭示、禁止事实、继承的叙事线与退出条件。
3. 除非用户明确想要叙事重置,否则至少将一条既有叙事线延续进新的大篇章。
4. 添加里程碑窗口与叙事线阶段窗口,而不是硬编码遥远的场景散文。
5. 重建滚动窗口。

## 滚动规划纪律

默认采用:

- 硬视野:5 章——具体目标与叙事线推进。
- 中视野:20 章——可能的节拍,可修订。
- 软视野:50 章——仅方向与约束。

不要提前数百章进行场景级规划。在重大揭示、出人意料的角色选择、篇章切换或与当前计划出现实质性偏离之后,重建规划。

## 检索与上下文纪律

将 V0.7 上下文编译器(Context Compiler)作为默认的记忆装载层。规划者、写作者与审校者的上下文分别编译,带有角色专属可见性、章节快照、相关性排序与 token 预算。

- 使用 `planner_context_get` 进行作者侧规划。它可能包含世界真相。
- 使用 `writer_context_get` 进行散文生成。它是正典的散文安全上下文包。
- 在进行高成本生成之前,使用 `context_preview` 检查 token 规模以及被选中的实体/叙事线。
- 仅在作者/调试工作流中使用 `context_snapshot_get` / `context_explain`;规划者/审校者快照可能包含秘密。
- 低层图检索仅用于精确的追问,不要用它手工重建整章上下文。

在调试记忆选取、token 压力、实体缺失或角色隔离问题时,阅读 `references/context-compiler.md`。

## 强制章节工作流

在完成第 1–5 步之前,不得开始正典散文写作。

1. 针对目标章节调用 `story_get_state`。
2. 使用编译后的作者/规划状态(自动规划时使用 `planner_context_get`)检查当前篇章、滚动窗口、相关叙事线、谜团、情感债、信念状态、里程碑与世界模型状态。
3. 低层图/叙事线工具仅用于精确的追问。当上下文编译器可用时,不要手工拼装整章上下文。
4. 构建结构化章节计划。至少包含 `primary_goal`、篇章、叙事线推进、知识/揭示意图,以及任何谜团/线索/兑现操作。
5. 调用 `chapter_plan_save`。不要基于 `blocked` 状态的计划起草。对 `warning` 状态要有意识地审视。
6. 如果结构示例有帮助,调用 `narrative_pattern_search`;只使用抽象结构。
7. 调用 `writer_context_get`。使用这个散文安全包,而不是原始故事图真相。隐藏的世界真相值必须对写作者上下文屏蔽。
8. 使用 `chapter_draft_generate` 生成散文,或在外部写作后用 `chapter_draft_save` 持久化。草稿不是正典。
9. 当语义审校端点已配置时,优先对确切的草稿版本使用 `chapter_review_full`。它会运行四个确定性审校者加四个语义审校者。如果语义审校不可用,则使用 `chapter_review_all`,并明确将结果视为仅确定性审校。
10. 如果任何审校者返回 `BLOCK`,不要提交。手动修订,或使用 `chapter_auto_revise`。若需要有界自动化,使用 `chapter_auto_revision_loop`;保持默认轮数较小,且绝不使用自动 BLOCK 覆盖。每个新草稿版本都必须从头重新审校。遇到校验/审校错误代码时,查阅 `references/error-playbook.md` 对应条目,修复根因后重试。
11. 对于正式使用的正典章节,在该确切草稿版本通过全部八项审校后,调用 `chapter_finalize(require_semantic=true)`。如果有意不启用语义审校,只有在明确知晓闸门仅为确定性审校时才可定稿。
12. 在规划下一章之前,查看 `planning_pressure_check` 与 `writing_workflow_status`。

如果 MCP 工具不可用,不要声称已读取或更新了故事图或规划运行时。让草稿保持明确的未提交状态。

## 自动化小说运行工作流

当用户希望系统持续推进章节,而不是手动触发每一次章节事务时,使用小说运行控制器(Novel Run Controller)。

1. 把控制器视为有界编排器,而不是无限后台任务。
2. 从 `novel_run_start` 开始。优先使用显式目标,如 `target_chapter`、`target_arc_key` 或 `max_chapters`。
3. 以较小的 `max_steps` 使用 `novel_run_continue`;控制器会在调用之间持久化进度。
4. 自动章节顺序为:作者规划 -> 经校验的章节计划 -> 安全写作者上下文 -> 带版本的草稿 -> 确定性/语义审校 -> 有界修订 -> 最终提交 -> 压力检查/重新规划。
5. 如果控制器进入 `needs_author_decision`,停止自动推进。读取 `novel_run_decision_list`,检查证据,做出所需的规划/故事/模型决策,并用 `novel_run_decision_submit` 解决。
6. 不要通过静默覆盖被阻塞的审校来解决决策。修复章节计划/草稿/状态,或显式更改安全的运行配置。
7. 在作者侧大规模重构之前使用 `novel_run_pause`;仅当不存在未解决决策时才使用 `novel_run_resume`。
8. 在篇章边界和配置的周期间隔处生成/检查 `novel_run_report`。
9. 绝不将 `planner_context_get` 用作写作者的散文上下文。它是作者层上下文,可能包含隐藏的世界真相。只有 `writer_context_get` 是散文安全的。
10. 如果自动规划者返回 `author_questions`,将其视为人工决策边界,而不是虚构新的世界真相。

运行状态、停止条件、决策与恢复行为详见 `references/run-controller.md`。

## 实体图 / 世界模型规则

将世界结构维护为一等实体,而不是把一切埋进自由格式的章节文本或 `character_states` 中。

使用:

- `Character`、`Faction`、`Location`、`Item`、`Skill`、`Realm`、`Artifact`、`Organization`、`Bloodline`、`Event` 等稳定实体类型;
- 对随章节变化的值使用时序属性;
- 对归属、成员、位置、亲缘、同盟、敌对、功法使用、境界要求以及因果/世界关系使用时序类型化关系;
- 用 `narrative_entity_link` 将谜团/叙事线/情感债/事实/事件/阶段连接到它们所涉的实体。

保持普通实体名称/属性散文安全。将隐藏的身份/关系值放入秘密别名/属性/关系中,并尽量绑定到一个 `WorldFact`。安全检索工具会依据章节 + 读者/视角(POV)知识过滤这些值。

在修改重要世界结构之前,调用 `entity_graph_check`。不要通过删除历史状态来表达变化;应创建新的时序属性或结束一段关系。

在创建或更改角色、势力、地点、物品、功法、境界、神器、关系或隐藏身份时,阅读 `references/entity-graph.md`。

## 知识分层规则

始终维护三个相互分离的层:

- **世界真相(World Truth)**:实际为真的内容。除非已揭示,仅作者可见。
- **角色知识(Character Knowledge)**:每个角色知道、相信、怀疑或拒绝的内容。
- **读者知识(Reader Knowledge)**:文本已允许读者知道或合理相信的内容。

撰写视角(POV)场景时,使用 `Reader Knowledge + POV Character Knowledge`。绝不将作者知识或未来规划知识直接转化为叙述。

涉及身份揭示、隐藏历史、欺骗、不可靠信念或 POV 不对称时,阅读 `references/belief-state.md`。

## 谜团与伏笔纪律

有意识地制造持久的读者疑问。优先采用分阶段释放:

`Mystery -> weak clue -> complication -> partial reveal -> contradiction/reinterpretation -> major reveal -> payoff/consequence`

线索用 `clue_add` 记录。不要自行把它认证为伏笔(Foreshadowing);只有后续明确的呼应/揭示/兑现才能追溯性地证明它。

优先选择能改变旧信息含义的揭示,而不是仅仅追加说明性内容。

在创建、重新激活、揭示或兑现长线叙事时,阅读 `references/foreshadowing.md`。

## 情感债纪律

将 EmotionDebt(情感债)用于持久的情感义务,如屈辱、承诺、牺牲、背叛、失去、误解、感恩、复仇、离别或未了的心愿。

优先选择带有后果的兑现。解决一笔情感债应当改变关系、目标、地位或未来冲突,而不只是清空账目。

情感债的铺设与兑现设计详见 `references/emotion-debt.md`。

## 章节计划纪律

优先选择能推进 1–3 条叙事线的计划。不要把每条活跃叙事线都硬塞进每一章。

除非有意将其作为短小的局部问题,否则不要在同一章内开启并完全解决一个长线谜团。

遵守篇章的 `forbidden_facts` 与已排期的叙事线窗口。规划中的未来揭示还不是当前的揭示。

## 参考图纪律

对以下结构性问题使用 `narrative_pattern_search`:

- 如何为一个 300+ 章的身份谜团分层;
- 如何制造信念反转;
- 如何延迟情感兑现而又不遗忘它;
- 后续的揭示如何能让旧章节更有价值。

只使用跨度、阶段序列、模式类型、能力与指标等结构化元数据。不要导入参考作品中的名称、措辞、场景、对话或情节事实。

## 草稿、审校与提交契约

把有意的正典更新放入草稿的 `declared_updates`。只有当 `chapter_finalize` 成功通过提交闸门(Commit Gate)时,它们才会被应用:

- `threads`
- `events`
- `mysteries`
- `clues`
- `reveals`
- `belief_updates`
- `emotion_debts`
- `payoffs`
- `world_facts`
- `character_states`
- `entities`
- `entity_aliases`
- `entity_attributes`
- `entity_relations`
- `narrative_entity_links`

(`arc_transition` 属于 ChapterPlan 的篇章切换声明,不是正典变更;它由 `chapter_plan_check` 校验,不进入 `declared_updates`。)

仅在语义端点已配置时使用 `auto_extract=true`。自动提取的条目只是候选,绝不能覆盖作者意图。

自 v0.8 起 `chapter_commit` 已从工具面移除:正典提交的唯一入口是 `chapter_finalize`。正常技能工作流必须使用带版本草稿 -> `chapter_review_all`/`chapter_review_full` -> `chapter_finalize`。成功定稿会将已保存的章节计划与滚动计划(RollingPlan)条目标记为已提交。

## 模型端点与可用性

生成与语义审校依赖按角色配置的 OpenAI 兼容端点(`NOVEL_PLANNER_*` / `NOVEL_WRITER_*` / `NOVEL_REVIEWER_*` / `NOVEL_REVISION_*`,回退 `NKG_LLM_*`)。配置缺失的表现与降级规则见 `references/tools.md` 的「模型端点配置」。不要在语义审校不可用时静默改为仅确定性闸门而不告知用户。

## 不可违反的规则

1. 不要仅仅因为作者数据库里存在就揭示世界真相。
2. 不要让 POV 角色依据无支撑的知识行动。
3. 不要让未来规划状态变成现在时的读者知识。
4. 不要把每条线索都变成已确认的伏笔。
5. 不要在没有角色、情节、世界或情感理由的情况下创建长线谜团。
6. 不要把重大揭示仅当作信息说明;优先重新诠释与后果。
7. 除非明确重置故事,否则不要以零继承叙事线进入新的大篇章。
8. 不要让高强度 EmotionDebt 无限期休眠;在新增之前先检查压力。
9. 不要在没有规划后果的情况下关闭一次兑现。
10. 不要复制参考小说的散文或情节事实。学习机制,而不是表达。
11. 不要基于被阻塞的章节计划起草正典散文。
12. 当相应工具失败时,不要声称计划或章节已保存/提交。
13. 不要把隐藏的世界真相值喂给写作者模型。使用 `writer_context_get`。
14. 不要提交未经审校的草稿;任何草稿修订之后,不得复用审校者的批准。
15. 将 `BLOCK` 视为硬停止,除非人工明确授权覆盖并记录理由。
16. 不要把确定性 PASS 当作不存在改述泄密、OOC 行为、揭示越界或节奏问题的证明;可用时应使用语义审校。
17. 绝不在返回给写作者的修订提示或审校发现中暴露隐藏的世界真相值。
18. 为自动修订循环设定界限;如果模型在配置轮数内无法解决 BLOCK,停止并把未解决的证据呈现给人类作者。
19. 绝不运行无界限的自主章节循环;使用带显式目标和有界继续步数的持久化小说运行。
20. 将 `needs_author_decision` 视为硬性的编排停止。不要伪造缺失的作者选择。
21. 绝不把 `planner_context_get` 直接用于散文生成;它是作者层上下文,可能包含隐藏的世界真相。
22. 绝不把 `entity_author_get` 暴露给仅做散文的写作者;应改用安全的实体图检索工具。
23. 当秘密别名/属性/关系能够安全建模时,不要把隐藏身份或关系存储在公开的实体名称/属性中。
24. 不要把参考图实体导入新小说的故事图;参考资料保持只读且结构上分离。
25. 不要通过向散文模型喂入规划者/审校者上下文快照来绕过 `writer_context_get`。
26. 将上下文快照视为审计状态,而不是正典(Canon);绝不仅因为某条目出现在检索轨迹中就推断故事真相。
27. 保持检索浅层化、以相关性驱动;不要把完整的实体图/叙事图加载进每一章。

## 参考文档

- `references/planning-runtime.md` — 蓝图、篇章、滚动视野、叙事线排期、里程碑、章节计划。
- `references/writing-workflow.md` — 章节事务与规划模板。
- `references/narrative-model.md` — 叙事图实体及状态含义。
- `references/entity-graph.md` — 实体图世界模型、时序关系、安全/作者视图与叙事交叉链接。
- `references/context-compiler.md` — 按角色隔离的检索、章节切片、相关性排序、token 预算与上下文审计。
- `references/foreshadowing.md` — 谜团/线索/揭示/兑现的生命周期。
- `references/belief-state.md` — 世界真相与角色知识、读者知识的对比。
- `references/emotion-debt.md` — 情感铺设、随时间发酵、部分兑现与后果。
- `references/tools.md` — Narrative-KG、规划、写作者、审校者与提交闸门的工具指南。
- `references/writing-runtime.md` — 草稿版本化、安全写作者上下文、确定性 + 语义审校者、修订循环与定稿闸门。
- `references/semantic-review.md` — 语义泄密/OOC/叙事/节奏审计与有界自动修订规则。
- `references/run-controller.md` — 持久化的有界自动推进运行、停止条件、作者决策、暂停/恢复与阶段报告。
- `references/error-playbook.md` — 计划校验/审校 findings/提交闸门错误码与 Run 决策类型的排查手册。
