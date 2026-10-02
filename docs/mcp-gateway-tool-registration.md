# Novel Agent V0.7 接入 lsl1016/mcp-server 工具注册指南

> **状态(2026-10-02,V0.11)**:本文流程有效;工具数已演进至 94(v0.11),重新导出 tool_schemas.json 后按本文注册即可。


> 目标：不再把 Novel Agent 自己作为一个独立 MCP Server 直接接客户端，而是把 Novel Agent 的 79 个能力作为普通 HTTP JSON 工具注册到 `lsl1016/mcp-server`，统一获得应用授权、工具上下线、审计、限流和 MCP 对外暴露能力。

## 0. 本文基于的 mcp-server 版本

- 仓库：`lsl1016/mcp-server`
- 参考分支：`main`
- 参考提交：`88be08e8db75a982b00ca49b5aa82cfed22fa63b`

本文严格按该仓库当前实现整理：工具注册走 `/api/manage/tools/batchCreate`；工具定义进入 `mcp_tool`，再通过 `mcp_app_tool` 授权给应用；MCP 客户端最终只连接网关 `/api/mcp`。

---

## 1. 推荐架构

```text
MCP 客户端 / ChatGPT / Claude / Codex / Go Agent
        │
        │ Authorization: Bearer <appKey>:<appSecret>
        ▼
lsl1016/mcp-server
POST /api/mcp
        │
        ├── tools/list -> mcp_tool + mcp_app_tool
        │
        └── tools/call
              │
              │ 通用 HTTP JSON 分发
              ▼
Novel Agent V0.7
POST /api/agent/tools/call/{tool_name}
              │
              ▼
NovelService / 规划 / 写作 / 运行控制器
              │
              ▼
故事数据库 + 参考图
```

### 为什么不要把 `/mcp` 再套进 `/mcp`

`lsl1016/mcp-server` 的核心价值是“一个 HTTP JSON 接口 = 一个动态 MCP Tool”。因此 Novel Agent 最合适提供一个极薄的 HTTP facade，让每个 Novel 工具独立注册。这样可以做到：

- 单工具授权；
- 单工具上下线；
- 单工具审计；
- 单工具限流；
- 读/写 Tool Annotation 正确暴露；
- 后续无需改 MCP 客户端配置，只改网关数据库。

---

## 2. Novel Agent 已增加的 HTTP facade

V0.7 增量版在 `novel_mcp.http_compat` 中增加：

```http
POST /api/agent/tools/call/{name}
Content-Type: application/json
Authorization: Bearer <NOVEL_FACADE_TOKEN>   # 可选
```

请求体 **就是该工具原本的 arguments 对象**。例如：

```http
POST /api/agent/tools/call/story_get_state
Content-Type: application/json

{
  "chapter": 327,
  "recent_window": 10
}
```

成功统一返回：

```json
{
  "errNo": 0,
  "errMsg": "success",
  "data": {
    "chapter": 327
  }
}
```

失败统一返回：

```json
{
  "errNo": 40001,
  "errMsg": "chapter is required",
  "data": null
}
```

这样做有两个原因：

1. `mcp-server` 原生识别 `errNo/errno/code` 与 `errStr/errMsg/message/msg`，所以无需额外适配错误语义。
2. `mcp-server` 当前要求 `outputSchema` 顶层是 object；Novel Agent 有部分工具原生返回 array，因此通过 `{errNo,errMsg,data}` 统一包一层可以直接兼容。

### 启动

```bash
export NOVEL_STORY_DB=../story-data/my-novel.db
export NOVEL_REFERENCE_ROOT=../reference-example

# 可选；不设置则 facade 不做二次鉴权
export NOVEL_FACADE_TOKEN="replace-me"

novel-mcp-http --host 0.0.0.0 --port 8765
```

此时同时存在：

- `POST /mcp`：Novel Agent 自己的 MCP 端点；
- `POST /api/agent/tools/call/{name}`：给通用 MCP 网关注册用的 HTTP facade。

---

## 3. mcp-server 注册字段映射

`batchCreate` 每个工具需要以下字段：

