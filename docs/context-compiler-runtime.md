# Novel Agent V0.7(基础篇) — 检索与上下文编译器运行时

> **状态(2026-10-02,V0.11)**:本文的机制描述(确定性评分/角色隔离/预算打包/裁剪序)仍然准确;
> 以下数字与能力已演进:默认预算 **writer 56k / planner 120k / reviewer 104k**(编译器硬顶 256k);
> planner 上下文新增注入 **`author_directive`(导演指令)**、**`due_foreshadowing`(伏笔销账台账,带 callback_key)**、
> `dormant_threads` / `aging_debts`;v0.10 实体图 V2(身份/事件/断言/双时序)丰富了检索面。
> 详见 `phase-b-final-report.md` 与 `run-controller.md` 导演位章节。


## 1. 目标

V0.7 解决的问题不是“模型能不能查到图谱”，而是：当小说写到几十万字、实体和线程规模增长后，系统如何自动判断某一章真正需要加载哪些记忆，并在权限、时间和 Token 预算约束下编译成可直接给 Planner / Writer / Reviewer 使用的上下文。

核心原则：

- **Graph Snapshot at Chapter N**：所有 Story Graph 查询按章节切片，不读取未来状态。
- **Role Isolation**：Planner、Writer、Reviewer 使用不同权限的上下文。
- **Relevance First**：不把整个 Entity Graph / Narrative Graph 塞给模型。
- **Budgeted Context**：每种角色都有默认 Token 预算和软分区配额。
- **Explainable Retrieval**：每个被检索实体/线程都有可追溯的分数与原因。
- **Reference Isolation**：参考库只返回结构化模式，不返回原文、命名实体和剧情事实。

## 2. 三类上下文（Context）

### 2.1 规划器上下文（Planner Context）

默认预算 24k tokens(v0.7 基线;V0.11 起 planner 默认 120k,可配)。可以看到：

- 蓝图（Blueprint）
- 世界真相（World Truth）
- 作者实体图（Author Entity Graph）
- NarrativeThread / Mystery / EmotionDebt
- 篇章（Arc）/ 滚动窗口（Rolling Window）/ 里程碑（Milestone）/ 叙事线排期（Thread Schedule）
- 故事/规划压力（Story/Planning Pressure）
- 参考模式（Reference Pattern）结构元数据

Planner Context 是作者层，不允许直接用于正文生成。

### 2.2 写作者上下文（Writer Context）

默认预算 12k tokens(v0.7 基线;V0.11 起 writer 默认 56k,可配)。只能看到：

- 章节计划（ChapterPlan）
- 读者认知（Reader Knowledge）
- 当前 POV 角色可知信息
- 当前章节切片下的可见实体、属性和关系
- 与本章最相关的 NarrativeThread / Mystery / EmotionDebt
- 近期 Canon
- `forbidden_fact_keys`（只有 key，不包含隐藏 truth value）

Writer Context 不包含隐藏 World Truth、秘密 alias、秘密 relation 或作者层备注。

### 2.3 审校者上下文（Reviewer Context）

默认预算 20k tokens。可以看到作者层事实，用于检查：

- 语义泄密
- OOC
- 连续性冲突
- Reveal 强度失控
- 叙事职责偏离

Reviewer 可以内部查看秘密，但其对 Writer 返回的 finding 仍必须脱敏。

## 3. 检索流程

```text
章节计划（ChapterPlan）
    ↓
锚点发现（Anchor Discovery）
    ├─ POV
    ├─ entity_keys / 角色 / 地点 / 物品
    ├─ advance / maintain NarrativeThread
    ├─ 已排期的叙事线阶段
    └─ 未解决的 Mystery / EmotionDebt
    ↓
实体检索（Entity Retrieval）
    ├─ 计划直接引用
    ├─ POV 关系
    ├─ 当前地点
    ├─ narrative_entity_link
    ├─ 近期 callback
    └─ 可见的 1~2 跳图扩展
    ↓
叙事检索（Narrative Retrieval）
    ├─ 章节计划的叙事线意图
    ├─ 叙事线排期（Thread Schedule）
    ├─ 进行中的 Mystery
    ├─ 进行中的 EmotionDebt
    └─ 近期阶段
    ↓
可见性 + 章节快照过滤
    ↓
确定性相关性排序
    ↓
Token 预算打包
    ↓
角色专属上下文包
```

## 4. 实体相关性分数（Entity relevance score）

V0.7 首版采用确定性评分，不依赖 embedding：

| 信号 | 权重 |
|---|---:|
| ChapterPlan 直接引用 | 0.30 |
| POV 角色 | 0.20 |
| 当前地点关系 | 0.15 |
| Active/Planned NarrativeThread 关联 | 0.15 |
| 最近出现 / callback | 0.10 |
| 未解决剧情义务 | 0.10 |

