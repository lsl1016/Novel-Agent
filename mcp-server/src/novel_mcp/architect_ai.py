"""Story Architect:一句创意 → architecture.json 的四段式生成器(Phase C 设计稿 §3-§7)。

S1 蓝图与世界真相 → S2 实体层 → S3 叙事层 → S4 结构层,每段携带前序键注册表,
段内即时校验(architecture_check 作用于已装配前缀)并就地重试(≤2 次);
S5 终检 + 有界修复回路(≤3 轮,只回喂出错分组)。

模型路由:NOVEL_ARCHITECT_* → NOVEL_PLANNER_* → NKG_LLM(作者侧全局结构决策,与 planner 同级)。
不做:正文生成(永远走写作运行时)、自动 apply(显式动作)。
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

from .architecture_check import check as check_architecture
from .llm_client import chat_json, configured

ENTITY_TYPE_ENUM = ('Character', 'Faction', 'Location', 'Item', 'Skill', 'Artifact',
                    'Organization', 'Bloodline', 'Race', 'Creature', 'Concept', 'Realm', 'Resource', 'Other')
STAGE_TYPE_ENUM = ('Clue', 'Payoff', 'Mystery', 'EmotionDebt', 'Reveal')
_THREAD_TYPES = ('mainline', 'mystery', 'relationship', 'conflict', 'worldbuilding')


def architect_model_configured() -> bool:
    return configured('NOVEL_ARCHITECT', ('NOVEL_PLANNER', 'NKG_LLM'))


def interview(idea: str, options: dict | None = None, call=None) -> dict:
    """Generate an idea-specific interview before architecture generation."""
    if not str(idea).strip():
        raise ValueError('请先输入故事创意')
    if call is None and not architect_model_configured():
        raise ValueError('尚未配置创作模型；可填写自主创作约束后继续')
    out = (call or _call)(
        '你是一位小说策划编辑。针对创意提出最多4个会改变故事走向的具体问题，'
        '覆盖主角动机、结局、叙事节奏与禁忌。不要重复用户已明确的信息。'
        '只返回 JSON: {"questions":[{"question":"中文问题","options":["选项一","选项二","选项三"]}]}。',
        json.dumps({'idea': idea, 'options': options or {}}, ensure_ascii=False))
    questions = []
    for q in out.get('questions', [])[:4]:
        if isinstance(q, dict) and str(q.get('question') or '').strip():
            questions.append({'question': str(q['question']),
                              'options': [str(x) for x in q.get('options', []) if isinstance(x, str)][:3]})
    if not questions:
        raise ValueError('模型未返回有效的访谈问题，请重试或自主填写约束')
    return {'questions': questions}


def scale_params(target_total_chapters: int) -> dict:
    """规模护栏公式(设计稿 §7),写进 prompt 并由校验器复核。"""
    t = max(20, int(target_total_chapters or 300))
    clamp = lambda v, lo, hi: max(lo, min(hi, v))
    return {
        'target_total_chapters': t,
        'arc_count': clamp(round(t / 45), 4, 12),
        'first_arc_length': clamp(round(t * 0.07), 12, 25),
        'thread_count': clamp(round(t / 40), 5, 10),
        'milestones_per_arc': '2-4',
        'final_reveal_window': [round(t * 0.6), round(t * 0.85)],
        'mid_reveal_window': [round(t * 0.2), round(t * 0.5)],
        'entity_count': '8-15',
        'note': f'只承诺规划骨架到第 {t} 章;正文推进永远由运行控制器负责',
    }


def _call(system: str, user: str) -> dict:
    """单次生成调用(测试注入点:monkeypatch 本函数即可全离线)。chat_json 返回 (obj, model),这里只留 obj。"""
    obj, _used = chat_json(system, user, prefix='NOVEL_ARCHITECT', fallback_prefixes=('NOVEL_PLANNER', 'NKG_LLM'),
                           temperature=float(os.environ.get('NOVEL_ARCHITECT_TEMPERATURE', '0.4')),
                           timeout=int(os.environ.get('NOVEL_ARCHITECT_TIMEOUT', '420')))
    return obj


def _clamp_notes(options: dict, sp: dict) -> str:
    return json.dumps({'options': options, 'scale': sp}, ensure_ascii=False)


def _s1_prompt() -> str:
    return '''你是长篇小说的 Story Architect(结构设计师)。用户给一句创意,你产出小说的蓝图与世界真相。
只输出 JSON 对象。返回结构(字段名不得自创):
{
 "blueprint":{"title":"书名","genre":"题材","tone":"语气关键词","core_promise":"一句话核心承诺","protagonist":"hero","narrative_voice":"第三人称限制视角/第一人称等","chapter_length_target":2200,"hard_constraints":["至少一条形如:真相X不得早于第N章揭示"]},
 "world_facts":[{"fact_key":"f_蛇形命名","truth":"作者独有真相内容","secrecy":"secret","reveal_after":整数,"notes":"为何它撑起核心反转"}],
 "assumptions":["auto模式下你对未给定参数的推断,逐条列出"],
 "author_decisions":[{"question":"...","answer":"..."}]
}
硬规则:
1. world_facts 2-4 条,全部 secrecy=secret;终局真相 reveal_after 落在 scale.final_reveal_window,中期真相落在 scale.mid_reveal_window。
2. hard_constraints 至少 1 条与真相揭示窗口绑定。
3. protagonist 固定为占位键 "hero"(后续阶段必须落位该实体)。
4. author_decisions 优先逐条保留 options.author_decisions 的作者访谈原答，不得改写或反转；仅对未回答的问题补充 2-3 条高杠杆创作假设，并逐条加入 assumptions 待作者确认。
5. 若用户给了 counter_expectation,把"避开该题材最俗的三件事"写进 hard_constraints。
6. options.hard_constraints 是作者已确认的约束，必须保留；被作者否决的假设及其替代要求必须落实，不能再次作为默认设定。'''


def _s2_prompt() -> str:
    return '''你是长篇小说的 Story Architect(实体层)。基于已定的蓝图与世界真相,产出实体图种子。
只输出 JSON 对象。返回结构:
{
 "entities":[{"entity_key":"蛇形键","entity_type":"枚举之一","name":"中文名","chapter":1,"description":"一句话"}],
 "identity_profiles":[{"profile_key":"...","entity_key":"已有实体","kind":"name|alias|role|title|incarnation|disguise|pseudonym","value":"...","secrecy":"secret|public","fact_key":"仅secret时必填,从真相注册表选","start_chapter":1}],
 "entity_attributes":[{"entity_key":"已有实体","attr_key":"蛇形键","value":"...","chapter":1}],
 "entity_relations":[{"source_entity_key":"已有实体","relation_type":"大写蛇形","target_entity_key":"已有实体","start_chapter":1}]
}
硬规则:
1. entities 按规模参数给 8-15 个;必须含 hero(主角);至少 1 师长/盟友、1 对手、2 势力、2-3 地点、1-2 关键物品。
2. entity_type 只能取:''' + '|'.join(ENTITY_TYPE_ENUM) + '''。
3. secret 的 identity_profiles 必须挂 fact_key,且只能从输入的真相注册表中选。
4. 所有 entity_key 引用必须来自本次输出声明的 entities(或注册表已有);关系建议用 OWNS/HELD_BY/MASTER_OF/TAUGHT_BY/LOCATED_IN/PART_OF/ALLIED_WITH/OPPOSES_TO 等大写蛇形。'''


def _s3_prompt() -> str:
    return '''你是长篇小说的 Story Architect(叙事层)。基于蓝图/真相/实体,产出叙事线、谜团、情感债与链接。
只输出 JSON 对象。返回结构:
{
 "threads":[{"thread_key":"t_蛇形","name":"...","thread_type":"mainline|mystery|relationship|conflict|worldbuilding","introduced_chapter":1,"target_min_chapter":1,"target_max_chapter":整数,"main_goal":"一句话"}],
 "mysteries":[{"mystery_key":"m_蛇形","name":"...","thread_key":"已有thread","introduced_chapter":1,"target_min_chapter":整数,"target_max_chapter":整数}],
 "emotion_debts":[{"debt_key":"d_蛇形","thread_key":"已有thread","name":"...","emotion_type":"...","intensity":0.5,"created_chapter":整数}],
 "narrative_entity_links":[{"narrative_type":"thread","narrative_key":"已有thread","entity_key":"已有实体","role":"protagonist|ally|antagonist|setting|object","chapter":1}]
}
硬规则:
1. threads 按规模参数给条数;至少 1 条 mystery 型主线 + 1 条 relationship 型;introduced_chapter ≤ 首弧长度。
2. 谜团必须挂已声明 thread,且其目标窗口 ⊆ 所属线程目标窗口;长跨度主线至少 1 个谜团。
3. 情感债 created_chapter ≤ 首弧长度(种子债必须能被首弧兑现),强度 0.3-0.7。
4. narrative_key/entity_key 只能从输入注册表或本次声明的 threads 中选。'''


def _s4_prompt() -> str:
    return '''你是长篇小说的 Story Architect(结构层)。基于全部前序产物,产出弧/里程碑/排期。
只输出 JSON 对象。返回结构:
{
 "arcs":[{"arc_key":"arc_蛇形","name":"...","order_no":从1起,"start_chapter":1,"target_end_chapter":整数,"primary_goal":"...","surface_conflict":"...","forbidden_facts":["仅secret真相键,可空"],"inherited_thread_keys":["已有thread"],"exit_conditions":["非空,1-3条"]}],
 "milestones":[{"milestone_key":"ms_蛇形","arc_key":"已有arc","name":"...","min_chapter":整数,"max_chapter":整数,"thread_keys":["已有thread"]}],
 "thread_schedule":[{"schedule_key":"sch_蛇形","thread_key":"已有thread","stage_type":"Clue|Payoff|Mystery|EmotionDebt|Reveal","min_chapter":整数,"max_chapter":整数,"purpose":"一句话"}],
 "replace_blueprint": false
}
硬规则:
1. 弧数与首弧长度严格按规模参数;弧按 order_no 无缝衔接(后一弧 start = 前一弧 end+1);末弧 target_end_chapter ≥ 0.9×目标章数。
2. 每弧 inherited_thread_keys 非空(新卷必须继承旧线);forbidden_facts 的真相 reveal_after 必须晚于该弧结束。
3. 每弧 2-4 个里程碑,窗口 ⊆ 所属弧窗口;排期窗口 ⊆ 首弧窗口,且不得填 callback_key(落库时自动分配)。
4. 所有 thread/fact/arc 引用只能从注册表选。'''


_STAGES = (
    ('s1', _s1_prompt, ('blueprint', 'world_facts')),
    ('s2', _s2_prompt, ('entities', 'identity_profiles', 'entity_attributes', 'entity_relations')),
    ('s3', _s3_prompt, ('threads', 'mysteries', 'emotion_debts', 'narrative_entity_links')),
    ('s4', _s4_prompt, ('arcs', 'milestones', 'thread_schedule', 'replace_blueprint')),
)

_INT_FIELDS = {
    'world_facts': ('reveal_after',), 'entities': ('chapter',), 'identity_profiles': ('start_chapter',),
    'entity_attributes': ('chapter',), 'entity_relations': ('start_chapter',), 'threads': ('introduced_chapter', 'target_min_chapter', 'target_max_chapter'),
    'mysteries': ('introduced_chapter', 'target_min_chapter', 'target_max_chapter'),
    'emotion_debts': ('created_chapter',), 'arcs': ('order_no', 'start_chapter', 'target_end_chapter'),
    'milestones': ('min_chapter', 'max_chapter'), 'thread_schedule': ('min_chapter', 'max_chapter'),
    'narrative_entity_links': ('chapter',),
}


def _normalize(arch: dict) -> dict:
    """宽松归一化:分组确保数组、整数字段强转、剥除 None 值键。"""
    out = dict(arch)
    for group, fields in _INT_FIELDS.items():
        rows = out.get(group)
        if not isinstance(rows, list):
            continue
        fixed = []
        for x in rows:
            if not isinstance(x, dict):
                continue
            for f in fields:
                if x.get(f) is not None:
                    try:
                        x[f] = int(x[f])
                    except (TypeError, ValueError):
                        x.pop(f, None)
            fixed.append(x)
        out[group] = fixed
    return out


def _relevant_errors(errors: list, groups: tuple) -> list:
    return [e for e in errors if e.get('group') in groups or not e.get('group')]


def generate(idea: str, options: dict | None = None, call: Callable[[str, str], dict] | None = None,
             options_for_check: dict | None = None) -> dict:
    """一句创意 → 完整 architecture(含修复回路)。返回 {architecture, validation, stages, assumptions, repair_rounds}。"""
    call = call or _call
    options = dict(options or {})
    options.setdefault('mode', 'auto')
    sp = scale_params(options.get('target_total_chapters'))
    check_opts = dict(options_for_check or options)
    check_opts.setdefault('target_total_chapters', sp['target_total_chapters'])

    summary: dict[str, Any] = {'idea': idea}
    arch: dict[str, Any] = {}
    stages: dict[str, Any] = {}
    assumptions: list = []

    import sys as _sys
    import time as _time

    def _progress(msg: str) -> None:
        # 生成一部长架构要多次思考型模型调用,静默十几分钟像卡死;stderr 即时报进度
        print(f'[architect] {msg}', file=_sys.stderr, flush=True)

    for sid, prompt_fn, groups in _STAGES:
        _t0 = _time.time()
        stage_input = {'task_summary': summary, 'key_registries': {
            'fact_keys': [x.get('fact_key') for x in arch.get('world_facts', [])],
            'entity_keys': [x.get('entity_key') for x in arch.get('entities', [])],
            'thread_keys': [x.get('thread_key') for x in arch.get('threads', [])],
            'arc_keys': [x.get('arc_key') for x in arch.get('arcs', [])],
        }}
        user = _clamp_notes(options, sp) + '\n' + json.dumps(stage_input, ensure_ascii=False)
        last_errors: list = []
        best_groups: dict | None = None   # 最优保留:错误数只减不增,重试恶化即回滚(防震荡)
        best_count: int | None = None
        for attempt in range(4):  # 段内 ≤3 次重试(网络/解析失败/校验错误都算)
            try:
                out = call(prompt_fn(), user if attempt == 0 else
                           user + '\n上一轮输出存在以下错误,请修正后完整重发:\n' + json.dumps(last_errors, ensure_ascii=False))
            except Exception as exc:  # 思考型模型偶发把 max_tokens 烧在 thinking 上,重试即可恢复
                last_errors = [{'message': f'stage call failed: {str(exc)[:200]}'}]
                continue
            if not isinstance(out, dict):
                last_errors = [{'message': f'输出不是 JSON 对象({type(out).__name__})'}]
                _progress(f'{sid} 第 {attempt + 1} 次尝试返回非对象({type(out).__name__}),重试')
                continue
            stages[sid] = out
            for g in groups:
                if out.get(g) is not None:
                    arch[g] = out[g]
            arch = _normalize(arch)
            if sid == 's1':
                assumptions = [a for a in (out.get('assumptions') or []) if isinstance(a, str)]
                for d in out.get('author_decisions') or []:
                    bp = arch.setdefault('blueprint', {})
                    if isinstance(bp, dict) and isinstance(d, dict) and d.get('question') and d.get('answer'):
                        ads = bp.setdefault('author_decisions', [])
                        if not any(x.get('question') == d['question'] for x in ads if isinstance(x, dict)):
                            ads.append({'question': d['question'], 'answer': d['answer']})
                summary['blueprint'] = {k: v for k, v in (arch.get('blueprint') or {}).items() if k != 'author_decisions'}
                summary['world_facts'] = arch.get('world_facts', [])
            elif sid == 's2':
                summary['entities'] = [{'entity_key': x.get('entity_key'), 'name': x.get('name'), 'entity_type': x.get('entity_type')}
                                       for x in arch.get('entities', [])]
            elif sid == 's3':
                summary['threads'] = [{'thread_key': x.get('thread_key'), 'name': x.get('name'), 'thread_type': x.get('thread_type')}
                                      for x in arch.get('threads', [])]
            last_errors = [e for e in check_architecture(arch, check_opts)['errors']
                           if e.get('group') in groups or (sid == 's4' and not e.get('group'))]
            n_err = len(last_errors)
            if best_count is None or n_err < best_count:
                best_count = n_err
                best_groups = {g: json.loads(json.dumps(arch.get(g))) for g in groups}
            elif n_err > best_count:
                # 本次尝试比历史更差:回滚到最优版本再进入下一轮重试(错误反馈仍用本轮的)
                for g in groups:
                    arch[g] = best_groups[g]
            if not last_errors:
                _progress(f'{sid} 完成 (尝试 {attempt + 1}, 耗时 {_time.time() - _t0:.0f}s)')
                break
            _progress(f'{sid} 第 {attempt + 1} 次尝试有 {n_err} 个错误(历史最优 {best_count}),重试: {[e.get("code") or str(e.get("message", ""))[:40] for e in last_errors[:3]]}')
        else:
            # 重试耗尽仍有错:保留历史最优版本,交给 S5 修复回路
            if best_groups is not None:
                for g in groups:
                    if best_groups[g] or arch.get(g) is not None:
                        arch[g] = best_groups[g]
        # 段内重试耗尽仍无产物:宁可响亮失败,绝不静默产空架构(空架构会 0 错误假成功)
        produced = {g: arch.get(g) for g in groups if arch.get(g)}
        if not produced:
            raise RuntimeError(f'architect stage {sid} produced nothing after retries: '
                               f'{[str(e.get("message", ""))[:120] for e in last_errors[:3]]}')

    # ---- S5 终检 + 有界修复回路(最优保留:修复恶化即回滚,错误数只减不增) ----
    repair_rounds = 0
    best_arch = json.loads(json.dumps(arch))
    best_total = len(check_architecture(arch, check_opts)['errors'])
    for _ in range(3):
        res = check_architecture(arch, check_opts)
        if not res['errors']:
            break
        repair_rounds += 1
        _progress(f'S5 修复轮 {repair_rounds}: {len(res["errors"])} 个错误 ({[e.get("code") for e in res["errors"][:4]]})')
        by_group: dict[str, list] = {}
        for e in res['errors']:
            g = e.get('group') or '(architecture)'
            by_group.setdefault(g, []).append(e)
        fix_user = ('以下是当前 architecture 中出错的分组与确定性校验错误。'
                    '只重发需要修复的分组。硬规则:已有的稳定键(thread_key/arc_key/fact_key/entity_key 等)一律不得改名、不得删除、不得新增未引用条目;'
                    '只修正错误信息指出的字段值。输出形如 {"分组名": [...]} 的完整修正分组:\n'
                    + json.dumps({'failing_groups': {g: arch.get(g) for g in by_group if g != '(architecture)'},
                                  'errors': res['errors']}, ensure_ascii=False))
        try:
            fixed = call('你是长篇小说 Story Architect(修复轮)。只输出 JSON 对象,不含解释。', fix_user)
        except Exception:
            continue
        if not isinstance(fixed, dict):
            continue
        candidate = json.loads(json.dumps(arch))
        candidate.update(_normalize(fixed))
        n_candidate = len(check_architecture(candidate, check_opts)['errors'])
        if n_candidate < len(res['errors']):
            arch = candidate
            if n_candidate < best_total:
                best_total, best_arch = n_candidate, json.loads(json.dumps(candidate))
        else:
            _progress(f'S5 修复轮 {repair_rounds} 未改善({n_candidate} >= {len(res["errors"])}),回滚')
    if len(check_architecture(arch, check_opts)['errors']) > best_total:
        arch = best_arch  # 收尾仍取全局最优
    validation = check_architecture(arch, check_opts)
    if not (arch.get('blueprint') and arch.get('world_facts') and arch.get('entities') and arch.get('threads') and arch.get('arcs')):
        raise RuntimeError('architect produced an empty/partial architecture (missing core groups)')
    _progress(f'完成: errors={len(validation["errors"])} warnings={len(validation["warnings"])} repair_rounds={repair_rounds}')

    return {'architecture': arch, 'validation': validation, 'stages': stages,
            'assumptions': assumptions, 'repair_rounds': repair_rounds,
            'ok': not validation['errors']}
