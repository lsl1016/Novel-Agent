"""世界模型 V2:一等 Event 与 Assertion/Evidence。

* Event 携带 participants / cause / outcome / consequence / location,
  实体属性与关系的变化可挂 cause_event_id 追溯到具体事件;
* Assertion 是 Mention → confirmed/disproved/superseded → Canonical Fact
  的命题状态机:抽取侧只能创建 candidate,确认是作者动作;
* 所有写入可参与 StoryStore 环境事务。
"""
from __future__ import annotations

from typing import Any

from .store import StoryStore, jd, jl

CAUSE_CHAIN_MAX_DEPTH = 16
ASSERTION_TERMINAL = {'confirmed', 'disproved', 'superseded'}


class WorldModel:
    def __init__(self, service: Any):
        self.store: StoryStore = service.store
        self.entity_graph = service.entity_graph

    # ------------------------------------------------------------------
    # 一等 Event
    # ------------------------------------------------------------------
    def event_create(self, name: str, chapter: int, event_key: str | None = None, event_type: str = 'event',
                     thread_key: str | None = None, location_key: str | None = None,
                     cause_event_id: int | None = None, cause_event_key: str | None = None,
                     outcome: str = '', consequence: str = '', status: str = 'verified',
                     participants: list[dict] | None = None, metadata: dict | None = None) -> dict[str, Any]:
        name=(name or '').strip()
        if not name: raise ValueError('event name is required')
        chapter=int(chapter)
        participants_provided = participants is not None
        participants=[p for p in (participants or []) if isinstance(p, dict)]
        with self.store.connect() as db:
            if cause_event_key is not None:
                row=db.execute('SELECT id FROM events WHERE event_key=? ORDER BY id DESC LIMIT 1',(cause_event_key,)).fetchone()
                if not row: raise KeyError(f'unknown cause_event_key: {cause_event_key}')
                cause_event_id=int(row['id'])
            if cause_event_id is not None and not db.execute('SELECT 1 FROM events WHERE id=?',(int(cause_event_id),)).fetchone():
                raise KeyError(f'unknown cause_event_id: {cause_event_id}')
            # event_key 提供时按键幂等复用(declared_updates 重放安全)
            event_id=None
            if event_key:
                row=db.execute('SELECT id FROM events WHERE event_key=? ORDER BY id DESC LIMIT 1',(event_key,)).fetchone()
                if row: event_id=int(row['id'])
            if event_id is None:
                cur=db.execute('INSERT INTO events(chapter,event_key,name,event_type,thread_key,status,metadata_json,cause_event_id,outcome,consequence,location_key) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    (chapter,event_key,name,event_type,thread_key,status,jd(metadata or {}),cause_event_id,outcome,consequence,location_key))
                event_id=int(cur.lastrowid)
            else:
                db.execute('''UPDATE events SET chapter=?,name=?,event_type=?,thread_key=?,status=?,metadata_json=?,cause_event_id=?,outcome=?,consequence=?,location_key=? WHERE id=?''',
                    (chapter,name,event_type,thread_key,status,jd(metadata or {}),cause_event_id,outcome,consequence,location_key,event_id))
            # 参与者仅在显式传入时替换;按键重放(未带 participants)保留既有参与者
            if participants_provided:
                db.execute('DELETE FROM event_participants WHERE event_id=?',(event_id,))
            for p in participants or []:
                ekey=p.get('entity_key')
                if not ekey: raise ValueError('participant requires entity_key')
                if not db.execute('SELECT 1 FROM entities WHERE entity_key=?',(ekey,)).fetchone():
                    raise KeyError(f'unknown participant entity_key: {ekey}')
                db.execute('INSERT INTO event_participants(event_id,entity_key,participant_role,outcome_state_json) VALUES(?,?,?,?)',
                    (event_id,ekey,p.get('participant_role','participant'),jd(p.get('outcome_state') or {})))
                db.execute('''INSERT INTO narrative_entity_links(narrative_type,narrative_key,entity_key,role,chapter,properties_json,source)
                    VALUES('event',?,?,?,?,'{}','event_participant') ON CONFLICT(narrative_type,narrative_key,entity_key,role,chapter) DO UPDATE SET properties_json=excluded.properties_json''',
                    (event_key or f'event_{event_id}',ekey,p.get('participant_role','participant'),chapter))
        return {'ok':True,'event':self.event_get(event_key=event_key) if event_key else self.event_get(event_id=event_id)}

    def _event_row(self, r) -> dict[str, Any]:
        d=dict(r); d['metadata']=jl(d.pop('metadata_json')) or {}
        return d

    def event_get(self, event_key: str | None = None, event_id: int | None = None) -> dict[str, Any]:
        with self.store.connect() as db:
            if event_id is not None:
                r=db.execute('SELECT * FROM events WHERE id=?',(int(event_id),)).fetchone()
            elif event_key:
                r=db.execute('SELECT * FROM events WHERE event_key=? ORDER BY id DESC LIMIT 1',(event_key,)).fetchone()
            else:
                raise ValueError('provide event_key or event_id')
            if not r: raise KeyError('event not found')
            ev=self._event_row(r)
            parts=[]
            for p in db.execute('SELECT * FROM event_participants WHERE event_id=? ORDER BY id',(ev['id'],)).fetchall():
                d=dict(p); d['outcome_state']=jl(d.pop('outcome_state_json')); parts.append(d)
            # 因果链向上追溯 + 直接后果向下列出
            chain=[]; cur=ev
            for _ in range(CAUSE_CHAIN_MAX_DEPTH):
                cid=cur.get('cause_event_id')
                if cid is None: break
                row=db.execute('SELECT * FROM events WHERE id=?',(cid,)).fetchone()
                if not row: break
                cur=self._event_row(row); chain.append(cur)
            effects=[self._event_row(x) for x in db.execute('SELECT * FROM events WHERE cause_event_id=? ORDER BY chapter,id',(ev['id'],)).fetchall()]
        ev.update({'participants':parts,'cause_chain':chain,'caused_events':effects})
        return ev

    def event_timeline(self, entity_key: str | None = None, from_chapter: int | None = None,
                       to_chapter: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        limit=max(1,min(int(limit),500))
        with self.store.connect() as db:
            if entity_key:
                sql='''SELECT e.*,ep.participant_role FROM events e JOIN event_participants ep ON ep.event_id=e.id
                       WHERE ep.entity_key=?'''
                args=[entity_key]
            else:
                sql='SELECT e.* FROM events e WHERE 1=1'; args=[]
            if from_chapter is not None: sql+=' AND e.chapter>=?'; args.append(int(from_chapter))
            if to_chapter is not None: sql+=' AND e.chapter<=?'; args.append(int(to_chapter))
            sql+=' ORDER BY e.chapter,e.id LIMIT ?'; args.append(limit)
            rows=db.execute(sql,args).fetchall()
        return [self._event_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Assertion / Evidence
    # ------------------------------------------------------------------
    def assertion_create(self, subject_key: str, predicate: str, object_value: Any = None, chapter: int = 0,
                         subject_type: str = 'entity', source_span: str | None = None,
                         extractor: str = 'author_declared', confidence: float = 1.0,
                         evidence: str | None = None, event_id: int | None = None,
                         confirmed: bool = False) -> dict[str, Any]:
        """记录一条断言。抽取来源只能得到 candidate;confirmed=True 仅供
        作者显式动作(如 candidate_promote)使用。"""
        subject_key=(subject_key or '').strip(); predicate=(predicate or '').strip()
        if not subject_key or not predicate: raise ValueError('subject_key and predicate are required')
        with self.store.connect() as db:
            if event_id is not None and not db.execute('SELECT 1 FROM events WHERE id=?',(int(event_id),)).fetchone():
                raise KeyError(f'unknown event_id: {event_id}')
            cur=db.execute('''INSERT INTO fact_assertions(subject_type,subject_key,predicate,object_value,chapter,source_span,extractor,confidence,evidence,truth_status,event_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                (subject_type,subject_key,predicate,jd(object_value) if not isinstance(object_value,str) else object_value,
                 int(chapter),source_span,extractor,float(confidence),evidence,'confirmed' if confirmed else 'candidate',event_id))
            aid=int(cur.lastrowid)
        return self.assertion_get(aid)

    def assertion_get(self, assertion_id: int) -> dict[str, Any]:
        with self.store.connect() as db:
            r=db.execute('SELECT * FROM fact_assertions WHERE assertion_id=?',(int(assertion_id),)).fetchone()
        if not r: raise KeyError(f'unknown assertion_id: {assertion_id}')
        d=dict(r); d['object']=jl(d.pop('object_value'))
        return d

    def assertion_list(self, subject_key: str | None = None, subject_type: str | None = None,
                       predicate: str | None = None, truth_status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql='SELECT * FROM fact_assertions WHERE 1=1'; args=[]
        if subject_key: sql+=' AND subject_key=?'; args.append(subject_key)
        if subject_type: sql+=' AND subject_type=?'; args.append(subject_type)
        if predicate: sql+=' AND predicate=?'; args.append(predicate)
        if truth_status: sql+=' AND truth_status=?'; args.append(truth_status)
        sql+=' ORDER BY chapter,assertion_id LIMIT ?'; args.append(max(1,min(int(limit),500)))
        with self.store.connect() as db:
            rows=db.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['object']=jl(d.pop('object_value')); out.append(d)
        return out

    def assertion_resolve(self, assertion_id: int, truth_status: str, superseded_by: int | None = None) -> dict[str, Any]:
        if truth_status not in ASSERTION_TERMINAL:
            raise ValueError(f'truth_status must be one of {sorted(ASSERTION_TERMINAL)}')
        with self.store.connect() as db:
            r=db.execute('SELECT truth_status FROM fact_assertions WHERE assertion_id=?',(int(assertion_id),)).fetchone()
            if not r: raise KeyError(f'unknown assertion_id: {assertion_id}')
            if r['truth_status'] in ASSERTION_TERMINAL:
                raise ValueError(f'assertion {assertion_id} is already {r["truth_status"]}')
            if truth_status=='superseded':
                if superseded_by is None: raise ValueError('superseded resolution requires superseded_by')
                if int(superseded_by)==int(assertion_id): raise ValueError('assertion cannot supersede itself')
                if not db.execute('SELECT 1 FROM fact_assertions WHERE assertion_id=?',(int(superseded_by),)).fetchone():
                    raise KeyError(f'unknown superseded_by assertion: {superseded_by}')
            db.execute('UPDATE fact_assertions SET truth_status=?,superseded_by=? WHERE assertion_id=?',
                (truth_status,superseded_by,int(assertion_id)))
        return {'ok':True,'assertion_id':assertion_id,'truth_status':truth_status,'superseded_by':superseded_by}
