# Novel Agent V0.7 实施报告

## 范围

V0.7 在 V0.6 的实体图 + 叙事图之上,增加了一个确定性的检索与上下文编译器(Context Compiler)。

## 已实现内容

- `ContextCompiler` 内置面向写作者 / 规划器 / 审校者的角色策略。
- 按章节切片的故事图检索(`chapter N` 使用正典快照 `N-1`)。
- 确定性的实体相关度排序。
- 确定性的叙事线(NarrativeThread)相关度排序。
- 面向机密别名/属性/关系与作者专属阶段的写作者安全可见性过滤。
- 带 token 预算的上下文打包,含角色专属软上限与尽力而为的最终裁剪。
- 面向规划器上下文的参考模式(Reference Pattern)结构检索。
- 不可变的 `context_snapshots` 审计表。
- 带分数与原因的检索解释轨迹。
- `writer_context_get` 已迁移到上下文编译器。
- `planner_context_get` 已迁移到上下文编译器。
- 语义审校者现在会获取独立的审校者上下文快照。
- 用于上下文预览/编译/快照/解释的 CLI 命令。
- 新增 6 个 MCP 工具;总数从 71 增加到 77。
- 已为全部 77 个工具重新生成动态 `lsl1016/mcp-server` 注册载荷。

## 新增 MCP 工具

1. `entity_retrieve_relevant`
2. `narrative_retrieve_relevant`
3. `context_compile`
4. `context_preview`
5. `context_snapshot_get`
6. `context_explain`

## 回归测试

- 完整测试套件:**46 / 46 全部通过**。
- 上下文编译器专项测试:6 项。
- MCP `tools/list`:77 个工具。
- 注册载荷:77 个唯一工具。
- 只读分类:41 个。
- 写入/破坏性分类:36 个。

## 专项验证

- 写作者编译不会暴露隐藏的世界真相字面值或机密 `PARENT_OF` 关系。
- 规划器编译可以看到作者真相与隐藏的实体关系。
- 时序性的 `LOCATED_IN` 变更在不同章节快照下解析结果不同。
- `private_author` 叙事阶段会被排除在写作者检索之外。
- 大量 1 跳实体噪声会经过相关度排序并按预算裁剪。
- 写作者上下文会自动持久化可审计的快照。
- `context_explain` 返回确定性的纳入证据。

## 兼容性

V0.6 的低层图工具继续受支持。V0.7 将首选运行时路径从手动多工具检索改为编译上下文,同时不移除任何现有 API。

## 交付冒烟测试

最终交付验证额外覆盖了外部传输层与动态注册边界:

- 零依赖 stdio `initialize` 报告服务器版本 `0.7.0`;
- stdio `tools/list` 返回 **77** 个工具;
- HTTP `/mcp` 的 `tools/list` 返回 **77** 个工具;
- 带鉴权的门面(facade) `POST /api/agent/tools/call/context_compile` 调用成功;
- 同一门面在不带 `NOVEL_FACADE_TOKEN` 时返回 HTTP 401 / `errNo=40101`;
- 写作者 `context_compile` 冒烟输出不包含隐藏真相字面值或机密 `PARENT_OF` 关系;
- `mcp-server-batch-create.json` 包含 **77 个唯一工具**,所有输入/输出 schema 都以对象为根,分类为 **41 只读 / 36 写入-破坏性**,并带有 `bizTag=novel-agent-v0.7`;
- 源码树通过 `python -m compileall`。
