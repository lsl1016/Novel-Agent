# Novel Agent V0.8 — A0 实施报告(可靠性地基)

> 对应《现状评估与演进计划》Phase A0 / 里程碑 M0。目标:在 Entity Graph V2(Phase A)动 schema 之前,先补齐提交可靠性、迁移框架、候选晋升闭环与仓储分层。

## 范围与变更

### 1. schema 迁移框架(新增 `schema.py`)

- 五处散落的模块 DDL(store/writing/planning/run_controller/context_compiler)收敛为单一有序迁移列表 `MIGRATIONS`。
- 版本号使用 SQLite 内建 `PRAGMA user_version`:每个迁移与版本号在**同一事务**中提交,避免半迁移状态。
- 迁移 1 = v0.7 基线(全部既有表,幂等:IF NOT EXISTS / INSERT OR IGNORE,兼容 user_version=0 的 v0.7 遗留库原地升级)。
- 迁移 2 = v0.8:`extraction_candidates` 增加 `resolution / resolved_at / promoted_target / review_note` 列与状态索引。
- 各模块 `__init__` 中的 `executescript` 全部移除,由 `StoryStore.__init__` 统一迁移。

### 2. 连接与事务语义集中(`store.py`)

- `connect()` 每连接设置 `PRAGMA foreign_keys=ON`、`busy_timeout=10000`;初始化时设置 `journal_mode=WAL`。
  **修复实测 bug:v0.7 声明的外键从未生效**(pragma 只作用于初始化连接),现已回归测试固化。
- 新增 `transaction()` 环境事务:事务期间所有 `connect()` 返回同一连接的"只联接"句柄(退出不提交不回滚),使跨仓储多次写入具备单事务原子性;普通连接句柄改为成功提交/失败回滚/退出关闭(顺带修复了连接泄漏)。
- 事务期间禁止慢操作(LLM 抽取已刻意移出事务,见下)。

### 3. chapter_commit 原子化 + 门禁收口(`service.py` / `tooldefs.py` / `server.py`)

- 提交门内部:计划校验 → 泄密预检 → **单事务(正典章节 + 计划标记 + declared_updates 应用)** → 事务外的 LLM 抽取与连续性复查。
  中途任何失败整体回滚,`chapters` 表不留半提交行(有 kill 场景回归测试)。
- **`chapter_commit` 从公开工具面移除**:正典提交唯一入口是 `chapter_finalize`(完整审校门)。skill、docs、tool_schemas、网关注册载荷全部同步。工具数 77 → **79**(-1 +3)。

### 4. 抽取候选晋升闭环(Mention → 正典的唯一显式路径)

三个新工具:

| 工具 | 说明 |
|---|---|
| `candidate_list` | 按章节/类型/状态列出候选(只读) |
| `candidate_promote` | 显式晋升为正典实体或 World Truth;强制落证据链(chapter、extractor、confidence、原文 evidence、promoted_via) |
| `candidate_reject` | 带理由拒绝,留审计 |

行为约束:候选状态机 `candidate → promoted/rejected` 单向;双重晋升报错;叙事节点类型(Mystery/Clue/Payoff 等)不冒充实体,指引使用既有作者工具;实体键默认 `ext_<type>_<slug>`、来源标记 `extraction_promote`,经 `entity_author_get` 可审计。这是方案 6.1.3 Assertion/Evidence 的最小落地,Phase A 将在其上演进为一等断言表。

### 5. 仓储层重构(新增 `repositories.py`)

- `WorldRepository`(world_facts+beliefs:真相清单、秘密清单、belief 快照、forbidden 计算——两处此前不一致的隐藏判定统一为"reader 或 holder 任一 confirmed 即合法可知")。
- `CanonRepository`(chapters+events+character_states:章节窗口、最新角色状态——消灭了三处重复的"最新状态"查询)。
- `CandidateRepository`(候选 CRUD 与状态迁移)。
- 编排层去内联 SQL:service/context_compiler/run_controller 中的跨聚合查询全部改走仓储或模块 DAO;service 删除死代码 `_relevant_entity_keys`。手写 SQL 保留在仓储内(设计决策:不上 ORM)。

## 验收结果(对照计划文档 A0 清单)

- [x] 旧库打开自动迁移,user_version 正确递增(v0.7 遗留库模拟测试:基线库 user_version=0 → 升级到最新且数据保留)
- [x] 提交中途失败(declared_updates 半批异常)→ chapters 表无残留、mysteries 无半批写入(kill -9 等价回滚由单事务保证)
- [x] 幽灵外键插入被拒绝(IntegrityError 回归测试固化)
- [x] 候选全链路:抽取写入 → list → promote(实体/世界真相双路径)→ `entity_author_get` 可见证据链 → 双晋升拒绝 → reject 审计
- [x] 工具 schema 对外兼容:76 个既有工具签名不变;chapter_commit 移除、3 个候选工具新增,tooldefs/server/tool_schemas/网关注册四方一致(79)
- [x] 测试:**52 / 52 passed**(46 原有全绿 + 6 个 A0 专项)
- [x] Registration payload 重新生成:79 工具、42 只读 / 37 写、`bizTag=novel-agent-v0.8`

## 同步更新的外围资产

- `skills/long-novel-writer/`(SKILL.md、references/tools.md)与 `dist/`(重新打包 skill.zip)
- `docs/`:README、tool-contracts、planning-runtime、run-controller、creation-state-protocol、mcp-gateway-tool-registration
- `registration/mcp-server-batch-create.json`(regen)、`mcp-server/tool_schemas.json`
- 版本号:pyproject / stdio serverInfo / http server_version → 0.8.0

## 遗留与后续

- 权限分层(5 类 App 白名单 + facade token 映射)按计划与 Phase B 并行,尚未实施;`entity_author_get` 的隔离仍依赖部署约定。
- `_body_secret_leak_check` 仍是字面量匹配、`foreshadowing_list_open` 的 `callback_key IS NULL` 配对偏松——按计划列入杂项清理。
- Canon 版本链(可回放)未动,属 Phase A 范畴。
