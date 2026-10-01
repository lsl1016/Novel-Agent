# Phase B 第一段报告:10 章短程排雷(2026-10-02)

> 目标:在投入 40 章长跑前暴露系统性卡点。结论:**无系统性阻塞**,已直接发起第二段(11-40 章)。
> 模型:planner/reviewer=glm-4.6(Anthropic 协议),writer/revision=glm-4.5-air。全部无人值守(`drive.py --auto-answer`)。

## 成果

- **10 章 / 19,613 字**全部经完整审校门提交,平均每章 1,961 字。
- 确定性审校 44/44 全 PASS;语义审校 1 次 BLOCK(第 5 章,semantic_narrative)触发一轮修订后收敛——**修订闭环首次实战验证**。
- 知识泄漏 BLOCK = 0;认知隔离全程有效(World Truth 未进正文)。
- 真实人工介入 = 0(planner 提问 7 次、计划被拦 1 次,全部 auto-answer/auto-retry 化解决,决策留档 10 条)。
- Writer 上下文 token:5,594 → 9,886,**第 6 章起趋平**(9696/9596/9773/9850/9886),整体斜率 424 由前 5 章爬升期拉高,后段斜率 ≈48/章——无失控迹象,待 40 章确认。
- declared_updates 稳定积累:每章线索 3-4、事件 2-6、角色状态 2-4、信念 1-3、偿付 1-3;情感债开 14/偿 14,节奏平衡。

## 排雷战果:抓出 5 类真实缺陷(61+ 单元测试均未覆盖)

| # | 缺陷 | 修复 |
|---|---|---|
| 1 | declared_updates 形状契约缺失:planner 自由格式(belief_updates 用 entity_key/change、events 纯字符串)提交时 KeyError | `chapter_plan_check` 全组形状校验(MALFORMED_DECLARED_UPDATE)+ planner prompt 形状契约;事务回滚保住正典(A0 验证) |
| 2 | author_questions 返回对象而非字符串,auto-answer 崩溃 | 源头归一化(service)+ helper 容错 |
| 3 | character_states 键名偏移(entity_key) | 别名归一化 + prompt 契约 |
| 4 | **V0.7 存量 bug:commit_chapter 列序错位**(正文落 arc 列、body 为空),metrics chars=0 暴露 | 修复 + 数据回位 + 列序回归测试 |
| 5 | threads.advance 对象列表 + due schedule 时 set() 崩 unhashable | 全路径归一化(dict→thread_key)+ 校验 + 决策带 traceback + drive 对 planner_failed 自动重试(≤3 次) |

防御体系分层生效的观察:形状偏移只发生在 prompt 未写明形状的组;prompt 写明契约后(belief_updates/events/character_states)第 2 章起零偏移。**"prompt 契约 + 校验拦截 + 归一化兜底"三层防线已收敛。**

## 校准项(已带入第二段)

1. writer 章长遵守弱(1,550-2,300 波动,目标 2,200)→ writer prompt 增加字数下限(≥目标 90%);
2. semantic_knowledge_leak WARN 10/11——抽样确认非误报:writer 倾向把弱线索写强("借师父之口几乎断言剑有自主意志"),reviewer 精准捕捉"逼近揭示强度"。保留 WARN 不阻塞,若 40 章持续偏高再收紧 writer 线索纪律;
3. 低频未定位:1 次 plan 生成 ok=False 且 errors 为空(auto-retry 兜住后续成功),drive 已加键级诊断,40 章复现时定位。

## 观察中(第二段重点)

- token 曲线第 6 章后的平台是否保持(核心 KPI);
- 谜团 3 开 0 解(窗口 50-140,正常)、t_lineage 沉睡 6 章、t_master_promise 13 个 stage 的活跃度分布;
- 里程碑 m1(12-20 章内门)与卷切换(20 章)处 planner/planning 的行为;
- 情感债净存量与 pressure 门(debt_age=200)何时首次触发。
