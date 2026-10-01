# 伏笔与揭示

## 记录线索

```json
// clue_add
{
  "thread_key": "THREAD_FATHER_MYSTERY",
  "chapter": 87,
  "content": "酒馆醉汉提到'二十年前那场大火里抬出来的棺材是空的'",
  "visibility": "reader",
  "strength": 0.3,
  "callback_key": "cb_empty_coffin"
}
```

- `visibility`:`reader`(读者可见)/`character`(仅指定 holder 可知)/`private_author`(作者备注,Writer 检索不可见)。
- `callback_key`:给**打算回收**的线索起稳定回收键;揭示/兑现时复用它配对。重要线索务必填写,否则会被任意后续揭示宽松配对而漏报。

## 信息强度

线索的 `strength` 大致按以下方式取用:

- `0.1`:接近潜意识层面的异常
- `0.3`:细心的读者能够察觉
- `0.5`:线索清晰但含义模糊
- `0.7`:强烈的暗示
- `0.9`:接近揭示

不要习惯性地单调提升强度。重新语境化往往比单纯变得更显眼更有效:同一 `callback_key` 可以在多个章节各埋一条不同强度的线索(火花的"阶梯"),它们共同构成 `LADDERED_REVEAL` 模式。

## 长引信叙事线模式

一个持久的模式是:

1. 创建一个与角色相关的问题;
2. 埋下微弱的证据;
3. 让另一条情节暂时占据主导;
4. 在新语境中重新激活该线索;
5. 给出能解决局部问题的部分答案;
6. 保留一个未解释的矛盾;
7. 稍后揭示更高层面的原因;
8. 让这次揭示重新诠释早前的场景;
9. 附加一个后果或情感兑现。

## 回收与监控

`foreshadowing_list_open(before_chapter, min_age=100, limit=30)` 列出**尚未被回收**的旧线索(min_age 是"至少这么老才算陈旧")。在两处必查:

1. 每次重建滚动窗口时——把 1-2 条陈旧线索的重激活排进 hard/medium 视野;
2. `story_pressure_check` 报告 `stale_foreshadowing` 风险时(默认 300 章)。

回收时优先 `declared_updates.reveals` 带 `callback_key`,使配对关系显式可审计。

## 失败模式

- 线索此后再无呼应;
- 一次揭示倾倒全部真相;
- 反转与旧证据矛盾,而不是重新诠释旧证据;
- 数百章休眠且从不重新激活;
- 揭示只改变设定,却不改变任何决策或关系。
