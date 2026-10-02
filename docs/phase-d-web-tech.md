# Phase D Web 工作台：技术实现方案

> 状态：技术方案（2026-10-02）。**D1 已实现（2026-10-02）**：`web_api.py` + `service.web_*` 聚合读 + `auth.py` viewer 角色 + React/Vite 前端（`frontend/`），已在长跑副本库上验收（主页/运行中心 SSE 实时流/写作工作室纸页）。**D2 已实现（2026-10-02，80/80 测试绿）**：`web_entities/web_entity/web_graph/web_board/web_timeline` 聚合（含 `belief_matrix` 信念矩阵与伏笔台账）+ 世界观设定集（目录/自绘 Canvas 图谱/实体档案抽屉）+ 叙事看板（线程泳道/谜团倒计时/情感债/信念矩阵/伏笔台账）+ 时间线浏览器 + **章节时光轴全局游标**（拖动全站按"截至第 N 章"重渲染，浏览器实测回拨联动生效）。D3 待做。**写操作交互 + UI 组件化(2026-10-02 第二轮)**:`app.css` 组件层(按钮/输入/表格/导航/对话框/Toast/纸页编辑器)+ Modal 确认与 ActionButton(透传 actions,自动 Toast 结果)+ 运行中心暂停/恢复 + **HITL 决策作答**(web_decision_answer:答案写入 blueprint.author_decisions 后 resume,controller/admin)+ 写作工作室**定稿按钮**(闸门全绿才亮,二次确认)与**草稿编辑器**(保存为新版本,source=web_edit)。写操作已在演示副本实测(暂停→paused→恢复按钮出现→恢复)。**亮色改版 + 可视化升级(第三轮)**:亮色工房为默认底材(白卡+柔和投影,语义色白底校准,暗色转后备主题);图谱画布升级(彩色填充节点/度数定大小+角标/贝塞尔边/滚轮缩放/拖拽平移/悬停邻域聚焦/图例);看板线程改比例时间带(兑付窗投影+休眠斜纹);信念矩阵热力格;主页目标进度条+近章字数迷你折线;时间线网格+事件类型配色。功能与 UI 风格见 `docs/phase-d-web-design.md`。
> 目标：在不破坏"后端零第三方依赖、SQLite 单写者、权限服务端强制"三个既有纪律的前提下，把工作台做出来。

## 1. 技术总览

```text
浏览器 (React SPA, Vite 构建, dist/ 静态产物)
   │  同源: /            → 静态文件
   │  同源: /api/v1/...  → 聚合读 + 动作(写走既有闸门)
   │  同源: /api/v1/stream/... → SSE 事件流
   ▼
 novel-web 进程 (Python stdlib, ThreadingHTTPServer)
   ├─ web_api.py   ← 新增 BFF：路由 /api/v1、SSE、静态托管
   ├─ http_compat.py 既有 MCP 端点不动（/mcp 供外部 Agent 用）
   ▼
 NovelService (91 工具的同一套方法, 进程内直调)
   ├─ 读: 新增聚合读方法（只读, 复用 repositories）
   └─ 写: thin passthrough → facade_call(name,args,headers)
         （= 与外部 Agent 完全相同的校验/权限/闸门路径）
   ▼
 StoryStore → SQLite (WAL, busy_timeout, 单写者纪律不变)
```

三条硬约束（全文反复回到它们）：

1. **后端坚持 stdlib**：BFF 用 `http.server` 扩展，不引入 FastAPI/Flask。理由与 http_compat.py 相同：用户 `pip install -e .` 即得全部。
2. **写路径唯一**：UI 的每个写动作 = `facade_call(工具名, 参数, 令牌)`。BFF 不自己写 SQL、不做业务判断。"UI 永不绕闸门"的技术表达就是：**BFF 没有第二条写路径**。
3. **权限在服务端**：浏览器持令牌，BFF 经 `auth.py` 解析角色；读者/查看模式不是前端隐藏，而是令牌对应的角色在服务端就拿不到 secret 载荷。

## 2. 后端：BFF 层（`web_api.py`，挂进现有服务器）

### 2.1 进程与路由

`novel-web --host 127.0.0.1 --port 8080 --db story.db --static frontend/dist`：

