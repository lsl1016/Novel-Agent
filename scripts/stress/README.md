# Phase B 长跑写作与压测基建

日常用到的命令按使用频率排:**导出小说 → 发起/续跑长跑 → 看指标 → 单章冒烟**。所有脚本都从仓库根目录运行。

## 快速开始(三条命令)

```bash
# 1) 从头开始写一部测试小说(首次需 --seed 载入种子架构,一直写到第 40 章):
python3 scripts/stress/drive.py --db story-data/stress.db --seed --auto-answer --target-chapter 40

# 2) 随时把已写章节导出成可读 Markdown:
python3 scripts/stress/export_novel.py

# 3) 随时看 KPI 指标:
python3 scripts/stress/metrics.py --db story-data/stress.db
```

## 组成

| 文件 | 用途 |
|---|---|
| `architecture.json` | 测试小说《青霜疑锋》种子架构:blueprint、3 条 World Truth(带合法 Reveal 窗口)、10 实体、身份档案、时序属性/关系、5 叙事线、3 谜团、3 情感债、2 卷、里程碑与线程调度 |
| `smoke.py` | 单章全链路冒烟:种子 → 真实模型规划 → 正文 → 确定性+语义审校 |
| `drive.py` | 无人值守长跑驱动:复用/续建 bounded run,循环 `novel_run_continue`,决策与异常自动处理,结束后自动生成指标 |
| `metrics.py` | KPI 采集:BLOCK 率、知识泄漏、修订轮数、人工介入、Writer token 增长斜率、线程沉睡、谜团积压、伏笔/情感债逾期 |
| `export_novel.py` | 把已提交章节导出为可读 Markdown(书名取自 blueprint.title) |
| `common.py` | 脚本共用:env 加载、planner 作者提问自动拍板 |

## 长跑写作:drive.py 用法

```bash
# 从头开始(首次):--seed 应用种子架构;--auto-answer 无人值守必备
python3 scripts/stress/drive.py --db story-data/stress.db --seed --auto-answer --target-chapter 40

# 断点续跑(不必带 --seed):自动复用活跃 run;若上一 run 已完成,自动从最后提交章之后新建 run
python3 scripts/stress/drive.py --db story-data/stress.db --auto-answer --target-chapter 40

# 只跑到第 10 章(短程排雷):
python3 scripts/stress/drive.py --db story-data/stress.db --seed --auto-answer --target-chapter 10

# 不用语义审校(更快/更省,只走确定性审校):
python3 scripts/stress/drive.py --db story-data/stress.db --auto-answer --target-chapter 40 --no-semantic

# 关闭压力硬停(默认开启:story pressure 超阈值即停等人):
python3 scripts/stress/drive.py --db story-data/stress.db --auto-answer --target-chapter 40 --no-pressure-stop
```

常用参数:

| 参数 | 默认 | 说明 |
|---|---|---|
| `--db` | `story-data/stress.db` | Story 数据库路径 |
| `--env` | `env/llm.env` | 模型端点配置文件 |
| `--seed` | 关 | 运行前应用 `architecture.json`(幂等,可重复) |
| `--target-chapter` | 40 | 写到第几章 |
| `--auto-answer` | 关 | planner 作者提问自动拍板进 `blueprint.author_decisions`;计划被拦/规划异常自动重试(连续 ≤3 次)。**无人值守必开**,不开则严格 HITL 停等人工 |
| `--max-chapters` | 50 | 单个 run 最多提交章数(有界自治) |
| `--max-steps` | 3 | 每次 continue 的章数 |
| `--max-revisions` | 3 | 每章最大自动修订轮数 |
| `--no-semantic` | — | 跳过语义审校(只走确定性 4 项) |
| `--no-pressure-stop` | — | 关闭剧情压力硬停 |
| `--report` | `<db同名>-metrics.json` | 结束时指标输出路径 |

退出码:`0` 完成或正常停;`1` 配置/种子错误;`2` 等待人工决策(`--auto-answer` 覆盖不了的类型,如压力超阈、连续 3 次计划被拦)。过夜跑建议 `nohup ... &` 或 tmux。

实测节奏(glm-4.6 规划/审校 + glm-4.5-air 写作):约 8-9 分钟/章。

## 导出小说:export_novel.py 用法

```bash
# 默认:导出 stress.db 的全部已提交章节到 story-data/novel/<书名>.md
python3 scripts/stress/export_novel.py

# 指定库与输出目录:
python3 scripts/stress/export_novel.py --db story-data/stress.db --out story-data/novel
```

输出为单个 Markdown:开头是字数统计与目录,每章含元信息(卷/POV/字数/提交时间/摘要)与正文。长跑进行中可随时重跑刷新快照。

想看某章的**历史草稿与审校意见**(而非已提交正文),查库即可:

```bash
sqlite3 story-data/stress.db "SELECT version,status,LENGTH(body) FROM chapter_drafts WHERE chapter=5"
sqlite3 story-data/stress.db "SELECT reviewer_type,verdict,findings_json FROM chapter_reviews WHERE chapter=5"
```

## 指标:metrics.py 用法

```bash
python3 scripts/stress/metrics.py --db story-data/stress.db --out story-data/stress-metrics.json
```

输出 JSON(同时打印到控制台),重点字段:

- `context_growth.tokens_per_chapter_slope`:明显为正 → 校准 Compiler 预算/检索权重
- `review.block_rate` 与 `knowledge_leak_blocks`:审稿门是否过松/过严
- `avg_revision_rounds` 是否逼近 max(收敛性)
- `threads.dormancy` / `mysteries.oldest_open_age`:长线线程是否被遗忘
- `human_interventions`:HITL 频次是否可控

## 单章冒烟:smoke.py 用法(改配置后建议先跑)

```bash
python3 scripts/stress/smoke.py --auto-answer          # 第 1 章全链路
python3 scripts/stress/smoke.py --auto-answer --chapter 3   # 指定章节(库已有种子时)
python3 scripts/stress/smoke.py --db story-data/smoke.db    # 用独立库,不动 stress.db
```

## 模型配置(env/llm.env)

已 gitignore,含密钥。当前分配:

- planner / semantic reviewer:`glm-4.6`(思考型;协议适配跳过 thinking 块,`*_MAX_TOKENS=16384` 给足思考+输出空间)
- writer / revision:`glm-4.5-air`(直出文本,长跑成本友好)

协议:auto(base URL 含 `/anthropic` 即走 Anthropic Message 协议);同一套配置兼容任意 OpenAI 兼容端点(改 BASE_URL 即可,无需改代码)。思考型模型响应慢,各角色 socket 超时经 `{PREFIX}_TIMEOUT` 调节(已配:planner 420s / writer 300s / reviewer 600s / revision 600s)。
