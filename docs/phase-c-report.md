# Phase C 实施报告:一句话创建小说(2026-10-02)

> 设计稿 `docs/phase-c-design.md`(四段式生成 + 跨引用确定性校验器 + 有界修复回路 + 规模参数化)。
> 本文记录实现、验收与真模型冒烟结果。

## 一、交付内容(C1+C2 核心 + C3)

| 组件 | 位置 | 说明 |
|---|---|---|
| 跨引用校验器 | `mcp-server/src/novel_mcp/architecture_check.py` | 纯函数 `check(architecture, options, known)`;8 类 Error(XREF_THREAD/XREF_ARC/XREF_FACT/XREF_PROTAGONIST/WINDOW_CONTAIN/REVEAL_ORDER/DEBT_SEEDABLE/COVERAGE)+ 4 类 Warning;**同时接线进 `story_architect_apply`**——生成器与外部 agent 手写架构走同一道闸门,库内已有键经 `known` 豁免(增量 apply 不误报) |
| 四段式生成器 | `mcp-server/src/novel_mcp/architect_ai.py` | S1 蓝图/世界真相 → S2 实体层 → S3 叙事层 → S4 结构层;每段携带前序键注册表,段内即时校验+重试(≤3 次,网络/解析/校验错误都重试);S5 终检+修复回路(≤3 轮,只回喂出错分组);规模护栏公式(弧数/首弧长/线程数/揭示窗口按目标章数自适应) |
| Service 方法 | `NovelService.novel_architecture_generate(idea, options)` | 返回 architecture/validation/stages/assumptions/repair_rounds;**生成 ≠ 应用** |
| MCP 工具(第 92 个) | `tooldefs.py` + `auth.py` | `novel_architecture_generate`,planner/admin 白名单(writer/reviewer/controller 不可见——架构含世界真相) |
| CLI | `novel-story create-from-idea --db --idea [--target-chapters --genre --tone --heat --counter-expectation] [--apply] [--run N] [--json]` | 默认生成+校验+落盘 `story-data/<slug>/`(idea/architecture/validation/stages/*.json,手改 stages 可只重跑后段);`--apply` 显式过闸门;`--run N` 复用 drive 循环自动开跑 |
| 一键入口 | `./novel.sh new "创意" [目标章数] [跑到第N章]` | 第三参触发 --apply --run 全链路 |
| 模型路由 | `NOVEL_ARCHITECT_*` → 回退 `NOVEL_PLANNER_*` | env/llm.env 已加段;docs/client-configs.md 矩阵更新为五角色 |

## 二、测试(设计稿 §12)

- 校验器单测 8 项:悬空 thread/fact/arc/protagonist 引用、窗口越界 ×3、REVEAL_ORDER/DEBT_SEEDABLE/COVERAGE、弧衔接间隙、known 豁免、callback_key 剥除;
- 生成器离线测试 4 项(stub LLM):注册表传递、段内重试收敛(故意悬空→修复)、跨段错误走修复回路、**生成→dry-run→apply→story_get_state 全链路**;
- apply 升级回归:全套 **99/99 通过**(工具面 91→92,快照同步);
- 金种子 `scripts/stress/architecture.json` 0 error 通过(并顺手修正种子一处里程碑窗口越出所在弧的手写笔误——校验器价值的第一个实证)。

## 三、加固记录(真模型暴露)

首轮流烟因 `model did not return a JSON object` 失败——思考型模型偶发把输出烧在 thinking 上。按设计 §14 补齐两道防线:

1. `chat_json` 解析失败纳入重试(此前只重试网络错误);
2. 生成器段内调用兜异常(网络/解析/校验错误统一按段重试),修复轮调用同样兜底。

## 四、token 预算放宽(作者授权,2026-10-02)

作者确认配额充足并要求放宽:API `MAX_TOKENS` 16384→131072(实测端点接受);上下文预算 writer 12k→**56k** / planner 24k→**120k** / reviewer 20k→**104k**,编译器硬顶 64k→256k。40 章库实测:writer 完整上下文 23,237 tokens——**原 12k 天花板砍掉了一半相关材料**,放宽后前 ~100 章不再裁剪。

## 五、真模型冒烟(M3 验收)

- 题材 A(都市悬疑,目标 300 章):`./novel.sh new "记忆质检员…" 300 3` —— 结果见下
- 题材 B(硬科幻,目标 120 章):仅生成,验证非玄幻泛化 —— 结果见下

结果(2026-10-02,glm-4.5-air 架构生成 + glm-4.6 规划/审校 + glm-4.5-air 写作):

| 题材 | 书名 | 目标章数 | 生成轮次 | 校验 | 后续 |
|---|---|---|---|---|---|
| 都市悬疑(记忆质检员) | 《删除线之下》 | 300 | S4 第 3 次尝试通过,0 修复轮 | **0 error**(3 warning) | apply → 长跑 3 章全部提交(《噪音》2466 字/《0.3秒》2322 字/《遮蔽栏》3110 字),0 泄漏,3 个作者决策自动消化,导出 `story-data/novel/删除线之下.md` |
| 硬科幻(世代飞船) | 《缺页之海》 | 120 | S4 重试 + 1 轮修复(最优保留生效:12→5 错后修复收敛) | **0 error**(1 warning) | 仅生成,产物在 `story-data/story-20261002-153627/` |

生成质量抽样(《删除线之下》):4 条世界真相的揭示窗(90/120/150/210 章)与 7 条弧的 forbidden_facts 形成**严格的渐进解锁结构**(首弧禁示全部 4 条,揭示窗过后逐弧解除),8 条叙事线覆盖全部 5 种类型,规模公式(300 章→7 弧/8 线/19 里程碑)严格成立。**M3 退出条件"创意 → architecture → 首章 Run 全链路"达成。**

真模型暴露并修复的三个缺陷(冒烟的价值):

1. `_call` 误返回 `chat_json` 的 `(obj, model)` 元组 → 所有真实调用被当"非对象"丢弃,空架构 0 错误**假成功**——离线桩测试返回 dict 故未暴露;已修复,并加"空/缺核心组响亮失败"兜底;
2. 修复回路震荡恶化(模型修复时擅自改稳定键名,1 错→12 错):S4 段内与 S5 修复轮都改为**最优保留**(错误数只减不增,恶化即回滚),修复提示词加"稳定键不得改名/删除"硬规则;
3. 架构生成器用思考型 glm-4.6 时 thinking 烧光输出额度导致 JSON 恒截断——切换为直出 glm-4.5-air(单段 20-40 秒,比 4.6 的 3-7 分钟快一个量级);`chat_json` 解析失败纳入重试;生成全程 stderr 进度日志。

## 六、遗留与下一步

- interview 交互模式(设计 §4)未实现,当前 auto 模式假设记录在 `idea.json.assumptions`;
- 参考图模式注入(S3/S4 few-shot,设计 C2 可选项)未做;
- 导出脚本书名解析链修复(`planning_blueprint.payload_json.title` → `meta.title`,此前写死兜底书名导致多书导出互相覆盖,已恢复《青霜疑锋》40 章);
- S4(结构层)是唯一高频重试段(弧窗口算术),后续可把弧窗口改确定性预计算、模型只填目标/线程/禁示,进一步降低重试率。
