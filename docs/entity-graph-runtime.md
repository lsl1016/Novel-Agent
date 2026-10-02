# Novel Agent V0.7 — 实体图 / 世界模型运行时(基础篇)

> **状态(2026-10-02)**:本文描述的实体图 V1 机制仍然生效。v0.10 起 Phase A 已交付 **实体图 V2**:
> 身份档案链(identity_profiles)、一等事件与因果链(events/event_participants/cause_event_id)、
> 断言与证据(fact_assertions)、**双时序披露**(fact_disclosures,按持有者各自的 knowledge_time)、
> 力量/器物/地理子图视图。schema 已收敛为迁移制(`schema.py` MIGRATIONS,现至 v6)。
> 详见 `phase-a-v2-report.md` 与 `tool-contracts.md` 的 V2 分组。


## 1. 目标

V0.7 把第一阶段实体知识图谱正式集成进 Novel Agent。Story Graph 不再只有 NarrativeThread / Mystery / Belief / EmotionDebt，而是拆成两个互补层：

```text
故事图(Story Graph)
├── 实体图 / 世界模型(Entity Graph / World Model)
│   ├── Character
│   ├── Faction
│   ├── Location
│   ├── Item / Artifact
│   ├── Skill / Realm
│   ├── Organization / Bloodline
│   ├── Event / Creature / Race / ...
│   ├── EntityAttribute
│   └── EntityRelation
└── 叙事图(Narrative Graph)
    ├── NarrativeThread
    ├── Mystery
    ├── Clue / Foreshadowing
    ├── Reveal / Payoff
    ├── EmotionDebt
    └── BeliefState
```

核心原则：

> Entity Graph 保存“世界是什么”；Narrative Graph 保存“这些事实如何被讲给读者和角色”。

## 2. 数据模型

### 2.1 entities

稳定实体身份。`entity_key` 永远优先于展示名。

关键字段：

- `entity_key`
- `entity_type`
- `name`
- `status`
- `introduced_chapter`
- `retired_chapter`
- `description`
- `properties_json`
- `source`

推荐类型：`Character / Faction / Location / Item / Skill / Realm / Artifact / Organization / Bloodline / Event / Creature / Race`。

`name/description/properties_json` 应尽量只存 prose-safe 信息；秘密身份不要直接放这里。

### 2.2 entity_aliases

用于别名、称号、伪装身份、真实身份名。

支持：

- `secrecy=public|secret|author_only`
- `reveal_after`
- `fact_key`

例如：

```text
father
name = 黑衣人              # 对正文安全
alias = 玄冥圣君           # secret
fact_key = hero_father_identity
reveal_after = 500
```

### 2.3 entity_attributes

时间敏感属性：境界、伤势、年龄、身份状态、能力、资源数量等。

```text
hero.realm
Ch.1-99   = 灵海境
Ch.100+   = 神府境
```

新的 `entity_attribute_set` 默认关闭上一条同属性时间窗口，而不是覆盖历史。

### 2.4 entity_relations

时间敏感关系，例如：

```text
PARENT_OF
MEMBER_OF
LOCATED_IN
OWNS
USES
ENEMY_OF
ALLY_OF
MASTER_OF
REQUIRES_REALM
CREATED
CAUSED
RELATED_TO
```

关系同样支持：

- `start_chapter / end_chapter`
- `secrecy`
- `reveal_after`
- `fact_key`
- `properties`

因此“真实父子关系”可以存在于作者世界模型里，同时对 Ch.200 的 Writer 完全不可见。

### 2.5 narrative_entity_links

连接 Entity Graph 与 Narrative Graph：

```text
NarrativeThread(hero_origin)
    └── subject -> Character(hero)

Mystery(ancient_sword_origin)
    └── about -> Artifact(ancient_sword)

EmotionDebt(master_loss)
    └── target -> Character(master)
```

这样 Planner 可以从“古剑谜题”反查古剑、拥有者、制造者、所在地点；也可以从人物反查其绑定的长期剧情线。

## 3. 三种读取权限

### 3.1 读者/视角（POV）安全视图

`entity_get / entity_context_get / entity_neighbors / entity_path_find`

根据：

```text
chapter
+ holder(reader 或 POV character)
+ secrecy
+ reveal_after
+ fact_key 对应 BeliefState
```

过滤秘密 aliases / attributes / relations。

### 3.2 作者视图（Author View）

`entity_author_get`

返回完整世界模型，包括秘密实体信息。只应授权给：

- 作者规划器（Author Planner）
- 语义审校者（Semantic Reviewer）
- 人工作者控制面

不得授权给 prose-only Writer。

### 3.3 Writer 自动上下文

`writer_context_get` 已自动加入：

```json
{
  "entity_context": {
    "entities": [],
    "subgraphs": []
  }
}
```

它只使用 Safe View。即使 Story DB 里存在秘密 `PARENT_OF`，Writer Prompt 也拿不到。

