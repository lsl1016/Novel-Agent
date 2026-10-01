from __future__ import annotations
import json, sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from .schema import apply_migrations

def jd(v: Any)->str: return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def jl(v: str|None)->Any:
    if v is None:return None
    try:return json.loads(v)
    except Exception:return v

class _AmbientHandle:
    """加入环境事务的连接句柄:``with`` 退出时不提交不回滚。"""
    def __init__(self, db: sqlite3.Connection): self._db = db
    def __enter__(self): return self._db
    def __exit__(self, *exc): return False

class _ConnHandle(_AmbientHandle):
    """普通连接句柄:成功提交、异常回滚,退出时关闭连接。"""
    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None: self._db.commit()
            else: self._db.rollback()
        finally: self._db.close()

class StoryStore:
    """SQLite 故事库 + 环境事务。

    所有表结构由 :mod:`novel_mcp.schema` 的迁移框架统一建立与升级。
    ``transaction()`` 提供环境事务:事务期间所有 ``connect()`` 返回同一
    连接的只联接句柄,使跨仓储的多次写入具备单事务原子性;事务内不要
    执行 LLM/网络等慢操作。
    """
    def __init__(self,path:str|Path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self._tx: sqlite3.Connection|None = None
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            apply_migrations(db)

    def _open(self)->sqlite3.Connection:
        db=sqlite3.connect(self.path,timeout=10); db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=10000')
        return db

    def connect(self):
        if self._tx is not None:
            return _AmbientHandle(self._tx)
        return _ConnHandle(self._open())

    @contextmanager
    def transaction(self):
        if self._tx is not None:
            yield self._tx; return
        db=self._open(); db.execute('BEGIN IMMEDIATE')
        self._tx=db
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback(); raise
        finally:
            self._tx=None; db.close()

    def set_meta(self,key:str,value:Any):
        with self.connect() as db: db.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,jd(value)))
    def get_meta(self,key:str,default=None):
        with self.connect() as db:
            r=db.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
        return jl(r['value']) if r else default
    def upsert_thread(self,thread_key:str,name:str|None=None,**kw):
        name=name or thread_key
        cols=['thread_key','name','thread_type','status','introduced_chapter','target_min','target_max','main_goal','notes']
        vals=[thread_key,name,kw.get('thread_type','narrative'),kw.get('status','open'),kw.get('introduced_chapter'),kw.get('target_min'),kw.get('target_max'),kw.get('main_goal'),kw.get('notes')]
        with self.connect() as db:
            db.execute('''INSERT INTO threads(thread_key,name,thread_type,status,introduced_chapter,target_min,target_max,main_goal,notes) VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(thread_key) DO UPDATE SET name=COALESCE(NULLIF(excluded.name,''),threads.name),thread_type=COALESCE(excluded.thread_type,threads.thread_type),status=COALESCE(excluded.status,threads.status),introduced_chapter=COALESCE(threads.introduced_chapter,excluded.introduced_chapter),target_min=COALESCE(excluded.target_min,threads.target_min),target_max=COALESCE(excluded.target_max,threads.target_max),main_goal=COALESCE(excluded.main_goal,threads.main_goal),notes=COALESCE(excluded.notes,threads.notes)''',vals)
    def add_stage(self,thread_key:str,chapter:int,stage_type:str,content:str,**kw)->int:
        self.upsert_thread(thread_key,thread_key,introduced_chapter=chapter)
        with self.connect() as db:
            cur=db.execute('''INSERT INTO stages(thread_key,chapter,stage_type,content,strength,visibility,holder,status,callback_key,source,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(thread_key,chapter,stage_type,content,float(kw.get('strength',0)),kw.get('visibility','reader'),kw.get('holder'),kw.get('status','verified'),kw.get('callback_key'),kw.get('source','author_declared'),jd(kw.get('metadata',{}))))
            return int(cur.lastrowid)
    def thread(self,thread_key:str):
        with self.connect() as db:
            t=db.execute('SELECT * FROM threads WHERE thread_key=?',(thread_key,)).fetchone()
            if not t:return None
            ss=db.execute('SELECT * FROM stages WHERE thread_key=? ORDER BY chapter,id',(thread_key,)).fetchall()
        return {**dict(t),'stages':[{**dict(x),'metadata':jl(x['metadata_json'])} for x in ss]}
    def thread_exists(self,thread_key:str)->bool:
        with self.connect() as db:
            return db.execute('SELECT 1 FROM threads WHERE thread_key=?',(thread_key,)).fetchone() is not None
    def search_threads(self,query='',status=None,thread_type=None,limit=20):
        sql='SELECT * FROM threads WHERE 1=1'; args=[]
        if query: sql+=' AND (thread_key LIKE ? OR name LIKE ? OR notes LIKE ?)'; q=f'%{query}%'; args += [q,q,q]
        if status: sql+=' AND status=?'; args.append(status)
        if thread_type: sql+=' AND thread_type=?'; args.append(thread_type)
        sql+=' ORDER BY introduced_chapter,thread_key LIMIT ?'; args.append(limit)
        with self.connect() as db:return [dict(r) for r in db.execute(sql,args).fetchall()]
    def active_threads(self)->list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM threads WHERE status NOT IN ('resolved','closed') ORDER BY introduced_chapter,thread_key").fetchall()]
    def open_mysteries(self,max_introduced:int|None=None)->list[dict]:
        sql="SELECT * FROM mysteries WHERE status='open'"; args=[]
        if max_introduced is not None: sql+=' AND introduced_chapter<=?'; args.append(max_introduced)
        sql+=' ORDER BY introduced_chapter'
        with self.connect() as db:return [dict(r) for r in db.execute(sql,args).fetchall()]
    def open_debts(self,max_created:int|None=None)->list[dict]:
        sql="SELECT * FROM debts WHERE status!='resolved'"; args=[]
        if max_created is not None: sql+=' AND created_chapter<=?'; args.append(max_created)
        sql+=' ORDER BY created_chapter'
        with self.connect() as db:return [dict(r) for r in db.execute(sql,args).fetchall()]
    def open_obligation_thread_keys(self,snapshot_chapter:int)->set[str]:
        with self.connect() as db:
            rows=db.execute("SELECT thread_key FROM mysteries WHERE status='open' AND introduced_chapter<=? UNION SELECT thread_key FROM debts WHERE status!='resolved' AND created_chapter<=?",(snapshot_chapter,snapshot_chapter)).fetchall()
        return {r['thread_key'] for r in rows}
    def mystery_flow(self,lo:int,hi:int)->dict:
        with self.connect() as db:
            opened=db.execute('SELECT COUNT(*) n FROM mysteries WHERE introduced_chapter BETWEEN ? AND ?',(lo,hi)).fetchone()['n']
            resolved=db.execute('SELECT COUNT(*) n FROM mysteries WHERE resolved_chapter BETWEEN ? AND ?',(lo,hi)).fetchone()['n']
        return {'opened':opened,'resolved':resolved}
    def thread_stage_recency(self,snapshot_chapter:int,limit:int=100)->list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute('SELECT thread_key,MAX(chapter) mc FROM stages WHERE chapter<=? GROUP BY thread_key ORDER BY mc DESC LIMIT ?',(snapshot_chapter,limit)).fetchall()]
    def open_clues(self,cutoff:int,limit:int)->list[dict]:
        with self.connect() as db:
            rows=db.execute('''SELECT s.*,t.name thread_name FROM stages s JOIN threads t ON t.thread_key=s.thread_key WHERE s.stage_type IN ('Clue','Foreshadowing') AND s.chapter<=? AND NOT EXISTS (SELECT 1 FROM stages x WHERE x.thread_key=s.thread_key AND x.chapter>s.chapter AND x.stage_type IN ('Payoff','Reveal') AND x.callback_key=s.callback_key) ORDER BY s.chapter LIMIT ?''',(cutoff,limit)).fetchall()
        return [{**dict(r),'metadata':jl(r['metadata_json'])} for r in rows]
    def create_mystery(self,**x):
        self.upsert_thread(x['thread_key'],x['thread_key'],introduced_chapter=x['introduced_chapter'],target_min=x.get('target_min_chapter'),target_max=x.get('target_max_chapter'))
        with self.connect() as db:
            db.execute('''INSERT INTO mysteries(mystery_key,thread_key,name,status,introduced_chapter,target_min,target_max,notes) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(mystery_key) DO UPDATE SET name=excluded.name,thread_key=excluded.thread_key,target_min=COALESCE(excluded.target_min,mysteries.target_min),target_max=COALESCE(excluded.target_max,mysteries.target_max),notes=excluded.notes''',(x['mystery_key'],x['thread_key'],x['name'],'open',x['introduced_chapter'],x.get('target_min_chapter'),x.get('target_max_chapter'),x.get('notes','')))
        self.add_stage(x['thread_key'],x['introduced_chapter'],'Mystery',x['name'],metadata={'mystery_key':x['mystery_key']})
    def add_belief(self,**x):
        with self.connect() as db:
            db.execute('''INSERT INTO beliefs(fact_key,holder,chapter,stance,value_json,confidence,source) VALUES(?,?,?,?,?,?,?) ON CONFLICT(fact_key,holder,chapter) DO UPDATE SET stance=excluded.stance,value_json=excluded.value_json,confidence=excluded.confidence,source=excluded.source''',(x['fact_key'],x['holder'],x['chapter'],x['stance'],jd(x.get('value')),x.get('confidence',1),x.get('source','author_declared')))
    def set_world_fact(self,fact_key,truth,secrecy='secret',reveal_after=None,notes=''):
        with self.connect() as db:
            db.execute('''INSERT INTO world_facts(fact_key,truth_json,secrecy,reveal_after,notes) VALUES(?,?,?,?,?) ON CONFLICT(fact_key) DO UPDATE SET truth_json=excluded.truth_json,secrecy=excluded.secrecy,reveal_after=excluded.reveal_after,notes=excluded.notes''',(fact_key,jd(truth),secrecy,reveal_after,notes))
            # 双时序:reveal_after 即 reader 的计划知晓时刻,同步为披露行保持单一语义
            if reveal_after is not None:
                db.execute('''INSERT INTO fact_disclosures(fact_key,holder,known_from_chapter,source) VALUES(?,'reader',?,'reveal_after_sync')
                    ON CONFLICT(fact_key,holder) DO UPDATE SET known_from_chapter=excluded.known_from_chapter''',(fact_key,int(reveal_after)))
    def belief_snapshot(self,fact_key:str,chapter:int):
        with self.connect() as db:
            wf=db.execute('SELECT * FROM world_facts WHERE fact_key=?',(fact_key,)).fetchone()
            rows=db.execute('''SELECT b.* FROM beliefs b JOIN (SELECT holder,MAX(chapter) mc FROM beliefs WHERE fact_key=? AND chapter<=? GROUP BY holder) x ON b.holder=x.holder AND b.chapter=x.mc WHERE b.fact_key=? ORDER BY b.holder''',(fact_key,chapter,fact_key)).fetchall()
        out={'fact_key':fact_key,'chapter':chapter,'world_truth':None,'holders':{}}
        if wf: out['world_truth']={'value':jl(wf['truth_json']),'secrecy':wf['secrecy'],'reveal_after':wf['reveal_after'],'notes':wf['notes']}
        for r in rows: out['holders'][r['holder']]={'stance':r['stance'],'value':jl(r['value_json']),'confidence':r['confidence'],'chapter':r['chapter'],'source':r['source']}
        return out
    def fact_known_from(self,fact_key:str,holder:str)->int|None:
        """双时序:该持有者对此事实的计划知晓时刻(knowledge_time)。

        取 per-holder 披露、reader 披露(reader 即全局公开,与旧 reveal_after
        语义一致)三者中最早者;无任何计划则返回 None(只能经确认信念或
        显式 declared reveal 合法知晓)。
        """
        with self.connect() as db:
            rows=db.execute('SELECT holder,known_from_chapter FROM fact_disclosures WHERE fact_key=?',(fact_key,)).fetchall()
            ra=db.execute('SELECT reveal_after FROM world_facts WHERE fact_key=?',(fact_key,)).fetchone()
        cands=[int(r['known_from_chapter']) for r in rows if r['holder'] in (holder,'reader')]
        if ra is not None and ra['reveal_after'] is not None: cands.append(int(ra['reveal_after']))
        return min(cands) if cands else None
    def create_debt(self,**x):
        self.upsert_thread(x['thread_key'],x['thread_key'],introduced_chapter=x['created_chapter'])
        with self.connect() as db: db.execute('''INSERT INTO debts(debt_key,thread_key,name,emotion_type,intensity,created_chapter,target_holder,status,notes) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(debt_key) DO UPDATE SET name=excluded.name,intensity=excluded.intensity,target_holder=excluded.target_holder,notes=excluded.notes''',(x['debt_key'],x['thread_key'],x['name'],x['emotion_type'],x['intensity'],x['created_chapter'],x.get('target_holder'),'open',x.get('notes','')))
        self.add_stage(x['thread_key'],x['created_chapter'],'EmotionDebt',x['name'],strength=x['intensity'],metadata={'debt_key':x['debt_key'],'emotion_type':x['emotion_type']})
    def resolve_debt(self,debt_key,chapter,content,resolution='full',consequence=''):
        with self.connect() as db:
            d=db.execute('SELECT * FROM debts WHERE debt_key=?',(debt_key,)).fetchone()
            if not d: raise KeyError(f'unknown debt_key: {debt_key}')
            status='resolved' if resolution=='full' else 'partial'
            db.execute('UPDATE debts SET status=?,resolved_chapter=?,resolution=?,consequence=? WHERE debt_key=?',(status,chapter,resolution,consequence,debt_key))
        self.add_stage(d['thread_key'],chapter,'Payoff',content,strength=d['intensity'],metadata={'debt_key':debt_key,'resolution':resolution,'consequence':consequence})
    def commit_chapter(self,chapter,title,body,arc='',pov='',summary=''):
        # 列序 (chapter,title,arc,pov,summary,body) 与参数必须严格对齐;
        # V0.7 起曾错位导致正文落入 arc 列,由 Phase B 长跑发现并修复。
        with self.connect() as db: db.execute('''INSERT INTO chapters(chapter,title,arc,pov,summary,body) VALUES(?,?,?,?,?,?) ON CONFLICT(chapter) DO UPDATE SET title=excluded.title,arc=excluded.arc,pov=excluded.pov,summary=excluded.summary,body=excluded.body,committed_at=CURRENT_TIMESTAMP''',(chapter,title,arc,pov,summary,body))
    def add_event(self,chapter,name,event_key=None,event_type='event',thread_key=None,status='verified',metadata=None):
        with self.connect() as db: db.execute('INSERT INTO events(chapter,event_key,name,event_type,thread_key,status,metadata_json) VALUES(?,?,?,?,?,?,?)',(chapter,event_key,name,event_type,thread_key,status,jd(metadata or {})))
    def add_character_state(self,character_key,chapter,state,source='author_declared'):
        with self.connect() as db: db.execute('INSERT INTO character_states(character_key,chapter,state_json,source) VALUES(?,?,?,?)',(character_key,chapter,jd(state),source))
    def add_candidate(self,chapter,node_type,name,payload):
        with self.connect() as db: db.execute('INSERT INTO extraction_candidates(chapter,node_type,name,payload_json) VALUES(?,?,?,?)',(chapter,node_type,name,jd(payload)))
