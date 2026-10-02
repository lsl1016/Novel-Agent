# Novel Agent V0.11 架构

系统有三条驱动路径(详见 `docs/agent-paths.md` 与 `docs/phase-d-web-tech.md`):外部 Agent 经 skill + MCP 逐工具驱动(下图左),浏览器 Web 工作台经 BFF 聚合读 + 动作/作业透传(下图右,与外部 Agent 共享同一服务端闸门),或无人值守长跑(drive.py / novel.sh)进程内直调 NovelService——三条路径共享同一状态与门禁,内置模型本身不接触工具,只接收编译好的上下文。开导演模式时,长跑在每章边界转为人工引导。

```text
LLM / Agent / IDE                浏览器(亮色工作台,九工作区 + 导演台)
        │                               │
        ▼                               ▼
long-novel-writer Skill          Novel Web BFF(静态 SPA + /api/v1 + SSE + 慢操作作业执行器)
        │                               │ 写动作透传 facade_call(同一闸门,支持 book 作用域)
        ▼                               ▼
lsl1016/mcp-server(可选网关) ──> Novel Agent MCP / HTTP Facade — 94 个工具
        │ tools/list / tools/call / 认证 / 审计 / 限流
        ▼
        ├─────────────────── 检索与上下文编译器 ──────────────────┐
        │                                                          │
        │  章节计划 → 锚点 → 图检索 → 角色过滤                      │
        │      → 章节快照 → 相关度排序 → token 预算                 │
        │      → 写作者(56k) / 规划器(120k,含真相) / 审校者(104k)   │
        │      → 规划器另注入:导演指令 / 伏笔销账台账 / 休眠与陈年债 │
        │                                                          │
        ├───────────────┬───────────────────┬───────────────────────┤
        ▼               ▼                   ▼                       ▼
    规划运行时      写作运行时          审校运行时             运行控制器
    蓝图            安全写作者          4 确定性 + 4 语义      导演位(steering_point /
    篇章 / 滚动窗口 版本化草稿          有界自动修订          plan_approval 决策位)
    章节计划             │                   │                断点续跑 / 报告
    一句话开书            │                   │                       │
    (四段生成+校验+修复)  └──────────┬────────┘                       │
                                   ▼                                │
                               提交闸门 ←────────────────────────────┘
                          chapter_finalize 唯一提交入口
                                   │
                                   ▼
                          规范故事图(SQLite,迁移制 schema v6)
                         ┌───────────┴───────────┐
                         ▼                       ▼
                     实体图 V2                 叙事图
                     世界模型                 叙事模型
                     身份/一等事件/断言        叙事线/谜团/信念
                     双时序披露/子图           线索/揭示/情感债/显式 callback
                         └───────────┬───────────┘
                                     │
                        context_snapshots / 决策 / 事件
                          审计 / 可解释性 / KPI

参考图(只读、独立)
    └─ 仅限结构层面的叙事模式元数据
```

## 隔离边界

1. **故事图 vs 参考图** — 参考数据永远不会自动成为新故事的正典(Canon)。
2. **世界真相(作者独有) vs 读者/视角(POV)知识** — 写作者上下文无法看到作者独有的真相;双时序披露按持有者各自的知识时刻解锁;viewer 读者角色在服务端裁剪真相载荷。
3. **规划 vs 草稿 vs 正典** — 未来意图与草稿在定稿(finalize)之前均为非正典;`chapter_commit` 已从工具面移除,提交唯一入口是过全部审校前置的 `chapter_finalize`。
4. **规划器 / 写作者 / 审校者上下文** — 三者以不同权限与预算独立编译;导演指令只进规划器,且计划生成后自动销账。
5. **运行控制器保持有界** — 检索与导演位不改变 HITL 或提交闸门的语义;压力闸门、目标达成、模型故障的停机语义不变。

## 里程碑实况

- Phase A0/A(可靠性地基 + 实体图 V2)✅;Phase B(M2,40 章无人值守长跑)✅ 见 `phase-b-final-report.md`;Phase C(M3,一句话开书)✅ 见 `phase-c-report.md`;Phase D(D1-D3 九工作区)✅ 见 `phase-d-web-tech.md`;V0.11 导演位 ✅ 见 `run-controller.md`。

各运行时细节:`context-compiler-runtime.md`、`entity-graph-runtime.md`、`planning-runtime.md`、`writing-runtime.md`、`semantic-review-runtime.md`、`run-controller.md`。