## 4. MCP 工具

### 4.1 检索工具

| 工具 | 用途 |
| --- | --- |
| `entity_get` | 获取一个实体的 Reader/POV 安全快照 |
| `entity_author_get` | 作者视角完整实体快照 |
| `entity_search` | 按名称/Key/类型搜索，秘密 alias 不可作为侧信道 |
| `entity_neighbors` | 局部关系图遍历 |
| `entity_path_find` | 查两实体之间的可见关系路径 |
| `entity_context_get` | 批量构建紧凑实体上下文 |
| `entity_graph_stats` | 统计实体/关系分布 |
| `narrative_entity_links_get` | 查询 Narrative <-> Entity 跨层绑定 |
| `entity_graph_check` | 在写入前校验实体变化 |

### 4.2 操作工具

| 工具 | 用途 |
| --- | --- |
| `entity_upsert` | 新增/更新实体 |
| `entity_alias_add` | 新增公开/秘密 alias |
| `entity_attribute_set` | 写入时间属性 |
| `entity_relation_upsert` | 写入时间关系 |
| `entity_relation_end` | 结束关系但保留历史 |
| `narrative_entity_link` | 叙事节点绑定实体 |
| `entity_graph_import` | 从通用 nodes/edges 迁移实体图，默认 dry-run |

## 5. 创作中的标准使用方式

### 5.1 写章节之前

```text
story_get_state
      ↓
entity_search / entity_context_get
      ↓
narrative_thread_get / belief_get
      ↓
ChapterPlan
      ↓
entity_graph_check
      ↓
chapter_plan_save
```

例如主角准备回到故乡：

```json
{
  "entity_keys": ["hero", "home_city", "old_enemy", "family_sword"]
}
```

Writer 自动拿到这些实体在上一章时刻的安全状态。

### 5.2 正文完成后

需要变成 Canon 的实体变化必须放进 `declared_updates`：

```json
{
  "entity_attributes": [
    {
      "entity_key": "hero",
      "attr_key": "realm",
      "value": "神府境",
      "chapter": 128
    }
  ],
  "entity_relations": [
    {
      "source_entity_key": "hero",
      "relation_type": "OWNS",
      "target_entity_key": "ancient_sword",
      "start_chapter": 128
    }
  ]
}
```

只有 `chapter_finalize` 成功后才写进 Canon。

## 6. 秘密关系（Secret Relation）示例

作者世界真相：

```text
father PARENT_OF hero
```

但是读者到 Ch.500 才应该知道。

先创建 World Fact：

```json
{
  "fact_key": "hero_father_identity",
  "truth": "father",
  "secrecy": "secret",
  "reveal_after": 500
}
```

关系：

```json
{
  "source_entity_key": "father",
  "relation_type": "PARENT_OF",
  "target_entity_key": "hero",
  "start_chapter": 1,
  "secrecy": "secret",
  "reveal_after": 500,
  "fact_key": "hero_father_identity"
}
```

Ch.200：

```text
entity_author_get -> 可见 PARENT_OF
entity_get(holder=hero) -> 不可见 PARENT_OF
writer_context_get -> 不可见 PARENT_OF
```

Ch.500 或合法 BeliefState 已确认后：Safe View 才能看到。

## 7. 故事架构师（Story Architect）集成

`story_architect_apply` 现在可一次编译：

```text
blueprint
world_facts
entities
entity_aliases
entity_attributes
entity_relations
narrative_entity_links
threads
mysteries
emotion_debts
arcs
milestones
thread_schedule
```

因此新小说初始化不再只是“设计谜题和分卷”，而是同时建立 World Model。

## 8. 参考图（Reference Graph）边界

Reference Graph 仍然只读。

`entity_graph_import` 默认作用于当前新小说 Story Graph；不要把《逆天邪神》的 Reference Entity Graph 直接导入新小说数据库。参考作品只用于：

- 结构模式搜索；
- 实体关系复杂度研究；
- 叙事机制对比。

不用于复制人物、设定、关系或剧情事实。

## 9. 与旧 character_states 的关系

V0.7 保留 `character_states` 兼容旧数据和 Reviewer。

长期方向：

```text
character_states -> Character Entity 的高频快照缓存
Entity Graph      -> 通用世界模型真源
```

当前 `entity_get(Character)` 会同时返回 `legacy_character_state`，方便渐进迁移。

## 10. 推荐权限

Writer App：

```text
entity_get
entity_search
entity_neighbors
entity_path_find
entity_context_get
narrative_entity_links_get
```

Author/Planner App：再增加：

```text
entity_author_get
entity_upsert
entity_alias_add
entity_attribute_set
entity_relation_upsert
entity_relation_end
narrative_entity_link
entity_graph_check
entity_graph_import
```

不要给低权限 Writer `entity_author_get`。
