# Novel Agent V0.9 — Phase A 进展:Entity Graph V2 核心

> 对应《现状评估与演进计划》Phase A 前三步:Identity/Role、Event 一等化、Assertion/Evidence,外加状态变化因果追溯(Relation History / Change Cause 的核心)。schema 演进作为内部记录直接落地,未引入任何对外概念。

## 新增能力

### 1. Identity / Role(`identity_profiles` 表 + `identity_profile_set` 工具)

一等身份档案,区分 `name / alias / pseudonym / disguise / role / title / position / incarnation`:

- `parent_profile_key` 串起转世/身份接续链;`scope_key` 标注官职所属势力/地点;
- `secrecy / reveal_after / fact_key` 与别名同规则——安全视图(`entity_get`)按 Reader/POV 可见性过滤,作者视图(`entity_author_get`)全量;测试覆盖:伪装身份对 Writer 隐藏、章节窗口(31 章起过期角色不再出现);
- `story_architect_apply` 支持 `identity_profiles` 组,新建小说可随架构一并导入。

### 2. 一等 Event(`events` 增强 + `event_participants` 表 + 3 个工具)

- `event_create`:参与者(角色 + 结果状态)、地点、结果(outcome)、后果(consequence)、因果链(`cause_event_id` / `cause_event_key`);**按 event_key 幂等**——重放仅更新事件本体,未显式传入参与者时保留既有参与者(declared_updates 重放安全);
- `event_get`:含向上因果链(≤16 层)与直接后果列表;
- `event_timeline`:按参与者实体 × 章节区间查询,即工作台"Timeline / Event Explorer"的后端;
- 参与者自动写入 `narrative_entity_links(narrative_type='event')`,Context Compiler 的计划锚点新增 `events[].event_key`——**计划提到的事件会把参与者实体带入 Writer/Planner 检索**(有测试);
- 幽灵参与者/幽灵 cause_event_id 被外键与预检双重拒绝。

### 3. 状态变化因果追溯

`entity_attribute_set` / `entity_relation_upsert` 新增 `cause_event_id`(工具 schema 同步):境界提升、关系变化、归属转移均可追溯到引发事件——方案 6.1.2 "状态变化应尽量能追溯到 Event" 落地。`chapter_commit` 的 declared_updates 中 `events` 条目升级为富事件(带 participants/outcome/consequence/cause),在提交事务内原子应用。

### 4. Assertion / Evidence(`fact_assertions` 表 + 3 个工具)

`Mention → candidate → confirmed/disproved/superseded` 的命题状态机:

- `assertion_create`:任何来源(抽取/作者)记录断言,携带 subject/predicate/object、章节、source span、抽取器、置信度、原文证据、可选 event_id;**抽取来源只能得到 candidate**(与 nkg_phase2 "LLM 不得自证 verified" 同一纪律);
- `assertion_resolve`:作者专属终态裁决——确认、否证、或以 `superseded_by` 取代(必须指向存在且非自身的断言);终态单向不可逆;
- `candidate_promote` 现在同时落一条 **confirmed 断言**(subject=晋升目标,predicate=identity/truth,source_span=`candidate:<id>`)——A0 的证据链从实体属性升级为一等断言,Phase A 两项工作在此接合。

## 工具面

新增 7 个工具:`identity_profile_set`、`event_create`、`event_get`、`event_timeline`、`assertion_create`、`assertion_list`、`assertion_resolve`;`entity_attribute_set` / `entity_relation_upsert` 增加 `cause_event_id` 参数。总数 **79 → 86**(tooldefs / server / tool_schemas / 网关注册四方一致,45 只读 / 41 写,bizTag `novel-agent-v0.9`)。版本号全面升至 0.9.0。

## 验证

- 测试 **58 / 58 passed**(52 原有全绿 + 6 个 V2 专项:身份可见性与链、事件因果链与幂等重放、断言生命周期与取代约束、晋升落断言、事件锚点流入检索、declared 富事件原子提交)。
- 全程零第三方依赖不变;所有新写入可参与 `chapter_commit` 环境事务。

## 补充批次(V0.10):双时序与专业子图

**双时序 per-holder(方案 6.1.4)**:新 `fact_disclosures(fact_key, holder, known_from_chapter)` 表。`fact_disclosure_set` 为任意持有者安排 knowledge_time;'reader' 行等价全局公开时刻。四道门全部改为"取 per-holder 披露 / reader 披露 / 旧 reveal_after 最早时刻":

- 实体安全视图(secret 别名/属性/关系)、`forbidden_facts`、`chapter_plan_check`(按接收者逐一判定)、正文泄密检查(只认 reader 时刻——POV 私知不能合法化为正文)。
- 兼容性:迁移回填 + `set_world_fact` 同步,旧 reveal_after 行为不变(58 项既有测试零修改通过)。

**专业子图(方案 6.1.5)**:基于既有原语(时序属性/关系/因果事件)提供三个作者层聚合视图,零新增表——`power_context_get`(境界/血脉/技能阶梯 + 传承关系,阶梯行附引发事件)、`artifact_history_get`(持有/绑定/封印/融合/觉醒沿革)、`geography_tree_get`(可见性过滤的空间包含树,secret 秘境对 reader 隐藏)。

工具 86 → **91**(+5);版本 0.10.0;网关注册重生成(49 只读/42 写);测试 **61/61**。

## Phase A 剩余(下一批)

- **Extraction Pipeline V2**:候选 → 断言 → 晋升的批量抽取质量评估(配合 Phase B 长跑);
- 从 stages/mysteries 反推历史事件:刻意**不做**自动回填(会注入低证据合成事件污染图),历史事件应经抽取候选 → 作者晋升进入。
