# MCP 客户端连接模式

## Stdio

使用等价于如下内容的客户端配置:

```json
{
  "mcpServers": {
    "narrative-kg": {
      "command": "python",
      "args": ["-m", "novel_mcp.stdio_compat"],
      "env": {
        "NOVEL_STORY_DB": "/absolute/path/story.db",
        "NOVEL_REFERENCE_ROOT": "/absolute/path/reference-graph",
        "NARRATIVE_KG_ROOT": "/absolute/path/narrative-kg"
      }
    }
  }
}
```

零依赖适配器适用于本地兼容场景。生产环境建议改为通过 `mcp` CLI 与宿主的 stdio 命令配置来启动官方 SDK v2 服务器。

## Streamable HTTP

运行:

```bash
PYTHONPATH=src mcp run server.py --transport streamable-http
```

然后使用 SDK 打印出的 URL 来配置 MCP 宿主(通常是一个单一的 `/mcp` 端点)。

不要仅仅因为参考图存储与故事图存储都能通过同一个 MCP 服务器访问,就将二者合并。

## 无依赖的 2026 无状态 HTTP

在不使用官方 SDK 包的情况下进行本地集成:

```bash
NOVEL_STORY_DB=/absolute/path/story.db \
NOVEL_REFERENCE_ROOT=/absolute/path/reference-graph \
novel-mcp-http --host 127.0.0.1 --port 8765
```

将宿主连接到 `http://127.0.0.1:8765/mcp`。该适配器实现了 2026-07-28 版 Streamable HTTP 传输的 JSON 响应分支,并把所有故事状态保存在 SQLite 中,而不是保存在 MCP 协议会话里。

## 模型端点配置(V0.10)

五个角色独立路由,每个角色支持 `BASE_URL / API_KEY / MODEL / TEMPERATURE / MAX_TOKENS / TIMEOUT` 六个变量,取值链:`NOVEL_{ROLE}_*` → `NOVEL_WRITER_*` → `NKG_LLM_*`(ARCHITECT 例外,回退 PLANNER):

```bash
NOVEL_PLANNER_BASE_URL=...      # 作者层 Chapter Planner(建议思考型模型)
NOVEL_PLANNER_API_KEY=...
NOVEL_PLANNER_MODEL=glm-4.6
NOVEL_WRITER_BASE_URL=...       # 正文 Writer
NOVEL_WRITER_MODEL=glm-4.5-air
NOVEL_REVIEWER_BASE_URL=...     # 语义审校(建议思考型;不配则语义审校不可用,确定性审校不受影响)
NOVEL_REVIEWER_MODEL=glm-4.6
NOVEL_REVISION_BASE_URL=...     # 自动修订 Writer
NOVEL_REVISION_MODEL=glm-4.5-air
NOVEL_ARCHITECT_BASE_URL=...    # 一句话开书的架构生成器(可选;不配回退用 PLANNER 组)
NOVEL_ARCHITECT_MODEL=glm-4.6
```

协议由 `NOVEL_LLM_PROTOCOL`(或 `{ROLE}_PROTOCOL`)指定,`auto`(默认)按 base URL 含 `/anthropic` 自动走 Anthropic Message 协议,否则 OpenAI 兼容——同一套配置可接任意 OpenAI 兼容端点,无需改代码。思考型模型需调大 `*_MAX_TOKENS`(默认 16384,thinking 块计入)与 `*_TIMEOUT`(参考 env/llm.env:planner 420s / writer 300s / reviewer 600s / revision 600s)。完整示例见 `env/llm.env`。

可选观察开关:`NOVEL_THINKING_LOG=<jsonl路径>` 把思考型模型的 thinking 块(OpenAI 协议的 `reasoning_content` 同理)按行追加写入,供实时观察规划/审校的推理过程(`scripts/stress/watch.py --thinking`);未设置时零开销,进程启动时读取、跑到一半无法追加。

## HTTP 门面角色鉴权(V0.10,已从建议变为强制实现)

```bash
# 多角色令牌:writer/reviewer/planner/controller/admin
NOVEL_FACADE_TOKENS="writer:t1,reviewer:t2,planner:t3,controller:t4,admin:t5"
# 兼容旧单令牌(映射为 admin);两者都未配置时为本地开放模式
```

角色 × 工具白名单与参数级守卫由 `novel_mcp/auth.py` 强制(如 writer 角色只能编译 writer 视角上下文、reviewer 不得 finalize),矩阵详见源码或 `docs/agent-paths.md`。

## 实体图角色分离

经动态 `lsl1016/mcp-server` 网关接入时,为每类应用发放独立的角色令牌(见上节,服务端强制):

- writer 应用:prose-safe 读 + 草稿写;`entity_author_get`、`belief_get`(返回 World Truth 真值)等作者层读均不在白名单。
- reviewer 应用:作者视角读 + 审校/自动修订(参数守卫禁止 finalize)。
- planner/作者应用:作者层全量(实体变更、身份档案、断言、披露、候选晋升)。
- controller 应用:Run 控制 + `chapter_finalize`。
