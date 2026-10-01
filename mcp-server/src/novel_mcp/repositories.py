"""聚合仓储层。

service/context_compiler 等编排层不直接执行 SQL,统一通过仓储方法访问
跨聚合数据。规则:

* 手写 SQL 保留在仓储内——时间切片、belief 快照等查询是领域逻辑本身;
* 各模块自有表(writing/planning/run)的 DAO 留在原模块,此处只收编
  service 层曾内联的世界观(world_facts/beliefs)与正典
  (chapters/events/character_states)查询,以及抽取候选;
* 仓储方法可安全参与 StoryStore.transaction() 环境事务。
"""
from __future__ import annotations

from typing import Any

from .store import StoryStore, jd, jl


class WorldRepository:
    """世界观真相与信念(world_facts + beliefs)。"""

    def __init__(self, store: StoryStore):
        self.store = store

    def _rows(self, where: str = '') -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute(f'SELECT * FROM world_facts {where} ORDER BY fact_key').fetchall()
        out = []
        for r in rows:
            d = dict(r); d['truth'] = jl(d.pop('truth_json')); out.append(d)
        return out

    def all_facts(self) -> list[dict[str, Any]]:
        return self._rows()

    def secret_facts(self) -> list[dict[str, Any]]:
        return self._rows("WHERE secrecy!='public'")

    def set_fact(self, fact_key: str, truth: Any, secrecy: str = 'secret', reveal_after: int | None = None, notes: str = '') -> None:
        self.store.set_world_fact(fact_key, truth, secrecy, reveal_after, notes)

    def add_belief(self, **x) -> None:
        self.store.add_belief(**x)

    def belief_snapshot(self, fact_key: str, chapter: int) -> dict[str, Any]:
        return self.store.belief_snapshot(fact_key, chapter)

    def forbidden_facts(self, snapshot_chapter: int, holder: str) -> list[dict[str, Any]]:
        """列出对 prose 上下文仍隐藏的 World Truth(只给 fact_key,不给值)。

        reader 或 holder 任一 confirmed,或已过该持有者的计划知晓时刻
        (per-holder 披露 / reader 披露 / 旧 reveal_after 取最早),即视为
        合法可知,不再列入。
        """
        out: list[dict[str, Any]] = []
        for f in self.secret_facts():
            snap = self.store.belief_snapshot(f['fact_key'], snapshot_chapter)
            hs = snap.get('holders') or {}
            known = {(hs.get('reader') or {}).get('stance'), (hs.get(holder) or {}).get('stance')}
            moment = self.store.fact_known_from(f['fact_key'], holder)
            if 'confirmed' not in known and (moment is None or snapshot_chapter < moment):
                out.append({'fact_key': f['fact_key'], 'known_from': moment, 'reason': 'hidden World Truth value withheld from prose context'})
        return out

    def set_disclosure(self, fact_key: str, holder: str, known_from_chapter: int, channel: str = '', source: str = 'author_declared') -> dict[str, Any]:
        """双时序:为某个持有者安排 knowledge_time(何时开始合法知晓该事实)。

        holder='reader' 等价于全局公开时刻(与旧 reveal_after 同语义且优先)。
        """
        holder = (holder or '').strip()
        if not holder:
            raise ValueError('holder is required')
        with self.store.connect() as db:
            if not db.execute('SELECT 1 FROM world_facts WHERE fact_key=?', (fact_key,)).fetchone():
                raise KeyError(f'unknown fact_key: {fact_key}')
            db.execute('''INSERT INTO fact_disclosures(fact_key,holder,known_from_chapter,channel,source)
                VALUES(?,?,?,?,?) ON CONFLICT(fact_key,holder) DO UPDATE SET
                known_from_chapter=excluded.known_from_chapter,channel=excluded.channel,source=excluded.source''',
                (fact_key, holder, int(known_from_chapter), channel, source))
        return {'ok': True, 'fact_key': fact_key, 'holder': holder, 'known_from_chapter': int(known_from_chapter), 'channel': channel}

    def disclosures(self, fact_key: str | None = None) -> list[dict[str, Any]]:
        sql = 'SELECT * FROM fact_disclosures'
        args: list[Any] = []
        if fact_key:
            sql += ' WHERE fact_key=?'; args.append(fact_key)
        sql += ' ORDER BY fact_key,known_from_chapter,holder'
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(sql, args).fetchall()]


