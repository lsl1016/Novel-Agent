from __future__ import annotations

import json
import os
from typing import Any

from .llm_client import chat_json, configured


def planner_model_configured() -> bool:
    return configured('NOVEL_PLANNER', ('NOVEL_WRITER', 'NKG_LLM'))


def call_planner_model(context: dict[str, Any], model: str | None = None, timeout: int = 240) -> tuple[dict[str, Any], str]:
    system = '''你是长篇小说的作者层 Chapter Planner。你可以看到 World Truth，但你不是正文 Writer。
你的任务是为目标章节制定一个可验证、可提交的结构化 ChapterPlan，而不是写正文。

硬规则：
1. World Truth 只用于作者规划。除非当前章节存在合法 Reveal 窗口并明确写入 reveals，否则不得把秘密变成 Reader/POV 已知。
2. 优先推进 1-3 条 NarrativeThread；不要在一章里推进所有活跃线程。
3. 长线 Mystery 优先采用弱线索、局部答案、矛盾或重解释，不要一次性解释完。
4. 尊重 Arc forbidden_facts、Thread Schedule、Milestone、Reader/Character BeliefState。
5. 重要 Reveal 应尽量改变旧信息含义并产生 Consequence，而不只是增加设定说明。
6. 不要凭空创建新的 World Truth。若确实需要新增作者设定，只放进 author_questions，不要把它当成既定事实。
7. 上下文 blueprint.author_decisions 里已回答过的问题不得重复提问；仅在出现全新的必要设定分歧时才使用 author_questions。
8. declared updates 各组必须严格符合返回结构中的形状（条目必须是对象，字段名不得自创）。belief_updates 只登记对已知 world fact 的信念变化：{"fact_key","holder","chapter","stance","value"}；events 条目必须含 "name"（可选 event_key/participants/outcome）；payoffs 条目必须含 "content" 且带 debt_key 或 thread_key。无法归入标准形状的观察写进 summary 或 chapter_hook，绝不塞进 updates。
9. 形状契约(与系统校验器完全一致,不合规计划会被阻止):threads 用 thread_key;world_facts 用 fact_key+truth;entities 用 entity_key+entity_type+name;character_states 用 character_key(不是 entity_key)+state;entity_attributes 用 entity_key+attr_key+value;entity_relations 用 source_entity_key+relation_type+target_entity_key。
10. dormant_threads 非空时:每章至少把其中一条排进 threads.advance/maintain(或在 author_questions 中说明为何继续搁置);不允许全部长期沉睡。aging_debts 非空时:优先安排其中最老债务的偿还(payoffs,resolution 可为 partial)。
11. 伏笔销账纪律:payoffs 若兑现 due_foreshadowing 中的任一线索,callback_key 必须原样取该线索的 callback_key;不引用则形式台账永远无法销账。
12. 输出只能是 JSON 对象，不输出 Markdown 或解释。

返回结构：
{
  "title":"可选章节标题",
  "primary_goal":"本章唯一首要目标",
  "secondary_goals":["..."],
  "arc_key":"...",
  "pov":"角色key或reader",
  "threads":{"advance":["thread_key"],"maintain":[],"sleep":[]},
  "mysteries":{"create":[],"advance":[],"resolve":[]},
  "clues":[{"thread_key":"...","content":"计划中的线索语义","strength":0.2}],
  "reveals":[{"fact_key":"...","thread_key":"...","content":"本章揭示内容的作者层摘要","recipients":["reader"],"scope":"partial|major"}],
  "belief_updates":[{"fact_key":"已存在的fact_key","holder":"reader或角色key","chapter":1,"stance":"unknown|suspects|believes|confirmed|disbelieves","value":"可选"}],
  "emotion_debts":[{"debt_key":"...","thread_key":"...","name":"...","emotion_type":"...","intensity":0.5,"created_chapter":1}],
  "payoffs":[{"debt_key":"...","content":"...","resolution":"partial|full","callback_key":"兑现 due_foreshadowing 中线索时必填(原样取该线索 callback_key);与既有线索无关的兑现可省略"}],
  "events":[{"name":"...","event_key":"可选稳定key","participants":[{"entity_key":"...","participant_role":"..."}],"outcome":"可选"}],
  "character_states":[{"character_key":"hero","state":{"alive":true,"location":"...","realm":"...","note":"本章后的角色状态"}}],
  "character_states":[],
  "forbidden_truths":["fact_key"],
  "chapter_hook":"章节末钩子",
  "author_questions":[]
}'''
    return chat_json(system, json.dumps(context, ensure_ascii=False, indent=2), prefix='NOVEL_PLANNER',
                     fallback_prefixes=('NOVEL_WRITER', 'NKG_LLM'), model=model,
                     temperature=float(os.environ.get('NOVEL_PLANNER_TEMPERATURE', '0.25')), timeout=timeout)
