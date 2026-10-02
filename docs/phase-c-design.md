# Phase C 设计稿：一句话创建小说（Story Architect 收尾）

> **实现状态(2026-10-02)**:C1+C2 核心 + C3 已实现(2026-10-02,见 phase-c-report.md):四段生成器/校验器/修复回路/CLI/一键入口/双题材真模型冒烟均达成;interview 交互模式与参考图注入为遗留可选项。开书向导 Web UI 已随 Phase D3 落地。

> 状态：设计稿（2026-10-02），待长跑 KPI 终报后进入实现。
> 对应总体规划第 8.2 节与第 15 节"阶段 C"，以及《现状评估与演进计划》第 7 节。
> 配套产品方案见 `docs/phase-c-product.md`（用户旅程/形态/指标）；本文专注系统实现。

## 1. 目标与范围

用户给一句创意，系统产出一套**可被现有 `story_architect_apply` 直接接受**的完整 `architecture.json`：

```text
"写一部百万字东方玄幻，核心是身份谜题 + 世界真相反转。"
  ↓  novel_architecture_generate（本设计新增）
蓝图 + 世界真相 + 实体图 + 身份档案 + 叙事线/谜团/情感债 + 篇章/里程碑/排期
  ↓  story_architect_apply --dry-run（已存在，确定性校验）
校验报告（0 error 才可应用）
  ↓  story_architect_apply（已存在）
权威故事状态（正典起点）
  ↓  novel_run_start(start_chapter=1)（已存在）
第一章自动开写
```

**做**：创意 → architecture JSON 的 LLM 生成环节 + 确定性校验闭环 + 三个入口（CLI / service / MCP 工具）。

**不做**：不生成正文（正文永远走写作运行时）；不改变 `story_architect_apply` 的确定性语义（生成物仍必须过同一道闸门）；默认不自动 apply（除非显式 `--apply`）；不做 UI（Phase D）。

## 2. 现状与差距

已有的（Phase C ~70% 的来源）：

| 已有资产 | 位置 | 说明 |
|---|---|---|
| 确定性应用 + dry-run 校验 | `service.py story_architect_apply` | 稳定键存在/唯一、`entity_graph.check`、实体引用存在性、弧继承 warning |
| 目标 JSON 金种子 | `scripts/stress/architecture.json` | 15 个分组的完整形状范例（青霜疑锋） |
| 形状契约式 JSON 生成 | `planner_ai.py` + `llm_client.chat_json` | prompt 契约 + 宽松归一化 + 有界重试，长跑已验证 |
| 作者决策预置 | `blueprint.author_decisions` | planner 提问的自动回答机制（`scripts/stress/common.py`） |
| 全链路末端 | `novel_run_start` | 新库 `start_chapter=1` 即可开跑（无已提交章节不冲突） |

缺的（本设计补齐）：

1. **生成器**：分阶段把一句创意展开成 15 个分组，且跨引用（entity_key / thread_key / fact_key / arc_key）全部可解析；
2. **跨引用校验器**：现有 `story_architect_apply` 只查实体引用和稳定键，**不查**叙事层引用（详见 §6）；
3. **规模参数化**："百万字"如何映射到弧数、线程数、揭示窗口；
4. **修复回路**：校验失败把结构化错误回喂模型，有界重试；
5. **入口**：CLI 子命令、service 方法、MCP 工具（planner/admin 白名单）。

## 3. 总体流程

```text
idea（一句话～一段话） + options（题材/目标章数/语气/热度…）
  ↓
[S0] 预处理：确定性解析 options；auto 模式下把未给参数记为"假设"
  ↓
[S1] 蓝图与世界真相        ← 输出：blueprint、world_facts（fact_key 登记）
  ↓
[S2] 实体层               ← 输入：S1 摘要 + fact_key 注册表
                              输出：entities、identity_profiles、entity_attributes、
                                    entity_relations、narrative 链接骨架（entity_key 注册表）
  ↓
[S3] 叙事层               ← 输入：S1+S2 摘要 + 双注册表
                              输出：threads、mysteries、emotion_debts、narrative_entity_links
  ↓
[S4] 结构层               ← 输入：全部前序摘要 + thread/fact 注册表 + 规模参数
                              输出：arcs、milestones、thread_schedule、replace_blueprint
  ↓
[S5] 确定性校验（§6 全规则） + 有界修复回路（≤3 轮，只回喂出错分组）
  ↓
产物落盘 story-data/<slug>/ + dry-run 报告
  ↓（可选 --apply）          ↓（可选 --run N）
story_architect_apply       novel_run_start(1) + drive 到第 N 章
```

