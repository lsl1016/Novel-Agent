# 实体图 / 世界模型

实体图(Entity Graph)用于记录故事世界中存在什么,以及这些实体如何随时间相互关联。叙事图(Narrative Graph)用于记录这些事实如何被揭示、误解、重新诠释与兑现。

## 核心分工

`Entity Graph = what the world is`

`Narrative Graph = how the story tells it`

推荐的实体类型包括 `Character`、`Faction`、`Location`、`Item`、`Skill`、`Realm`、`Artifact`、`Organization`、`Bloodline`、`Event`、`Creature`、`Race`,以及按需的自定义类型。

## 稳定键规则

创建稳定键,如 `hero`、`north_region`、`ancient_sword` 或 `qingyun_sect`。不要把可变的显示名作为主要标识。

## 秘密状态规则

尽量保持 `entities.name`、`description` 与 `properties` 散文安全。将隐藏身份与隐藏关系放入:

- `entity_alias_add(... secrecy=secret, fact_key=...)`
- `entity_attribute_set(... secrecy=secret, fact_key=...)`
- `entity_relation_upsert(... secrecy=secret, fact_key=...)`

当秘密实体事实参与读者/角色知识控制时,把它们绑定到一个 `WorldFact`。

```json
// 例:主角父亲的真实身份对读者隐藏,第 500 章后合法揭示
// 1) 事实
//    world_facts: {"fact_key": "hero_father_identity", "truth": "…", "secrecy": "secret", "reveal_after": 500}
// 2) 秘密别名
{"entity_key": "hero_father", "alias": "影阁主", "alias_type": "identity",
 "secrecy": "secret", "reveal_after": 500, "fact_key": "hero_father_identity"}
// 3) 秘密关系(同一事实键绑定)
{"source_entity_key": "hero", "relation_type": "CHILD_OF",
 "target_entity_key": "hero_father", "secrecy": "secret",
 "reveal_after": 500, "fact_key": "hero_father_identity"}
```

`entity_author_get` 仅限作者使用。绝不把它暴露给仅做散文的写作者。读者/POV 安全检索请使用 `entity_get`、`entity_context_get`、`entity_neighbors` 与 `entity_path_find`。

## 时序规则

状态变化时不要覆盖历史。

示例:

- 第 1-99 章 `hero.realm = 灵海境`
- 第 100 章起 `hero.realm = 神府境`

```json
// entity_attribute_set
{"entity_key": "hero", "attr_key": "realm", "value": "神府境",
 "chapter": 100, "close_previous": true, "confidence": 1.0}
```

`close_previous=true`(默认)会自动把前一段值的 `end_chapter` 闭合为 99。需要修正历史时,显式给 `end_chapter`,不要靠覆盖。

关系用生命周期表达变化:

```json
// entity_relation_upsert:结盟
{"source_entity_key": "hero", "relation_type": "ALLY_OF", "target_entity_key": "qingyun_sect",
 "start_chapter": 120}
// entity_relation_end:决裂(结束而非删除)
{"source_entity_key": "hero", "relation_type": "ALLY_OF", "target_entity_key": "qingyun_sect",
 "chapter": 310}
```

常用关系类型:`PARENT_OF / MEMBER_OF / LOCATED_IN / OWNS / USES / ENEMY_OF / ALLY_OF / MASTER_OF`,以及自定义类型。

## 修改前校验

```json
// entity_graph_check:把拟议变更先过一遍
{"chapter": 143,
 "entities": [], "attributes": [{"entity_key": "hero", "attr_key": "realm", "value": "神府境", "chapter": 143}],
 "relations": []}
```

返回 `errors`(阻止)/`warnings`(需要留意)。不要通过删除历史状态来表达变化;应创建新的时序属性或结束一段关系。

## 叙事链接

显式连接世界模型与叙事模型:

- `thread -> Character`(角色 `subject`)
- `mystery -> Artifact`(角色 `about`)
- `debt -> Character`(角色 `target`)
- `fact -> Character`(角色 `identity_subject`)
- `event -> Faction`(角色 `participant`)

```json
// narrative_entity_link
{"narrative_type": "mystery", "narrative_key": "MYSTERY_FATHER_DEATH",
 "entity_key": "hero_father", "role": "about", "chapter": 1}
```

使用 `narrative_entity_link` 建立链接,并用 `narrative_entity_links_get` 查看。这些链接是 Context Compiler 检索锚点(跨层链接权重 0.15)——没建链接的实体很难被自动选进章节上下文。

## 章节工作流

在规划或撰写章节之前:

1. 用 `entity_search` 搜索相关实体。
2. 用 `entity_get` 或 `entity_context_get` 获取读者/POV 安全的状态。
3. 当关系结构重要时,使用 `entity_neighbors` 或 `entity_path_find`。
4. 用 `entity_graph_check` 校验拟议的世界变更。
5. 把有意的实体更新放入 `declared_updates`,使其只有在 `chapter_finalize` 之后才成为正典。

章节内支持的实体正典更新包括:`entities`、`entity_aliases`、`entity_attributes`、`entity_relations`、`narrative_entity_links`。

## 参考隔离

不要把参考小说的实体图导入新小说的故事图。`entity_graph_import` 只用于当前故事自身的实体数据或迁移/导入任务(默认 `dry_run=true`)。参考知识保持只读,并在结构上保持分离。
