# 语义审校者 + 自动修订运行时

> **状态(2026-10-02,V0.11)**:语义审校运行时仍如本文所述;四审校器结论矩阵与修订收敛史已可视化于 Web 审校中心;llm_client 已改平衡括号 JSON 解析(多对象/尾注容错)。


## 目的

确定性规则可以检测字面形式的机密值和结构化矛盾,但无法可靠检测保持语义的改述,例如不直接点名却揭示某个身份。V0.4 增加了一个感知作者信息的语义层。

## 语义审校者契约

`chapter_semantic_review` 在内部接收:

- 精确的草稿正文;
- 已保存的章节计划;
- 安全的写作者上下文;
- 近期已提交上下文;
- 故事/规划压力;
- 作者专属的隐藏世界真相台账;
- 本章之前的读者/视角(POV)信念状态;
- 当前草稿中是否声明了合法的揭示(Reveal)。

它返回四项审校:

1. `semantic_knowledge_leak` — 改述式/推断式的机密泄露,以及无依据的视角(POV)确定性断言。
2. `semantic_character` — OOC 行为、动机漂移、能力/关系不连续。
3. `semantic_narrative` — 线索亮度、揭示过头、长线谜团过度解释、计划贴合度。
4. `semantic_pacing` — 叙事线过载、停滞、信息倾倒压力、开局/兑现失衡。

## 脱敏规则

审校者可以在内部与隐藏真相比对,但不允许把真相教给写作者。

在任何语义发现被存储或返回之前,所有字符串型的隐藏真相都会被替换为:

`[REDACTED_WORLD_TRUTH:<fact_key>]`

修订写作者只会收到这份脱敏证据,加上 `writer_context_get`。

## 完整审校

使用:

`chapter_review_full(chapter, version, semantic=true)`

它会针对同一个精确草稿版本先运行确定性闸门,再运行语义闸门。两类证据会一起持久化。

重跑确定性审校不会抹除语义审校,反之亦然。

## 自动修订

`chapter_auto_revise`:

- 要求对象是已审校过的精确草稿版本;
- 收集 BLOCK 与可选的 WARN 级发现;
- 只向修订写作者发送安全上下文 + 脱敏后的发现;
- 保留章节计划与已声明的正典更新意图;
- 以 `parent_version` 写入新的草稿版本;
- 绝不将新版本标记为已审校。

## 有界自动循环

`chapter_auto_revision_loop` 执行:

`review -> if blocked revise -> new version -> fresh review -> ...`

安全约束:

- `max_rounds` 限定在 0–8;默认 3。
- 旧的审校通过结果不会沿用;
- 无变化的修订会以 `revision_stalled` 状态停止;
- 语义审校配置失败会以 `review_incomplete` 状态停止;
- 自动修订绝不使用 `override_block`;
- 可选的定稿会使用精确通过的那个版本。

## 模型配置

语义审校者:

```bash
export NOVEL_REVIEWER_BASE_URL=https://your-endpoint/v1
export NOVEL_REVIEWER_API_KEY=...
export NOVEL_REVIEWER_MODEL=...
```

回退顺序:先 `NOVEL_WRITER_*`,再 `NKG_LLM_*`。

修订写作者:

```bash
export NOVEL_REVISION_BASE_URL=https://your-endpoint/v1
export NOVEL_REVISION_API_KEY=...
export NOVEL_REVISION_MODEL=...
```

回退顺序:先 `NOVEL_WRITER_*`,再 `NKG_LLM_*`。

## 推荐策略

对于普通的本地迭代,确定性审校可能就足够了。

对于正典的长篇正式章节,建议优先使用:

`chapter_review_full -> chapter_finalize(require_semantic=true)`

对于自动化起草,请使用一个较小的有界自动修订循环,并把未解决的 BLOCK 发现呈现给人类作者,而不是无限扩大循环。