- 与 `novel-mcp-http` 同构（复用 `ThreadingHTTPServer` + Handler 模式），一个进程同时服务 SPA、API、SSE，**同源部署，无 CORS 问题**；
- 默认只绑 127.0.0.1（本地优先）；
- MCP 端点可选同进程挂载（`/mcp` 分流到既有 handler），这样本地用户一个进程全搞定。

### 2.2 API 设计（`/api/v1`）

聚合读端点（新增只读 service 方法，进程内直调 repositories，避免浏览器 N+1）：

| 端点 | 背后的聚合 | 用途 |
|---|---|---|
| `GET /api/v1/home?chapter=N` | 进度 + 压力四指标 + 运行状态 + 三类待办数 + 近 7 章统计 | 主页一次取齐 |
| `GET /api/v1/entities?chapter=N&q=&type=` | 实体目录 + 可见性过滤计数 | 设定集列表 |
| `GET /api/v1/entity/{key}?chapter=N` | 全档案：身份链/属性时间线/关系/别名/叙事链接/证据断言 | 右抽屉 |
| `GET /api/v1/graph?chapter=N&scope=&focus=` | 可见边表 + 节点表（前端渲染画布用，不含 secret 边——作者模式另走 `?author=1` 且角色为 planner/admin） | 图谱画布 |
| `GET /api/v1/board?chapter=N` | 线程+stage 窗口、谜团倒计时、伏笔-兑现配对、情感债、信念矩阵（`belief_matrix(chapter)` 新方法：事实×持有者×认知态） | 叙事看板 |
| `GET /api/v1/plan?chapter=N` | 弧/里程碑/排期/滚动窗/冲突标记 | 规划器 |
| `GET /api/v1/chapter/{n}` | 计划 + 草稿版本列表 + 激活稿 + 审校结论 + 定稿状态 | 写作工作室 |
| `GET /api/v1/chapter/{n}/draft/{v}` | 草稿正文（作者模式；viewer 角色只有正典正文） | 编辑器 |
| `GET /api/v1/timeline?from=&to=&entity=` | 事件 + 参与者 + 因果边 + 变迁轨道 | 时间线 |
| `GET /api/v1/runs` / `GET /api/v1/runs/{id}` | 运行列表/详情 + 事件尾 + 每章 token 曲线 | 运行中心 |
| `GET /api/v1/context-snapshots/{chapter}` | 提交时快照 + explain | 审计/解释 |

写动作端点（thin passthrough，全部 `POST`，返回 facade 的原样结果）：

| 端点 | 透传到 |
|---|---|
| `POST /api/v1/actions/{tool}` | `facade_call(tool, body, Authorization)` —— 91 工具的白名单子集（按角色），例如 `novel_run_start` / `novel_run_decision_submit` / `chapter_draft_save` / `chapter_finalize` / `candidate_promote` / `blueprint_update`… |

这样做的收益：BFF 零业务逻辑、闸门语义与外部 Agent 路径**逐字节相同**、新工具上线 UI 即可调用（加个按钮映射）。

### 2.3 SSE 实时流

`GET /api/v1/stream/runs/{id}`（`text/event-stream`）：

- 服务端每 1.5s 轮询 `novel_run_events`（按 id 增量）+ `novel_runs` 状态 + `chapters` 计数，diff 后推送；
- 事件类型：`pipeline_stage`（计划→草稿→审校→修订→提交 步进）、`chapter_committed`、`decision_open`、`run_status`、`heartbeat`；
- SQLite WAL 下读连接不阻塞写作事务（已验证的并发读路径）；
- 断线用 `Last-Event-ID`（事件表自增 id）续传；
- 只在运行中心页订阅，避免无谓轮询。

### 2.4 鉴权与角色

- 登录页输入令牌（`NOVEL_FACADE_TOKENS` 之一）→ `sessionStorage` → 所有请求 `Authorization: Bearer`；BFF 经 `auth.py` `resolve_role`；
- **新增 `viewer` 角色**（auth.py 加一组只读白名单：安全读工具 + 只看正典正文），这就是"读者模式"的服务端实体——作者拿 admin/planner 令牌，家人朋友拿 viewer 令牌，投屏不剧透；
- 角色 → 可见工作区映射在前端路由层做（viewer 进不了写作工作室的草稿区），但**安全不依赖这个映射**。

