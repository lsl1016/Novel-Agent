# Novel Agent v0.7 — 检索与上下文编译器驱动的长篇小说运行时

Narrative-KG 现已成为一个面向长篇小说的**世界模型 + 叙事模型 + 规划 + 写作 + 语义审校 + 有界自动推进运行时**。

## 分层结构

- `skills/long-novel-writer/` — 创作纪律与工具使用工作流。
- `mcp-server/` — 覆盖叙事图、实体图(V2:身份档案/一等事件/断言/双时序披露/专业子图)、规划、写作者/审校者、作者规划器、运行控制器与抽取候选晋升的 **91 个 MCP 工具**。
- `story-data/` — 可写的正典故事数据库与运行状态。
- `reference-example/` — 只读的结构参考样例;绝不并入新故事的正典。
- `docs/entity-graph-runtime.md` — 实体图 / 世界模型作为一等公民的设计与用法。
- `docs/planning-runtime.md` — 蓝图 → 篇章 → 滚动规划 → 章节计划。
- `docs/writing-runtime.md` / `docs/semantic-review-runtime.md` — 安全写作者 → 审校 → 修订 → 定稿。
- `docs/run-controller.md` — 持久化的有界自动推进状态机。
- `docs/a0-implementation-report.md` — v0.8 A0:schema 迁移框架、原子化提交、仓储层与抽取候选晋升闭环。
- `docs/phase-a-v2-report.md` — v0.9 Entity Graph V2 核心:Identity/Role、一等 Event、Assertion/Evidence、因果追溯。
- `scripts/stress/README.md` — Phase B 长跑压测:模型端点配置(OpenAI/Anthropic 双协议)、单章冒烟、无人值守驱动与 KPI 采集。
- `docs/agent-paths.md` — 双路径架构与外部 Agent 接入:模型如何被调用、自动长跑 vs MCP 工具路径、三种接入用法与边界。
- `docs/client-configs.md` — MCP 客户端连接、模型端点矩阵与门面角色鉴权。

## V0.7 知识模型

```text
正典故事图
├── 实体图 / 世界模型
│   ├── 角色 / 阵营 / 地点
│   ├── 物品 / 神器 / 技能 / 境界
│   ├── 时间属性
│   ├── 时间关系
│   └── narrative_entity_links
└── 叙事图
    ├── 叙事线 / 谜团
    ├── 线索 / 伏笔 / 揭示 / 兑现
    ├── 情感债
    └── 信念状态
```

实体图回答**世界是什么**。叙事图回答**故事如何揭示它**。

秘密别名/属性/关系可绑定到 `WorldFact + BeliefState`。`entity_author_get` 能看到作者真相;写作者安全工具会自动过滤隐藏的世界关系。


## V0.7 检索与上下文编译器

V0.7 在故事图与模型之间加入了记忆检索层:

```text
章节计划
    ↓
上下文编译器
    ├── 实体图检索
    ├── 叙事图检索
    ├── 章节时间切片
    ├── 写作者/规划者/审校者可见性隔离
    ├── 确定性相关性排序
    └── token 预算打包
    ↓
角色专属上下文
```

推荐的运行时行为:

- 写作者:`writer_context_get` → 编译后的 12k 预算安全上下文。
- 规划者:`planner_context_get` → 编译后的作者上下文,内含结构参考模式。
- 审校者:语义审校会收到一份独立的、可感知作者真相的审校者快照。
- 调试/审计:`context_preview`、`context_snapshot_get`、`context_explain`。

参见 `docs/context-compiler-runtime.md`。

## 运行时

```text
作者意图 / 蓝图
        ↓
作者规划器(世界真相 + 作者实体图)
        ↓
已校验的章节计划
        ↓
安全写作者上下文
  ├── 读者 / 视角角色信念
  └── 可见性过滤后的实体图
        ↓
写作者 → 版本化草稿
        ↓
4 个确定性审校者 + 4 个语义审校者
        ↓
BLOCK → 有界修订循环
        ↓
chapter_finalize
        ↓
正典实体图 + 叙事图
        ↓
运行控制器 / 压力 / 人在回路(HITL) / 重新规划
```

## 快速开始

```bash
cd mcp-server
python -m pip install -e . --no-build-isolation

novel-story init-story \
  --db ../story-data/my-novel.db \
  --title 'My Novel' \
  --main-goal '第一阶段主线目标' \
  --current-arc '开篇'

novel-story apply-architecture \
  --db ../story-data/my-novel.db \
  --file ../examples-architecture.json \
  --dry-run

novel-story apply-architecture \
  --db ../story-data/my-novel.db \
  --file ../examples-architecture.json
```

`examples-architecture.json` 现已包含世界事实、实体、实体属性、实体关系、叙事↔实体链接、叙事线、谜团、情感债、篇章、里程碑与日程。

## 长跑写作与导出(推荐入口)

配置好模型端点(`env/llm.env`,见 `scripts/stress/README.md`)后,三条命令完成"写一本书 → 读正文 → 看指标":

```bash
# 发起/续跑长跑写作(首次带 --seed 载入种子架构;无人值守建议 --auto-answer):
python3 scripts/stress/drive.py --db story-data/stress.db --seed --auto-answer --target-chapter 40

# 随时把已提交章节导出为可读 Markdown(story-data/novel/<书名>.md):
python3 scripts/stress/export_novel.py

# 随时输出 KPI 指标(token 增长/BLOCK 率/线程沉睡等):
python3 scripts/stress/metrics.py --db story-data/stress.db
```

完整参数表、断点续跑、单章冒烟、审校意见回放等见 **`scripts/stress/README.md`**。实测约 8-9 分钟/章。

## 实体图检索

写作者安全读取:

```text
entity_search
entity_get
entity_context_get
entity_neighbors
entity_path_find
```

作者/完整读取:

```text
entity_author_get
```

世界模型变更:

```text
entity_upsert
entity_alias_add
entity_attribute_set
entity_relation_upsert
entity_relation_end
narrative_entity_link
entity_graph_check
entity_graph_import
```

参见 `docs/entity-graph-runtime.md`。

## 通用 MCP 网关注册

要将 Novel Agent 的全部 **91** 个 HTTP 工具注册到 `lsl1016/mcp-server`,参见:

- `docs/mcp-gateway-tool-registration.md`
- `registration/generate_mcp_server_registration.py`
- `registration/mcp-server-batch-create.json`

兼容服务器为网关流程暴露 `POST /api/agent/tools/call/{name}` 端点。

## 状态隔离

- 规划者与语义审校者可以查看作者真相。
- 写作者与修订写作者只会收到 `writer_context_get` 的安全上下文。
- 不得将 `entity_author_get` 授予仅负责正文写作的写作者应用。
- 规划、草稿、审校与运行状态都不是正典。
- 只有成功执行的 `chapter_finalize` 才会修改正典故事图;自 v0.8 起 `chapter_commit` 不再是公开工具,抽取结果只能经 `candidate_promote`(携带证据链)进入正典。
- 参考图保持只读,并与新小说相互独立。
