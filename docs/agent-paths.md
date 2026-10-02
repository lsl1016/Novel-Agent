# 双路径架构与外部 Agent 接入指南

> 本文回答三个问题:模型是怎么被调用的(它们看得到工具吗)?自动长跑走哪条路?外部 Agent 怎么用这套写作运行时?

## 1. 双路径总览

系统有两条共享同一状态与门禁的驱动路径:

```text
路径一:外部 Agent(人机协作 / 接管)                路径二:无人值守长跑(量产)
  Claude / Codex / 自研 Agent                        drive.py / cron / CI
        │ skill 纪律 + MCP tools/list & tools/call          │ 进程内直调(不经工具层)
        ▼                                                   ▼
  MCP 传输(server.py / stdio_compat / http_compat)   NovelService 方法直调
        └──────────────────┬────────────────────────────┘
                           ▼
                     NovelService(92 个工具的实现本体)
                           │
                           ├─ Context Compiler 编译角色上下文
                           │    ├─ planner 上下文(作者层,含 World Truth)
                           │    ├─ writer 上下文(安全,只含 Reader/POV 可知)
                           │    └─ reviewer 上下文(作者视角,输出前脱敏)
                           │
                           └─ llm_client(纯文本/JSON 进出,模型无工具)
                                ├─ planner  → ChapterPlan JSON
                                ├─ writer   → 章节正文
                                ├─ reviewer → reviews JSON(隐藏真值已脱敏)
                                └─ revision → 修订正文
```

**关键设计:四个模型(planner/writer/reviewer/revision)完全看不到工具。** 它们收到的是编译好的上下文 JSON,返回一段正文或一个 JSON 对象,没有 function calling、没有 agent loop。"该查什么、下一步做什么"由 Python 代码(service / run_controller)决定——真正在当 agent 的是 runtime 本身,模型是被调度的无状态文本变换。这是方案 7.1(检索权收归确定性 Compiler)与 4.4(自动化有界)的落地。

## 2. 工具的暴露方式(路径一专用)

工具的单一事实源是 `mcp-server/src/novel_mcp/tooldefs.py`(92 个工具的名称 + JSON Schema);`runtime.call_tool(name, args)` 反射到 `NovelService` 同名方法——工具本质是 service 方法的 RPC 皮。三条传输:

| 传输 | 入口 | 适用 |
|---|---|---|
| 官方 MCP SDK v2 | `mcp run server.py`(stdio / streamable-http) | 标准 MCP 客户端,需 `pip install 'mcp>=2,<3'` |
| 零依赖 stdio | `novel-mcp-compat`(JSON-RPC: initialize/tools/list/tools/call) | 本地兼容、冒烟 |
| HTTP 门面 | `POST /mcp` + `POST /api/agent/tools/call/{name}` | 通用网关(lsl1016/mcp-server 批量注册,见 registration/),带 errNo 信封与角色鉴权 |

连接配置见 `docs/client-configs.md`;skill 从 `dist/skill.zip` 安装。

## 3. 自动长跑不经过工具层与 skill

长跑路径(drive.py)进程内直调 service 方法,grep 可证 runtime 对 `skills/` 零引用。skill 的纪律在 runtime 里有**内嵌版**:

| SKILL.md 纪律(给外部 agent 的散文版) | 长跑路径的对应物(代码/提示词版) |
|---|---|
| 12 步章节事务 | `run_controller.step` 执行顺序 |
| Writer 只见安全上下文 | Context Compiler + writer system prompt 安全契约 |
| 线索强度阶梯 / 不一次揭完 | planner 硬规则 + semantic_narrative 审校 |
| Draft ≠ Canon、必须过审 | `chapter_finalize` 版本精确审校门 |
| declared_updates 形状契约 | planner prompt 契约 + `chapter_plan_check` 校验器 + 归一化 |

## 4. 覆盖面对照

| 能力域 | 自动长跑 | 外部 Agent |
|---|---|---|
| 规划 / 写作 / 审校 / 修订 / 提交 / Run 控制(≈25 工具) | ✅ 等效执行(进程内) | ✅ 逐工具调用 |
| Reference Graph 结构学习 | ✅(planner 上下文自动携带 reference_patterns) | ✅ `narrative_pattern_search` |
| 作者侧工具:实体/身份档案/断言/披露/候选晋升/世界真相编辑 | ❌ 不在自动路径(planner 不声明这些组) | ✅ 专属操作面 |
| 一句话开书(架构生成 `novel_architecture_generate`) | ❌(开书是显式人工/agent 动作,不在无人值守路径) | ✅ planner/admin 白名单;推荐两步:生成 → 审阅 → `story_architect_apply` |
| 正文由谁写 | 服务端配置的 writer 模型 | agent 自己(`chapter_draft_save(source='external')`)或内置模型 |

## 5. 外部 Agent 的三种用法

**A. Agent 自己当 Writer(skill 标准工作流)**:`writer_context_get` → agent 自写正文 → `chapter_draft_save` → `chapter_review_all/full` → (有问题:`chapter_revision_context_get` 自改) → `chapter_finalize`。所有门禁照常生效:上下文编译时 agent 物理拿不到 World Truth 真值,finalize 强制精确版本完整审校。

**B. Agent 当监督者(托管给内置长跑)**:`novel_run_start` 发起有界 run,`novel_run_status` 巡检,`novel_run_decision_list/submit` 处理 HITL 决策,`novel_run_report` 看报告。

**C. 混合(推荐)**:agent 做作者层操作(建架构、管世界状态、晋升候选——恰是自动路径不碰的面),章节量产交给 run,关键章节(卷首、大 Reveal)切回 A 亲手写。

## 6. 边界与注意事项

1. **语义审校依赖服务端模型配置**(`NOVEL_REVIEWER_*`):确定性 4 项零配置可用;语义 4 项需要配置。外部 agent 想自己当语义审校者也行(reviewer 角色可见作者层真相),但"findings 不得回显隐藏真值"的脱敏在服务端路径是代码强制(`redact_hidden_values`),在外部 agent 路径靠 skill 纪律自觉。
2. **内置模型工具 vs agent 自写**:`chapter_draft_generate` / `chapter_auto_revise` 用服务端配置的模型;agent 用自身能力时应走 `chapter_draft_save` / `chapter_revision_context_get`。
3. **权限**:经 HTTP 门面接入时用 `NOVEL_FACADE_TOKENS` 按角色发令牌(writer/reviewer/planner/controller/admin,见 `novel_mcp/auth.py`);writer 角色额外受参数守卫(只能编译 writer 视角上下文)。
4. **两条路共享同一 Story DB 与 Commit Gate**:长跑到一半,外部 agent 可随时用 MCP 工具检查、接管、回放(`context_snapshot_get` / `context_explain` 可解释任意章节"模型当时看到了什么")。