**为什么分四段而不是一次生成**：金种子含 ~90 个对象、6 类跨引用。一次性生成大 JSON 时悬空引用是必然故障模式（长跑 planner 的 belief_updates 自由发挥教训同源）。分段让每段 payload 小、每段只新增一类键、每段输入携带前序键注册表，模型只需要"在给定键集合内选择"，不需要"记住自己发明过哪些键"。

## 4. 输入契约

```json
{
  "idea": "写一部百万字东方玄幻，核心是身份谜题 + 世界真相反转。",
  "options": {
    "genre": "东方玄幻",              // 缺省从 idea 推断，记为假设
    "target_total_chapters": 300,     // 规模主参数，见 §7
    "tone": null,                     // 语气关键词，可空
    "heat": "中",                     // 情感浓度 低/中/高 → 情感债密度
    "chapter_length_target": 2200,
    "counter_expectation": null,      // 反套路提示：要求避开该题材最俗的三件事
    "mode": "auto"                    // auto | interview
  }
}
```

`interview` 模式：S1 之前允许模型就 2-4 个高杠杆问题向用户提问（题材边界、主角类型、禁忌内容、结局倾向），答案写入 options；`auto` 模式不提问，所有推断记入 `blueprint.notes.assumptions[]`，apply 后作者可改。默认 `auto`（与长跑无人值守哲学一致）。

## 5. 分阶段生成契约

所有阶段走 `llm_client.chat_json`，复用 planner 的三层防线模式：**prompt 形状契约 + 确定性校验 + 宽松归一化**。模型路由见 §8。

| 阶段 | 输入要点 | 输出分组 | 形状契约要点（写进 prompt） |
|---|---|---|---|
| S1 蓝图/真相 | idea、options、规模参数 | blueprint、world_facts | 2-4 条 secret 真相；每条带 `reveal_after`（按 §7 窗口）；`hard_constraints` 至少 1 条"真相 X 不得早于第 N 章"；protagonist 用占位键 `hero`（S2 必须落位） |
| S2 实体层 | S1 摘要 + fact_key 注册表 | entities、identity_profiles、entity_attributes、entity_relations | 实体 8-15 个（按规模）；至少含 protagonist、1 师长/盟友、1 对手、2 势力、2-3 地点、1-2 关键物品；`hero` 必须存在；secret 属性/身份必须挂 `fact_key`（只能从注册表选） |
| S3 叙事层 | S1+S2 摘要 + entity_key 注册表 | threads、mysteries、emotion_debts、narrative_entity_links | 线程 5-10 条，至少 1 条 mystery 型主线 + 1 条 relationship 型；谜团必须挂已存在 thread；情感债 `created_chapter` ≤ 首弧长度（种子债必须能被首弧兑现）；链接的 entity_key 只能从注册表选 |
| S4 结构层 | 全部摘要 + thread/fact 注册表 + 规模公式 | arcs、milestones、thread_schedule、replace_blueprint | 弧覆盖到 `target_total_chapters`（末弧 `target_end_chapter` ≥ 0.9×目标）；每弧 2-4 里程碑、`exit_conditions` 非空、`inherited_thread_keys` 非空；`forbidden_facts` 只能引用 secret 真相键；排期窗口落在首弧内 |

每阶段产物立即过一遍**该阶段可判定的**校验规则（如 S3 出来即查 thread 引用），不合格就地重试该阶段（≤2 次），不拖到 S5 才发现。

## 6. 确定性校验器（新模块 `architecture_check.py`）

纯函数 `check(architecture, options) -> {errors, warnings}`。**同时接线到 `story_architect_apply`**（升级其现有校验），使外部 agent 手写的 architecture 也受同样约束——生成器与外部作者走同一道闸门。

现有 `story_architect_apply` 已覆盖：稳定键存在/唯一、`entity_graph.check`（类型/关系合法性）、`entity_aliases`/`narrative_entity_links`/`identity_profiles` 的 entity 引用、弧继承 warning。

新增规则：

**Error（阻断应用）**

| 规则 | 说明 |
|---|---|
| XREF_THREAD | `mysteries.thread_key`、`emotion_debts.thread_key`、`thread_schedule.thread_key`、`arcs.inherited_thread_keys`、`milestones.thread_keys`、`narrative_entity_links(thread).narrative_key` 必须指向已声明 thread |
| XREF_ARC | `milestones.arc_key` 必须指向已声明 arc；arcs 的 `start_chapter` 必须与前一弧 `target_end_chapter+1` 衔接（允许 ≤3 章缓冲，超出报错） |
| XREF_FACT | `arcs.forbidden_facts`、`world_facts.fact_key` 被 identity/alias/attribute/relation 引用的 `fact_key` 必须存在 |
| XREF_PROTAGONIST | `blueprint.protagonist` 必须指向已声明 entity |
| WINDOW_CONTAIN | 谜团目标窗 ⊆ 所属线程目标窗；里程碑窗 ⊆ 所属弧 `[start_chapter, target_end_chapter]`；排期窗 ⊆ 首弧 |
| REVEAL_ORDER | secret 真相的 `reveal_after` > 以其为 `forbidden_facts` 的弧的 `target_end_chapter`（弧内禁止揭示的真相不能安排在弧结束前揭示——这是硬约束自洽性） |
| DEBT_SEEDABLE | `emotion_debts.created_chapter` ≤ 首弧 `target_end_chapter` |
| COVERAGE | 末弧 `target_end_chapter` ≥ 0.9 × `target_total_chapters` |

