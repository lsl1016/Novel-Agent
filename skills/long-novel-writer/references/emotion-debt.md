# 情感债(Emotion Debt)

EmotionDebt(情感债)是对未来情感了结的持久承诺。它让旧事件在数十乃至数百章后仍能产生戏剧压力。

好的情感债类型包括:屈辱、感恩、复仇、承诺、离别、牺牲、背叛、误解、愧疚、失去以及未了的心愿。

## 创建

```json
// emotion_debt_create
{
  "debt_key": "debt_yun_chen_humiliation",
  "thread_key": "THREAD_RISE_ARC1",
  "name": "云澈受辱于萧家大殿",
  "emotion_type": "humiliation",
  "intensity": 0.8,
  "created_chapter": 12,
  "target_holder": "xiao_clan_leader",
  "notes": "当众被退婚羞辱;偿还时机应与主角境界跃升绑定"
}
```

- `debt_key` 用稳定键,不随表述变化;同一冲突不要重复开多笔债,优先复用并提高强度。
- `intensity` 如实记录(0-1)。高强度的情感债若一直未解决,应当产生可见的后果——它会被 `story_pressure_check` 的 `emotion_debt_overdue` 风险跟踪(默认 200 章未了结即过期)。
- `target_holder` 记录债务关系的对象,便于后续兑现时检查双方状态仍连续。

## 兑现方式

```json
// emotion_debt_resolve
{
  "debt_key": "debt_yun_chen_humiliation",
  "chapter": 187,
  "content": "云澈以天玄境重临萧家大殿,当众揭穿萧擎天勾结黑风寨的罪证",
  "resolution": "full",
  "consequence": "萧家彻底失势;云澈与萧岚的关系进入不可逆的敌对"
}
```

- `partial`:缓解压力,但保留底层的关系/冲突。适合长线债务的中段节拍(让读者尝到甜头但不彻底)。
- `full`:关闭这笔具体的情感债;`consequence` 必填——如果兑现改变了故事(关系、地位、阵营、未来冲突),把它显式写下来,它会随 `declared_updates` 进入正典。

当兑现与铺设形成镜像或转化关系时,它更有力量:同一地点、反转的权力关系、含义已变的重复语句、被兑现的承诺,或一个证明角色成长的选择。不要机械复制铺设场景。

## 章节计划中的使用

在 ChapterPlan / `declared_updates.payoffs` 中兑现一笔债:

```json
{"debt_key": "debt_yun_chen_humiliation", "content": "…", "resolution": "partial", "consequence": "…"}
```

注意:narrative 审校要求**计划中出现的 payoff 必须在草稿 `declared_updates.payoffs` 中显式声明**,否则 `PLANNED_PAYOFF_NOT_DECLARED` 会被 BLOCK。

## 反模式

- 开笔之后数十万字从不提及(休眠债会被 pressure 跟踪,但读者也忘了——先弱呼应再兑现);
- `partial` 无限拖延,从不给真正的了结;
- 兑现只清账、无后果:关系与世界纹丝不动,等于没写;
- 用新债掩盖旧债:同一对象上叠 5 笔同类型债而不解决任何一笔。
