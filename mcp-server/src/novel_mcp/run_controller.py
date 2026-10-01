from __future__ import annotations

import uuid
from typing import Any

from .store import jd, jl

DEFAULT_CONFIG = {
    'target_chapter': None,
    'target_arc_key': None,
    'max_chapters': None,
    'max_revision_rounds': 3,
    'require_semantic': True,
    'allow_warnings': True,
    'auto_extract': False,
    'auto_plan': True,
    'stop_on_pressure': True,
    'pressure_risk_limit': 4,
    'report_every': 10,
    'hard_horizon': 5,
    'medium_horizon': 20,
    'soft_horizon': 50,
    'planner_model': None,
    'writer_model': None,
    'reviewer_model': None,
    'revision_model': None,
}

SAFE_CONFIG_KEYS = set(DEFAULT_CONFIG)


def _run_row(row: Any) -> dict[str, Any]:
    d = dict(row)
    d['config'] = jl(d.pop('config_json')) or {}
    d['stop_reason'] = jl(d.pop('stop_reason_json')) if d.get('stop_reason_json') is not None else None
    d.pop('stop_reason_json', None)
    return d


class NovelRunController:
    """持久化的有界自动推进状态机。表结构由 novel_mcp.schema 迁移统一管理。"""

    def __init__(self, service: Any):
        self.service = service
        self.story = service.store

    def _event(self, run_id: str, phase: str, status: str, chapter: int | None = None, detail: dict[str, Any] | None = None) -> None:
        with self.story.connect() as db:
            db.execute('INSERT INTO novel_run_events(run_id,chapter,phase,status,detail_json) VALUES(?,?,?,?,?)',
                       (run_id, chapter, phase, status, jd(detail or {})))

    def get(self, run_id: str) -> dict[str, Any]:
        with self.story.connect() as db:
            row = db.execute('SELECT * FROM novel_runs WHERE run_id=?', (run_id,)).fetchone()
        if not row:
            raise KeyError(f'unknown run_id: {run_id}')
        return _run_row(row)

    def _events(self, run_id: str) -> list[dict[str, Any]]:
        with self.story.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM novel_run_events WHERE run_id=? ORDER BY id', (run_id,)).fetchall()]

    def _update(self, run_id: str, *, status: str | None = None, current_chapter: int | None = None,
                last_committed_chapter: int | None = None, chapters_committed: int | None = None,
                config: dict[str, Any] | None = None, stop_reason: dict[str, Any] | None = None,
                clear_stop: bool = False) -> dict[str, Any]:
        fields = []; args: list[Any] = []
        if status is not None: fields.append('status=?'); args.append(status)
        if current_chapter is not None: fields.append('current_chapter=?'); args.append(current_chapter)
        if last_committed_chapter is not None: fields.append('last_committed_chapter=?'); args.append(last_committed_chapter)
        if chapters_committed is not None: fields.append('chapters_committed=?'); args.append(chapters_committed)
        if config is not None: fields.append('config_json=?'); args.append(jd(config))
        if stop_reason is not None: fields.append('stop_reason_json=?'); args.append(jd(stop_reason))
        elif clear_stop: fields.append('stop_reason_json=NULL')
        fields.append('updated_at=CURRENT_TIMESTAMP')
        args.append(run_id)
        with self.story.connect() as db:
            db.execute(f'UPDATE novel_runs SET {",".join(fields)} WHERE run_id=?', args)
        return self.get(run_id)

    def start(self, start_chapter: int | None = None, **config: Any) -> dict[str, Any]:
        last = self.service.canon.max_committed_chapter()
        if start_chapter is None:
            start_chapter = int(last or 0) + 1
        if start_chapter < 1:
            raise ValueError('start_chapter must be >= 1')
        if last is not None and int(start_chapter) <= int(last):
            raise ValueError(f'start_chapter must be after latest committed chapter {last}; resume an existing run instead of rewriting canon')
        cfg = dict(DEFAULT_CONFIG)
        cfg.update({k: v for k, v in config.items() if k in SAFE_CONFIG_KEYS and v is not None})
        if cfg['max_chapters'] is not None and int(cfg['max_chapters']) < 1:
            raise ValueError('max_chapters must be >= 1')
        if not 0 <= int(cfg['max_revision_rounds']) <= 8:
            raise ValueError('max_revision_rounds must be between 0 and 8')
        if int(cfg['report_every']) < 1:
            raise ValueError('report_every must be >= 1')
        run_id = 'run_' + uuid.uuid4().hex[:16]
        with self.story.connect() as db:
            db.execute('''INSERT INTO novel_runs(run_id,status,start_chapter,current_chapter,last_committed_chapter,chapters_committed,config_json)
                          VALUES(?,?,?,?,?,?,?)''',
                       (run_id, 'running', start_chapter, start_chapter, last, 0, jd(cfg)))
        self._event(run_id, 'run', 'started', start_chapter, {'config': cfg})
        return self.status(run_id)

    def _open_decision(self, run_id: str, chapter: int, decision_type: str, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        with self.story.connect() as db:
            existing = db.execute("SELECT * FROM novel_run_decisions WHERE run_id=? AND status='open' ORDER BY created_at LIMIT 1", (run_id,)).fetchone()
            if existing:
                decision = dict(existing); decision['context'] = jl(decision.pop('context_json')) or {}; decision['resolution'] = jl(decision.pop('resolution_json')) if decision.get('resolution_json') else None; decision.pop('resolution_json', None)
            else:
                did = 'decision_' + uuid.uuid4().hex[:16]
                db.execute('''INSERT INTO novel_run_decisions(decision_id,run_id,chapter,decision_type,status,prompt,context_json)
                              VALUES(?,?,?,?,?,?,?)''', (did, run_id, chapter, decision_type, 'open', prompt, jd(context)))
                decision = {'decision_id': did, 'run_id': run_id, 'chapter': chapter, 'decision_type': decision_type,
                            'status': 'open', 'prompt': prompt, 'context': context, 'resolution': None}
        reason = {'code': 'AUTHOR_DECISION_REQUIRED', 'decision_id': decision['decision_id'], 'decision_type': decision_type, 'chapter': chapter}
        self._update(run_id, status='needs_author_decision', stop_reason=reason)
        self._event(run_id, 'decision', 'opened', chapter, {'decision_id': decision['decision_id'], 'decision_type': decision_type})
        return decision

    def decisions(self, run_id: str, status: str | None = 'open') -> list[dict[str, Any]]:
        sql = 'SELECT * FROM novel_run_decisions WHERE run_id=?'; args: list[Any] = [run_id]
        if status:
            sql += ' AND status=?'; args.append(status)
        sql += ' ORDER BY created_at,decision_id'
        with self.story.connect() as db:
            rows = db.execute(sql, args).fetchall()
        out = []
        for r in rows:
            d = dict(r); d['context'] = jl(d.pop('context_json')) or {}; d['resolution'] = jl(d.pop('resolution_json')) if d.get('resolution_json') else None; d.pop('resolution_json', None); out.append(d)
        return out

    def submit_decision(self, run_id: str, decision_id: str, resolution: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(resolution, dict):
            raise ValueError('resolution must be an object')
        with self.story.connect() as db:
            row = db.execute('SELECT * FROM novel_run_decisions WHERE decision_id=? AND run_id=?', (decision_id, run_id)).fetchone()
            if not row: raise KeyError(f'unknown decision_id: {decision_id}')
            if row['status'] != 'open': raise ValueError('decision is already resolved')
            db.execute("UPDATE novel_run_decisions SET status='resolved',resolution_json=?,resolved_at=CURRENT_TIMESTAMP WHERE decision_id=?", (jd(resolution), decision_id))
        run = self.get(run_id); cfg = dict(run['config'])
        patch = resolution.get('config_patch') if isinstance(resolution.get('config_patch'), dict) else {}
        for k, v in patch.items():
            if k in SAFE_CONFIG_KEYS: cfg[k] = v
        action = resolution.get('action', 'resume')
        if action == 'abort':
            self._update(run_id, status='cancelled', config=cfg, stop_reason={'code': 'AUTHOR_ABORTED', 'decision_id': decision_id})
        elif action == 'pause':
            self._update(run_id, status='paused', config=cfg, stop_reason={'code': 'AUTHOR_PAUSED', 'decision_id': decision_id})
        else:
            self._update(run_id, status='running', config=cfg, clear_stop=True)
        self._event(run_id, 'decision', 'resolved', row['chapter'], {'decision_id': decision_id, 'resolution': resolution})
        return {'ok': True, 'run': self.status(run_id), 'decision_id': decision_id}

    def pause(self, run_id: str, reason: str = '') -> dict[str, Any]:
        run = self._update(run_id, status='paused', stop_reason={'code': 'PAUSED', 'reason': reason})
        self._event(run_id, 'run', 'paused', run['current_chapter'], {'reason': reason})
        return self.status(run_id)

    def resume(self, run_id: str) -> dict[str, Any]:
        if self.decisions(run_id, 'open'):
            return {'ok': False, 'error': {'code': 'OPEN_AUTHOR_DECISION', 'message': 'resolve the open decision before resume'}, 'run': self.status(run_id)}
        run = self.get(run_id)
        if run['status'] in {'completed', 'cancelled'}:
            return {'ok': False, 'error': {'code': 'RUN_TERMINAL', 'status': run['status']}, 'run': self.status(run_id)}
        self._update(run_id, status='running', clear_stop=True)
        self._event(run_id, 'run', 'resumed', run['current_chapter'])
        return self.status(run_id)

    def _terminal_reason(self, run: dict[str, Any]) -> dict[str, Any] | None:
        cfg = run['config']; ch = int(run['current_chapter'])
        if cfg.get('target_chapter') is not None and ch > int(cfg['target_chapter']):
            return {'code': 'TARGET_CHAPTER_REACHED', 'target_chapter': int(cfg['target_chapter'])}
        if cfg.get('max_chapters') is not None and int(run['chapters_committed']) >= int(cfg['max_chapters']):
            return {'code': 'MAX_CHAPTERS_REACHED', 'max_chapters': int(cfg['max_chapters'])}
        arc_key = cfg.get('target_arc_key')
        if arc_key:
            try:
                arc = self.service.arc_plan_get(arc_key)
            except Exception:
                arc = None
            if arc and arc.get('target_end_chapter') is not None and run.get('last_committed_chapter') is not None and int(run['last_committed_chapter']) >= int(arc['target_end_chapter']):
                return {'code': 'TARGET_ARC_COMPLETED', 'target_arc_key': arc_key, 'target_end_chapter': arc['target_end_chapter']}
        return None

    def _ensure_window(self, chapter: int, cfg: dict[str, Any]) -> None:
        win = self.service.planning_get_window(chapter, 1)
        if not win.get('items'):
            self.service.planning_rebuild_window(chapter, int(cfg['hard_horizon']), int(cfg['medium_horizon']), int(cfg['soft_horizon']), [], True)

    def step(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        if run['status'] != 'running':
            return {'ok': False, 'status': run['status'], 'run': self.status(run_id), 'error': {'code': 'RUN_NOT_RUNNING'}}
        reason = self._terminal_reason(run)
        if reason:
            self._update(run_id, status='completed', stop_reason=reason)
            self._event(run_id, 'run', 'completed', run['current_chapter'], reason)
            return {'ok': True, 'status': 'completed', 'reason': reason, 'run': self.status(run_id)}
        ch = int(run['current_chapter']); cfg = run['config']
        self._event(run_id, 'chapter', 'started', ch)

        if cfg.get('stop_on_pressure'):
            pressure = self.service.planning_pressure_check(ch)
            narrative_risks = list((pressure.get('narrative_pressure') or {}).get('risks') or [])
            structural_risks = [x for x in ((pressure.get('planning_pressure') or {}).get('risks') or []) if x.get('code') in {'THREAD_SCHEDULE_OVERDUE','MILESTONE_OVERDUE','BLOCKED_CHAPTER_PLAN'}]
            risk_count = len(narrative_risks) + len(structural_risks)
            if risk_count >= int(cfg.get('pressure_risk_limit', 4)):
                decision = self._open_decision(run_id, ch, 'story_pressure',
                    '剧情/规划压力达到停止阈值。请检查风险并调整计划或运行配置后继续。',
                    {'risk_count': risk_count, 'pressure': pressure})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}

        self._ensure_window(ch, cfg)
        try:
            cp = self.service.chapter_plan_get(ch)
        except Exception:
            cp = None
        if not cp or cp.get('validation_status') == 'blocked':
            if not cfg.get('auto_plan'):
                decision = self._open_decision(run_id, ch, 'chapter_plan_required', '当前章节缺少可用 ChapterPlan。请保存/修复计划后继续。', {'chapter_plan': cp})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            try:
                generated = self.service.chapter_plan_generate(ch, model=cfg.get('planner_model'), save=True, allow_blocked=False)
            except Exception as exc:
                import traceback
                decision = self._open_decision(run_id, ch, 'planner_failed', '自动 Chapter Planner 无法生成可用计划。请检查模型配置或手工保存计划。', {'error': str(exc), 'traceback': traceback.format_exc()[-2000:]})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            if not generated.get('ok'):
                decision = self._open_decision(run_id, ch, 'chapter_plan_blocked', '自动生成的 ChapterPlan 被验证器阻止。请人工修改计划。', {'plan_result': generated})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            cp = generated.get('chapter_plan') or self.service.chapter_plan_get(ch)
        self._event(run_id, 'planning', 'ready', ch, {'plan_version': cp.get('version') if cp else None})

        wf = self.service.writing_workflow_status(ch)
        if wf.get('workflow', {}).get('status') == 'committed':
            finalized = {'committed': True, 'chapter': ch, 'already_committed': True}
        else:
            try:
                draft = self.service.chapter_draft_get(ch)
            except Exception:
                draft = None
            if not draft:
                try:
                    draft_result = self.service.chapter_draft_generate(ch, model=cfg.get('writer_model'))
                    draft = draft_result['draft']
                except Exception as exc:
                    decision = self._open_decision(run_id, ch, 'writer_failed', 'Writer 无法生成章节草稿。请检查模型配置或手工保存草稿。', {'error': str(exc)})
                    return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            self._event(run_id, 'draft', 'ready', ch, {'version': draft['version']})
            try:
                loop = self.service.chapter_auto_revision_loop(
                    ch, draft['version'], max_rounds=int(cfg.get('max_revision_rounds', 3)),
                    require_semantic=bool(cfg.get('require_semantic', True)), reviewer_model=cfg.get('reviewer_model'),
                    revision_model=cfg.get('revision_model'), finalize=True, allow_warnings=bool(cfg.get('allow_warnings', True)),
                    auto_extract=bool(cfg.get('auto_extract', False)))
            except Exception as exc:
                # 流水线异常不得击穿驱动进程:转为硬决策点,保留现场供人工检查
                decision = self._open_decision(run_id, ch, 'chapter_pipeline_error',
                    f'章节流水线异常终止:{exc}', {'error': str(exc)})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            if not loop.get('ok') or loop.get('status') != 'committed':
                decision = self._open_decision(run_id, ch, 'review_or_revision_blocked',
                    '章节在审查/自动修订后仍未能提交。请查看证据、人工修订或调整 ChapterPlan。', {'result': loop})
                return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}
            finalized = loop.get('finalize') or {'committed': True, 'chapter': ch}
        if not finalized.get('committed'):
            decision = self._open_decision(run_id, ch, 'finalize_failed', '章节未能通过最终提交门。', {'result': finalized})
            return {'ok': False, 'status': 'needs_author_decision', 'chapter': ch, 'decision': decision}

        run = self.get(run_id)
        count = int(run['chapters_committed']) + (0 if finalized.get('already_committed') else 1)
        next_chapter = ch + 1
        self._update(run_id, current_chapter=next_chapter, last_committed_chapter=ch, chapters_committed=count, clear_stop=True)
        self._event(run_id, 'chapter', 'committed', ch, {'next_chapter': next_chapter, 'chapters_committed': count})

        if count and count % int(cfg.get('report_every', 10)) == 0:
            self.report(run_id, persist=True)
        newrun = self.get(run_id)
        reason = self._terminal_reason(newrun)
        if reason:
            self._update(run_id, status='completed', stop_reason=reason)
            self._event(run_id, 'run', 'completed', next_chapter, reason)
            return {'ok': True, 'status': 'completed', 'chapter': ch, 'reason': reason, 'run': self.status(run_id)}
        return {'ok': True, 'status': 'running', 'chapter': ch, 'next_chapter': next_chapter, 'run': self.status(run_id)}

    def continue_run(self, run_id: str, max_steps: int = 5) -> dict[str, Any]:
        if not 1 <= max_steps <= 50:
            raise ValueError('max_steps must be between 1 and 50')
        results = []
        for _ in range(max_steps):
            run = self.get(run_id)
            if run['status'] != 'running': break
            r = self.step(run_id); results.append(r)
            if r.get('status') != 'running': break
        return {'ok': self.get(run_id)['status'] not in {'failed'}, 'steps': len(results), 'results': results, 'run': self.status(run_id)}

    def report(self, run_id: str, persist: bool = True) -> dict[str, Any]:
        run = self.get(run_id)
        ev = self._events(run_id)
        committed = self.service.canon.chapters_range(run['start_chapter'], run.get('last_committed_chapter') or run['start_chapter'] - 1)
        phase_counts: dict[str, int] = {}
        for e in ev: phase_counts[e['phase']] = phase_counts.get(e['phase'], 0) + 1
        from_ch = committed[0]['chapter'] if committed else None; to_ch = committed[-1]['chapter'] if committed else None
        pressure = self.service.planning_pressure_check((to_ch or run['current_chapter']))
        report = {
            'run_id': run_id, 'status': run['status'], 'range': {'from_chapter': from_ch, 'to_chapter': to_ch},
            'chapters_committed': run['chapters_committed'], 'chapter_summaries': committed,
            'event_phase_counts': phase_counts, 'current_pressure': pressure,
            'open_decisions': self.decisions(run_id, 'open'), 'stop_reason': run.get('stop_reason'),
        }
        if persist:
            with self.story.connect() as db:
                db.execute('INSERT INTO novel_run_reports(run_id,from_chapter,to_chapter,report_json) VALUES(?,?,?,?)', (run_id, from_ch, to_ch, jd(report)))
        return report

    def status(self, run_id: str) -> dict[str, Any]:
        run = self.get(run_id)
        with self.story.connect() as db:
            events = [dict(r) for r in db.execute('SELECT * FROM novel_run_events WHERE run_id=? ORDER BY id DESC LIMIT 20', (run_id,)).fetchall()]
        for e in events: e['detail'] = jl(e.pop('detail_json')) or {}
        return {'ok': True, 'run': run, 'open_decisions': self.decisions(run_id, 'open'), 'recent_events': list(reversed(events))}
