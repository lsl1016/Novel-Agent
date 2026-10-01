# Novel Agent V0.2 — 规划运行时

规划运行时（Planning Runtime）位于作者意图与章节正文起草之间。它不生成正文，而是存储并校验：一章为何存在、它允许揭示什么，以及它推进了哪些长期剧情义务。

## 规划层级

```text
小说蓝图
  -> 故事架构
      -> 篇章规划
          -> 叙事线排期 + 里程碑
              -> 滚动窗口(硬 / 中 / 软)
                  -> 章节计划
                      -> chapter_plan_check
                          -> Writer
                              -> chapter_finalize(正典提交门)
```

## 1. 小说蓝图（Novel Blueprint）

蓝图是最稳定的规划对象。推荐字段：

```json
{
  "genre": "玄幻",
  "core_promise": "读者长期追读的核心体验",
  "protagonist": {
    "core_desire": "...",
    "core_flaw": "...",
    "end_state": "..."
  },
  "world": {
    "surface_order": "...",
    "hidden_history": "...",
    "power_system": "..."
  },
  "main_conflict": "...",
  "ending_truth": "...",
  "non_negotiables": []
}
```

使用 `blueprint_get` / `blueprint_update`。`blueprint_update.expected_version` 提供乐观锁，防止两个规划器互相静默覆盖。

## 2. 故事架构师（Story Architect）

`story_architect_apply` 将作者设计的结构编译为权威规划状态。它接受以下输入：

- `blueprint`
- `world_facts`
- `threads`
- `mysteries`
- `emotion_debts`
- `arcs`
- `milestones`
- `thread_schedule`

对大型架构变更，务必先以 `dry_run=true` 运行。

故事架构师是确定性的。它不会自行发明内容；由 LLM 设计架构，工具只负责校验和持久化。

## 3. 篇章规划（Arc Plan）

篇章规划应描述叙事功能，而不是逐场景的正文。

```json
{
  "arc_key": "arc_01",
  "name": "北境篇",
  "order_no": 1,
  "start_chapter": 1,
  "target_end_chapter": 110,
  "primary_goal": "主角在北境立足",
  "surface_conflict": "宗门与地方势力竞争",
  "hidden_functions": ["建立古剑谜题", "建立师父失踪情绪债"],
  "allowed_reveals": ["古剑与上古势力有关"],
  "forbidden_facts": ["sword_creator_identity"],
  "inherited_thread_keys": ["hero_origin"],
  "exit_conditions": ["主角获得离开北境的资格"]
}
```

`forbidden_facts` 通过结构化的章节计划校验来强制执行。

## 4. 叙事线排期（Thread Schedule）

叙事线排期声明*某个生命周期阶段应当何时发生*，而不硬编码具体正文。

```json
{
  "schedule_key": "hero_origin_clue_03",
  "thread_key": "hero_origin",
  "stage_type": "Clue",
  "min_chapter": 80,
  "max_chapter": 100,
  "purpose": "重新激活身世线，但不能揭晓父亲身份",
  "constraints": {"max_strength": 0.3}
}
```

这是长线架构与章节规划之间的桥梁。

## 5. 里程碑（Milestones）

里程碑表示在某个章节窗口内应当成立的结果。

示例：

- 主角获得势力认可
- 读者意识到某件器物不正常
- 某笔情感债得到部分兑现
- 某个篇章结束时，至少有一条被继承的叙事线仍在延续

里程碑是规划义务，不是自动写入故事图（Story Graph）的事实。

## 6. 滚动规划器（Rolling Planner）

默认时间跨度：

- **硬（Hard）**：接下来 5 章。具体的章节目标与叙事线推进。
- **中（Medium）**：第 6–20 章。可能出现节拍（beat）；允许修订。
- **软（Soft）**：第 21–50 章。仅包含方向与约束。

在重大揭示、角色做出计划外的决定、篇章切换之后，或每隔几章，运行 `planning_rebuild_window`。不要把数百章提前锁定为场景级细节。

## 7. 章节计划（ChapterPlan）

推荐结构：

```json
{
  "primary_goal": "调查失踪商队",
  "secondary_goal": "重新激活古剑线",
  "arc_key": "arc_03",
  "threads": {
    "advance": ["ancient_sword"],
    "maintain": ["hero_origin"],
    "sleep": ["master_secret"]
  },
  "mysteries": {
    "create": [],
    "advance": ["ancient_sword_origin"],
    "resolve": []
  },
  "clues": [
    {"thread_key": "ancient_sword", "content": "尸体纹路与剑纹相同", "strength": 0.2}
  ],
  "reveals": [],
  "payoffs": [],
  "forbidden_truths": ["sword_creator_identity"],
  "chapter_hook": "商队尸体出现相同纹路"
}
```

使用 `chapter_plan_save` 保存。保存后的计划带有校验状态：

- `ready`
- `warning`
- `blocked`

不要基于 blocked 状态的计划起草正文。

## 8. V0.2 的校验规则

运行时目前检查：

- 秘密世界真相（World Truth）的揭示时机
- 缺乏依据的角色/读者认知
- 没有任何继承叙事线的篇章切换
- 在叙事线目标窗口之前发生的兑现（payoff）
- 违反篇章的 `forbidden_facts`
- 缺少结构化的章节目标
- 单章推进的叙事线过多
- 同一章内开启又关闭同一个谜团
- 已到期的排期叙事线阶段未被推进
- 滚动硬窗口出现空档
- 逾期未完成的里程碑
- 逾期未执行的叙事线排期

## 9. 提交交互

`chapter_finalize`(内部调用 chapter_commit)将已保存的章节计划和 RollingPlan 条目标记为已提交。自 v0.8 起提交在单事务中原子完成。作者声明的状态始终保持权威。可选的 Phase 2 抽取仍然只创建候选。

## 10. 规划事务

写一章之前的流程：

```text
story_get_state
-> planning_get_window
-> 检查到期的排期/里程碑
-> chapter_plan_save
-> 修复 BLOCK / 复核 WARN
-> 起草正文
-> chapter_finalize(正典提交门)
-> planning_pressure_check
-> 按需重建滚动窗口
```
