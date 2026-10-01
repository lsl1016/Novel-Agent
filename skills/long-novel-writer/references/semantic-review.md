# 语义审校

使用语义审校来捕捉确定性图检查无法可靠发现的问题。确定性审校管"结构与字面",语义审校管"含义与效果";两者不可互替。

## 四个审校者的判定标准

- **semantic_knowledge_leak**:改述式/推断式秘密泄露、POV 无依据的确定性、叙述者把猜测写成事实。明确泄密 → `BLOCK`;接近答案但保留歧义 → `WARN`。
- **semantic_character**:动机、价值观、关系、能力、语气的无支撑突变。严重 OOC/状态矛盾 → `BLOCK`;轻微漂移 → `WARN`。
- **semantic_narrative**:ChapterPlan 是否真正落实;线索强度是否明显超出/低于计划;揭示是否越级;是否把长线谜团一次解释过满;是否存在更好的旧信息重解释空间。结构违约或揭示越级 → `BLOCK`,其余通常 `WARN`。
- **semantic_pacing**:信息密度、叙事停滞、线程过载、连续开坑不回收、高潮/过渡位置失衡。除非已导致章节目标无法成立,否则只 `WARN`。

## 调用方式

```text
chapter_review_full(chapter, version)      # 推荐:确定性 + 语义,同一确切版本
chapter_semantic_review(chapter, version)  # 仅语义四个
```

审校证据绑定确切草稿版本;任何修订产生新版本后必须全新审校。`chapter_review_full` 返回 `INCOMPLETE` 通常意味着语义端点未配置(见 `error-playbook.md` 第 3 节)。

## 脱敏与安全规则

服务器会把隐藏世界真相(`hidden_truth_ledger`)交给内部语义审校者做比对,但:

1. 绝不能把该真相传给写作者或修订写作者;
2. 返回/持久化的发现先经脱敏——隐藏真值被替换为 `[REDACTED_WORLD_TRUTH:<fact_key>]`;
3. 审校者只允许引用正文中的短证据,不得在 finding 中复述 hidden_truth 的真实值;
4. 若模型漏掉某个审校者,运行时会以 `WARN` + `SEMANTIC_REVIEWER_OUTPUT_MISSING` 补位——这不等于通过,高价值章节应重跑。

## 编写修订提示时的纪律

把发现交给 `chapter_auto_revise` 或人工修订时:

- 只传脱敏后的 findings(运行时已处理,不要绕过);
- 修订约束是"只能增加歧义、收回越权断言、回到 POV 可知范围",**绝不能把审校者内部掌握的真相补进正文**;
- 泄密的正确修法是消除确定性,不是换一种说法把真相说清楚。

## 自动修订规则

使用小型有界循环(`chapter_auto_revision_loop`,默认 max_rounds=3,网关部署下被收紧为 ≤3)。每次修订都是一个不可变的新草稿版本,必须重新接受审校。当达到修订上限(`revision_limit_reached`)或模型未产生有意义变化(`REVISION_NO_CHANGE`)时,停止并询问人类作者。自动化代码绝不能使用 BLOCK 覆盖。