### 2.5 新增后端工作清单（Python 侧全部改动）

| 模块 | 改动 |
|---|---|
| `web_api.py`（新，~300 行） | Handler 子类：GET 静态/API/SSE、POST actions、token 鉴权中间层 |
| `service.py` | 聚合读方法：`home_summary` / `belief_matrix` / `board_view` / `timeline_view` / `chapter_workspace`（只读，复用 repositories，每方法 ≤5 条 SQL） |
| `auth.py` | `viewer` 角色白名单（READS_PROSE_SAFE 子集 + 正典正文读） |
| `cli.py` | `novel-web` 入口 |
| `tooldefs.py` | 不动（BFF 聚合读不是工具，外部 Agent 不需要它们） |

## 3. 前端

### 3.1 选型（每个都有明确理由）

| 层 | 选型 | 理由 |
|---|---|---|
| 框架 | **React 18 + TypeScript + Vite** | 数据密集仪表的主流选择；类型直接吃后端 inputSchema 生成的类型 |
| 服务端状态 | **TanStack Query** | 缓存/失效/重试一站式；"章节游标"作为 query key 参数，拖动即精准失效重取 |
| UI 状态 | **Zustand** | 只有三个全局态：章节游标、当前令牌/角色、抽屉状态 |
| 路由 | React Router | 深链 `/book/:id/entity/:key`、`/chapter/:n` |
| 样式 | **Tailwind + Radix Primitives + `tokens.css`** | Radix 给无障碍的弹层/页签；`tokens.css` 是语义色单一来源（§3.3），Tailwind 只引用 token，杜绝色值散落 |
| 可视化 | **ECharts**（信念矩阵热力图、token 曲线、弧线甘特）+ **自绘 Canvas 2D**（实体大图）+ **React Flow**（因果链/身份链/伏笔连线等小型 DAG） | 一个库覆盖矩阵/曲线/甘特三类；大图自绘才能落实"图形语言"（形状=类型、虚线+锁=秘密、视口裁剪、LOD 折叠） |
| 编辑器 | **CodeMirror 6** + `@codemirror/merge` | 版本 diff、中文排版主题、行锚点定位审校发现 |
| SSE | 原生 `EventSource` 封装 hook | 不需要 WebSocket（单向流） |

### 3.2 目录结构

```text
frontend/
  src/
    api/          # client.ts(带令牌拦截器)、sse.ts、按域的 hooks
    app/          # 路由、布局、登录页
    stores/       # cursor.ts(章节游标)、session.ts、drawer.ts
    shared/       # StatusPill、SecretLock、ChapterAxis(通用章轴刻度)、
                  # GateChecklist、Drawer、ErrorBoundary
    features/     # home/ wizard/ world/ board/ planner/ studio/
                  # review/ timeline/ run/ settings/  每域自含组件+hooks
    tokens.css    # 语义色/design tokens 唯一来源
  e2e/            # Playwright
```

### 3.3 语义色 token（单一来源）

`tokens.css` 定义 §3.2（设计稿）的全部语义变量（`--sem-canon`、`--sem-draft`、`--sem-secret`、`--sem-block/warn/pass`、`--sem-truth/reader/character`、`--arc-1..12`），暗色工房与纸页书房两个底材主题都只引用这些变量换底色——**语义与底材解耦**是双质感不分裂的技术保证。

### 3.4 关键机制实现

- **章节时光轴**：`cursor.ts` 存章号 → 所有序据 hooks 的 query key 带章号 → 拖动滑杆防抖 200ms 重取 → 各端点服务端用 `chapter_at_or_before` 语义出数。回拨的正确性由服务端保证，前端零状态逻辑。
- **定稿检查单**：一个纯函数组件消费 `chapter_workspace` 返回的门条件（计划有效/审校齐全/版本一致），全绿才启用按钮——按钮点击仍是 `POST /actions/chapter_finalize`，服务端再验一遍。
- **编辑器发现定位**：审校发现带引文片段 → 前端在 CM6 doc 里 `search()` 锚点滚动高亮；定位不到时列出引文让作者手动跳。
- **图谱画布**：Canvas 2D 双层（静态层/交互层），力导布局在前端跑；节点 >600 时自动折叠 Faction 为超节点（点开下钻子图）；secret 边仅在 `?author=1` 且角色允许时由服务端下发。

