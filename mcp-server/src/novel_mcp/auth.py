"""App 级权限分层(方案 12.2):facade 令牌 → 角色 → 工具白名单。

角色与授权:

* viewer     — 读者模式(Web 工作台):仅运行状态读与正典正文浏览,
               经由 BFF 聚合读端点获得裁剪载荷;草稿/真相/规划一律不可见。
* writer     — prose-safe 读 + 草稿写;不得触碰任何作者层真相
               (belief_get/entity_author_get/assertion_list 均不授权,
               context_* 强制 writer 视角参数)。
* reviewer   — 作者视角读(含 entity_author_get/belief_get/作者子图/审计
               快照)+ 审校与自动修订;不得 finalize(参数守卫)、不得改正典。
* planner    — 作者层全量:规划、正典变更、身份/事件/断言/披露/候选晋升。
* controller — Run 控制面 + chapter_finalize + 运行状态读。
* admin      — 全部工具(默认运维)。

令牌配置 ``NOVEL_FACADE_TOKENS="writer:t1,reviewer:t2,planner:t3,controller:t4,admin:t5"``;
兼容旧版单令牌 ``NOVEL_FACADE_TOKEN``(映射为 admin);两者均未配置时 facade 不鉴权
(本地开发模式)。MCP stdio/SDK 传输为本地进程,不经此层。
"""
from __future__ import annotations

import os
from typing import Any

READS_PROSE_SAFE = {
    'story_get_state', 'narrative_thread_get', 'narrative_thread_search', 'foreshadowing_list_open',
    'entity_get', 'entity_search', 'entity_neighbors', 'entity_path_find', 'entity_context_get',
    'entity_graph_stats', 'entity_retrieve_relevant', 'narrative_retrieve_relevant',
    'event_get', 'event_timeline', 'geography_tree_get',
    'chapter_plan_check', 'continuity_check', 'story_pressure_check', 'planning_pressure_check',
}

# viewer(读者模式)只允许看"已经发生的事":运行状态与正典正文经 BFF 聚合读端点
# 提供(载荷裁剪在 web_api 层);工具面仅放行只读的运行状态查询。
VIEWER_TOOLS = {
    'novel_run_status',
}

WRITER_TOOLS = READS_PROSE_SAFE | {
    'writer_context_get', 'chapter_draft_generate', 'chapter_draft_save', 'chapter_draft_get',
    'chapter_review_get', 'chapter_revision_context_get', 'writing_workflow_status',
    'context_compile', 'context_preview',  # 参数守卫:仅 writer 视角
}

READS_AUTHOR_LAYER = {
    'belief_get', 'entity_author_get', 'narrative_entity_links_get', 'entity_graph_check',
    'context_snapshot_get', 'context_explain', 'power_context_get', 'artifact_history_get',
    'assertion_list', 'candidate_list',
}

REVIEWER_TOOLS = WRITER_TOOLS | READS_AUTHOR_LAYER | {
    'chapter_review_all', 'chapter_semantic_review', 'chapter_review_full',
    'chapter_auto_revise', 'chapter_auto_revision_loop',  # 参数守卫:不得 finalize
}

PLANNER_TOOLS = REVIEWER_TOOLS | {
    'planner_context_get', 'chapter_plan_generate', 'chapter_plan_save', 'chapter_plan_check',
    'blueprint_get', 'blueprint_update', 'story_architect_get', 'story_architect_apply',
    'novel_architecture_generate',
    'arc_plan_create', 'arc_plan_get', 'arc_progress_get', 'milestone_create', 'milestone_list',
    'thread_schedule_update', 'thread_schedule_get', 'planning_rebuild_window', 'planning_get_window',
    'narrative_pattern_search',
    'mystery_create', 'clue_add', 'belief_update', 'emotion_debt_create', 'emotion_debt_resolve',
    'entity_upsert', 'entity_alias_add', 'entity_attribute_set', 'entity_relation_upsert',
    'entity_relation_end', 'narrative_entity_link', 'entity_graph_import',
    'identity_profile_set', 'event_create', 'assertion_create', 'assertion_resolve',
    'candidate_promote', 'candidate_reject', 'fact_disclosure_set', 'fact_disclosures_get',
    'chapter_directive_set', 'chapter_direction_propose',
}

