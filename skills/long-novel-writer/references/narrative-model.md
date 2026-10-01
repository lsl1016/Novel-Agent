# 叙事模型

本文件描述叙事图(Narrative Graph)。实体图世界模型是独立的;见 `entity-graph.md`。

## 核心故事图实体

- `NarrativeThread`:跨越多章的持久戏剧因果线。
- `Mystery`:故事有意让读者携带的疑问。
- `Clue`:会改变概率或注意力的信息,但尚未经追溯验证为伏笔。
- `Foreshadowing`:被后续呼应/揭示/兑现证明有意义的线索。
- `Reveal`:改变已知真相或解释的信息。
- `Payoff`:了结铺设的叙事或情感后果。
- `EmotionDebt`:未解决的情感义务,会产生未来的兑现需求。
- `BeliefState`:某一章节中特定持有者对某事实的立场。
- `WorldFact`:正典的作者真相,可选保密。
- `Event`:具体的故事事件。
- `CharacterState`:时间线敏感的角色状态,如位置、身份、伤势、忠诚阵营或生死。

## 关键生命周期规则

**Clue 不是 Foreshadowing。** `clue_add` 写入的线索带 `foreshadowing_status=candidate_until_callback` 元数据,只有后续明确的呼应/揭示/兑现才能追溯性地证明它。给有意回收的线索起一个 `callback_key`,兑现时复用同一个 key——`foreshadowing_list_open` 靠它配对;`callback_key` 为空的旧线索会被任意后续 Payoff/Reveal 宽松配对,容易漏报,重要线索务必显式指定。

**Mystery 的关闭必须显式。** `mystery_create` 开启;只有 `declared_updates.reveals` 中带 `mystery_key` 且 `resolution=full` 的揭示才会把它置为 resolved 并记录 `resolved_chapter`。`story_pressure_check` 用 `mystery_backlog_high`(≥5 笔陈旧)与 `opening_rate_exceeds_payoff_rate` 跟踪开合平衡。

**Reveal 改变信念,而不只是信息。** 一次正式揭示通常应伴随 `declared_updates.belief_updates`,把 reader/相关角色的 stance 从 `unknown/suspects` 推进到 `believes/confirmed`。

## 叙事线阶段

有用的概念阶段:

`OPENED -> SEEDED -> DEEPENING -> PARTIAL_REVEAL -> DORMANT -> REACTIVATED -> MAJOR_REVEAL -> REVERSED/REINTERPRETED -> PAYOFF -> RESOLVED`

并非每条叙事线都需要经历每个阶段。操作语义:

| 阶段 | 判定 | 典型动作 |
|---|---|---|
| `OPENED` | 叙事线注册,尚未给读者可感知内容 | `thread_schedule` 排期首阶段 |
| `SEEDED` | 弱线索已埋(clue strength ≤0.3) | 不再追加,让其他线主导 |
| `DEEPENING` | 中强度推进/局部答案 | 保持 1-3 章一次的节奏 |
| `PARTIAL_REVEAL` | 解决局部问题但保留更大疑问 | 记录 belief_update(suspects/believes) |
| `DORMANT` | 超过 ~50 章无推进 | 计划重激活点;长期休眠会进入 pressure 风险 |
| `REACTIVATED` | 在新语境中重提旧线索 | 重新语境化比单纯加亮更有效 |
| `MAJOR_REVEAL` | 高层真相揭示 | 强度 0.7-0.9 的 clue/Reveal + belief 置 confirmed |
| `REVERSED/REINTERPRETED` | 新真相改变旧事件含义 | 检查与旧证据一致(重新诠释而非矛盾) |
| `PAYOFF` | 兑现铺设(叙事或情感) | 伴随后果;debt 用 `emotion_debt_resolve` |
| `RESOLVED` | 叙事线关闭 | thread status → resolved;新篇章不继承它 |

沉睡监控:参照物是"100 章内应有弱呼应,300 章内必须有阶段推进"(`thread_scores` 参考指标中 dormancy_100/300 的含义)。
