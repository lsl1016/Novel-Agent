# 信念状态(Belief State)

信念状态是"三层知识分离"的运行时载体:世界真相(作者)与各持有者信念分开存储,`belief_get(fact_key, chapter)` 一次返回两者且不合并。

## 持有者

常见的持有者是 `reader` 以及稳定的角色键,如 `hero`、`female_lead` 或 `villain`。

立场取值(五档):

| stance | 语义 | 典型来源 |
|---|---|---|
| `unknown` | 不知道该事实存在 | 默认态 |
| `suspects` | 觉察到异常/有错误方向 | 弱线索、间接证据 |
| `believes` | 相信某个(可能错误的)解释 | 局部答案、误导 |
| `confirmed` | 确认为真 | 合法揭示 |
| `disbelieves` | 曾相信的解释被推翻 | 反转、反证 |

持有者的信念值可以与世界真相(作者独有)**不同且保持不同**——`value` 字段记录该持有者认为的版本,错误信念是有价值的叙事资产,不要提前"纠正"它。

## 记录转变

```json
// belief_update
{
  "fact_key": "hero_father_identity",
  "holder": "reader",
  "chapter": 143,
  "stance": "suspects",
  "value": {"guess": "父亲与二十年前的边军失踪案有关"},
  "confidence": 0.4,
  "source": "author_declared"
}
```

同一 `(fact_key, holder, chapter)` 唯一;查询取该持有者 ≤N 章的最新一条。好的揭示通常分阶段改变信念:

`unknown -> suspects -> believes a provisional explanation -> disbelieves it -> confirmed deeper truth`

用 `belief_update` 记录**每一次**转变,而不只是最终答案——`chapter_plan_check` 的 `KNOWLEDGE_WITHOUT_SUPPORT` 检查正是依赖这些历史来判断"POV 是否有资格知道"。

## 视角(POV)约束

对于一个 POV 章节,散文只能把以下两类内容呈现为已知:

- 读者已经知道的内容;或
- 该 POV 持有者当前知道/相信、且叙事模式所允许的内容。

仅作者可见的世界真相可以指导潜台词、场面铺排与因果规划,但在合法揭示之前不得被断言为叙事事实。

## 与隐藏机制的配合

World Fact 的 `secrecy != public` 且未到 `reveal_after` 时,若 reader 与当前 POV 都未 `confirmed`,该事实会进入 Writer 上下文的 `forbidden_fact_keys`(只给键名,不给真值)。因此:

- 揭示一章的完整动作 = `declared_updates.reveals` 声明揭示 + `belief_update` 把相关 holder 置 `confirmed`(或由 reveals 语义隐式完成)+ 后续章节才能把该知识当作既有前提;
- 让某角色"早就知道"(知情者视角)时,先为其单独 `belief_update(confirmed)`,该角色视角的章节才能合法使用该信息,而 reader 仍保持 unknown——这是 POV 不对称的正确建模方式。

涉及身份揭示、欺骗与不可靠叙述者的更多模式见 `narrative-model.md` 与 `error-playbook.md`。
