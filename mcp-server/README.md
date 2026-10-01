# Narrative-KG 小说 MCP 服务器 v0.7

一个具备两个正典知识层的长篇小说运行时:

- **实体图 / 世界模型** — 角色、阵营、地点、物品、技能、境界、神器,以及时间属性与时间关系。
- **叙事图** — 叙事线、谜团、线索、揭示、兑现、情感债与信念。

规划、写作者/审校者、语义审校以及有界的小说运行编排都构建在这两层之上。

## 安装

```bash
python -m pip install -e . --no-build-isolation
```

可选的官方 MCP SDK 适配器:

```bash
python -m pip install -e '.[mcp]' --no-build-isolation
```

## 环境变量

```bash
export NOVEL_STORY_DB=../story-data/my-novel.db
export NOVEL_REFERENCE_ROOT=../reference-example
```

模型端点兼容 OpenAI,并沿用现有的 `NOVEL_PLANNER_*`、`NOVEL_WRITER_*`、`NOVEL_REVIEWER_*` 以及修订相关配置。

## HTTP / MCP

零依赖的兼容服务器:

```bash
novel-mcp-http --host 127.0.0.1 --port 8765
```

端点:

```text
POST /mcp
POST /api/agent/tools/call/{tool_name}
```


## 检索与上下文编译器 v0.7

新增的读取侧工具:

- `entity_retrieve_relevant`
- `narrative_retrieve_relevant`
- `context_compile`
- `context_preview`
- `context_snapshot_get`
- `context_explain`

`writer_context_get`、`planner_context_get` 与语义审校现在使用按角色编译的上下文,而不是大范围的图数据倾倒。写作者上下文按章节切片,并且看不到隐藏的世界真相取值。

## 工具 — 共 77 个

- 叙事故事图:15
- 实体图 / 世界模型:16
- 规划运行时:16
- 作者规划器 / 运行控制器:11
- 写作者 / 审校者运行时:9
- 语义审校 / 自动修订:4

机器可读的 schema:`tool_schemas.json`。

## 实体图安全

`entity_author_get` 仅供作者角色使用。写作者安全读取会做章节/持有者过滤:

```text
entity_get
entity_search
entity_neighbors
entity_path_find
entity_context_get
```

秘密别名/属性/关系的可见性由 `secrecy`、`reveal_after` 以及可选的 `fact_key` 控制;`fact_key` 会绑定到世界真相 / 信念状态(BeliefState)台账。

`writer_context_get` 会自动嵌入安全的 `entity_context`,不会暴露隐藏关系。

## 正典实体更新

草稿/计划可以声明:

```text
entities
entity_aliases
entity_attributes
entity_relations
narrative_entity_links
```

只有在正常的定稿门禁提交该章节之后,它们才会被应用。

## 网关注册

使用 `../registration/generate_mcp_server_registration.py` 为全部 77 个工具构建 `lsl1016/mcp-server` 的 `batchCreate` 载荷。
