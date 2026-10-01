from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .store import StoryStore, jd, jl


def _merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return patch
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _json_row(r: Any, fields: dict[str, str]) -> dict[str, Any]:
    d = dict(r)
    for src, dst in fields.items():
        d[dst] = jl(d.pop(src))
    return d


class PlanningStore:
    """叠加在 StoryStore 之上的确定性规划持久层。表结构由 novel_mcp.schema 迁移管理。"""

    def __init__(self, story: StoryStore):
        self.story = story

    # ---------- 蓝图 ----------
    def blueprint_get(self) -> dict[str, Any]:
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM planning_blueprint WHERE id=1').fetchone()
        return {'version': r['version'], 'blueprint': jl(r['payload_json']), 'updated_at': r['updated_at']}

    def blueprint_update(self, patch: dict[str, Any], replace: bool = False, expected_version: int | None = None) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise ValueError('patch must be an object')
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM planning_blueprint WHERE id=1').fetchone()
            if expected_version is not None and int(r['version']) != int(expected_version):
                raise ValueError(f'blueprint version conflict: expected {expected_version}, actual {r["version"]}')
            current = jl(r['payload_json']) or {}
            payload = patch if replace else _merge(current, patch)
            version = int(r['version']) + 1
            db.execute('UPDATE planning_blueprint SET version=?,payload_json=?,updated_at=CURRENT_TIMESTAMP WHERE id=1', (version, jd(payload)))
        return {'ok': True, 'version': version, 'blueprint': payload}

    # ---------- 卷(Arc)规划器 ----------
    def arc_put(self, x: dict[str, Any]) -> dict[str, Any]:
        if not x.get('arc_key') or not x.get('name'):
            raise ValueError('arc_key and name are required')
        with self.story.connect() as db:
            db.execute('''INSERT INTO arc_plans(
              arc_key,name,order_no,start_chapter,target_end_chapter,status,primary_goal,surface_conflict,
              hidden_functions_json,allowed_reveals_json,forbidden_facts_json,inherited_thread_keys_json,
              exit_conditions_json,notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(arc_key) DO UPDATE SET
              name=excluded.name,order_no=excluded.order_no,start_chapter=excluded.start_chapter,
              target_end_chapter=excluded.target_end_chapter,status=excluded.status,
              primary_goal=excluded.primary_goal,surface_conflict=excluded.surface_conflict,
              hidden_functions_json=excluded.hidden_functions_json,allowed_reveals_json=excluded.allowed_reveals_json,
              forbidden_facts_json=excluded.forbidden_facts_json,inherited_thread_keys_json=excluded.inherited_thread_keys_json,
              exit_conditions_json=excluded.exit_conditions_json,notes=excluded.notes,updated_at=CURRENT_TIMESTAMP''', (
                x['arc_key'], x['name'], int(x.get('order_no', 0)), x.get('start_chapter'), x.get('target_end_chapter'),
                x.get('status', 'planned'), x.get('primary_goal', ''), x.get('surface_conflict', ''),
                jd(x.get('hidden_functions', [])), jd(x.get('allowed_reveals', [])), jd(x.get('forbidden_facts', [])),
                jd(x.get('inherited_thread_keys', [])), jd(x.get('exit_conditions', [])), x.get('notes', '')
            ))
        return self.arc_get(x['arc_key'])

    def arc_get(self, arc_key: str) -> dict[str, Any] | None:
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM arc_plans WHERE arc_key=?', (arc_key,)).fetchone()
        if not r:
            return None
        return _json_row(r, {
            'hidden_functions_json': 'hidden_functions',
            'allowed_reveals_json': 'allowed_reveals',
            'forbidden_facts_json': 'forbidden_facts',
            'inherited_thread_keys_json': 'inherited_thread_keys',
            'exit_conditions_json': 'exit_conditions',
        })

    def arc_for_chapter(self, chapter: int) -> dict[str, Any] | None:
        with self.story.connect() as db:
            r = db.execute('''SELECT * FROM arc_plans
              WHERE (start_chapter IS NULL OR start_chapter<=?) AND (target_end_chapter IS NULL OR target_end_chapter>=?)
              ORDER BY COALESCE(start_chapter,0) DESC, order_no DESC LIMIT 1''', (chapter, chapter)).fetchone()
        if not r:
            return None
        return self.arc_get(r['arc_key'])

    def arc_list(self) -> list[dict[str, Any]]:
        with self.story.connect() as db:
            rows = db.execute('SELECT arc_key FROM arc_plans ORDER BY order_no,start_chapter,arc_key').fetchall()
        return [self.arc_get(r['arc_key']) for r in rows]

    # ---------- 里程碑 ----------
    def milestone_put(self, x: dict[str, Any]) -> dict[str, Any]:
        if not x.get('milestone_key') or not x.get('name'):
            raise ValueError('milestone_key and name are required')
        with self.story.connect() as db:
            db.execute('''INSERT INTO planning_milestones(milestone_key,arc_key,name,min_chapter,max_chapter,status,thread_keys_json,success_conditions_json,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(milestone_key) DO UPDATE SET
              arc_key=excluded.arc_key,name=excluded.name,min_chapter=excluded.min_chapter,max_chapter=excluded.max_chapter,
              status=excluded.status,thread_keys_json=excluded.thread_keys_json,success_conditions_json=excluded.success_conditions_json,
              metadata_json=excluded.metadata_json,updated_at=CURRENT_TIMESTAMP''', (
                x['milestone_key'], x.get('arc_key'), x['name'], x.get('min_chapter'), x.get('max_chapter'), x.get('status', 'planned'),
                jd(x.get('thread_keys', [])), jd(x.get('success_conditions', [])), jd(x.get('metadata', {}))
              ))
        return self.milestone_get(x['milestone_key'])

    def milestone_get(self, key: str) -> dict[str, Any] | None:
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM planning_milestones WHERE milestone_key=?', (key,)).fetchone()
        return _json_row(r, {'thread_keys_json':'thread_keys','success_conditions_json':'success_conditions','metadata_json':'metadata'}) if r else None

    def milestone_list(self, arc_key: str | None = None, status: str | None = None, before_chapter: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = 'SELECT milestone_key FROM planning_milestones WHERE 1=1'; args: list[Any] = []
        if arc_key:
            sql += ' AND arc_key=?'; args.append(arc_key)
        if status:
            sql += ' AND status=?'; args.append(status)
        if before_chapter is not None:
            sql += ' AND COALESCE(max_chapter,min_chapter,999999999)<=?'; args.append(before_chapter)
        sql += ' ORDER BY COALESCE(min_chapter,999999999),milestone_key LIMIT ?'; args.append(limit)
        with self.story.connect() as db:
            rows = db.execute(sql, args).fetchall()
        return [self.milestone_get(r['milestone_key']) for r in rows]

    # ---------- 叙事线调度 ----------
    def schedule_due_rows(self, chapter: int) -> list[dict[str, Any]]:
        with self.story.connect() as db:
            rows = db.execute("SELECT * FROM thread_schedule WHERE status='planned' AND (min_chapter IS NULL OR min_chapter<=?) AND (max_chapter IS NULL OR max_chapter>=?)", (chapter, chapter)).fetchall()
        return [_json_row(r, {'constraints_json':'constraints','metadata_json':'metadata'}) for r in rows]

    def schedule_due_thread_keys(self, chapter: int) -> set[str]:
        return {x['thread_key'] for x in self.schedule_due_rows(chapter)}

    def schedule_put(self, x: dict[str, Any]) -> dict[str, Any]:
        if not x.get('schedule_key') or not x.get('thread_key') or not x.get('stage_type'):
            raise ValueError('schedule_key, thread_key, and stage_type are required')
        with self.story.connect() as db:
            db.execute('''INSERT INTO thread_schedule(schedule_key,thread_key,stage_type,min_chapter,max_chapter,purpose,status,constraints_json,metadata_json)
              VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(schedule_key) DO UPDATE SET
              thread_key=excluded.thread_key,stage_type=excluded.stage_type,min_chapter=excluded.min_chapter,max_chapter=excluded.max_chapter,
              purpose=excluded.purpose,status=excluded.status,constraints_json=excluded.constraints_json,metadata_json=excluded.metadata_json,
              updated_at=CURRENT_TIMESTAMP''', (
                x['schedule_key'], x['thread_key'], x['stage_type'], x.get('min_chapter'), x.get('max_chapter'), x.get('purpose',''),
                x.get('status','planned'), jd(x.get('constraints',{})), jd(x.get('metadata',{}))
              ))
        return self.schedule_get(schedule_key=x['schedule_key'])[0]

    def schedule_get(self, schedule_key: str | None = None, thread_key: str | None = None, chapter: int | None = None, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = 'SELECT * FROM thread_schedule WHERE 1=1'; args: list[Any] = []
        if schedule_key:
            sql += ' AND schedule_key=?'; args.append(schedule_key)
        if thread_key:
            sql += ' AND thread_key=?'; args.append(thread_key)
        if chapter is not None:
            sql += ' AND (min_chapter IS NULL OR min_chapter<=?) AND (max_chapter IS NULL OR max_chapter>=?)'; args += [chapter, chapter]
        if status:
            sql += ' AND status=?'; args.append(status)
        sql += ' ORDER BY COALESCE(min_chapter,999999999),schedule_key LIMIT ?'; args.append(limit)
        with self.story.connect() as db:
            rows = db.execute(sql, args).fetchall()
        return [_json_row(r, {'constraints_json':'constraints','metadata_json':'metadata'}) for r in rows]

    # ---------- 滚动规划器 ----------
    @staticmethod
    def tier_for(offset: int, hard_horizon: int, medium_horizon: int) -> str:
        if offset < hard_horizon:
            return 'hard'
        if offset < medium_horizon:
            return 'medium'
        return 'soft'

    def rebuild_window(self, anchor_chapter: int, hard_horizon: int = 5, medium_horizon: int = 20, soft_horizon: int = 50,
                       proposals: list[dict[str, Any]] | None = None, preserve_existing: bool = True) -> dict[str, Any]:
        if not (1 <= hard_horizon <= medium_horizon <= soft_horizon <= 200):
            raise ValueError('require 1 <= hard_horizon <= medium_horizon <= soft_horizon <= 200')
        proposals_by_ch = {int(x['chapter']): x for x in (proposals or []) if isinstance(x, dict) and x.get('chapter') is not None}
        with self.story.connect() as db:
            for offset in range(soft_horizon):
                ch = anchor_chapter + offset
                tier = self.tier_for(offset, hard_horizon, medium_horizon)
                old = db.execute('SELECT * FROM rolling_plan_items WHERE chapter=?', (ch,)).fetchone()
                p = proposals_by_ch.get(ch, {})
                arc = p.get('arc_key') or (old['arc_key'] if old and preserve_existing else None)
                goal = p.get('primary_goal') if 'primary_goal' in p else (old['primary_goal'] if old and preserve_existing else '')
                plan = p.get('plan') if 'plan' in p else (jl(old['plan_json']) if old and preserve_existing else {})
                status = p.get('status') or (old['status'] if old and preserve_existing else 'planned')
                version = (int(old['version']) + 1) if old else 1
                db.execute('''INSERT INTO rolling_plan_items(chapter,arc_key,tier,status,primary_goal,plan_json,version)
                  VALUES(?,?,?,?,?,?,?) ON CONFLICT(chapter) DO UPDATE SET
                  arc_key=excluded.arc_key,tier=excluded.tier,status=excluded.status,primary_goal=excluded.primary_goal,
                  plan_json=excluded.plan_json,version=excluded.version,updated_at=CURRENT_TIMESTAMP''',
                  (ch, arc, tier, status, goal, jd(plan or {}), version))
        return self.get_window(anchor_chapter, soft_horizon)

    def get_window(self, anchor_chapter: int, horizon: int = 50) -> dict[str, Any]:
        end = anchor_chapter + horizon - 1
        with self.story.connect() as db:
            rows = db.execute('SELECT * FROM rolling_plan_items WHERE chapter BETWEEN ? AND ? ORDER BY chapter', (anchor_chapter, end)).fetchall()
        items = []
        for r in rows:
            d = dict(r); d['plan'] = jl(d.pop('plan_json')); items.append(d)
        return {
            'anchor_chapter': anchor_chapter,
            'end_chapter': end,
            'items': items,
            'counts': {tier: sum(1 for x in items if x['tier'] == tier) for tier in ('hard','medium','soft')},
        }

    # ---------- 章节规划器 ----------
    def chapter_plan_put(self, chapter: int, plan: dict[str, Any], arc_key: str | None, pov_holder: str, status: str,
                         validation_status: str, validation: dict[str, Any]) -> dict[str, Any]:
        with self.story.connect() as db:
            old = db.execute('SELECT version FROM chapter_plans WHERE chapter=?', (chapter,)).fetchone()
            version = int(old['version']) + 1 if old else 1
            db.execute('''INSERT INTO chapter_plans(chapter,arc_key,pov_holder,status,version,plan_json,validation_status,validation_json)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(chapter) DO UPDATE SET
              arc_key=excluded.arc_key,pov_holder=excluded.pov_holder,status=excluded.status,version=excluded.version,
              plan_json=excluded.plan_json,validation_status=excluded.validation_status,validation_json=excluded.validation_json,
              updated_at=CURRENT_TIMESTAMP''',
              (chapter, arc_key, pov_holder, status, version, jd(plan), validation_status, jd(validation)))
            rp = db.execute('SELECT * FROM rolling_plan_items WHERE chapter=?', (chapter,)).fetchone()
            tier = rp['tier'] if rp else 'hard'
            db.execute('''INSERT INTO rolling_plan_items(chapter,arc_key,tier,status,primary_goal,plan_json,version)
              VALUES(?,?,?,?,?,?,?) ON CONFLICT(chapter) DO UPDATE SET arc_key=excluded.arc_key,status=excluded.status,
              primary_goal=excluded.primary_goal,plan_json=excluded.plan_json,version=rolling_plan_items.version+1,updated_at=CURRENT_TIMESTAMP''',
              (chapter, arc_key, tier, 'planned', plan.get('primary_goal',''), jd(plan), 1))
        return self.chapter_plan_get(chapter)

    def chapter_plan_get(self, chapter: int) -> dict[str, Any] | None:
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM chapter_plans WHERE chapter=?', (chapter,)).fetchone()
        if not r:
            return None
        return _json_row(r, {'plan_json':'plan','validation_json':'validation'})

    def mark_chapter_committed(self, chapter: int) -> None:
        with self.story.connect() as db:
            db.execute("UPDATE chapter_plans SET status='committed',updated_at=CURRENT_TIMESTAMP WHERE chapter=?", (chapter,))
            db.execute("UPDATE rolling_plan_items SET status='committed',updated_at=CURRENT_TIMESTAMP WHERE chapter=?", (chapter,))

    # ---------- 诊断 ----------
    def planning_snapshot(self, chapter: int) -> dict[str, Any]:
        arc = self.arc_for_chapter(chapter)
        plan = self.chapter_plan_get(chapter)
        window = self.get_window(chapter, 10)
        due_schedule = self.schedule_get(chapter=chapter, status='planned', limit=50)
        due_milestones = []
        for m in self.milestone_list(status='planned', limit=100):
            lo, hi = m.get('min_chapter'), m.get('max_chapter')
            if (lo is None or lo <= chapter) and (hi is None or hi >= chapter):
                due_milestones.append(m)
        bp = self.blueprint_get()
        return {
            'blueprint_version': bp['version'],
            'current_arc_plan': arc,
            'chapter_plan': plan,
            'rolling_window': window,
            'due_thread_schedule': due_schedule,
            'due_milestones': due_milestones,
        }

    def pressure(self, chapter: int, hard_lookahead: int = 5) -> dict[str, Any]:
        risks: list[dict[str, Any]] = []
        recommendations: list[str] = []
        window = self.get_window(chapter, max(1, hard_lookahead))
        by_ch = {x['chapter']: x for x in window['items']}
        for ch in range(chapter, chapter + hard_lookahead):
            item = by_ch.get(ch)
            cp = self.chapter_plan_get(ch)
            if not item or not item.get('primary_goal'):
                risks.append({'code':'HARD_WINDOW_GOAL_MISSING','chapter':ch})
            if not cp:
                risks.append({'code':'HARD_WINDOW_CHAPTER_PLAN_MISSING','chapter':ch})
            elif cp['validation_status'] == 'blocked':
                risks.append({'code':'BLOCKED_CHAPTER_PLAN','chapter':ch})
        overdue_schedule = []
        with self.story.connect() as db:
            rows = db.execute("SELECT * FROM thread_schedule WHERE status='planned' AND max_chapter IS NOT NULL AND max_chapter<? ORDER BY max_chapter", (chapter,)).fetchall()
        for r in rows:
            overdue_schedule.append(_json_row(r, {'constraints_json':'constraints','metadata_json':'metadata'}))
        if overdue_schedule:
            risks.append({'code':'THREAD_SCHEDULE_OVERDUE','count':len(overdue_schedule)})
            recommendations.append('reactivate or reschedule overdue narrative thread stages before adding new long-fuse obligations')
        overdue_ms = self.milestone_list(status='planned', before_chapter=chapter-1, limit=100)
        if overdue_ms:
            risks.append({'code':'MILESTONE_OVERDUE','count':len(overdue_ms)})
            recommendations.append('resolve, move, or explicitly cancel overdue arc milestones')
        if any(x['code'].startswith('HARD_WINDOW_') for x in risks):
            recommendations.append('fill and validate the next hard planning window before drafting prose')
        return {
            'chapter': chapter,
            'hard_lookahead': hard_lookahead,
            'risks': risks,
            'overdue_thread_schedule': overdue_schedule,
            'overdue_milestones': overdue_ms,
            'recommendations': list(dict.fromkeys(recommendations)),
            'ok': not any(x['code'] in {'BLOCKED_CHAPTER_PLAN'} for x in risks),
        }
