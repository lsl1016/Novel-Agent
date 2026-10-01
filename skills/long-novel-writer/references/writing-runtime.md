# 写作者 / 审校者运行时

## 状态边界

`ChapterPlan` 是未来的作者意图。`chapter_drafts` 是非正典的散文尝试。只有 `chapter_finalize` 可以把获批草稿提升为正典故事图状态。

章节工作流生命周期(`writing_workflow_status` 可查):

```text
planned(计划已存) -> draft(草稿 v1) -> reviewed(有审校证据)
   -> [BLOCK -> revision v2 -> 全新审校 -> ...] -> committed(仅 finalize)
```

## 安全写作者上下文

`writer_context_get` 有意移除隐藏的世界真相值。写作者与修订写作者收到的是读者/POV 信念、公开真相、获批计划、角色状态、相关叙事线与近期已提交上下文。返回包的关键字段:

- `forbidden_fact_keys`:存在秘密但**不含真值**——提示"这里有禁区",绝不能猜测补全;
- `chapter_plan` / `arc_plan` / `pov_holder`:写作的直接依据;
- `context_snapshot_id` / `retrieval_trace`:本次上下文的审计句柄;
- `active_thread_context` / `open_mysteries` / `open_emotion_debts`:本章叙事义务。

草稿的前提:该章存在**未被 block** 的 ChapterPlan;blocked 计划会在保存草稿时直接报错。

## 版本化

每次保存都会创建新的 `(chapter, version)`,版本不可变。`chapter_draft_save(parent_version=...)` 声明修订谱系。审校证据只属于那个确切版本——修订在构造上就会使先前的批准失效,不存在"版本间继承 PASS"。

`chapter_draft_generate` 与 `chapter_draft_save` 都会先做正文秘密字面值预检,结果在返回的 `preflight.knowledge_leak` 中;它是提示,不替代正式审校。

## 审校族

确定性审校:`knowledge_leak`、`continuity`、`narrative`、`character`。

语义审校:`semantic_knowledge_leak`、`semantic_character`、`semantic_narrative`、`semantic_pacing`。

语义审校者可以在内部与仅作者可见的真相比对,但返回/存储的发现必须先对隐藏真相值脱敏,写作者才能看到。各审校者的 BLOCK/WARN 判定标准见 `semantic-review.md`;findings 错误码见 `error-playbook.md`。

`chapter_finalize(require_semantic=true)` 要求八个审校者全部存在于**该确切版本**;缺项返回 `REVIEW_INCOMPLETE` 并列出 missing。

## 自动修订

单次修订使用 `chapter_auto_revise`,有界循环使用 `chapter_auto_revision_loop`。修订载荷只含草稿、脱敏 findings 与安全上下文——修订模型接触不到隐藏真相,因此它**不可能**靠"把真相写出来"来消除泄密 finding。绝不通过无限增加循环次数来强求 PASS;`revision_limit_reached` / `revision_stalled` / `REVISION_NO_CHANGE` 都应停止并转人工(见 `error-playbook.md` 第 3 节)。新版本必须重新审校。

## 定稿

```text
chapter_finalize(chapter, version, require_semantic=true, allow_warnings=true)
```

- BLOCK 是硬停止,除非人工明确授权 `override_block=true` 并提供 `override_reason`(自动流程不得使用);
- WARN 需 `allow_warnings=true` 显式接受;
- 提交时会对计划做最终重验(`PLAN_REVALIDATION_BLOCKED` 表示计划在写作期间失效);
- 成功后草稿标记 `committed`,章节计划与滚动计划条目一并标记已提交,`declared_updates` 才真正写入正典。
