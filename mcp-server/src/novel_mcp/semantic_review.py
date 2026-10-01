from __future__ import annotations

import json
import os
import re
from typing import Any

from .llm_client import chat, chat_json, configured, parse_json_object  # noqa: F401  (re-export)

SEMANTIC_REVIEWER_TYPES = (
    'semantic_knowledge_leak',
    'semantic_character',
    'semantic_narrative',
    'semantic_pacing',
)


def semantic_reviewer_configured() -> bool:
    return configured('NOVEL_REVIEWER', 'NOVEL_WRITER')


def revision_model_configured() -> bool:
    return configured('NOVEL_REVISION', 'NOVEL_WRITER')


def _call_json_model(system_prompt: str, user_prompt: str, *, prefix: str, fallback_prefix: str | None = None,
                     model: str | None = None, temperature: float = 0.1, timeout: int = 240) -> tuple[dict[str, Any], str]:
    return chat_json(system_prompt, user_prompt, prefix=prefix, fallback_prefixes=fallback_prefix,
                     model=model, temperature=temperature, timeout=timeout)



def call_semantic_reviewer(payload: dict[str, Any], model: str | None = None, timeout: int = 240) -> tuple[dict[str, Any], str]:
    system = '''你是长篇小说的语义审稿器，而不是作者。你会看到作者层 World Truth、当前 Reader/POV Knowledge、ChapterPlan、人物状态、近期章节和待审正文。你的任务是发现确定性规则难以发现的语义问题。

必须分别输出四个 reviewer：semantic_knowledge_leak、semantic_character、semantic_narrative、semantic_pacing。

硬规则：
1. 绝不能建议把隐藏 World Truth 写进正文；只判断正文是否已经通过同义改写、身份暗示、因果断言、叙述视角等方式泄露了尚未合法 Reveal 的真相。
2. semantic_knowledge_leak：语义级秘密泄露、POV 无依据知道信息、叙述者把猜测写成事实。明确泄密用 BLOCK；仅接近答案但仍保留歧义用 WARN。
3. semantic_character：人物动机、价值观、关系、能力、语气是否无支撑突变。严重 OOC/状态矛盾用 BLOCK，轻微漂移用 WARN。
4. semantic_narrative：检查 ChapterPlan 是否真正落实；Clue 强度是否明显超出/低于计划；Reveal 是否越级；是否把长线 Mystery 一次解释过满；是否有更好的旧信息重解释空间。结构违约或 Reveal 越级可 BLOCK，其余通常 WARN。
5. semantic_pacing：检查信息密度、叙事停滞、线程过载、连续开坑不回收、高潮/过渡位置失衡。除非已经导致章节目标无法成立，否则只 WARN。
6. 只能引用待审正文中的短证据，不要在 finding 中复述任何 hidden_truth 的真实值。
7. 不得修改 Story Graph，不得创建事实，只返回审查结果。

严格返回 JSON：
{"reviews":[{"reviewer_type":"semantic_knowledge_leak","verdict":"PASS|WARN|BLOCK","score":0.0,"findings":[{"code":"...","message":"...","fact_key":"可选","evidence":"正文短句，可选","suggestion":"不泄密的修订建议，可选"}]}],"summary":"..."}
四个 reviewer 必须全部出现且只出现一次。score 越高越好。'''
    user = json.dumps(payload, ensure_ascii=False, indent=2)
    return _call_json_model(system, user, prefix='NOVEL_REVIEWER', fallback_prefix='NOVEL_WRITER', model=model,
                            temperature=float(os.environ.get('NOVEL_REVIEWER_TEMPERATURE', '0.05')), timeout=timeout)


def call_revision_model(payload: dict[str, Any], model: str | None = None, timeout: int = 300) -> tuple[str, str]:
    system = '''你是长篇小说修订 Writer。你只能修订当前 draft，不得改变已批准的 ChapterPlan、World Truth、长期线程目标或 declared_updates 的语义含义。

优先级：
1. 修复所有 BLOCK。
2. 修复不会损害章节意图的 WARN。
3. 对秘密泄露，只能增加歧义、改回 POV 可知范围、删除越权断言；绝不能把 reviewer 内部掌握的隐藏真相补进正文。
4. 对 OOC，恢复人物既有动机/语气/能力边界，不凭空添加新设定。
5. 对伏笔强度问题，按 ChapterPlan 的 clue strength / reveal intent 调节显隐程度。
6. 尽量保留原正文的有效场景、节奏和语言风格，避免整章推倒重写。
7. 只输出完整修订后章节正文，不输出解释、标题、Markdown 围栏或分析。'''
    req_payload_user = json.dumps(payload, ensure_ascii=False, indent=2)
    text, used_model = chat(system, req_payload_user, prefix='NOVEL_REVISION', fallback_prefixes='NOVEL_WRITER',
                            model=model, temperature=float(os.environ.get('NOVEL_REVISION_TEMPERATURE', '0.35')),
                            json_mode=False, timeout=timeout)
    text = (text or '').strip()
    if text.startswith('```'):
        text = re.sub(r'^```(?:\w+)?\s*', '', text)
        text = re.sub(r'\s*```$', '', text).strip()
    if not text:
        raise ValueError('empty revision')
    return text, used_model


def normalize_semantic_reviews(raw: dict[str, Any]) -> list[dict[str, Any]]:
    by_type: dict[str, dict[str, Any]] = {}
    for item in raw.get('reviews', []) if isinstance(raw.get('reviews'), list) else []:
        if not isinstance(item, dict):
            continue
        typ = str(item.get('reviewer_type') or '')
        if typ not in SEMANTIC_REVIEWER_TYPES or typ in by_type:
            continue
        verdict = str(item.get('verdict') or 'WARN').upper()
        if verdict not in {'PASS', 'WARN', 'BLOCK'}:
            verdict = 'WARN'
        try:
            score = float(item.get('score', 1.0 if verdict == 'PASS' else 0.7 if verdict == 'WARN' else 0.2))
        except Exception:
            score = 0.7
        findings = item.get('findings') if isinstance(item.get('findings'), list) else []
        by_type[typ] = {
            'reviewer_type': typ,
            'verdict': verdict,
            'score': max(0.0, min(1.0, score)),
            'findings': [x for x in findings if isinstance(x, dict)],
            'metadata': {},
        }
    for typ in SEMANTIC_REVIEWER_TYPES:
        if typ not in by_type:
            by_type[typ] = {
                'reviewer_type': typ,
                'verdict': 'WARN',
                'score': 0.5,
                'findings': [{'code': 'SEMANTIC_REVIEWER_OUTPUT_MISSING', 'message': f'model omitted {typ}'}],
                'metadata': {},
            }
    return [by_type[x] for x in SEMANTIC_REVIEWER_TYPES]


def redact_hidden_values(value: Any, hidden_truths: dict[str, Any]) -> Any:
    replacements: list[tuple[str, str]] = []
    for fact_key, truth in hidden_truths.items():
        if isinstance(truth, str) and len(truth) >= 2:
            replacements.append((truth, f'[REDACTED_WORLD_TRUTH:{fact_key}]'))
    def redact_text(s: str) -> str:
        for truth, repl in replacements:
            s = s.replace(truth, repl)
        return s
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact_hidden_values(x, hidden_truths) for x in value]
    if isinstance(value, dict):
        return {k: redact_hidden_values(v, hidden_truths) for k, v in value.items()}
    return value