额外 1-hop / 2-hop 图扩展仅作为弱信号，不允许压过 ChapterPlan 显式意图。

## 5. 叙事相关性分数（Narrative relevance score）

- `advance` 叙事线：0.40
- `maintain` 叙事线：0.30
- 当前 Thread Schedule：0.25
- 相关 open Mystery：最高 0.15
- 相关 EmotionDebt：最高 0.15
- 最近 50 章 callback：0.05
- `sleep` thread：仅保留弱提醒

Writer 只得到 Reader/POV 可见 stage；`private_author` stage 只允许 Planner / Reviewer 使用。

## 6. Token 预算（Token Budget）

默认值：

- Writer：12k(v0.7 基线;V0.11 默认 56k)
- Reviewer：20k
- Planner：24k(v0.7 基线;V0.11 默认 120k)

Writer 默认软配额：

```text
ChapterPlan           10%
Belief                10%
Entity Graph          22%
Narrative Graph       20%
Recent Canon          20%
Character State        8%
Reference              5%
Safety                 5%
```

Planner / Reviewer 使用不同分配。软配额之外还有最终 hard-cap best-effort 裁剪：优先裁掉 Reference、较旧 recent canon、低相关 entity/thread，而不会先裁 ChapterPlan 或安全约束。

Token 估算为依赖无关的确定性近似：中文字符约 1 token，其余 JSON 文本约 4 字符/token。它用于稳定排序和预算，不用于账单级精确计费。

## 7. 时间切片

写第 N 章时，Canonical snapshot 固定为 `N-1`：

```text
第 328 章 Writer
→ 第 327 章的 Story Graph 快照
```

因此：

- Ch.1-480 的 `MEMBER_OF=A` 不会污染 Ch.700；
- Ch.520+ 的 `MEMBER_OF=B` 不会提前出现在 Ch.328；
- 尚未揭露的秘密关系不会因为数据库已经存在而被 Writer 遍历到。

## 8. 新增 MCP Tools

### `entity_retrieve_relevant`

获取当前章节最相关的实体和解释性 relevance score。

### `narrative_retrieve_relevant`

获取当前章节最相关的 NarrativeThread / Mystery / EmotionDebt / stage。

### `context_compile`

统一入口：

```json
{
  "chapter": 328,
  "role": "writer",
  "holder": "hero",
  "max_tokens": 12000
}
```

MCP 调用默认 `persist=false`，因此可以作为 read-only 工具使用。内部 `writer_context_get` / `planner_context_get` / semantic reviewer 会自动保存审计快照。

### `context_preview`

只返回检索数量、Top entity/thread 和 Token 估算，不返回完整上下文。

### `context_snapshot_get`

读取一次历史编译上下文。**Author/debug-only**；Planner/Reviewer 快照可能包含 World Truth，不要授权给 prose-only Writer App。

### `context_explain`

解释某个 `entity:*` / `thread:*` / `reference:*` 为什么被加载。

## 9. 上下文快照（Context Snapshot）

每次生产 Writer / Planner / Reviewer 上下文都可落 `context_snapshots`：

```text
snapshot_id
chapter
snapshot_chapter
role
holder
max_tokens
estimated_tokens
payload_json
trace_json
created_at
```

用途：

- 复现“第328章 Writer 当时到底知道什么”；
- 调查为什么某个实体没被加载；
- 对比模型版本或检索策略；
- 未来做 30~50 章 Narrative Stress Test 的上下文质量评测。

## 10. 与 V0.6 工具关系

V0.6 的 `entity_get / entity_search / entity_neighbors / thread_get / belief_get` 仍保留，作为精确查询和人工调试工具。

正常自动写作路径优先：

```text
context_compile / writer_context_get
```

而不是让 Writer 自己连续调用十几个底层查询工具。

## 11. 参考图（Reference Graph）

Planner Context 可自动加入少量 Reference Pattern：

- 局部揭示（partial reveal）
- 信念反转（belief reversal）
- 兑现（payoff）
- 长引线（long fuse）

返回仍然只包含 span / stage sequence / pattern type / capabilities 等结构信息，不复制参考小说正文、人物名或具体剧情事实。

## 12. 已知边界

- V0.7 首版不使用 embedding/向量检索；优先保证确定性、可解释和可回归。
- Entity core `name/description/properties` 仍要求是 prose-safe；秘密身份必须放 secret alias/attribute/relation。
- Token estimator 是近似值。
- Reference Pattern 自动检索是结构辅助，不参与 Canon 决策。
- 后续可以在不改变工具契约的情况下增加 embedding、Graph centrality 和 LLM rerank。
