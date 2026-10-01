# 规划运行时指南

在初始化小说、变更篇章、为长线叙事排期、重建滚动视野或创建章节计划(ChapterPlan)时,使用本参考。

## 层级

`Blueprint -> Story Architecture -> Arc -> Thread Schedule/Milestone -> Rolling Window -> ChapterPlan -> Validate -> Draft -> Commit`

## 默认滚动窗口

- 硬视野:5 章——具体目标与叙事线推进。
- 中视野:20 章——可能的节拍,可修订。
- 软视野:50 章——仅方向与约束。

不要提前数百章进行场景级规划。`planning_rebuild_window(anchor_chapter)` 生成/重排三层条目;`planning_get_window` 查看。硬视野内每章都应有 `primary_goal`,缺失会以 `HARD_WINDOW_GOAL_MISSING` 进入规划压力。

## 蓝图

把最稳定的作者真相放在这里:类型承诺、主角欲望/缺陷/结局状态、世界模型、主要冲突、结局真相、不可妥协项。蓝图是作者规划数据,不是读者知识。`blueprint_update(patch, expected_version=N)` 带乐观锁,防止并发规划互相覆盖。

## 故事架构师

使用 `story_architect_apply` 持久化设计好的架构,支持 `world_facts` / `entities` / `entity_aliases` / `entity_attributes` / `entity_relations` / `narrative_entity_links` / `threads` / `mysteries` / `emotion_debts` / `arcs` / `milestones` / `thread_schedule` / `blueprint` 十三组数据。大改动务必先试运行(dry-run)。所有组都要求稳定键,重复键会被拒绝。

## 篇章计划

```json
// arc_plan_create
{
  "arc_key": "ARC1_CAPITAL",
  "name": "帝都风云",
  "order_no": 1,
  "start_chapter": 1,
  "target_end_chapter": 120,
  "primary_goal": "云澈在帝都立足并查清退婚背后势力",
  "surface_conflict": "萧家压制 vs 云澈暗中崛起",
  "hidden_functions": ["为父亲身份谜团埋设第一批线索"],
  "allowed_reveals": ["hero_marriage_annulment"],
  "forbidden_facts": ["hero_father_identity", "world_truth_phoenix_remain"],
  "inherited_thread_keys": ["THREAD_FATHER_MYSTERY"],
  "exit_conditions": ["云澈获得进入内院的资格", "萧擎天倒台或结盟"]
}
```

后续篇章通常应至少继承一条早期叙事线(NarrativeThread)——`order_no>0` 且无继承会在架构校验中产生 `ARC_WITHOUT_DECLARED_INHERITANCE` 警告。

## 叙事线排期与里程碑

把生命周期阶段排入区间,而不是精确的散文:

```json
// thread_schedule_update
{"schedule_key": "sched_father_seed_1", "thread_key": "THREAD_FATHER_MYSTERY",
 "stage_type": "SEEDED", "min_chapter": 80, "max_chapter": 100,
 "purpose": "第一批空棺材线索", "constraints": {"max_strength": 0.3}}

// milestone_create
{"milestone_key": "ms_capital_exit", "arc_key": "ARC1_CAPITAL", "name": "离开帝都",
 "min_chapter": 100, "max_chapter": 120, "thread_keys": ["THREAD_FATHER_MYSTERY"],
 "success_conditions": ["hero realm >= 天玄境", "萧擎天事件了结"]}
```

逾期排期/里程碑会以 `THREAD_SCHEDULE_OVERDUE` / `MILESTONE_OVERDUE` 进入规划压力并可能触发 run 停止——重排期或显式关闭,不要无视。

## 章节计划

完整可保存的示例(带知识断言与篇章切换):

```json
{
  "title": "第143章 空棺",
  "primary_goal": "云澈第一次对父亲之死产生具体怀疑",
  "arc_key": "ARC1_CAPITAL",
  "pov": "hero",
  "threads": {"advance": ["THREAD_FATHER_MYSTERY"], "maintain": ["THREAD_RISE_ARC1"], "sleep": []},
  "mysteries": {"create": [], "advance": ["MYSTERY_FATHER_DEATH"], "resolve": []},
  "clues": [{"thread_key": "THREAD_FATHER_MYSTERY", "content": "族谱里父亲的名字被墨涂去", "strength": 0.4}],
  "knowledge_assertions": [
    {"fact_key": "hero_father_identity", "recipients": ["reader"], "assume_known": false}
  ],
  "reveals": [],
  "belief_updates": [{"fact_key": "hero_father_identity", "holder": "hero", "stance": "suspects"}],
  "payoffs": [],
  "events": [],
  "character_states": [],
  "forbidden_truths": ["hero_father_identity"],
  "chapter_hook": "深夜,有人在云家祠堂外烧纸——用的却是云家的祭文",
  "author_questions": []
}
```

字段语义:

- `knowledge_assertions` 声明"本章结束时谁应当知道什么":提前接触秘密 → `WORLD_TRUTH_LEAK`;`assume_known=true` 但无信念支撑 → `KNOWLEDGE_WITHOUT_SUPPORT`;
- `reveals[]` 每项含 `fact_key`(必填,供校验)/`recipients`/`scope: partial|major`;未声明的计划揭示会在草稿审校时 BLOCK;
- `arc_transition: {"is_new_arc": true, "inherited_thread_keys": [...]}` 仅在篇章切换章使用;
- `author_questions` 是自动规划者的人机边界:出现即表示需要作者补充设定,不得代答。

调用 `chapter_plan_save(chapter, plan, pov_holder=...)`。校验状态 `ready/warning/blocked`;不要基于 `blocked` 状态起草。外部工具可用 `chapter_plan_check` 预检未保存的临时计划。