| mcp-server 字段 | Novel Agent 来源 | 建议 |
|---|---|---|
| `bizTag` | 固定 | `novel-agent-v0.7` |
| `url` | facade | `http://novel-agent:8765/api/agent/tools/call/{name}` |
| `requestConfig` | 生成 | POST + timeout + headers |
| `name` | `tool_schemas.json.name` | 原样保留，稳定 ID |
| `title` | `tool_schemas.json.title` | 原样 |
| `description` | `tool_schemas.json.description` | 原样 |
| `inputSchema` | `tool_schemas.json.inputSchema` | JSON stringify 后提交 |
| `outputSchema` | 包装后的 schema | 顶层 object，`data` 内放原 schema |
| `readOnly` | 工具策略 | `1=写`，`2=只读` |
| `isInternal` | 固定 | `2`，Novel Agent 作为内部上游 |
| `status` | 固定 | `2`，启用 |
| `owner` | 固定/环境 | 推荐 `novel-agent` |

注意：`readOnly=1` 在 `mcp-server` 中代表写操作，`readOnly=2` 才代表只读；写工具会被 MCP Tool Annotation 标记为 destructive。

---

## 4. requestConfig 规则

所有 Novel Agent facade 工具都使用：

```json
{
  "method": "POST",
  "timeout_ms": 10000,
  "headers": {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Authorization": "Bearer replace-me"
  }
}
```

`Authorization` 仅在设置 `NOVEL_FACADE_TOKEN` 时需要。

### 超时分级

`mcp-server` 当前允许的上游超时范围是 100ms~120000ms。因此注册生成器使用：

| 类型 | 超时 | 例子 |
|---|---:|---|
| 纯查询 | 10s | `story_get_state`, `belief_get` |
| 普通写操作 | 20s | `clue_add`, `belief_update` |
| 较重事务 | 30s | `story_architect_apply`, `chapter_finalize` |
| LLM/自动流程 | 120s | `chapter_plan_generate`, `chapter_semantic_review` |

### 两个需要额外收紧的工具

为了不让同步 HTTP 网关调用超过 120 秒，注册配置会比 Novel Agent 原生 schema 更严格：

- `novel_run_continue.max_steps`：原生最大 50；网关注册版最大 **3**，默认 **1**。
- `chapter_auto_revision_loop.max_rounds`：原生最大 8；网关注册版最大 **3**，默认 **2**。

生产环境更推荐让 Agent 多次调用单步工具，而不是一次同步请求里连续跑几十章。

---

## 5. 直接生成 79 个工具的 batchCreate JSON

项目新增：

```text
registration/
├── generate_mcp_server_registration.py
└── mcp-server-batch-create.json
```

重新生成：

```bash
cd registration

python generate_mcp_server_registration.py \
  --base-url http://novel-agent:8765 \
  --facade-token "$NOVEL_FACADE_TOKEN" \
  --owner novel-agent \
  --biz-tag novel-agent-v0.7 \
  --out mcp-server-batch-create.json
```

当前生成结果：

- 工具总数：**79**(v0.8:移除 chapter_commit,新增 candidate_list/promote/reject)
- 只读：**41**
- 写/破坏性：**36**

---

## 6. 批量注册到 lsl1016/mcp-server

假设网关管理地址：

```bash
export MCP_GATEWAY=http://127.0.0.1:18080
export MCP_ADMIN_TOKEN=demo-admin-token
```

注册：

```bash
curl -sS \
  -H "X-Admin-Token: $MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  --data-binary @registration/mcp-server-batch-create.json \
  "$MCP_GATEWAY/api/manage/tools/batchCreate"
```

成功响应形态由网关统一包装：

```json
{
  "errNo": 0,
  "errMsg": "success",
  "data": {
    "list": [
      {"id": 101, "name": "story_get_state"},
      {"id": 102, "name": "narrative_thread_get"}
    ]
  }
}
```

保存 `data.list[].id`，下一步用于 App 授权。

---

## 7. 创建 Novel Agent MCP App 并授权

创建应用：

```bash
curl -sS \
  -H "X-Admin-Token: $MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "appName": "novel-agent",
    "description": "Novel Agent V0.7 tools",
    "owner": "novel-agent"
  }' \
  "$MCP_GATEWAY/api/manage/app/create"
```

记录返回：

```text
app.id
app.appKey
app.appSecret
```

给应用授权工具：

```bash
curl -sS \
  -H "X-Admin-Token: $MCP_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "appId": 1,
    "toolIds": [101,102,103]
  }' \
  "$MCP_GATEWAY/api/manage/app/grantTools"
```

如果需要全部 79 个，就把 `batchCreate` 返回的所有 ID 一次性授权。

---

## 8. 客户端只连接统一 MCP 网关

