"""architecture.json 跨引用确定性校验器(Phase C,设计稿 §6)。

纯函数 ``check(architecture, options, known)`` → {'errors','warnings'}。
生成器(stages 局部校验 + 终检)与 ``story_architect_apply``(外部作者手写架构)
共用同一道闸门;``known`` 提供库内已有稳定键,避免增量 apply 误报悬空引用。

规则不改变 story_architect_apply 的确定性语义:所有规则只读 architecture 本身。
"""
from __future__ import annotations

from typing import Any

_GROUPS_STABLE_KEY = {
    'world_facts': 'fact_key', 'entities': 'entity_key', 'threads': 'thread_key',
    'mysteries': 'mystery_key', 'emotion_debts': 'debt_key', 'arcs': 'arc_key',
    'milestones': 'milestone_key', 'thread_schedule': 'schedule_key',
}


def _items(architecture: dict, group: str) -> list[dict]:
    vals = architecture.get(group) or []
    return [x for x in vals if isinstance(x, dict)] if isinstance(vals, list) else []


def _keys(architecture: dict, group: str, key: str, known: set[str] | None = None) -> set[str]:
    ks = {x.get(key) for x in _items(architecture, group) if x.get(key)}
    return ks | (known or set())


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def check(architecture: dict, options: dict | None = None, known: dict | None = None) -> dict:
    options = options or {}
    known = known or {}
    errors: list[dict] = []
    warnings: list[dict] = []

    threads = _keys(architecture, 'threads', 'thread_key', known.get('threads'))
    entities = _keys(architecture, 'entities', 'entity_key', known.get('entities'))
    facts = _keys(architecture, 'world_facts', 'fact_key', known.get('facts'))
    arcs = _keys(architecture, 'arcs', 'arc_key', known.get('arcs'))
    arc_rows = _items(architecture, 'arcs')
    thread_rows = {x.get('thread_key'): x for x in _items(architecture, 'threads')}
    fact_rows = {x.get('fact_key'): x for x in _items(architecture, 'world_facts')}

    # ---- XREF_THREAD ----
    for group, field in (('mysteries', 'thread_key'), ('emotion_debts', 'thread_key'),
                         ('thread_schedule', 'thread_key')):
        for x in _items(architecture, group):
            if x.get(field) and x[field] not in threads:
                errors.append({'code': 'XREF_THREAD', 'group': group, 'thread_key': x[field],
                               'message': f'{group}.{field} references undeclared thread {x[field]}'})
    for a in arc_rows:
        for tk in a.get('inherited_thread_keys') or []:
            if tk not in threads:
                errors.append({'code': 'XREF_THREAD', 'group': 'arcs', 'arc_key': a.get('arc_key'),
                               'thread_key': tk, 'message': f'arc inherits undeclared thread {tk}'})
    for m in _items(architecture, 'milestones'):
        for tk in m.get('thread_keys') or []:
            if tk not in threads:
                errors.append({'code': 'XREF_THREAD', 'group': 'milestones', 'milestone_key': m.get('milestone_key'),
                               'thread_key': tk, 'message': f'milestone references undeclared thread {tk}'})
    for l in _items(architecture, 'narrative_entity_links'):
        if l.get('narrative_type') == 'thread' and l.get('narrative_key') and l['narrative_key'] not in threads:
            errors.append({'code': 'XREF_THREAD', 'group': 'narrative_entity_links',
                           'narrative_key': l['narrative_key'],
                           'message': f'link references undeclared thread {l["narrative_key"]}'})

    # ---- XREF_ARC:里程碑挂弧 + 弧间衔接(≤3 章缓冲) ----
    for m in _items(architecture, 'milestones'):
        if m.get('arc_key') and m['arc_key'] not in arcs:
            errors.append({'code': 'XREF_ARC', 'group': 'milestones', 'milestone_key': m.get('milestone_key'),
                           'arc_key': m['arc_key'], 'message': f'milestone references undeclared arc {m["arc_key"]}'})
    ordered = sorted(arc_rows, key=lambda a: (_int(a.get('order_no')) or 0, _int(a.get('start_chapter')) or 0))
    if ordered:
        first = ordered[0]
        fs = _int(first.get('start_chapter'))
        if (_int(first.get('order_no')) or 0) <= 1 and fs is not None and fs != 1:
            errors.append({'code': 'XREF_ARC', 'group': 'arcs', 'arc_key': first.get('arc_key'),
                           'message': f'first arc must start at chapter 1, got {fs}'})
        for prev, cur in zip(ordered, ordered[1:]):
            pe, cs = _int(prev.get('target_end_chapter')), _int(cur.get('start_chapter'))
            if pe is None or cs is None:
                continue
            if not (pe + 1 <= cs <= pe + 4):
                errors.append({'code': 'XREF_ARC', 'group': 'arcs', 'arc_key': cur.get('arc_key'),
                               'message': f'arc starts at {cs} but previous arc {prev.get("arc_key")} ends at {pe} (gap/overlap > 3 chapters)'})

    # ---- XREF_FACT ----
    for a in arc_rows:
        for fk in a.get('forbidden_facts') or []:
            if fk not in facts:
                errors.append({'code': 'XREF_FACT', 'group': 'arcs', 'arc_key': a.get('arc_key'),
                               'fact_key': fk, 'message': f'forbidden_facts references undeclared fact {fk}'})
    for x in _items(architecture, 'identity_profiles'):
        if x.get('fact_key') and x['fact_key'] not in facts:
            errors.append({'code': 'XREF_FACT', 'group': 'identity_profiles', 'profile_key': x.get('profile_key'),
                           'fact_key': x['fact_key'], 'message': f'identity references undeclared fact {x["fact_key"]}'})

    # ---- XREF_PROTAGONIST ----
    bp = architecture.get('blueprint') or {}
    if isinstance(bp, dict) and bp.get('protagonist') and entities and bp['protagonist'] not in entities:
        errors.append({'code': 'XREF_PROTAGONIST', 'group': 'blueprint', 'protagonist': bp['protagonist'],
                       'message': f'blueprint.protagonist {bp["protagonist"]} is not a declared entity'})

    # ---- WINDOW_CONTAIN ----
    for m in _items(architecture, 'mysteries'):
        t = thread_rows.get(m.get('thread_key'))
        if not t:
            continue
        lo_t, hi_t = _int(t.get('target_min_chapter')), _int(t.get('target_max_chapter'))
        lo_m, hi_m = _int(m.get('target_min_chapter')), _int(m.get('target_max_chapter'))
        if None not in (lo_t, hi_t, lo_m, hi_m) and not (lo_t <= lo_m and hi_m <= hi_t):
            errors.append({'code': 'WINDOW_CONTAIN', 'group': 'mysteries', 'mystery_key': m.get('mystery_key'),
                           'message': f'mystery window [{lo_m},{hi_m}] not within thread window [{lo_t},{hi_t}]'})
    arc_window = {a.get('arc_key'): (_int(a.get('start_chapter')), _int(a.get('target_end_chapter'))) for a in arc_rows}
    for m in _items(architecture, 'milestones'):
        w = arc_window.get(m.get('arc_key'))
        lo_m, hi_m = _int(m.get('min_chapter')), _int(m.get('max_chapter'))
        if w and None not in w and lo_m is not None and hi_m is not None:
            if not (w[0] <= lo_m and hi_m <= w[1]):
                errors.append({'code': 'WINDOW_CONTAIN', 'group': 'milestones', 'milestone_key': m.get('milestone_key'),
                               'message': f'milestone window [{lo_m},{hi_m}] not within arc window [{w[0]},{w[1]}]'})
    if ordered:
        fa = ordered[0]
        fa_w = (_int(fa.get('start_chapter')), _int(fa.get('target_end_chapter')))
        if None not in fa_w:
            for s in _items(architecture, 'thread_schedule'):
                lo_s, hi_s = _int(s.get('min_chapter')), _int(s.get('max_chapter'))
                if lo_s is not None and hi_s is not None and not (fa_w[0] <= lo_s and hi_s <= fa_w[1]):
                    errors.append({'code': 'WINDOW_CONTAIN', 'group': 'thread_schedule', 'schedule_key': s.get('schedule_key'),
                                   'message': f'schedule window [{lo_s},{hi_s}] not within first arc window [{fa_w[0]},{fa_w[1]}]'})

    # ---- REVEAL_ORDER:forbidden 弧结束前不得安排揭示 ----
    for a in arc_rows:
        ae = _int(a.get('target_end_chapter'))
        if ae is None:
            continue
        for fk in a.get('forbidden_facts') or []:
            f = fact_rows.get(fk)
            if not f:
                continue
            rv = _int(f.get('reveal_after'))
            if rv is not None and rv <= ae:
                errors.append({'code': 'REVEAL_ORDER', 'group': 'arcs', 'fact_key': fk, 'arc_key': a.get('arc_key'),
                               'message': f'fact {fk} reveal_after {rv} must be after forbidden arc end {ae}'})

    # ---- DEBT_SEEDABLE:种子债必须能被首弧兑现 ----
    if ordered:
        fa_end = _int(ordered[0].get('target_end_chapter'))
        if fa_end is not None:
            for d in _items(architecture, 'emotion_debts'):
                c = _int(d.get('created_chapter'))
                if c is not None and c > fa_end:
                    errors.append({'code': 'DEBT_SEEDABLE', 'group': 'emotion_debts', 'debt_key': d.get('debt_key'),
                                   'message': f'debt created at ch{c} exceeds first arc end {fa_end}; seed debts must be payable in the first arc'})

    # ---- COVERAGE:骨架要排到目标章数的 90%(仅在给出目标时) ----
    t_target = _int((options or {}).get('target_total_chapters'))
    if t_target and arc_rows:
        max_end = max((_int(a.get('target_end_chapter')) or 0) for a in arc_rows)
        if max_end < 0.9 * t_target:
            errors.append({'code': 'COVERAGE', 'message': f'arcs only cover to ch{max_end}, target is {t_target} (need >= {round(0.9 * t_target)})'})

    # ---- Warnings ----
    book_len = t_target or (max((_int(a.get('target_end_chapter')) or 0) for a in arc_rows) if arc_rows else 0)
    if book_len:
        mystery_threads = {m.get('thread_key') for m in _items(architecture, 'mysteries')}
        for t in _items(architecture, 'threads'):
            lo_t, hi_t = _int(t.get('target_min_chapter')), _int(t.get('target_max_chapter'))
            if lo_t is not None and hi_t is not None and (hi_t - lo_t) > 0.5 * book_len and t.get('thread_key') not in mystery_threads:
                warnings.append({'code': 'MYSTERY_PER_MAINLINE', 'thread_key': t.get('thread_key'),
                                 'message': 'long-span mainline thread has no mystery attached'})
    if ordered:
        fa_end = _int(ordered[0].get('target_end_chapter')) or 0
        scheduled = {s.get('thread_key') for s in _items(architecture, 'thread_schedule')}
        for t in _items(architecture, 'threads'):
            intro = _int(t.get('introduced_chapter'))
            if intro is not None and intro <= fa_end and t.get('thread_key') not in scheduled:
                warnings.append({'code': 'SCHEDULE_DENSITY', 'thread_key': t.get('thread_key'),
                                 'message': f'thread introduced at ch{intro} has no schedule within first arc'})
    if not (options.get('tone') or bp.get('tone')):
        warnings.append({'code': 'TONE_MISSING', 'message': 'no tone specified in options or blueprint'})
    for s in _items(architecture, 'thread_schedule'):
        if s.get('callback_key'):
            s.pop('callback_key', None)
            warnings.append({'code': 'CLUE_CALLBACK', 'schedule_key': s.get('schedule_key'),
                             'message': 'callback_key is assigned automatically (stage_{id}) on insert; removed from architecture'})

    return {'errors': errors, 'warnings': warnings}