class CanonRepository:
    """已提交正典(chapters + events + character_states)。"""

    def __init__(self, store: StoryStore):
        self.store = store

    def max_committed_chapter(self) -> int | None:
        with self.store.connect() as db:
            return db.execute('SELECT MAX(chapter) c FROM chapters').fetchone()['c']

    def chapter_at_or_before(self, chapter: int) -> dict[str, Any] | None:
        with self.store.connect() as db:
            r = db.execute('SELECT * FROM chapters WHERE chapter<=? ORDER BY chapter DESC LIMIT 1', (chapter,)).fetchone()
        return dict(r) if r else None

    def commit_chapter(self, chapter: int, title: str, body: str, arc: str = '', pov: str = '', summary: str = '') -> None:
        self.store.commit_chapter(chapter, title, body, arc, pov, summary)

    def chapters_range(self, lo: int, hi: int) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT chapter,title,arc,pov,summary,committed_at FROM chapters WHERE chapter>=? AND chapter<=? ORDER BY chapter',
                (lo, hi)).fetchall()]

    def recent_chapters_with_body(self, before_chapter: int, limit: int) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT chapter,title,arc,pov,summary,body FROM chapters WHERE chapter<? ORDER BY chapter DESC LIMIT ?',
                (before_chapter, limit)).fetchall()]

    def recent_events(self, lo: int, hi: int) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT * FROM events WHERE chapter BETWEEN ? AND ? ORDER BY chapter,id', (lo, hi)).fetchall()]

    def add_event(self, chapter: int, name: str, event_key: str | None = None, event_type: str = 'event',
                  thread_key: str | None = None, status: str = 'verified', metadata: dict | None = None) -> None:
        self.store.add_event(chapter, name, event_key, event_type, thread_key, status, metadata)

    def character_state(self, character_key: str, chapter: int, inclusive: bool = True) -> dict[str, Any] | None:
        """取某角色在指定章节之前(或含当章)的最新状态。"""
        op = '<=' if inclusive else '<'
        with self.store.connect() as db:
            r = db.execute(f'SELECT * FROM character_states WHERE character_key=? AND chapter{op}? ORDER BY chapter DESC LIMIT 1',
                           (character_key, chapter)).fetchone()
        if not r:
            return None
        d = dict(r); d['state'] = jl(d.pop('state_json'))
        return d

    def latest_character_states(self, chapter: int) -> list[dict[str, Any]]:
        with self.store.connect() as db:
            rows = db.execute('''SELECT c.* FROM character_states c JOIN
                (SELECT character_key,MAX(chapter) mc FROM character_states WHERE chapter<=? GROUP BY character_key) x
                ON c.character_key=x.character_key AND c.chapter=x.mc ORDER BY c.character_key''',
                (chapter,)).fetchall()
        return [{**dict(r), 'state': jl(r['state_json'])} for r in rows]

    def add_character_state(self, character_key: str, chapter: int, state: dict, source: str = 'author_declared') -> None:
        self.store.add_character_state(character_key, chapter, state, source)


class CandidateRepository:
    """抽取候选(extraction_candidates):Mention 层的只进清单 + 人工晋升/拒绝。

    这是 Assertion/Evidence 闭环(A0)的最小落地:候选只由抽取器写入,
    成为正典的唯一路径是显式 promote(携带证据链),否则 reject 留审计。
    """

    def __init__(self, store: StoryStore):
        self.store = store

    def add(self, chapter: int, node_type: str, name: str, payload: dict) -> int:
        with self.store.connect() as db:
            cur = db.execute('INSERT INTO extraction_candidates(chapter,node_type,name,payload_json) VALUES(?,?,?,?)',
                             (chapter, node_type, name, jd(payload)))
            return int(cur.lastrowid)

    def _row(self, r) -> dict[str, Any]:
        d = dict(r); d['payload'] = jl(d.pop('payload_json')) or {}
        return d

    def get(self, candidate_id: int) -> dict[str, Any] | None:
        with self.store.connect() as db:
            r = db.execute('SELECT * FROM extraction_candidates WHERE id=?', (int(candidate_id),)).fetchone()
        return self._row(r) if r else None

    def list(self, chapter: int | None = None, node_type: str | None = None, status: str = 'candidate', limit: int = 100) -> list[dict[str, Any]]:
        sql = 'SELECT * FROM extraction_candidates WHERE status=?'; args: list[Any] = [status]
        if chapter is not None:
            sql += ' AND chapter=?'; args.append(int(chapter))
        if node_type:
            sql += ' AND node_type=?'; args.append(node_type)
        sql += ' ORDER BY chapter,id LIMIT ?'; args.append(max(1, min(int(limit), 500)))
        with self.store.connect() as db:
            return [self._row(r) for r in db.execute(sql, args).fetchall()]

    def resolve(self, candidate_id: int, resolution: str, promoted_target: str | None = None, review_note: str = '') -> None:
        if resolution not in {'promoted', 'rejected'}:
            raise ValueError("resolution must be 'promoted' or 'rejected'")
        with self.store.connect() as db:
            cur = db.execute('''UPDATE extraction_candidates
                SET status=?,resolution=?,resolved_at=CURRENT_TIMESTAMP,promoted_target=?,review_note=?
                WHERE id=? AND status='candidate' ''',
                (resolution, resolution, promoted_target, review_note, int(candidate_id)))
            if not cur.rowcount:
                raise ValueError(f'candidate {candidate_id} is not open (already resolved or missing)')