完成注册后，Claude/Codex/自研 Agent 不再需要直连 Novel Agent `/mcp`：

```json
{
  "mcpServers": {
    "novel-tools": {
      "type": "http",
      "url": "http://127.0.0.1:18080/api/mcp",
      "headers": {
        "Authorization": "Bearer <appKey>:<appSecret>"
      }
    }
  }
}
```

网关会在 `tools/list` 时只返回当前 App 已授权并启用的 Novel 工具。

---

## 9. 注册后的验证

### 9.1 tools/list

```bash
curl -sS "$MCP_GATEWAY/api/mcp" \
  -H "Authorization: Bearer <appKey>:<appSecret>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' 
```

检查：

- `story_get_state` 存在；
- 未授权工具不出现；
- 只读工具 `readOnlyHint=true`；
- 写工具带破坏性（destructive）提示。

### 9.2 tools/call

```bash
curl -sS "$MCP_GATEWAY/api/mcp" \
  -H "Authorization: Bearer <appKey>:<appSecret>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"story_get_state",
      "arguments":{"chapter":1}
    }
  }' 
```

调用链应为：

```text
MCP tools/call
  -> mcp-server LookupTool/应用权限
  -> JSON Schema 校验
  -> POST /api/agent/tools/call/story_get_state
  -> Novel Agent
  -> {errNo:0,errMsg:"success",data:{...}}
  -> mcp-server structuredContent
```

---

## 10. 79 个工具注册策略


### 故事图 / 基础叙事状态

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `story_get_state` | 读 | 10s | 获取某一章的权威写作上下文：篇章、目标、活跃叙事线、未决谜团…… |
| `narrative_thread_get` | 读 | 10s | 返回故事图中单条叙事线的完整生命周期。 |
| `narrative_thread_search` | 读 | 10s | 按文本、状态或类型搜索故事图叙事线。 |
| `mystery_create` | 写 | 20s | 创建或登记一个面向读者的长线谜团及其预期兑现窗口。 |
| `clue_add` | 写 | 20s | 向叙事线添加一条线索，并控制其可见性与信息强度。…… |
| `foreshadowing_list_open` | 读 | 10s | 列出需要重新激活或兑现的旧未决线索/伏笔。 |
| `belief_get` | 读 | 10s | 返回某一章单个事实的世界真相以及读者与人物信念，但不包含…… |
| `belief_update` | 写 | 20s | 记录读者或某人物对某一事实的相信/怀疑/知晓变化。 |
| `emotion_debt_create` | 写 | 20s | 创建长期存续的情感债，例如羞辱、承诺、牺牲、失去、误会…… |
| `emotion_debt_resolve` | 写 | 20s | 用一个兑现事件解决或部分解决一笔情感债。 |
| `narrative_pattern_search` | 读 | 10s | 在只读参考图中搜索结构示例。返回抽象结构…… |
| `chapter_plan_check` | 读 | 10s | 对照秘密世界真相、当前信念、叙事线……校验拟议的章节计划 |
| `continuity_check` | 读 | 10s | 对照权威故事……核对拟议事实、人物状态与时间线断言 |
| `story_pressure_check` | 读 | 10s | 度量未决谜团负载、失效伏笔、逾期情感债、近期未决…… |
| `chapter_commit` | 写 | 20s | 将完成的正文与作者声明的叙事更新提交到故事图。可选阶段…… |

### 实体图 / 世界模型

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `entity_get` | 读 | 10s | 读者/视角（POV）安全实体快照，过滤隐藏 alias / attribute / relation |
| `entity_author_get` | 读 | 10s | 作者视角完整实体快照；禁止授权普通写作者 |
| `entity_search` | 读 | 10s | 实体搜索；秘密 alias 不形成搜索侧信道 |
| `entity_neighbors` | 读 | 10s | 按章节与 holder 遍历可见邻接关系 |
| `entity_path_find` | 读 | 10s | 查找两实体之间的可见关系路径 |
| `entity_context_get` | 读 | 10s | 批量构造安全实体上下文 |
| `entity_graph_stats` | 读 | 10s | 实体/关系统计 |
| `entity_upsert` | 写 | 20s | 新增/更新实体 |
| `entity_alias_add` | 写 | 20s | 新增公开或秘密别名/身份 |
| `entity_attribute_set` | 写 | 20s | 写入时间属性 |
| `entity_relation_upsert` | 写 | 20s | 写入时间关系 |
| `entity_relation_end` | 写 | 20s | 结束关系并保留历史 |
| `narrative_entity_link` | 写 | 20s | 连接叙事图与实体图 |
| `narrative_entity_links_get` | 读 | 10s | 查询跨层绑定 |
| `entity_graph_check` | 读 | 10s | 写入前一致性校验 |
| `entity_graph_import` | 写 | 20s | 通用 nodes/edges 导入，默认 dry-run |

