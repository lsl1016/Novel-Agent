from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any

from .store import jd, jl

ROLE_DEFAULT_TOKENS = {
    # 预算两轮放宽(2026-10-02,作者确认 token 配额充足、明确要求 4 倍):
    # writer 12k→56k / planner 24k→120k / reviewer 20k→104k。
    # 注意:更大的预算只意味着"少裁剪",检索相关度排序不变;百章以上长跑再评估质量曲线
    'writer': 56000,
    'planner': 120000,
    'reviewer': 104000,
}

ROLE_BUDGETS = {
    # 百分比总和为 1.00。上下文编译器将这些值视为各分区的软上限。
    'writer': {
        'plan': 0.10,
        'beliefs': 0.10,
        'entities': 0.22,
        'narrative': 0.20,
        'recent_canon': 0.20,
        'character_state': 0.08,
        'reference': 0.05,
        'safety': 0.05,
    },
    'planner': {
        'plan': 0.08,
        'world_truth': 0.14,
        'beliefs': 0.08,
        'entities': 0.20,
        'narrative': 0.20,
        'recent_canon': 0.10,
        'planning': 0.10,
        'reference': 0.10,
    },
    'reviewer': {
        'plan': 0.10,
        'world_truth': 0.12,
        'beliefs': 0.10,
        'entities': 0.22,
        'narrative': 0.18,
        'recent_canon': 0.12,
        'character_state': 0.08,
        'safety': 0.08,
    },
}


_CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]')


