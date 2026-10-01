# 写作工作流

## 正典章节事务

每一章都使用以下顺序:

1. `story_get_state(chapter)`
2. 定向叙事图读取 + 安全实体图读取(`entity_search/entity_get/entity_context_get`)与 `planning_pressure_check`
3. 创建并保存 `ChapterPlan`
4. 要求章节计划状态为 `ready`,或是有意识接受的 `warning`
5. `writer_context_get(chapter)`
6. `chapter_draft_generate`,或外部写作 + `chapter_draft_save`
7. 优先使用 `chapter_review_full(chapter, version)`;仅当有意不启用语义审校时,才使用仅确定性的 `chapter_review_all`。
8. 若为 `BLOCK`:手动修订、使用 `chapter_auto_revise`,或运行有界的 `chapter_auto_revision_loop`;每个新版本都独立保存/审校。
9. 若接受 PASS/WARN:使用 `chapter_finalize(chapter, version, require_semantic=true)` 进行正式的语义闸门提交。
10. 检查故事/规划压力并重新规划。

草稿不是正典。审校结果绑定于一个确切的草稿版本。错误码级排查见 `error-playbook.md`。

## 审校闸门

确定性审校:
- **knowledge_leak**:字面形式的隐藏世界真相在没有合法揭示时不得出现(`SECRET_LITERAL_IN_PROSE`)。
- **continuity**:声明的事实、角色状态、实体图属性与时序关系不得与正典矛盾。
- **narrative**:规划中的重大揭示/兑现必须显式声明(`PLANNED_REVEAL_NOT_DECLARED` / `PLANNED_PAYOFF_NOT_DECLARED` 即 BLOCK);规划中的叙事线推进应有所体现。
- **character**:状态跳变与不可能的 POV 条件会被阻塞或警告(`DEAD_POV_CHARACTER`)。

语义审校:
- **semantic_knowledge_leak**:改述/推断式秘密泄露与无支撑的确定性。
- **semantic_character**:OOC 动机/语气/能力漂移。
- **semantic_narrative**:线索可见性、揭示越界、长线谜团过度解释。
- **semantic_pacing**:停滞、过载、信息密度、开头/兑现失衡。

## 计划模板(含示例值)

```json
{
  "primary_goal": "云澈第一次对父亲之死产生具体怀疑",
  "arc_key": "ARC1_CAPITAL",
  "pov": "hero",
  "threads": {
    "advance": ["THREAD_FATHER_MYSTERY"],
    "maintain": ["THREAD_RISE_ARC1"],
    "sleep": ["THREAD_SIDE_DEBT"]
  },
  "mysteries": {"create": [], "advance": ["MYSTERY_FATHER_DEATH"], "resolve": []},
  "clues": [
    {"thread_key": "THREAD_FATHER_MYSTERY", "content": "族谱里父亲的名字被墨涂去",
     "strength": 0.4, "callback_key": "cb_blotted_name"}
  ],
  "reveals": [],
  "knowledge_assertions": [
    {"fact_key": "hero_father_identity", "recipients": ["hero"], "assume_known": false}
  ],
  "belief_updates": [
    {"fact_key": "hero_father_identity", "holder": "hero", "stance": "suspects"}
  ],
  "emotion_debts": [],
  "payoffs": [],
  "events": [{"name": "云澈查阅族谱", "event_key": "ev_genealogy_143", "thread_key": "THREAD_FATHER_MYSTERY"}],
  "character_states": [{"character_key": "hero", "state": {"location": "云家祠堂"}}],
  "entity_keys": ["hero", "yun_ancestral_hall"],
  "forbidden_truths": ["hero_father_identity"],
  "chapter_hook": "深夜,有人在云家祠堂外烧纸——用的却是云家的祭文",
  "author_questions": []
}
```

写作时把"有揭示意图的一章"替换出 `reveals`:

```json
{"fact_key": "hero_marriage_annulment", "thread_key": "THREAD_RISE_ARC1",
 "content": "萧岚当众宣布退婚的真正原因", "recipients": ["reader", "hero"],
 "scope": "partial", "callback_key": "cb_annulment"}
```

`reveals[].fact_key` 必须与 WorldFact 对应,`scope=partial` 表示只揭开局部;带 `mystery_key` 且 `resolution=full` 才会关闭谜团。字段语义详见 `planning-runtime.md`。

## declared_updates 完整示例

草稿携带的正典变更意图(只在 `chapter_finalize` 通过后应用):

```json
{
  "threads": [{"thread_key": "THREAD_FATHER_MYSTERY", "status": "open"}],
  "clues": [{"thread_key": "THREAD_FATHER_MYSTERY", "content": "族谱涂名被云澈发现",
             "strength": 0.4, "callback_key": "cb_blotted_name"}],
  "belief_updates": [{"fact_key": "hero_father_identity", "holder": "hero",
                      "chapter": 143, "stance": "suspects"}],
  "events": [{"name": "祠堂烧纸人影", "event_key": "ev_shrine_143"}],
  "character_states": [{"character_key": "hero", "state": {"location": "云家", "mood": "警觉"}}],
  "entity_attributes": [{"entity_key": "hero", "attr_key": "realm",
                         "value": "神府境", "chapter": 143}]
}
```

全部可用键:`threads / mysteries / clues / reveals / belief_updates / emotion_debts / payoffs / world_facts / events / character_states / entities / entity_aliases / entity_attributes / entity_relations / narrative_entity_links`。省略键表示本章对该域无变更。

每章优先安排 1-3 个有意义的叙事状态变更;`arc_transition` 属于 ChapterPlan 而非 declared_updates。