### 检索 / 上下文编译器

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `entity_retrieve_relevant` | 读 | 10s | 基于章节计划、视角、地点、线程和时间切片检索相关实体；写作者自动应用可见性过滤 |
| `narrative_retrieve_relevant` | 读 | 10s | 检索与本章相关的叙事线、谜团、情感债、信念等叙事义务 |
| `context_compile` | 读 | 10s | 按 writer/planner/reviewer 角色编译受预算约束的上下文；MCP 默认不持久化快照 |
| `context_preview` | 读 | 10s | 预览将加载的上下文规模、实体/叙事项数量与估算 token，不调用写作模型 |
| `context_snapshot_get` | 读 | 10s | 获取已持久化上下文快照；可能包含作者层真相，仅授权作者/审校者/管理员 |
| `context_explain` | 读 | 10s | 解释某实体或叙事项为何进入上下文及其相关性得分；可能暴露作者层检索轨迹 |

### 规划运行时

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `blueprint_get` | 读 | 10s | 获取权威的高层小说蓝图及其乐观锁版本。 |
| `blueprint_update` | 写 | 20s | 修补或替换权威的小说蓝图。使用 expected_version 防止并发…… |
| `story_architect_get` | 读 | 10s | 获取编译后的高层架构：蓝图、篇章计划、里程碑、叙事线排期…… |
| `story_architect_apply` | 写 | 30s | 将作者设计的架构编译为权威故事图与规划状态。…… |
| `arc_plan_create` | 写 | 20s | 创建或更新一个篇章计划，包含目标、冲突、揭示约束、继承叙事线…… |
| `arc_plan_get` | 读 | 10s | 获取单个权威篇章计划。 |
| `arc_progress_get` | 读 | 10s | 度量一个篇章的已提交进度并返回其里程碑。 |
| `milestone_create` | 写 | 20s | 创建或更新跨章节规划里程碑，包含目标章节窗口与…… |
| `milestone_list` | 读 | 10s | 按篇章、状态或截止期限列出篇章里程碑。 |
| `thread_schedule_update` | 写 | 20s | 将叙事线阶段排入章节窗口，而不强制确切的正文或…… |
| `thread_schedule_get` | 读 | 10s | 按排期键、叙事线、章节或状态查询已规划的叙事线阶段。 |
| `planning_rebuild_window` | 写 | 30s | 构建或重新分层滚动式硬/中/软规划窗口。可选提案填充章节…… |
| `planning_get_window` | 读 | 10s | 从锚点章节获取章节级硬/中/软滚动计划项。 |
| `chapter_plan_save` | 写 | 20s | 保存结构化章节计划，运行知识/揭示/篇章/叙事线校验器，并持久化…… |
| `chapter_plan_get` | 读 | 10s | 获取已保存的结构化章节计划及其最近一次校验结果。 |
| `planning_pressure_check` | 读 | 10s | 将故事压力诊断与滚动窗口完整度、逾期里程碑……合并 |

### 运行控制器 / 作者规划器

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `planner_context_get` | 读 | 10s | 为单章构建作者层规划上下文。与写作者上下文不同，它有意…… |
| `chapter_plan_generate` | 写 | 120s | 使用已配置的作者层规划模型生成并可选择保存结构化…… |
| `novel_run_start` | 写 | 30s | 启动一个持久化的有界小说运行控制器循环。配置自动规划、写作…… |
| `novel_run_step` | 写 | 120s | 为持久化的小说运行执行至多一个章节事务：确保计划、草稿…… |
| `novel_run_continue` | 写 | 120s | 将小说运行推进有界数量的章节步数，达成目标即提前停止…… |
| `novel_run_status` | 读 | 10s | 查看持久化运行状态、当前/最近章节、停止原因、未决作者决策…… |
| `novel_run_pause` | 写 | 30s | 暂停活动中的小说运行，不丢失章节/运行状态。 |
| `novel_run_resume` | 写 | 30s | 恢复已暂停/决策已解决的小说运行。必须先解决所有未决作者决策。 |
| `novel_run_report` | 写 | 30s | 为小说运行生成确定性阶段报告，包含已提交章节、控制器…… |
| `novel_run_decision_list` | 读 | 10s | 列出某次小说运行的持久化人工决策点。 |
| `novel_run_decision_submit` | 写 | 30s | 解决一个持久化的作者决策，并可在继续前选择性地修补安全运行配置…… |