def estimate_tokens(value: Any) -> int:
    """确定性的、无依赖的 token 估算。

    中文字符保守地按每个字 1 个 token 计数;其余 UTF-8 JSON 文本
    按每 4 个字符约 1 个 token 近似。目标是稳定的预算控制,
    而非精确到分词器的计费预测。
    """
    raw = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(',', ':'), default=str)
    if not raw:
        return 0
    cjk = len(_CJK_RE.findall(raw))
    rest = max(0, len(raw) - cjk)
    return max(1, cjk + math.ceil(rest / 4))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _uniq(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in values:
        if not isinstance(x, str):
            continue
        x = x.strip()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class ContextCompiler:
    """面向长篇写作的检索与角色感知上下文编译器。

    它只负责编排各权威存储。除可选的不可变上下文快照审计记录外,
    它绝不修改故事图/叙事图状态。
    """

    def __init__(self, service: Any):
        self.service = service
        self.store = service.store
        self.entity_graph = service.entity_graph
        self.planning = service.planning
        self.reference = service.reference
        self.world = service.world
        self.canon = service.canon

    # ------------------------------------------------------------------
    # 锚点发现
    # ------------------------------------------------------------------
    def _plan(self, chapter: int) -> dict[str, Any] | None:
        return self.planning.chapter_plan_get(chapter)

    def _extract_entity_keys(self, plan: dict[str, Any] | None) -> list[str]:
        p = (plan or {}).get('plan') if isinstance(plan, dict) and 'plan' in plan else (plan or {})
        keys: list[str] = []

        def walk(value: Any, key_name: str = '') -> None:
            if isinstance(value, dict):
                for k, v in value.items():
                    kl = str(k).lower()
                    if kl in {'entity_key', 'source_entity_key', 'target_entity_key', 'character_key', 'location_key', 'item_key', 'artifact_key', 'faction_key'} and isinstance(v, str):
                        keys.append(v)
                    elif kl in {'entity_keys', 'characters', 'locations', 'items', 'artifacts', 'factions'} and isinstance(v, list):
                        for item in v:
                            if isinstance(item, str):
                                keys.append(item)
                            elif isinstance(item, dict) and isinstance(item.get('entity_key'), str):
                                keys.append(item['entity_key'])
                    else:
                        walk(v, kl)
            elif isinstance(value, list):
                for item in value:
                    walk(item, key_name)

        walk(p)
        return _uniq(keys)

    def _planned_threads(self, plan: dict[str, Any] | None) -> dict[str, list[str]]:
        p = (plan or {}).get('plan') if isinstance(plan, dict) and 'plan' in plan else (plan or {})
        block = p.get('threads') if isinstance(p, dict) else None
        if not isinstance(block, dict):
            return {'advance': [], 'maintain': [], 'sleep': []}
        return {k: _uniq(_as_list(block.get(k))) for k in ('advance', 'maintain', 'sleep')}

    def _planned_narrative_keys(self, plan: dict[str, Any] | None) -> dict[str, set[str]]:
        p = (plan or {}).get('plan') if isinstance(plan, dict) and 'plan' in plan else (plan or {})
        threads = self._planned_threads(plan)
        out: dict[str, set[str]] = {
            'thread': set(threads['advance'] + threads['maintain'] + threads['sleep']),
            'mystery': set(),
            'debt': set(),
            'fact': set(),
            'event': set(),
        }
        if not isinstance(p, dict):
            return out
        for x in _as_list(p.get('mysteries')):
            if isinstance(x, str): out['mystery'].add(x)
            elif isinstance(x, dict) and x.get('mystery_key'): out['mystery'].add(str(x['mystery_key']))
        for x in _as_list(p.get('events')):
            if isinstance(x, str): out['event'].add(x)
            elif isinstance(x, dict) and x.get('event_key'): out['event'].add(str(x['event_key']))
        for group in ('emotion_debts', 'payoffs'):
            for x in _as_list(p.get(group)):
                if isinstance(x, str): out['debt'].add(x)
                elif isinstance(x, dict) and x.get('debt_key'): out['debt'].add(str(x['debt_key']))
        for group in ('reveals', 'belief_updates'):
            for x in _as_list(p.get(group)):
                if isinstance(x, dict) and x.get('fact_key'): out['fact'].add(str(x['fact_key']))
        for x in _as_list(p.get('forbidden_truths')):
            if isinstance(x, str): out['fact'].add(x)
        return out

    def _pov_holder(self, chapter_plan: dict[str, Any] | None, holder: str | None) -> str:
        if holder:
            return holder
        if chapter_plan:
            plan = chapter_plan.get('plan') or {}
            return chapter_plan.get('pov_holder') or plan.get('pov') or 'reader'
        return 'reader'

    # ------------------------------------------------------------------
    # 实体检索
    # ------------------------------------------------------------------
    def entity_retrieve_relevant(self, chapter: int, role: str = 'writer', holder: str | None = None,
                                 plan: dict[str, Any] | None = None, limit: int = 30, max_depth: int = 2) -> dict[str, Any]:
        role = self._validate_role(role)
        cp = plan if plan is not None else self._plan(chapter)
        holder = self._pov_holder(cp, holder)
        snapshot_chapter = max(0, int(chapter) - 1)
        author = role in {'planner', 'reviewer'}
        limit = max(1, min(int(limit), 100))
        max_depth = max(1, min(int(max_depth), 2))

        scores: dict[str, dict[str, Any]] = {}

        def add(key: str, component: str, weight: float, reason: str) -> None:
            if not key or not self.entity_graph._exists(key):
                return
            row = scores.setdefault(key, {'score': 0.0, 'components': defaultdict(float), 'reasons': []})
            # 同一计分成分不重复累加;防止嘈杂的链接信号
            # 压过章节计划(ChapterPlan)的直接意图。
            if weight > row['components'][component]:
                row['score'] += weight - row['components'][component]
                row['components'][component] = weight
            if reason not in row['reasons']:
                row['reasons'].append(reason)

        direct = self._extract_entity_keys(cp)
        for k in direct:
            add(k, 'chapter_plan', 0.30, 'directly referenced by ChapterPlan')

        if holder != 'reader' and self.entity_graph._exists(holder):
            add(holder, 'pov', 0.20, 'current POV entity')

        narrative = self._planned_narrative_keys(cp)
        # 跨层叙事链接是一等检索锚点。
        for nt, keys in narrative.items():
            for nk in sorted(keys):
                query_types = [nt]
                if nt == 'debt': query_types += ['emotion_debt']
                if nt == 'fact': query_types += ['world_fact']
                for qtype in query_types:
                    for r in self.entity_graph.linked_entity_rows(qtype, nk, snapshot_chapter):
                        add(r['entity_key'], 'active_thread', 0.15, f'linked to planned {nt} {nk} ({r["role"]})')

        # 当前叙事义务:未决的谜团/情感债,以及到期的调度。
        due_threads = self.store.open_obligation_thread_keys(snapshot_chapter) | self.planning.schedule_due_thread_keys(chapter)
        for tk in sorted(due_threads):
            for r in self.entity_graph.linked_entity_rows('thread', tk, snapshot_chapter):
                add(r['entity_key'], 'obligation', 0.10, f'linked to unresolved/due narrative obligation {tk}')

        # 最近的实体回调/引入。
        for r in self.entity_graph.recent_link_rows(snapshot_chapter, 100):
            age = max(0, snapshot_chapter - int(r['mc'] or 0))
            weight = 0.10 if age <= 10 else (0.07 if age <= 50 else (0.03 if age <= 200 else 0.0))
            if weight:
                add(r['entity_key'], 'recency', weight, f'narrative callback {age} chapters ago')

        # 围绕视角/直接锚点的当前位置,使用按可见性过滤后的图。
        base_anchors = _uniq(([holder] if holder != 'reader' else []) + direct)
        for root in base_anchors[:15]:
            if not self.entity_graph._exists(root):
                continue
            graph = self.entity_graph.neighbors(root, snapshot_chapter, holder, author=author, depth=1, limit=80)
            for edge in graph.get('edges', []):
                src, dst = edge.get('source_entity_key'), edge.get('target_entity_key')
                other = dst if src == root else src
                if edge.get('relation_type') == 'LOCATED_IN':
                    add(other, 'location', 0.15, f'current location relation from {root}')
                else:
                    add(other, 'graph_neighbor', 0.06, f'visible 1-hop relation {edge.get("relation_type")} from {root}')

        # 额外的一跳刻意保持弱权重,且只沿可见边扩展。
        if max_depth > 1:
            first = sorted(scores, key=lambda k: (-scores[k]['score'], k))[:20]
            for root in first:
                graph = self.entity_graph.neighbors(root, snapshot_chapter, holder, author=author, depth=1, limit=40)
                for edge in graph.get('edges', []):
                    src, dst = edge.get('source_entity_key'), edge.get('target_entity_key')
                    other = dst if src == root else src
                    add(other, 'graph_2hop', 0.025, f'weak graph expansion from relevant entity {root}')

        # 回退机制让早期空章节仍然可用,而无需加载整张图。
        if not scores:
            for key in self.entity_graph.active_fallback_keys(snapshot_chapter, min(limit, 12)):
                add(key, 'fallback', 0.02, 'small active-entity fallback because no stronger anchor exists')

        ranked = sorted(scores.items(), key=lambda kv: (-min(1.0, kv[1]['score']), kv[0]))[:limit]
        items = []
        for key, meta in ranked:
            entity = self.entity_graph.get(key, snapshot_chapter, holder, author=author)
            if not entity:
                continue
            items.append({
                'entity_key': key,
                'score': round(min(1.0, meta['score']), 4),
                'reasons': meta['reasons'],
                'components': {k: round(v, 4) for k, v in sorted(meta['components'].items())},
                'entity': entity,
            })
        return {
            'chapter': chapter,
            'snapshot_chapter': snapshot_chapter,
            'role': role,
            'holder': holder,
            'author_view': author,
            'items': items,
            'scoring_model': 'deterministic-v0.7',
        }

    # ------------------------------------------------------------------
    # 叙事检索
    # ------------------------------------------------------------------
    @staticmethod
    def _stage_visible(stage: dict[str, Any], holder: str, author: bool) -> bool:
        if author:
            return True
        vis = stage.get('visibility') or 'reader'
        if vis == 'reader':
            return True
        if vis == 'character':
            return bool(stage.get('holder')) and stage.get('holder') == holder
        return False

    def narrative_retrieve_relevant(self, chapter: int, role: str = 'writer', holder: str | None = None,
                                    plan: dict[str, Any] | None = None, limit: int = 20) -> dict[str, Any]:
        role = self._validate_role(role)
        cp = plan if plan is not None else self._plan(chapter)
        holder = self._pov_holder(cp, holder)
        snapshot_chapter = max(0, int(chapter) - 1)
        author = role in {'planner', 'reviewer'}
        limit = max(1, min(int(limit), 100))
        planned = self._planned_threads(cp)
        scores: dict[str, dict[str, Any]] = {}

        def add(tk: str, component: str, weight: float, reason: str) -> None:
            if not tk or not self.store.thread_exists(tk):
                return
            row = scores.setdefault(tk, {'score': 0.0, 'components': defaultdict(float), 'reasons': []})
            if weight > row['components'][component]:
                row['score'] += weight - row['components'][component]
                row['components'][component] = weight
            if reason not in row['reasons']:
                row['reasons'].append(reason)

        for tk in planned['advance']:
            add(tk, 'chapter_plan', 0.40, 'ChapterPlan advances this thread')
        for tk in planned['maintain']:
            add(tk, 'chapter_plan', 0.30, 'ChapterPlan maintains this thread')
        for tk in planned['sleep']:
            add(tk, 'chapter_plan', 0.08, 'ChapterPlan explicitly keeps this thread dormant')

        for r in self.planning.schedule_due_rows(chapter):
            add(r['thread_key'], 'schedule', 0.25, f'due thread schedule {r["schedule_key"]}')
        open_m = self.store.open_mysteries(snapshot_chapter)
        debts = self.store.open_debts(snapshot_chapter)
        # 陈年/近期阈值按书长自适应:千章网文保持原量级(~200/~50),40章短书自动缩到 10/5,
        # 否则长线线程在短书里永远拿底分,被挤出上下文后规划器再也看不见(休眠死循环)
        old_age = max(10, snapshot_chapter // 4)
        recent_age = max(5, snapshot_chapter // 8)
        for m in open_m:
            age = snapshot_chapter - int(m['introduced_chapter'])
            weight = 0.15 if m['thread_key'] in set(planned['advance'] + planned['maintain']) else (0.10 if age >= old_age else 0.04)
            add(m['thread_key'], 'mystery', weight, f'open mystery {m["mystery_key"]}, age={age}')
        for d in debts:
            age = snapshot_chapter - int(d['created_chapter'])
            weight = 0.15 if d['thread_key'] in set(planned['advance'] + planned['maintain']) else (0.10 if age >= old_age else 0.04)
            add(d['thread_key'], 'emotion_debt', weight, f'open emotion debt {d["debt_key"]}, age={age}')
        for r in self.store.thread_stage_recency(snapshot_chapter, 100):
            age = snapshot_chapter - int(r['mc'] or 0)
            if age <= recent_age:
                add(r['thread_key'], 'recency', 0.05, f'thread callback {age} chapters ago')

        ranked = sorted(scores.items(), key=lambda kv: (-min(1.0, kv[1]['score']), kv[0]))[:limit]
        items = []
        selected = {tk for tk, _ in ranked}
        for tk, meta in ranked:
            thread = self.store.thread(tk)
            if not thread:
                continue
            stages = [s for s in thread.get('stages', []) if int(s.get('chapter') or 0) <= snapshot_chapter and self._stage_visible(s, holder, author)]
            compact_stages = stages[-5:]
            related_m = [m for m in open_m if m['thread_key'] == tk]
            related_d = [d for d in debts if d['thread_key'] == tk]
            items.append({
                'thread_key': tk,
                'name': thread.get('name'),
                'status': thread.get('status'),
                'target_min': thread.get('target_min'),
                'target_max': thread.get('target_max'),
                'score': round(min(1.0, meta['score']), 4),
                'reasons': meta['reasons'],
                'components': {k: round(v, 4) for k, v in sorted(meta['components'].items())},
                'recent_stages': compact_stages,
                'open_mysteries': related_m[:5],
                'open_emotion_debts': related_d[:5],
            })
        return {
            'chapter': chapter,
            'snapshot_chapter': snapshot_chapter,
            'role': role,
            'holder': holder,
            'items': items,
            'selected_thread_keys': sorted(selected),
            'scoring_model': 'deterministic-v0.7',
        }

    # ------------------------------------------------------------------
    # 编译 / 预算 / 审计
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_role(role: str) -> str:
        role = (role or '').strip().lower()
        if role not in ROLE_DEFAULT_TOKENS:
            raise ValueError('role must be writer, planner, or reviewer')
        return role

    def _belief_context(self, fact_keys: list[str], snapshot_chapter: int, holder: str, author: bool) -> list[dict[str, Any]]:
        out = []
        for fk in _uniq(fact_keys):
            snap = self.store.belief_snapshot(fk, snapshot_chapter)
            wt = snap.get('world_truth') or {}
            row = {
                'fact_key': fk,
                'reader': (snap.get('holders') or {}).get('reader', {'stance': 'unknown'}),
                'pov': (snap.get('holders') or {}).get(holder, {'stance': 'unknown'}),
                'holder': (snap.get('holders') or {}).get(holder, {'stance': 'unknown'}),
            }
            if author:
                row['world_truth'] = wt
            elif wt.get('secrecy') == 'public':
                row['public_truth'] = wt.get('value')
            out.append(row)
        return out

    def _forbidden_facts(self, snapshot_chapter: int, holder: str) -> list[dict[str, Any]]:
        return self.world.forbidden_facts(snapshot_chapter, holder)

    def _world_truth(self) -> list[dict[str, Any]]:
        return self.world.all_facts()

    def _recent_canon(self, chapter: int, recent_window: int, excerpt_chars: int, budget: int) -> list[dict[str, Any]]:
        rows = self.canon.recent_chapters_with_body(chapter, recent_window)
        items = []
        used = 0
        for r in rows:
            item = {k: r[k] for k in ('chapter', 'title', 'arc', 'pov', 'summary')}
            if excerpt_chars > 0 and r['body']:
                item['ending_excerpt'] = r['body'][-excerpt_chars:]
            cost = estimate_tokens(item)
            if items and used + cost > budget:
                break
            items.append(item); used += cost
        return list(reversed(items))

    def _character_states(self, keys: list[str], snapshot_chapter: int, budget: int) -> list[dict[str, Any]]:
        out = []
        used = 0
        for key in keys:
            d = self.canon.character_state(key, snapshot_chapter)
            if not d:
                continue
            cost = estimate_tokens(d)
            if out and used + cost > budget:
                break
            out.append(d); used += cost
        return out

    def _reference_need(self, plan: dict[str, Any] | None, narrative: dict[str, Any]) -> tuple[int, list[str]]:
        p = (plan or {}).get('plan') if isinstance(plan, dict) and 'plan' in plan else (plan or {})
        if not isinstance(p, dict):
            p = {}
        need: list[str] = []
        if _as_list(p.get('reveals')): need.append('partial_reveal')
        if _as_list(p.get('payoffs')): need.append('payoff')
        for x in _as_list(p.get('belief_updates')):
            if isinstance(x, dict) and x.get('stance') in {'disbelieves', 'confirmed'}:
                need.append('reversal')
        span = 0
        for item in narrative.get('items', []):
            age = max(0, int(narrative.get('snapshot_chapter', 0)) - int((item.get('recent_stages') or [{}])[0].get('chapter') or narrative.get('snapshot_chapter', 0)))
            span = max(span, age)
        if span >= 300:
            need.append('long_fuse')
        return (300 if 'long_fuse' in need else 0), _uniq(need)

    @staticmethod
    def _pack_ranked(items: list[dict[str, Any]], budget: int, key: str = 'score') -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        used = 0
        for item in sorted(items, key=lambda x: (-float(x.get(key) or 0), str(x.get('entity_key') or x.get('thread_key') or ''))):
            cost = estimate_tokens(item)
            if out and used + cost > budget:
                continue
            if not out and cost > budget:
                # 即使首条目的详细载荷本身就超出软上限,也要保留它。
                out.append(item)
                break
            out.append(item); used += cost
        return out

    def compile(self, chapter: int, role: str = 'writer', holder: str | None = None, max_tokens: int | None = None,
                recent_window: int | None = None, excerpt_chars: int | None = None, include_reference: bool | None = None,
                persist: bool = True) -> dict[str, Any]:
        role = self._validate_role(role)
        chapter = int(chapter)
        cp = self._plan(chapter)
        holder = self._pov_holder(cp, holder)
        snapshot_chapter = max(0, chapter - 1)
        max_tokens = int(max_tokens or ROLE_DEFAULT_TOKENS[role])
        if max_tokens < 1000 or max_tokens > 256000:
            raise ValueError('max_tokens must be between 1000 and 256000')
        recent_window = int(recent_window or (8 if role == 'writer' else 12))
        recent_window = max(1, min(recent_window, 50))
        excerpt_chars = int(500 if excerpt_chars is None and role == 'writer' else (0 if excerpt_chars is None else excerpt_chars))
        excerpt_chars = max(0, min(excerpt_chars, 2000))
        include_reference = (role == 'planner') if include_reference is None else bool(include_reference)
        author = role in {'planner', 'reviewer'}
        budgets = {k: max(80, int(max_tokens * v)) for k, v in ROLE_BUDGETS[role].items()}

        entities = self.entity_retrieve_relevant(chapter, role, holder, cp, limit=60 if author else 40, max_depth=2)
        narrative = self.narrative_retrieve_relevant(chapter, role, holder, cp, limit=40 if author else 25)
        packed_entities = self._pack_ranked(entities['items'], budgets.get('entities', 2000))
        packed_narrative = self._pack_ranked(narrative['items'], budgets.get('narrative', 2000))

        narrative_keys = self._planned_narrative_keys(cp)
        fact_keys = list(narrative_keys['fact'])
        # 实体关系/属性可能绑定秘密事实;需纳入其信念状态,但不得向写作者泄露取值。
        for item in packed_entities:
            ent = item.get('entity') or {}
            for a in (ent.get('attributes') or {}).values():
                if isinstance(a, dict) and a.get('fact_key'): fact_keys.append(a['fact_key'])
            for r in ent.get('relations') or []:
                if isinstance(r, dict) and r.get('fact_key'): fact_keys.append(r['fact_key'])
        beliefs = self._belief_context(fact_keys, snapshot_chapter, holder, author)
        beliefs = self._pack_ranked([{'score': 1.0, **x} for x in beliefs], budgets.get('beliefs', 1200))
        for x in beliefs: x.pop('score', None)

        top_entity_keys = [x['entity_key'] for x in packed_entities]
        chars = self._character_states(top_entity_keys, snapshot_chapter, budgets.get('character_state', 1000))
        recent = self._recent_canon(chapter, recent_window, excerpt_chars, budgets.get('recent_canon', 2000))
        arc = self.planning.arc_for_chapter(chapter)
        blueprint = self.planning.blueprint_get()

        reference_patterns: list[dict[str, Any]] = []
        if include_reference and self.reference:
            min_span, need = self._reference_need(cp, narrative)
            reference_patterns = self.reference.search('', min_span=min_span, need=need, limit=5)
            reference_patterns = self._pack_ranked([{'score': float(x.get('need_coverage') or 0), **x} for x in reference_patterns], budgets.get('reference', 1500))
            for x in reference_patterns: x.pop('score', None)

        plan_payload = cp
        context: dict[str, Any] = {
            'chapter_plan': plan_payload,
            'arc_plan': arc,
            'entity_context': {
                'chapter': snapshot_chapter,
                'view': 'author' if author else holder,
                'items': packed_entities,
            },
            'narrative_context': {
                'items': packed_narrative,
                'selected_thread_keys': [x['thread_key'] for x in packed_narrative],
            },
            'belief_context': beliefs,
            'character_states': chars,
            'recent_canon': recent,
            'reference_patterns': reference_patterns,
        }
        if role == 'writer':
            bp = blueprint.get('blueprint') or {}
            context['blueprint'] = {
                'version': blueprint.get('version'),
                'writing_constraints': {k: v for k, v in bp.items() if k in {'genre', 'tone', 'style', 'core_promise', 'protagonist', 'narrative_voice', 'chapter_length_target'}},
            }
            context['forbidden_fact_keys'] = self._forbidden_facts(snapshot_chapter, holder)
            context['safety_contract'] = 'Use only Reader/POV-visible facts. Hidden World Truth values and secret Entity Graph edges are intentionally absent.'
        else:
            context['blueprint'] = blueprint
            context['world_truth_ledger'] = self._world_truth()
            context['planning_pressure'] = self.service.planning_pressure_check(chapter)
            if role == 'planner':
                context['rolling_window'] = self.planning.get_window(chapter, 50)
                context['due_thread_schedule'] = self.planning.schedule_get(chapter=chapter, status='planned', limit=100)
                context['milestones'] = self.planning.milestone_list(status='planned', limit=200)
                # 伏笔销账台账(40 章实测 0/129 显式回收的根因修复):planner 必须能
                # 看到未回收线索及其 callback_key,规则 11 的"原样引用"才有落点。
                directive = self.service.chapter_directive_get(chapter)
                if directive:
                    context['author_directive'] = directive['directive']
                context['due_foreshadowing'] = [
                    {'thread_key': c['thread_key'], 'thread_name': c.get('thread_name'), 'chapter': c['chapter'],
                     'age': chapter - c['chapter'], 'callback_key': c.get('callback_key'),
                     'content': (c.get('content') or '')[:60]}
                    for c in self.store.open_clues(chapter - 1, 60)
                ]
            else:
                context['safety_contract'] = 'Reviewer may compare against Author Truth but must not echo hidden values into Writer-visible findings.'

        # 硬上限尽力而为:裁剪低优先级的尾部,同时保留章节计划、
        # 安全契约,以及(若存在)至少一个排名最高的实体/叙事线。
        def current_cost() -> int:
            return estimate_tokens({'chapter': chapter, 'role': role, 'holder': holder, 'context': context}) + 250
        trim_ops = [
            lambda: context.get('reference_patterns') and context['reference_patterns'].pop(),
            lambda: context.get('recent_canon') and context['recent_canon'].pop(0),
            lambda: context.get('character_states') and context['character_states'].pop(),
            lambda: len((context.get('narrative_context') or {}).get('items') or []) > 1 and context['narrative_context']['items'].pop(),
            lambda: len((context.get('entity_context') or {}).get('items') or []) > 1 and context['entity_context']['items'].pop(),
            lambda: context.get('belief_context') and context['belief_context'].pop(),
            lambda: len(context.get('world_truth_ledger') or []) > 1 and context['world_truth_ledger'].pop(),
        ]
        guard = 0
        while current_cost() > max_tokens and guard < 500:
            changed = False
            for op in trim_ops:
                before = current_cost()
                result = op()
                after = current_cost()
                if result is not False and after < before:
                    changed = True
                    break
            if not changed:
                break
            guard += 1
        if 'narrative_context' in context:
            context['narrative_context']['selected_thread_keys'] = [x.get('thread_key') for x in context['narrative_context'].get('items', []) if x.get('thread_key')]

        packed_entities=(context.get('entity_context') or {}).get('items') or []
        packed_narrative=(context.get('narrative_context') or {}).get('items') or []
        reference_patterns=context.get('reference_patterns') or []
        trace: list[dict[str, Any]] = []
        for x in packed_entities:
            trace.append({'item_key': f'entity:{x["entity_key"]}', 'kind': 'entity', 'score': x.get('score'), 'reasons': x.get('reasons') or []})
        for x in packed_narrative:
            trace.append({'item_key': f'thread:{x["thread_key"]}', 'kind': 'narrative_thread', 'score': x.get('score'), 'reasons': x.get('reasons') or []})
        for x in reference_patterns:
            trace.append({'item_key': f'reference:{x.get("reference_thread_key")}', 'kind': 'reference_pattern', 'score': x.get('need_coverage'), 'reasons': ['structural Reference Graph match selected by current narrative needs']})

        envelope = {
            'compiler_version': '0.10.0',
            'chapter': chapter,
            'snapshot_chapter': snapshot_chapter,
            'role': role,
            'holder': holder,
            'context': context,
            'retrieval_trace': trace,
        }
        estimated = estimate_tokens(envelope)
        section_tokens = {k: estimate_tokens(v) for k, v in context.items()}
        envelope['budget'] = {
            'max_tokens': max_tokens,
            'estimated_tokens': estimated,
            'over_budget': estimated > max_tokens,
            'section_soft_caps': budgets,
            'section_estimated_tokens': section_tokens,
            'estimator': 'cjk+chars/4 deterministic approximation',
        }
        digest = hashlib.sha256(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()[:16]
        snapshot_id = f'ctx_{chapter}_{role}_{digest}'
        envelope['snapshot_id'] = snapshot_id
        if persist:
            with self.store.connect() as db:
                db.execute('''INSERT INTO context_snapshots(snapshot_id,chapter,snapshot_chapter,role,holder,max_tokens,estimated_tokens,payload_json,trace_json)
                    VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(snapshot_id) DO NOTHING''',
                    (snapshot_id, chapter, snapshot_chapter, role, holder, max_tokens, estimated, jd(envelope), jd(trace)))
        return envelope

    def preview(self, chapter: int, role: str = 'writer', holder: str | None = None, max_tokens: int | None = None) -> dict[str, Any]:
        compiled = self.compile(chapter, role, holder, max_tokens=max_tokens, persist=False)
        ctx = compiled['context']
        return {
            'chapter': chapter,
            'role': compiled['role'],
            'holder': compiled['holder'],
            'max_tokens': compiled['budget']['max_tokens'],
            'estimated_tokens': compiled['budget']['estimated_tokens'],
            'over_budget': compiled['budget']['over_budget'],
            'counts': {
                'entities': len((ctx.get('entity_context') or {}).get('items') or []),
                'narrative_threads': len((ctx.get('narrative_context') or {}).get('items') or []),
                'beliefs': len(ctx.get('belief_context') or []),
                'character_states': len(ctx.get('character_states') or []),
                'recent_chapters': len(ctx.get('recent_canon') or []),
                'reference_patterns': len(ctx.get('reference_patterns') or []),
            },
            'top_entities': [
                {'entity_key': x.get('entity_key'), 'score': x.get('score'), 'reasons': x.get('reasons')}
                for x in ((ctx.get('entity_context') or {}).get('items') or [])[:10]
            ],
            'top_threads': [
                {'thread_key': x.get('thread_key'), 'score': x.get('score'), 'reasons': x.get('reasons')}
                for x in ((ctx.get('narrative_context') or {}).get('items') or [])[:10]
            ],
            'section_estimated_tokens': compiled['budget']['section_estimated_tokens'],
        }

    def snapshot_get(self, snapshot_id: str | None = None, chapter: int | None = None, role: str | None = None) -> dict[str, Any]:
        if snapshot_id:
            with self.store.connect() as db:
                r = db.execute('SELECT * FROM context_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
        else:
            if chapter is None or not role:
                raise ValueError('provide snapshot_id, or both chapter and role')
            with self.store.connect() as db:
                r = db.execute('SELECT * FROM context_snapshots WHERE chapter=? AND role=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (int(chapter), role)).fetchone()
        if not r:
            raise KeyError('context snapshot not found')
        payload = jl(r['payload_json'])
        return {'snapshot_id': r['snapshot_id'], 'created_at': r['created_at'], 'payload': payload}

    def explain(self, snapshot_id: str, item_key: str | None = None) -> dict[str, Any]:
        with self.store.connect() as db:
            r = db.execute('SELECT * FROM context_snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
        if not r:
            raise KeyError('context snapshot not found')
        trace = jl(r['trace_json']) or []
        if item_key:
            matches = [x for x in trace if x.get('item_key') == item_key]
            if not matches:
                raise KeyError(f'item_key not present in snapshot: {item_key}')
            return {'snapshot_id': snapshot_id, 'item_key': item_key, 'explanations': matches}
        return {'snapshot_id': snapshot_id, 'chapter': r['chapter'], 'role': r['role'], 'holder': r['holder'], 'trace': trace}