**Warning（提示不阻断）**

| 规则 | 说明 |
|---|---|
| MYSTERY_PER_MAINLINE | 目标跨度 > 0.5×全书的长线程建议至少挂 1 个谜团 |
| SCHEDULE_DENSITY | 首弧内每条 `introduced_chapter` ≤ 首弧长度的线程应有 ≥1 条排期（否则首弧无处安放该线） |
| TONE_MISSING | options.tone 为空且 blueprint.tone 为空 |
| CLUE_CALLBACK | 排期 stage 落库后 callback_key 自动为 `stage_{id}`，无需生成器填写——若模型画蛇添足填了则剥除并 warning |

## 7. 规模参数化

以 `target_total_chapters`（T）为主参数的生成护栏（prompt 中以公式给出，校验器复核）：

| 项 | 公式 | 300 章示例 |
|---|---|---|
| 弧数 | `clamp(round(T/45), 4, 12)` | 7 弧 |
| 首弧长度 | `clamp(round(T*0.07), 12, 25)` | 21 章 |
| 叙事线 | `clamp(round(T/40), 5, 10)` | 8 条 |
| 谜团 | 每条长跨度线 1-2 个 | 5-8 个 |
| 里程碑 | 每弧 2-4 个 | ~20 个 |
| 核心真相揭示窗 | 终局真相 `reveal_after ≈ 0.6-0.85×T`；中期真相 `≈ 0.2-0.5×T` | 180-255 / 60-150 |
| `chapter_length_target` | 未指定时按题材 1800-2600 | — |

百万字 ≈ 450-500 章（2200 字/章），公式同样成立。**只承诺规划骨架到 T 章，不承诺生成 T 章正文**——正文推进永远是运行控制器的事。

## 8. 模型路由与环境变量

新增第四个角色变量组 `NOVEL_ARCHITECT_*`，回退链与现有模式一致：

```text
NOVEL_ARCHITECT_BASE_URL → NOVEL_PLANNER_BASE_URL → 全局缺省
NOVEL_ARCHITECT_API_KEY  → NOVEL_PLANNER_API_KEY
NOVEL_ARCHITECT_MODEL    → NOVEL_PLANNER_MODEL    （缺省同 glm-4.6 thinking）
NOVEL_ARCHITECT_MAX_TOKENS / _TIMEOUT 同理
```

架构生成是"作者侧"工作（看得见全部真相、做全局结构决策），语义上与 planner 同级，故回退到 planner 配置；`env/llm.env` 增加可选段（不配也能跑，直接用 planner 组）。`docs/client-configs.md` 模型矩阵同步加一行。

## 9. 入口设计

**Service 方法**（长跑路径等价物，进程内直调）：

```python
svc.novel_architecture_generate(
    idea='写一部百万字东方玄幻……',
    options={'target_total_chapters': 300, 'mode': 'auto'},
)   # → {architecture, validation, stages(各阶段耗时/token), assumptions}
```

**CLI**（对应 `novel-story init-story` / `apply-architecture` 的既有风格）：

```bash
novel-story create-from-idea \
  --db ../story-data/my-novel.db \
  --idea '写一部百万字东方玄幻，核心是身份谜题 + 世界真相反转。' \
  --target-chapters 300 \
  --out ../story-data/my-novel/architecture.json \
  --dry-run-report        # 默认：只生成+校验+落盘，不 apply
  # --apply               # 显式授权后过 story_architect_apply
  # --run 3               # apply 后自动 novel_run_start(1) 并推进 3 章（复用 drive 循环）
  # --interview           # 交互式追问模式
```

**MCP 工具** `novel_architecture_generate`（第 92 个工具）：入参 idea/options，出参同 service；白名单归 **planner + admin**（作者侧工具，writer/reviewer/controller 不可见）。外部 agent 的推荐用法仍是两步：`novel_architecture_generate` → 人工或 agent 审阅 diff → `story_architect_apply`。

`--run N` 全链路即第 15 节"一句话 → 第一章"演示路径：init → generate → apply → `novel_run_start(1)` → N 章。新库无已提交章节，与 run_controller 的"start 必须晚于最后正典"约束天然兼容。