### 写作 / 审校运行时

| 工具 | 读/写 | 超时 | 说明 |
|---|---|---:|---|
| `writer_context_get` | 读 | 10s | 为单章构建正文安全上下文。隐藏的世界真相值被有意…… |
| `chapter_draft_generate` | 写 | 120s | 使用已配置的兼容 OpenAI 的写作者模型，从安全写作者……生成正文 |
| `chapter_draft_save` | 写 | 20s | 将外部生成或修订的正文保存为带版本、非权威的章节草稿。…… |
| `chapter_draft_get` | 读 | 10s | 获取非权威章节草稿的最新或指定版本。 |
| `chapter_review_all` | 写 | 30s | 对草稿运行四个相互独立的确定性审校闸门：知识泄漏、连续性…… |
| `chapter_review_get` | 读 | 10s | 获取最新或指定草稿版本的审校结果包。 |
| `chapter_revision_context_get` | 读 | 10s | 构建包含草稿、审校者发现、安全写作者上下文……的修订包 |
| `writing_workflow_status` | 读 | 10s | 查看章节计划、全部草稿版本、活动草稿、工作流状态与最近审校…… |
| `chapter_finalize` | 写 | 30s | 最终提交闸门。要求有效的章节计划以及针对确切草稿……的完整审校 |
| `chapter_semantic_review` | 写 | 120s | 运行基于模型、感知作者层的语义审校器，检测换述式秘密泄漏、人物…… |
| `chapter_review_full` | 写 | 120s | 在同一草稿版本上运行确定性审校器，并默认运行语义审校器家族…… |
| `chapter_auto_revise` | 写 | 120s | 使用已配置的修订模型修复 BLOCK 与可选 WARN 发现，而不暴露…… |
| `chapter_auto_revision_loop` | 写 | 120s | 审校活动草稿，自动修订被阻断的版本，并对每个新版本重新审校…… |

---

## 11. 推荐的生产授权拆分

不建议把 79 个工具全部授权给同一个低权限写作者 Agent。推荐至少拆三类 App：

### A. 写作者 App

只给正文写作所需的安全读取和草稿能力：

```text
story_get_state
narrative_thread_get
belief_get
entity_search
entity_get
entity_context_get
entity_neighbors
entity_path_find
narrative_entity_links_get
writer_context_get
chapter_plan_get
chapter_draft_save
chapter_draft_get
writing_workflow_status
```

不要给写作者：

```text
planner_context_get
entity_author_get
entity_upsert
entity_relation_upsert
blueprint_update
story_architect_apply
belief_update
chapter_finalize
novel_run_continue
```

尤其 `planner_context_get` 明确属于作者层（Author Layer），可能包含世界真相，不应暴露给普通写作者。

### B. 规划者/作者 App

给蓝图、篇章、叙事线排期、里程碑、章节计划等规划工具，并允许读取世界真相。

### C. 控制器 App

给 `novel_run_*`、审校、定稿等编排型写权限工具。

这样可以把 Novel Agent 内部已有的作者/写作者权限边界继续延伸到 MCP 网关层。

---

## 12. outputSchema 与输出投影

`mcp-server` 支持在 output schema 顶层配置：

```json
{
  "x-output-projection": true
}
```

用于裁剪上游返回，降低模型上下文占用。Novel Agent 第一版注册包**默认不开启投影**，原因是不同工具的返回结构差异较大，先保证完整结果和兼容性。

后续最适合优先做精细投影的工具：

- `story_get_state`
- `story_pressure_check`
- `planning_pressure_check`
- `novel_run_status`
- `writer_context_get`

对于 `chapter_draft_get`、`chapter_revision_context_get` 等包含长正文的工具，应尤其注意不要把不必要的完整正文反复塞进模型上下文。

---

## 13. 部署网络建议

### 同一个 Docker Compose 网络

注册 URL 用：

```text
http://novel-agent:8765/api/agent/tools/call/{name}
```