CONTROLLER_TOOLS = {
    'novel_run_start', 'novel_run_step', 'novel_run_continue', 'novel_run_status',
    'novel_run_pause', 'novel_run_resume', 'novel_run_report',
    'novel_run_decision_list', 'novel_run_decision_submit',
    'chapter_finalize',
    'chapter_directive_set',
    'story_get_state', 'writing_workflow_status', 'chapter_plan_get', 'chapter_review_get',
    'story_pressure_check', 'planning_pressure_check',
}

ROLE_TOOLS: dict[str, set[str]] = {
    'viewer': VIEWER_TOOLS,
    'writer': WRITER_TOOLS,
    'reviewer': REVIEWER_TOOLS,
    'planner': PLANNER_TOOLS,
    'controller': CONTROLLER_TOOLS,
    # admin 在校验时按"全量"处理
}

# 角色 × 工具的参数级守卫:返回 None 表示通过,否则为拒绝原因。
# writer 是唯一可能被参数抬权到作者层的角色,守卫集中在它身上。
WRITER_CONTEXT_ROLES = (None, 'writer')


def _guard(role: str, name: str, args: dict[str, Any]) -> str | None:
    if role != 'writer':
        if role == 'reviewer' and name == 'chapter_auto_revision_loop' and args.get('finalize'):
            return 'reviewer app must not finalize; use the controller app'
        return None
    if name in ('context_compile', 'context_preview'):
        if args.get('role') not in WRITER_CONTEXT_ROLES:
            return "writer app may only compile writer-role context"
    if name == 'context_snapshot_get':
        if args.get('role') != 'writer':
            return "writer app may only read writer-role snapshots"
    return None


def parse_tokens(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in raw.split(','):
        part = part.strip()
        if not part or ':' not in part:
            continue
        role, token = part.split(':', 1)
        role, token = role.strip().lower(), token.strip()
        if role in ROLE_TOOLS or role == 'admin':
            if token:
                out[token] = role
    return out


def auth_enabled() -> bool:
    return bool(os.environ.get('NOVEL_FACADE_TOKENS', '').strip() or os.environ.get('NOVEL_FACADE_TOKEN', '').strip())


def resolve_role(headers: dict[str, str]) -> tuple[str | None, int]:
    """从 Authorization: Bearer <token> 解析角色。

    返回 (role, errNo);errNo=0 成功;40101 未认证。未启用鉴权时返回
    ('admin', 0) —— 本地开发保持开放语义。
    """
    raw = os.environ.get('NOVEL_FACADE_TOKENS', '').strip()
    tokens = parse_tokens(raw) if raw else {}
    legacy = os.environ.get('NOVEL_FACADE_TOKEN', '').strip()
    if legacy:
        tokens.setdefault(legacy, 'admin')
    if not tokens:
        return 'admin', 0
    lowered = {str(k).lower(): v for k, v in (headers or {}).items()}
    presented = (lowered.get('authorization') or '').strip()
    token = presented[7:].strip() if presented.lower().startswith('bearer ') else ''
    if not token or token not in tokens:
        return None, 40101
    return tokens[token], 0


def tool_allowed(role: str, name: str, args: dict[str, Any] | None = None) -> tuple[bool, str | None]:
    args = args or {}
    if role == 'admin':
        return True, None
    allowed_set = ROLE_TOOLS.get(role)
    if allowed_set is None:
        return False, f'unknown role: {role}'
    if name not in allowed_set:
        return False, f'tool {name} is not granted to {role} apps'
    reason = _guard(role, name, args)
    if reason:
        return False, reason
    return True, None