## 10. 产物与溯源

每次生成落盘 `story-data/<slug>/`（slug 从标题拼音/首词派生）：

```text
story-data/my-novel/
  idea.json               # 原始输入 + options + 假设（auto 模式的推断记录）
  architecture.json       # 最终产物（可直接喂 apply-architecture --file）
  validation.json         # 最终校验报告 + 修复回路轮次记录
  stages/s1…s4.json       # 各阶段原始产物（可复现、可手改后重跑后段）
```

改稿友好：用户手改 `stages/s2.json` 后重跑 S3-S5 即可，不必从头再生成。不建新表——溯源靠文件，正典状态仍只在 SQLite。

## 11. HITL 边界

1. 生成 ≠ 应用：默认停在 dry-run 报告，`--apply` 是显式动作；
2. apply 后仍可走既有编辑工具逐项修正（architecture 只是种子，不是锁）；
3. interview 模式的提问上限 4 个，问题必须是"影响骨架的"（题材/主角/禁忌/结局倾向），不得问细节（细节是 planner 章节计划的 author_questions 的事，已有机制）；
4. `blueprint.author_decisions` 预置：S1 生成时同时写入 2-3 条种子决策（如"主角前期压制成长速度"），降低长跑中 planner 提问频率——复用 `answer_planner_questions` 机制。

## 12. 测试计划

| 层 | 内容 |
|---|---|
| 校验器单测 | 构造悬空 thread/fact/arc 引用、窗口越界、reveal 早于 forbidden 弧、覆盖率不足等用例，逐条断言 error/warning；金种子 `architecture.json` 必须 0 error 通过 |
| 生成器单测（stub LLM） | 注入固定四段 canned 输出，断言注册表传递、归一化、修复回路在 ≤3 轮内收敛（第 1 轮故意给悬空引用，第 2 轮修复） |
| apply 升级回归 | `story_architect_apply` 接入新校验后，既有 70 测试全绿 + 新增 XREF 用例 |
| 真模型冒烟 | 两个不同题材各生成一次（东方玄幻之外加科幻或都市悬疑，验证非玄幻泛化），dry-run 0 error，其中 1 个 apply 后跑 3 章无阻断 |
| 规模护栏 | T=100/300/500 三档，断言弧数/线程数/覆盖率公式成立 |

## 13. 里程碑

| 子阶段 | 内容 | 验收 |
|---|---|---|
| C1 核心闭环 | `architecture_check.py` + 四段生成器 + 修复回路 + service 方法 + CLI（无 --run） | §12 前两行全绿；真模型一次过 dry-run |
| C2 打磨 | interview 模式、author_decisions 预置、apply 校验升级合入、参考图模式注入（可选：从 reference-graph 取该题材叙事模式作为 S3/S4 的 few-shot 上下文） | 外部 agent 手写 architecture 也受同一校验；回归全绿 |
| C3 全链路演示 | `--run N` + 第二题材种子小说 3-5 章 + 文档（README 快速开始改为"一句话开书"） | 一条命令从创意到第 3 章正文落库 |

## 14. 风险与对策

| 风险 | 对策 |
|---|---|
| 模型发明注册表之外的键 | 分段 payload + 键注册表随输入下发 + 阶段内即时校验 + S5 有界修复 |
| 规模与骨架不匹配（说百万字只排出 60 章） | COVERAGE 硬校验 + §7 公式写进 prompt |
| 题材套路化/同质化 | `counter_expectation` 输入位 + prompt 要求"避开该题材最俗三件事"并入 hard_constraints |
| 真相揭示安排自相矛盾 | REVEAL_ORDER 硬校验（forbidden 弧与 reveal_after 的偏序关系） |
| JSON 解析失败/偷懒截断 | chat_json 既有重试 + 每阶段 payload 小（≤4k token 输出）+ MALFORMED 即重试该阶段 |
| 成本 | 单次生成 5-7 次调用、~40-60k token，相对写 300 章忽略不计 |

## 15. 与现有机制的对齐点

- 生成的 `thread_schedule` stage 落库后 callback_key 自动为 `stage_{id}`（Phase B 已实现），生成器不填、校验器剥除——伏笔"显式回收"约束从种子就成立；
- secret 真相走 dual-time 体系：`reveal_after` 是读者侧全局闸，per-holder 的 knowledge_time 留给正文演进，architecture 只需声明读者窗；
- 权限：新工具进 `auth.py` 的 PLANNER_TOOLS + admin；writer/reviewer 永远拿不到（架构含世界真相）；
- 文档落点：README 快速开始（C3 后改写）、`docs/agent-paths.md` 覆盖矩阵加一行、`docs/client-configs.md` 加 ARCHITECT 变量组。
