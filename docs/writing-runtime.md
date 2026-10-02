# Novel Agent V0.4 — 写作运行时

> **状态(2026-10-02,V0.11)**:写作运行时仍如本文所述;v0.11 起 Web 工作台可编辑草稿(source=web_edit)并经同一审校闸门定稿;SHORT_CHAPTER 确定性 WARN 已加入叙事审校器。


## 目标

把每一章当作带版本的事务来运行:

`Approved ChapterPlan -> Safe Writer Context -> Draft -> Deterministic + Semantic Review -> Revision -> Finalize -> Canon`

在 `chapter_finalize` 成功之前,草稿正文都是非正典的。

## 安全写作者上下文

`writer_context_get` 暴露读者/视角(POV)信念、公开真相、角色状态、已批准的计划、相关叙事线、到期排期、近期已提交上下文与写作约束。

它有意省略隐藏的世界真相值。被禁止的机密以 `fact_key` 表示,而不是机密值本身。

## 草稿生命周期

`v1 draft -> review BLOCK -> v2 revision -> review WARN/PASS -> finalize`

每次保存都会创建一个新的精确 `(chapter, version)`。审校证据与版本绑定,绝不继承。

## 确定性审校者

1. `knowledge_leak` — 字面隐藏真相泄露。
2. `continuity` — 正典事实/状态矛盾。
3. `narrative` — 计划/声明不匹配,以及排期的状态变更缺失。
4. `character` — 不可能的视角(POV)/状态条件。

## 语义审校者

1. `semantic_knowledge_leak` — 改述式/推断式泄露与无依据的确定性断言。
2. `semantic_character` — OOC/动机/能力漂移。
3. `semantic_narrative` — 线索强度、揭示过头、过度解释、叙事线意图。
4. `semantic_pacing` — 停滞、过载、信息密度、开局/兑现失衡。

使用 `chapter_review_full` 一并运行两族审校。

## 自动修订

使用 `chapter_auto_revise` 执行一次受控修订,或使用 `chapter_auto_revision_loop` 执行有界的审校/修订循环。修订上下文只包含脱敏后的发现与安全的写作者上下文;隐藏的世界真相绝不会发送给修订写作者。

## 定稿闸门

`chapter_finalize(require_semantic=true)` 要求针对精确草稿版本的全部八项审校。不传 `require_semantic` 时,为保持向后兼容,原有的四项确定性闸门仍然足够。

任何 BLOCK 都会阻止提交,除非人类明确使用低层覆盖路径并给出理由。自动修订绝不会授权覆盖。

## 模型配置

写作者:

- `NOVEL_WRITER_BASE_URL`
- `NOVEL_WRITER_API_KEY`
- `NOVEL_WRITER_MODEL`

语义审校者:

- `NOVEL_REVIEWER_BASE_URL`
- `NOVEL_REVIEWER_API_KEY`
- `NOVEL_REVIEWER_MODEL`

修订写作者:

- `NOVEL_REVISION_BASE_URL`
- `NOVEL_REVISION_API_KEY`
- `NOVEL_REVISION_MODEL`

以上均为 OpenAI 兼容端点。审校者/修订配置可以回退到写作者配置。
