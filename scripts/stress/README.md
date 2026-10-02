# Phase B 长跑写作与压测基建

日常用到的命令按使用频率排:**导出小说 → 发起/续跑长跑 → 看指标 → 单章冒烟**。所有脚本都从仓库根目录运行。

**导演模式(人工引导长跑)**:drive.py 面向无人值守;若要每章边界人工介入(输入指令/让模型提案走向/审核修改计划),经 Web 工作台运行中心以 `steering_mode`/`plan_review` 启动(见 `docs/run-controller.md` 导演位章节),或 MCP `novel_run_start` 携带同名参数后逐章 `novel_run_step` + 决策。

**一键入口**:仓库根目录的 `./novel.sh` 把下列常用操作收编为子命令(`start`/`stop`/`status`/`watch`/`log`/`export`/`book`/`metrics`/`smoke`,库不存在时自动 `--seed`,启动自动带思考捕获),详见根 `README.md`。本文件保留各脚本的完整参数说明。

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
| `watch.py` | 实时观察长跑:轮询事件流,打印章节启动/规划/草稿/审校/入库(只读,不影响运行中的长跑) |
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

## 实时观察长跑:watch.py 用法

长跑进行中,另开一个终端:

```bash
python3 scripts/stress/watch.py                              # 默认盯 stress.db,3 秒轮询
python3 scripts/stress/watch.py --interval 1 --snapback 10   # 1 秒轮询,启动回放最近 10 条事件
python3 scripts/stress/watch.py --db story-data/smoke.db     # 盯别的库
```

能看到的事件流(按发生顺序):

- `chapter started` 章节开工 → `planning ready` 规划就绪 → `draft v1/v2... 完成` 写作者交付/修订版落库 → `review ⚠️ WARN / ⛔ BLOCK` 语义审校判定 → `chapter committed 📖《标题》入库 N字` 提交闸门放行;
- `decision opened ⏸` = 规划器提请作者决策(自动应答中,通常是重大剧情节点的叙事提问);
- 事件时间戳若由 UTC 环境的进程写入,展示时自动 +8h 修正。

注意:写作者调用大模型期间(约 3-5 分钟)不会逐字流出——正文是在调用返回后整版落库的,watcher 看到的是**阶段级实时**,不是打字机效果。脚本只读数据库,随时开关无副作用。

### 看模型的"思考创作过程"

思考型模型(glm-4.6 的规划/审校)的 thinking 内容默认在客户端被丢弃;设置 `NOVEL_THINKING_LOG` 后会追加写入 JSONL,watcher 可实时打印:

```bash
# 1) 启动长跑时开启思考捕获(对以后新起的 run 生效):
NOVEL_THINKING_LOG=story-data/thinking.jsonl \
  nohup python3 scripts/stress/drive.py --db story-data/stress.db --auto-answer \
  --target-chapter 40 --report story-data/stress-metrics.json > story-data/drive.log 2>&1 &

# 2) 另开终端,事件流 + 思考流一起看:
python3 scripts/stress/watch.py --thinking story-data/thinking.jsonl
```

每条思考记录含 `ts / role / model / thinking / answer_preview`(答案预览截断 400 字,思考全文完整保留),显示如:

```
11:20:01  💭 planner 思考(76字):
            第32章规划:先核对上一章结尾——界墙开线的善后场景……
```

说明:①写作者 glm-4.5-air 是直出模型,没有思考块,它的"创作过程"= 编译给它的上下文(`context_snapshots.payload_json`)+ 各版草稿差异,本来就落库可查;②`NOVEL_THINKING_LOG` 未设置时零开销,不影响生产;③环境变量在进程启动时读取,跑到一半无法追加,需重启长跑(断点续跑,已提交章节无损)才生效。

另外,`drive.py` 已开启行缓冲,以后用 `nohup python3 scripts/stress/drive.py ... > story-data/drive.log 2>&1 &` 启动的长跑,可以直接 `tail -f story-data/drive.log` 看驱动层进度(`[progress]`/`[auto-answer]`/`[auto-retry]` 行)。

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