## 4. 数据与性能

| 关注点 | 方案 |
|---|---|
| 页面加载请求数 | 聚合端点保证每工作区首屏 1-2 个请求 |
| 章节游标拖动 | 防抖 + Query 缓存（同章号回拨命中缓存零请求） |
| 信念矩阵规模 | 事实 × 持有者上限提示；>200 格分页（按事实组分页） |
| 图谱规模 | 视口裁剪、LOD（缩小时隐藏标签）、超节点折叠、边数上限 |
| token 曲线 | 40+ 章数据一次下发，前端 ECharts 缓存渲染 |
| 长文正文 | 草稿/正文按需取（章节懒加载），不做全书虚拟滚动 |

## 5. 工程与部署

```bash
# 开发
cd frontend && npm i && npm run dev      # Vite :5173, /api 代理到 :8080
novel-web --db story-data/stress.db --port 8080   # 后端热改重启

# 构建
npm run build                            # → frontend/dist/
# 发布形态：dist 预编译随仓库/包分发,运行用户不需要 Node
novel-web --db story-data/stress.db --static frontend/dist --port 8080
# 打开 http://127.0.0.1:8080 → 登录页输入令牌
```

- 依赖政策：**后端零新增 Python 依赖**；前端 npm 依赖正常使用，但产物 vendored（dist 入库或随 release 附带），运行侧零 Node 要求；
- 测试数据库直接用 stress 种子书（40 章真实数据）做开发夹具——所有界面天然有数据。

## 6. 测试

| 层 | 工具 | 内容 |
|---|---|---|
| BFF | pytest（沿用 tmp db 模式） | 聚合读正确性（游标语义）、actions 透传的权限矩阵（viewer 拿不到 secret/不能写）、SSE 增量推送、静态服务 |
| 前端单测 | Vitest + Testing Library | 定稿检查单逻辑、矩阵渲染、令牌/角色路由守卫、tokens 约束（组件快照无裸色值） |
| E2E | Playwright + stress 夹具库 | D1 验收流：登录 → 主页 → 运行中心实时步进 → 写作工作室读稿 → viewer 模式无 secret |
| 回归 | 既有 70 测试保持全绿 | BFF 不得影响 MCP 路径 |

## 7. 里程碑（技术拆解，对齐设计稿 D1-D3）

| 阶段 | 技术交付 |
|---|---|
| **D1 可视先行** | web_api.py 骨架 + 令牌登录 + viewer 角色 + `/home` `/runs` `/chapter` 端点 + SSE + 前端框架/tokens/路由 + 主页、运行中心、写作工作室（读 + 编辑器 + 定稿检查单）|
| **D2 图谱可视** | `/entities` `/entity` `/graph` `/board` `/timeline` + `belief_matrix` + Canvas 画布 + ECharts 矩阵/甘特 + React Flow 因果链 + 章节游标全站联动 |
| **D3 创作闭环** | 开书向导（消费 Phase C 契约：idea.json/bible.md/stages diff）+ `/plan` 规划器 + 审校中心深化 + 设置/导出 + 多书切换 |

依赖顺序：D1 完全不依赖 Phase C；D3 的向导依赖 Phase C 落地（C1 即够用）。

## 8. 技术风险与对策

| 风险 | 对策 |
|---|---|
| BFF 聚合读与写作事务争锁 | 聚合读全走只读连接（WAL 并发读已验证）；SSE 轮询限频 |
| stdlib HTTP 的静态服务性能 | 本地单用户场景足够；必要时 dist 打 zip 用 `zipfile` 内存映射（stdlib 方案） |
| CM6 中文排版细节（避头尾、标点悬挂） | 首版只做行高/栏宽/字体三件事，排版增强进 backlog |
| 前端类型与 91 工具 schema 漂移 | CI 脚本从 tooldefs.py 导出 JSON Schema 生成 TS 类型（`scripts/gen-api-types`） |
| Canvas 大图交互手感 | D2 先做 200 节点内流畅；>600 折叠策略兜底；不做物理引擎级动效 |
| 双进程写竞争（novel-web 与 novel-mcp-http 同时开） | 引导用户单进程模式（novel-web 内嵌 /mcp）；文档明示 SQLite busy_timeout 已兜底 |