不要填 `127.0.0.1`，因为对 `mcp-server` 容器来说 `127.0.0.1` 是它自己。

### mcp-server 在 Docker、Novel Agent 跑宿主机

Mac/Windows 通常可以：

```text
http://host.docker.internal:8765/api/agent/tools/call/{name}
```

Linux Docker 需要显式配置 host-gateway 或使用宿主机可达地址。

---

## 14. 安全建议

存在三层凭证，职责不要混用：

| 层 | 凭证 | 用途 |
|---|---|---|
| MCP 客户端 -> mcp-server | `Bearer appKey:appSecret` | MCP 应用身份/授权 |
| 管理员 -> mcp-server | `X-Admin-Token` | 注册、授权、上下线 |
| mcp-server -> Novel facade | `Bearer NOVEL_FACADE_TOKEN` | 防止 facade 被绕过网关直调 |

生产环境建议 Novel facade 只监听内网，并设置 `NOVEL_FACADE_TOKEN`。

---

## 15. 更新工具版本的建议流程

Novel Agent 工具 Schema 发生变化时，不要删表重建。推荐：

1. 从新版 `tool_schemas.json` 重新生成注册文件。
2. 根据工具 `name` 找现有 ID。
3. 新工具 -> `/api/manage/tools/batchCreate`。
4. 已有工具 schema/description/url 变化 -> `/api/manage/tools/batchUpdate`。
5. 废弃工具 -> `/api/manage/tools/batchUpdateStatus` 下线。
6. 新工具再通过 `/api/manage/app/grantTools` 授权到对应 App。

`name` 应作为长期稳定的工具标识，不建议随文案调整而修改。

---

## 16. 本次增量文件

```text
novel-agent-v0.7-work/
├── docs/
│   └── mcp-gateway-tool-registration.md   # 本文
├── registration/
│   ├── generate_mcp_server_registration.py
│   └── mcp-server-batch-create.json        # 79 个工具，可直接 POST(v0.8)
└── mcp-server/src/novel_mcp/
    └── http_compat.py                      # 增加 /api/agent/tools/call/{name}
```

---

## 17. 与 lsl1016/mcp-server 源码的对应关系

- `README.md`：网关整体模型、`batchCreate`、App 授权、MCP 客户端接入。
- `service/manage/tools/tool.go`：注册字段、`readOnly/isInternal/status` 取值、Schema/URL/requestConfig 校验。
- `mcp/toolconfig/config.go`：HTTP method、Header、100ms~120s timeout 规则。
- `mcp/dispatch.go`：GET/DELETE -> query，其余 method -> JSON body；识别常见上游错误字段。
- `mcp/registry.go`：tools/list 按 App 授权过滤，tools/call 再次复核；动态 Schema 直接进入 MCP Tool 定义。
- `mcp/toolconfig/output_schema.go`：output schema 顶层 object 与可选 `x-output-projection`。
- `service/manage/app/app.go`：App 创建、grantTools、授权启停。

这套接法的核心原则是：**Novel Agent 负责业务状态与写作约束，lsl1016/mcp-server 负责 MCP 网关、工具注册、应用授权、限流和审计。两边职责不重复。**


## 14. V0.7 检索 / 上下文编译器注册与授权建议

V0.7 新增 6 个只读检索工具：

- `entity_retrieve_relevant`
- `narrative_retrieve_relevant`
- `context_compile`
- `context_preview`
- `context_snapshot_get`
- `context_explain`

推荐授权：

| 工具 | 写作者 App | 规划者/作者 App | 审校者/管理员 App |
|---|---|---|---|
| `entity_retrieve_relevant` | 可 | 可 | 可 |
| `narrative_retrieve_relevant` | 可 | 可 | 可 |
| `context_compile` | 可，仅 `role=writer` | 可 | 可 |
| `context_preview` | 可 | 可 | 可 |
| `context_snapshot_get` | **不建议** | 可 | 可 |
| `context_explain` | **不建议** | 可 | 可 |

`context_snapshot_get`/`context_explain` 虽然是只读的，但规划者/审校者快照可能包含世界真相，所以不能仅依据 MCP `readOnlyHint` 判断是否可以授权给写作者。它们属于作者/调试权限。

生产写作者最推荐直接使用 `writer_context_get`。它内部已经走上下文编译器，并自动保存写作者安全快照。不要把 `planner_context_get` 或规划者/审校者快照作为正文上下文。
