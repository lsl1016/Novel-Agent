from __future__ import annotations
from collections import deque
from typing import Any
from .store import jd,jl

ENTITY_TYPES={
    'Character','Faction','Location','Item','Skill','Realm','Artifact','Organization',
    'Bloodline','Event','Creature','Race','Concept','Resource','Other'
}

IDENTITY_KINDS={'name','alias','role','title','position','incarnation','disguise','pseudonym','other'}

# 专业子图的属性/关系键约定(Phase A)。底层仍是时序属性与关系原语,
# 这些常量只定义聚合视图的默认收集范围。
POWER_ATTR_KEYS={'realm','cultivation','bloodline','physique','constitution','element','skill','technique','legacy','power_level'}
POWER_RELATION_TYPES={'MASTER_OF','TAUGHT_BY','INHERITS_FROM','CULTIVATES','BELONGS_TO_LINEAGE','AWAKENED_OF'}
ARTIFACT_ATTR_KEYS={'seal_state','spirit','grade','awakening_state','refine_level','artifact_type'}
ARTIFACT_RELATION_TYPES={'OWNS','HELD_BY','BOUND_TO','SEALED_IN','HOUSED_IN','FUSED_WITH','AWAKENED_BY','REFINED_BY','REGISTERED_TO','SPIRIT_OF'}
GEO_RELATION_TYPES={'LOCATED_IN','PART_OF','TERRITORY_OF','WITHIN','BORDERS'}

class EntityGraph:
    """叠加在 StoryStore 之上的时序实体图。

    核心实体行与公开属性是作者层权威的世界结构。
    秘密应存放在带 secrecy/reveal_after/fact_key 的别名/属性/关系中,
    以便安全检索可以在读者/视角上下文中过滤它们。
    """
    def __init__(self,store): self.store=store

    def _exists(self,key:str)->bool:
        with self.store.connect() as db:
            return db.execute('SELECT 1 FROM entities WHERE entity_key=?',(key,)).fetchone() is not None

    def upsert_entity(self,entity_key:str,entity_type:str,name:str,chapter:int|None=None,status:str='active',description:str='',properties:dict|None=None,source:str='author_declared'):
        entity_key=(entity_key or '').strip(); entity_type=(entity_type or '').strip(); name=(name or '').strip()
        if not entity_key or not entity_type or not name: raise ValueError('entity_key, entity_type and name are required')
        if properties is not None and not isinstance(properties,dict): raise ValueError('properties must be an object')
        with self.store.connect() as db:
            old=db.execute('SELECT * FROM entities WHERE entity_key=?',(entity_key,)).fetchone()
            if old and old['entity_type']!=entity_type:
                raise ValueError(f'entity type is immutable for {entity_key}: {old["entity_type"]} -> {entity_type}')
            db.execute('''INSERT INTO entities(entity_key,entity_type,name,status,introduced_chapter,description,properties_json,source)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(entity_key) DO UPDATE SET
                  name=excluded.name,status=excluded.status,
                  introduced_chapter=COALESCE(entities.introduced_chapter,excluded.introduced_chapter),
                  description=excluded.description,properties_json=excluded.properties_json,
                  source=excluded.source,updated_at=CURRENT_TIMESTAMP''',
                (entity_key,entity_type,name,status,chapter,description,jd(properties or {}),source))
        return self.get(entity_key,chapter if chapter is not None else 10**9,author=True)

    def add_alias(self,entity_key:str,alias:str,alias_type:str='alias',secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,source:str='author_declared'):
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        alias=(alias or '').strip()
        if not alias: raise ValueError('alias is required')
        with self.store.connect() as db:
            db.execute('''INSERT INTO entity_aliases(entity_key,alias,alias_type,secrecy,reveal_after,fact_key,source)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(entity_key,alias) DO UPDATE SET alias_type=excluded.alias_type,secrecy=excluded.secrecy,reveal_after=excluded.reveal_after,fact_key=excluded.fact_key,source=excluded.source''',
                (entity_key,alias,alias_type,secrecy,reveal_after,fact_key,source))
        return {'ok':True,'entity_key':entity_key,'alias':alias}

    def set_attribute(self,entity_key:str,attr_key:str,value:Any,chapter:int=0,end_chapter:int|None=None,secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,source:str='author_declared',confidence:float=1.0,close_previous:bool=True,cause_event_id:int|None=None):
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        attr_key=(attr_key or '').strip()
        if not attr_key: raise ValueError('attr_key is required')
        chapter=int(chapter)
        if end_chapter is not None and int(end_chapter)<chapter: raise ValueError('end_chapter must be >= chapter')
        with self.store.connect() as db:
            if cause_event_id is not None and not db.execute('SELECT 1 FROM events WHERE id=?',(int(cause_event_id),)).fetchone():
                raise KeyError(f'unknown cause_event_id: {cause_event_id}')
            if close_previous:
                db.execute('''UPDATE entity_attributes SET end_chapter=? WHERE entity_key=? AND attr_key=? AND start_chapter<? AND (end_chapter IS NULL OR end_chapter>=?)''',(chapter-1,entity_key,attr_key,chapter,chapter))
            db.execute('''INSERT INTO entity_attributes(entity_key,attr_key,value_json,start_chapter,end_chapter,secrecy,reveal_after,fact_key,source,confidence,cause_event_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(entity_key,attr_key,start_chapter) DO UPDATE SET value_json=excluded.value_json,end_chapter=excluded.end_chapter,secrecy=excluded.secrecy,reveal_after=excluded.reveal_after,fact_key=excluded.fact_key,source=excluded.source,confidence=excluded.confidence,cause_event_id=excluded.cause_event_id''',
                (entity_key,attr_key,jd(value),chapter,end_chapter,secrecy,reveal_after,fact_key,source,float(confidence),cause_event_id))
        return {'ok':True,'entity_key':entity_key,'attr_key':attr_key,'chapter':chapter,'value':value,'cause_event_id':cause_event_id}

    def upsert_relation(self,source_entity_key:str,relation_type:str,target_entity_key:str,start_chapter:int=0,end_chapter:int|None=None,status:str='active',secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,properties:dict|None=None,source:str='author_declared',cause_event_id:int|None=None):
        if not self._exists(source_entity_key): raise KeyError(f'unknown entity_key: {source_entity_key}')
        if not self._exists(target_entity_key): raise KeyError(f'unknown entity_key: {target_entity_key}')
        relation_type=(relation_type or '').strip().upper()
        if not relation_type: raise ValueError('relation_type is required')
        start_chapter=int(start_chapter)
        if end_chapter is not None and int(end_chapter)<start_chapter: raise ValueError('end_chapter must be >= start_chapter')
        with self.store.connect() as db:
            if cause_event_id is not None and not db.execute('SELECT 1 FROM events WHERE id=?',(int(cause_event_id),)).fetchone():
                raise KeyError(f'unknown cause_event_id: {cause_event_id}')
            db.execute('''INSERT INTO entity_relations(source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter,status,secrecy,reveal_after,fact_key,properties_json,source,cause_event_id)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source_entity_key,relation_type,target_entity_key,start_chapter) DO UPDATE SET
                  end_chapter=excluded.end_chapter,status=excluded.status,secrecy=excluded.secrecy,reveal_after=excluded.reveal_after,fact_key=excluded.fact_key,properties_json=excluded.properties_json,source=excluded.source,cause_event_id=excluded.cause_event_id''',
                (source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter,status,secrecy,reveal_after,fact_key,jd(properties or {}),source,cause_event_id))
            r=db.execute('SELECT id FROM entity_relations WHERE source_entity_key=? AND relation_type=? AND target_entity_key=? AND start_chapter=?',(source_entity_key,relation_type,target_entity_key,start_chapter)).fetchone()
        return {'ok':True,'relation_id':r['id'],'source_entity_key':source_entity_key,'relation_type':relation_type,'target_entity_key':target_entity_key,'cause_event_id':cause_event_id}

    def end_relation(self,source_entity_key:str,relation_type:str,target_entity_key:str,chapter:int):
        with self.store.connect() as db:
            cur=db.execute('''UPDATE entity_relations SET end_chapter=?,status='ended' WHERE source_entity_key=? AND relation_type=? AND target_entity_key=? AND status='active' AND start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?)''',(chapter,source_entity_key,relation_type.upper(),target_entity_key,chapter,chapter))
        if not cur.rowcount: raise KeyError('active relation not found')
        return {'ok':True,'ended':cur.rowcount,'chapter':chapter}

    def link_narrative(self,narrative_type:str,narrative_key:str,entity_key:str,role:str='involves',chapter:int=0,properties:dict|None=None,source:str='author_declared'):
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        if not narrative_type or not narrative_key: raise ValueError('narrative_type and narrative_key are required')
        with self.store.connect() as db:
            db.execute('''INSERT INTO narrative_entity_links(narrative_type,narrative_key,entity_key,role,chapter,properties_json,source)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(narrative_type,narrative_key,entity_key,role,chapter) DO UPDATE SET properties_json=excluded.properties_json,source=excluded.source''',
                (narrative_type,narrative_key,entity_key,role,chapter,jd(properties or {}),source))
        return {'ok':True,'narrative_type':narrative_type,'narrative_key':narrative_key,'entity_key':entity_key,'role':role}

    def narrative_links(self,entity_key:str|None=None,narrative_type:str|None=None,narrative_key:str|None=None,limit:int=100):
        sql='SELECT * FROM narrative_entity_links WHERE 1=1'; args=[]
        if entity_key: sql+=' AND entity_key=?'; args.append(entity_key)
        if narrative_type: sql+=' AND narrative_type=?'; args.append(narrative_type)
        if narrative_key: sql+=' AND narrative_key=?'; args.append(narrative_key)
        sql+=' ORDER BY chapter,id LIMIT ?'; args.append(int(limit))
        with self.store.connect() as db: rows=db.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); raw=d.pop('properties_json',None); d['properties']=jl(raw) if raw is not None else {}; out.append(d)
        return out

    def _fact_known(self,fact_key:str|None,chapter:int,holder:str)->bool:
        if not fact_key: return False
        snap=self.store.belief_snapshot(fact_key,chapter)
        truth=((snap.get('world_truth') or {}).get('value'))
        holders=['reader'] if holder=='reader' else ['reader',holder]
        for h in holders:
            belief=(snap.get('holders',{}).get(h) or {})
            stance=belief.get('stance')
            if stance=='confirmed': return True
            if stance=='believes' and truth is not None and belief.get('value')==truth: return True
        kf=self.store.fact_known_from(fact_key,holder)
        return kf is not None and chapter>=kf

    def _visible(self,row,chapter:int,holder:str,author:bool=False)->bool:
        if author: return True
        secrecy=row['secrecy'] if 'secrecy' in row.keys() else 'public'
        if secrecy=='public': return True
        ra=row['reveal_after'] if 'reveal_after' in row.keys() else None
        if ra is not None and chapter>=int(ra): return True
        fk=row['fact_key'] if 'fact_key' in row.keys() else None
        return self._fact_known(fk,chapter,holder)

    def _entity_core(self,row):
        d=dict(row); raw=d.pop('properties_json',None); d['properties']=jl(raw) if raw is not None else {}
        return d

    def get(self,entity_key:str,chapter:int,holder:str='reader',author:bool=False,include_inactive:bool=False):
        with self.store.connect() as db:
            e=db.execute('SELECT * FROM entities WHERE entity_key=?',(entity_key,)).fetchone()
            if not e: return None
            aliases=db.execute('SELECT * FROM entity_aliases WHERE entity_key=? ORDER BY id',(entity_key,)).fetchall()
            attrs=db.execute('''SELECT * FROM entity_attributes WHERE entity_key=? AND start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?) ORDER BY attr_key,start_chapter DESC,id DESC''',(entity_key,chapter,chapter)).fetchall()
            rels=db.execute('''SELECT * FROM entity_relations WHERE (source_entity_key=? OR target_entity_key=?) AND start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?) ORDER BY id''',(entity_key,entity_key,chapter,chapter)).fetchall()
            cs=db.execute('SELECT * FROM character_states WHERE character_key=? AND chapter<=? ORDER BY chapter DESC LIMIT 1',(entity_key,chapter)).fetchone()
        if not include_inactive and e['status'] not in {'active','unknown'}: return None
        visible_aliases=[dict(r) for r in aliases if self._visible(r,chapter,holder,author)]
        # 每个 attr_key 仅保留最新一条可见行
        attr_out={}
        for r in attrs:
            if r['attr_key'] in attr_out or not self._visible(r,chapter,holder,author): continue
            d=dict(r); raw=d.pop('value_json',None); d['value']=jl(raw); attr_out[r['attr_key']]=d
        rel_out=[]
        for r in rels:
            if not self._visible(r,chapter,holder,author): continue
            d=dict(r); raw=d.pop('properties_json',None); d['properties']=jl(raw) if raw is not None else {}
            d['direction']='out' if r['source_entity_key']==entity_key else 'in'
            rel_out.append(d)
        links=self.narrative_links(entity_key=entity_key,limit=100)
        out=self._entity_core(e)
        out.update({'chapter':chapter,'view':'author' if author else holder,'aliases':visible_aliases,'identity_profiles':self.identity_profiles(entity_key,chapter,holder,author),'attributes':attr_out,'relations':rel_out,'narrative_links':links})
        if cs: out['legacy_character_state']={**dict(cs),'state':jl(cs['state_json'])}
        return out

    def search(self,query:str='',entity_type:str|None=None,status:str|None='active',chapter:int=10**9,holder:str='reader',author:bool=False,limit:int=20):
        q=(query or '').strip(); sql='SELECT DISTINCT e.* FROM entities e LEFT JOIN entity_aliases a ON a.entity_key=e.entity_key WHERE 1=1'; args=[]
        if entity_type: sql+=' AND e.entity_type=?'; args.append(entity_type)
        if status: sql+=' AND e.status=?'; args.append(status)
        if q:
            sql+=' AND (e.entity_key LIKE ? OR e.name LIKE ? OR e.description LIKE ? OR a.alias LIKE ?)'; like=f'%{q}%'; args += [like,like,like,like]
        sql+=' ORDER BY e.introduced_chapter,e.entity_key LIMIT ?'; args.append(max(1,min(int(limit),200))*3)
        with self.store.connect() as db: rows=db.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            # 防止秘密别名成为搜索侧信道:确认查询匹配核心字段或某条可见别名
            if q and q not in r['entity_key'] and q not in r['name'] and q not in (r['description'] or ''):
                with self.store.connect() as db:
                    als=db.execute('SELECT * FROM entity_aliases WHERE entity_key=? AND alias LIKE ?',(r['entity_key'],f'%{q}%')).fetchall()
                if not any(self._visible(a,chapter,holder,author) for a in als): continue
            out.append({'entity_key':r['entity_key'],'entity_type':r['entity_type'],'name':r['name'],'status':r['status'],'introduced_chapter':r['introduced_chapter'],'description':r['description']})
            if len(out)>=limit: break
        return out

    def _visible_edges(self,chapter:int,holder:str,author:bool,relation_types:list[str]|None=None):
        sql='SELECT * FROM entity_relations WHERE start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?)'; args=[chapter,chapter]
        if relation_types:
            rts=[x.upper() for x in relation_types]; sql+=' AND relation_type IN ('+','.join('?' for _ in rts)+')'; args.extend(rts)
        with self.store.connect() as db: rows=db.execute(sql,args).fetchall()
        return [r for r in rows if self._visible(r,chapter,holder,author)]

    def neighbors(self,entity_key:str,chapter:int,holder:str='reader',author:bool=False,relation_types:list[str]|None=None,direction:str='both',depth:int=1,limit:int=100):
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        depth=max(1,min(int(depth),4)); limit=max(1,min(int(limit),500)); edges=self._visible_edges(chapter,holder,author,relation_types)
        adj={}
        for r in edges:
            if direction in {'both','out'}: adj.setdefault(r['source_entity_key'],[]).append((r['target_entity_key'],r,'out'))
            if direction in {'both','in'}: adj.setdefault(r['target_entity_key'],[]).append((r['source_entity_key'],r,'in'))
        seen={entity_key}; q=deque([(entity_key,0)]); out_edges=[]
        while q and len(out_edges)<limit:
            cur,d=q.popleft()
            if d>=depth: continue
            for nxt,r,dirn in adj.get(cur,[]):
                ed=dict(r); raw=ed.pop('properties_json',None); ed['properties']=jl(raw) if raw is not None else {}; ed['traversal_direction']=dirn; out_edges.append(ed)
                if nxt not in seen:
                    seen.add(nxt); q.append((nxt,d+1))
                if len(out_edges)>=limit: break
        nodes=[]
        with self.store.connect() as db:
            for k in sorted(seen):
                r=db.execute('SELECT * FROM entities WHERE entity_key=?',(k,)).fetchone()
                if r: nodes.append({'entity_key':r['entity_key'],'entity_type':r['entity_type'],'name':r['name'],'status':r['status']})
        return {'root':entity_key,'chapter':chapter,'view':'author' if author else holder,'nodes':nodes,'edges':out_edges}

    def path_find(self,source_entity_key:str,target_entity_key:str,chapter:int,holder:str='reader',author:bool=False,relation_types:list[str]|None=None,max_depth:int=4):
        if not self._exists(source_entity_key) or not self._exists(target_entity_key): raise KeyError('source or target entity not found')
        max_depth=max(1,min(int(max_depth),6)); edges=self._visible_edges(chapter,holder,author,relation_types)
        adj={}
        for r in edges:
            adj.setdefault(r['source_entity_key'],[]).append((r['target_entity_key'],r,'out'))
            adj.setdefault(r['target_entity_key'],[]).append((r['source_entity_key'],r,'in'))
        q=deque([(source_entity_key,[])]); seen={source_entity_key}
        while q:
            cur,path=q.popleft()
            if len(path)>=max_depth: continue
            for nxt,r,dirn in adj.get(cur,[]):
                step=dict(r); raw=step.pop('properties_json',None); step['properties']=jl(raw) if raw is not None else {}; step['traversal_direction']=dirn
                np=path+[step]
                if nxt==target_entity_key: return {'found':True,'chapter':chapter,'path':np,'hop_count':len(np)}
                if nxt not in seen: seen.add(nxt); q.append((nxt,np))
        return {'found':False,'chapter':chapter,'path':[],'hop_count':None}

    def context(self,entity_keys:list[str],chapter:int,holder:str='reader',author:bool=False,depth:int=1,limit:int=100):
        keys=list(dict.fromkeys([x for x in entity_keys if isinstance(x,str) and x.strip()]))[:50]
        entities=[self.get(k,chapter,holder,author) for k in keys]
        entities=[x for x in entities if x]
        subgraphs=[self.neighbors(k,chapter,holder,author,depth=depth,limit=max(10,limit//max(1,len(keys)))) for k in keys if self._exists(k)] if depth>0 else []
        return {'chapter':chapter,'view':'author' if author else holder,'entities':entities,'subgraphs':subgraphs}

    def stats(self):
        with self.store.connect() as db:
            types=[dict(r) for r in db.execute('SELECT entity_type,COUNT(*) count FROM entities GROUP BY entity_type ORDER BY count DESC,entity_type').fetchall()]
            rels=[dict(r) for r in db.execute('SELECT relation_type,COUNT(*) count FROM entity_relations GROUP BY relation_type ORDER BY count DESC,relation_type').fetchall()]
            counts={
                'entities':db.execute('SELECT COUNT(*) n FROM entities').fetchone()['n'],
                'aliases':db.execute('SELECT COUNT(*) n FROM entity_aliases').fetchone()['n'],
                'attributes':db.execute('SELECT COUNT(*) n FROM entity_attributes').fetchone()['n'],
                'relations':db.execute('SELECT COUNT(*) n FROM entity_relations').fetchone()['n'],
                'narrative_links':db.execute('SELECT COUNT(*) n FROM narrative_entity_links').fetchone()['n'],
            }
        return {'counts':counts,'entity_types':types,'relation_types':rels}

    def identity_profile_put(self,x:dict):
        """V2 Identity/Role:本名/假名/伪装/官职/神位/称号/转世的一等档案。

        kind 表身份类别;parent_profile_key 串起转世/身份接续链;secrecy/
        reveal_after/fact_key 与别名同规则,安全视图按可见性过滤。
        """
        profile_key=(x.get('profile_key') or '').strip(); entity_key=(x.get('entity_key') or '').strip()
        kind=(x.get('kind') or '').strip(); value=(x.get('value') or '').strip()
        if not profile_key or not entity_key or not value: raise ValueError('profile_key, entity_key and value are required')
        if kind not in IDENTITY_KINDS: raise ValueError(f'kind must be one of {sorted(IDENTITY_KINDS)}')
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        start=int(x.get('start_chapter',0) or 0); end=x.get('end_chapter')
        if end is not None and int(end)<start: raise ValueError('end_chapter must be >= start_chapter')
        parent=x.get('parent_profile_key')
        if parent is not None and parent==profile_key: raise ValueError('parent_profile_key cannot reference itself')
        with self.store.connect() as db:
            db.execute('''INSERT INTO identity_profiles(profile_key,entity_key,kind,value,scope_key,secrecy,reveal_after,fact_key,start_chapter,end_chapter,parent_profile_key,notes,source,confidence)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(profile_key) DO UPDATE SET
                entity_key=excluded.entity_key,kind=excluded.kind,value=excluded.value,scope_key=excluded.scope_key,
                secrecy=excluded.secrecy,reveal_after=excluded.reveal_after,fact_key=excluded.fact_key,
                start_chapter=excluded.start_chapter,end_chapter=excluded.end_chapter,parent_profile_key=excluded.parent_profile_key,
                notes=excluded.notes,source=excluded.source,confidence=excluded.confidence''',
              (profile_key,entity_key,kind,value,x.get('scope_key'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),start,end,parent,x.get('notes',''),x.get('source','author_declared'),float(x.get('confidence',1))))
        return {'ok':True,'profile_key':profile_key,'entity_key':entity_key,'kind':kind,'value':value}

    def identity_profiles(self,entity_key:str,chapter:int,holder:str='reader',author:bool=False)->list[dict]:
        with self.store.connect() as db:
            rows=db.execute('SELECT * FROM identity_profiles WHERE entity_key=? AND start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?) ORDER BY start_chapter,profile_key',(entity_key,chapter,chapter)).fetchall()
        return [dict(r) for r in rows if self._visible(r,chapter,holder,author)]

    # ------------------------------------------------------------------
    # 专业子图聚合视图(Phase A):Power / Artifact / Geography
    # ------------------------------------------------------------------
    def _events_by_ids(self,ids:set[int])->dict[int,dict]:
        if not ids: return {}
        qs=','.join('?' for _ in ids)
        with self.store.connect() as db:
            rows=db.execute(f'SELECT id,event_key,name,chapter FROM events WHERE id IN ({qs})',list(ids)).fetchall()
        return {r['id']:dict(r) for r in rows}

    def attribute_history(self,entity_key:str,attr_keys:set[str]|None=None)->list[dict]:
        sql='SELECT * FROM entity_attributes WHERE entity_key=?'; args=[entity_key]
        if attr_keys:
            ks=sorted(attr_keys); sql+=' AND attr_key IN ('+','.join('?' for _ in ks)+')'; args.extend(ks)
        sql+=' ORDER BY attr_key,start_chapter,id'
        with self.store.connect() as db:
            rows=db.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['value']=jl(d.pop('value_json')); out.append(d)
        ev=self._events_by_ids({r['cause_event_id'] for r in out if r.get('cause_event_id') is not None})
        for d in out:
            d['cause_event']=ev.get(d.get('cause_event_id'))
        return out

    def relation_history(self,entity_key:str,relation_types:set[str]|None=None)->list[dict]:
        sql='SELECT * FROM entity_relations WHERE (source_entity_key=? OR target_entity_key=?)'; args=[entity_key,entity_key]
        if relation_types:
            rts=sorted(relation_types); sql+=' AND relation_type IN ('+','.join('?' for _ in rts)+')'; args.extend(rts)
        sql+=' ORDER BY start_chapter,id'
        with self.store.connect() as db:
            rows=db.execute(sql,args).fetchall()
        out=[]
        for r in rows:
            d=dict(r); d['properties']=jl(d.pop('properties_json')) or {}
            d['direction']='out' if r['source_entity_key']==entity_key else 'in'
            out.append(d)
        ev=self._events_by_ids({r['cause_event_id'] for r in out if r.get('cause_event_id') is not None})
        for d in out:
            d['cause_event']=ev.get(d.get('cause_event_id'))
        return out

    def power_context(self,entity_key:str,chapter:int)->dict:
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        current={}
        for d in self.attribute_history(entity_key,POWER_ATTR_KEYS):
            active=d['end_chapter'] is None or d['end_chapter']>=chapter
            if active and d['start_chapter']<=chapter and d['attr_key'] not in current:
                current[d['attr_key']]=d['value']
        return {
            'entity_key':entity_key,'chapter':chapter,'view':'author',
            'current_power_state':current,
            'progression_ladders':self.attribute_history(entity_key,POWER_ATTR_KEYS),
            'lineage_relations':self.relation_history(entity_key,POWER_RELATION_TYPES),
        }

    def artifact_history(self,entity_key:str)->dict:
        if not self._exists(entity_key): raise KeyError(f'unknown entity_key: {entity_key}')
        return {
            'entity_key':entity_key,'view':'author',
            'custody_and_state':self.relation_history(entity_key,ARTIFACT_RELATION_TYPES),
            'attribute_ladders':self.attribute_history(entity_key,ARTIFACT_ATTR_KEYS),
        }

    def geography_subtree(self,root_entity_key:str,chapter:int,holder:str='reader',relation_types:list[str]|None=None,max_depth:int=4,limit:int=100)->dict:
        if not self._exists(root_entity_key): raise KeyError(f'unknown entity_key: {root_entity_key}')
        max_depth=max(1,min(int(max_depth),8)); limit=max(1,min(int(limit),500))
        rts={x.upper() for x in (relation_types or GEO_RELATION_TYPES)}
        edges=self._visible_edges(chapter,holder,False,sorted(rts))
        contains={}
        for r in edges:
            # LOCATED_IN/PART_OF 语义:source 是 target 的一部分 → target 包含 source
            contains.setdefault(r['target_entity_key'],[]).append((r['source_entity_key'],r))
        seen={root_entity_key}; out_edges=[]; depth_reached=0
        frontier=[(root_entity_key,0)]
        while frontier and len(out_edges)<limit:
            cur,d=frontier.pop(0)
            depth_reached=max(depth_reached,d)
            if d>=max_depth: continue
            for child,edge in contains.get(cur,[]):
                e=dict(edge); e['properties']=jl(e.pop('properties_json')) or {}; out_edges.append(e)
                if child not in seen:
                    seen.add(child); frontier.append((child,d+1))
                if len(out_edges)>=limit: break
        nodes=[]
        with self.store.connect() as db:
            for k in sorted(seen):
                r=db.execute('SELECT entity_key,entity_type,name,status,introduced_chapter,retired_chapter FROM entities WHERE entity_key=?',(k,)).fetchone()
                if r: nodes.append(dict(r))
        return {'root':root_entity_key,'chapter':chapter,'view':holder,'depth_reached':depth_reached,'nodes':nodes,'edges':out_edges}

    def linked_entity_rows(self,narrative_type:str,narrative_key:str,max_chapter:int)->list[dict]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT entity_key,role FROM narrative_entity_links WHERE narrative_type=? AND narrative_key=? AND chapter<=? ORDER BY chapter DESC,id DESC',(narrative_type,narrative_key,max_chapter)).fetchall()]

    def recent_link_rows(self,max_chapter:int,limit:int=100)->list[dict]:
        with self.store.connect() as db:
            return [dict(r) for r in db.execute('SELECT entity_key,MAX(chapter) mc FROM narrative_entity_links WHERE chapter<=? GROUP BY entity_key ORDER BY mc DESC LIMIT ?',(max_chapter,limit)).fetchall()]

    def active_fallback_keys(self,max_chapter:int,limit:int)->list[str]:
        with self.store.connect() as db:
            return [r['entity_key'] for r in db.execute("SELECT entity_key FROM entities WHERE status='active' AND (introduced_chapter IS NULL OR introduced_chapter<=?) ORDER BY COALESCE(introduced_chapter,0) DESC,entity_key LIMIT ?",(max_chapter,limit)).fetchall()]

    def check(self,chapter:int,entities:list|None=None,attributes:list|None=None,relations:list|None=None):
        entities=entities or []; attributes=attributes or []; relations=relations or []; errors=[]; warnings=[]
        proposed={x.get('entity_key') for x in entities if isinstance(x,dict) and x.get('entity_key')}
        def known(k): return k in proposed or self._exists(k)
        for x in entities:
            if not isinstance(x,dict) or not x.get('entity_key') or not x.get('entity_type') or not x.get('name'):
                errors.append({'code':'ENTITY_REQUIRED_FIELDS','entity':x}); continue
            with self.store.connect() as db: old=db.execute('SELECT entity_type FROM entities WHERE entity_key=?',(x['entity_key'],)).fetchone()
            if old and old['entity_type']!=x['entity_type']: errors.append({'code':'ENTITY_TYPE_CONFLICT','entity_key':x['entity_key'],'existing':old['entity_type'],'proposed':x['entity_type']})
        for x in attributes:
            if not isinstance(x,dict) or not x.get('entity_key') or not x.get('attr_key'): errors.append({'code':'ATTRIBUTE_REQUIRED_FIELDS','attribute':x}); continue
            if not known(x['entity_key']): errors.append({'code':'ATTRIBUTE_ENTITY_MISSING','entity_key':x['entity_key']})
            st=int(x.get('chapter',chapter)); en=x.get('end_chapter')
            if en is not None and int(en)<st: errors.append({'code':'ATTRIBUTE_INVALID_WINDOW','entity_key':x['entity_key'],'attr_key':x['attr_key']})
        for x in relations:
            if not isinstance(x,dict) or not x.get('source_entity_key') or not x.get('target_entity_key') or not x.get('relation_type'):
                errors.append({'code':'RELATION_REQUIRED_FIELDS','relation':x}); continue
            if not known(x['source_entity_key']): errors.append({'code':'RELATION_SOURCE_MISSING','entity_key':x['source_entity_key']})
            if not known(x['target_entity_key']): errors.append({'code':'RELATION_TARGET_MISSING','entity_key':x['target_entity_key']})
            if x['source_entity_key']==x['target_entity_key']: warnings.append({'code':'SELF_RELATION','entity_key':x['source_entity_key'],'relation_type':x['relation_type']})
            st=int(x.get('start_chapter',chapter)); en=x.get('end_chapter')
            if en is not None and int(en)<st: errors.append({'code':'RELATION_INVALID_WINDOW','relation_type':x['relation_type']})
        return {'ok':not errors,'chapter':chapter,'errors':errors,'warnings':warnings}

    def import_graph(self,graph:dict,namespace:str='story',include_types:list[str]|None=None,dry_run:bool=True):
        if not isinstance(graph,dict): raise ValueError('graph must be an object with nodes/edges')
        nodes=graph.get('nodes') or []; edges=graph.get('edges') or []
        allowed=set(include_types or ENTITY_TYPES); mapping={}; plan_entities=[]
        for n in nodes:
            if not isinstance(n,dict) or n.get('type') not in allowed: continue
            raw=str(n.get('id') or n.get('entity_key') or '').strip()
            if not raw: continue
            key=f'{namespace}:{raw}' if namespace else raw; mapping[raw]=key
            plan_entities.append({'entity_key':key,'entity_type':n.get('type'),'name':n.get('name') or raw,'chapter':n.get('chapter'),'status':'active','description':'','properties':n.get('properties') or {},'source':'import'})
        plan_rel=[]
        for e in edges:
            if not isinstance(e,dict) or e.get('source') not in mapping or e.get('target') not in mapping: continue
            plan_rel.append({'source_entity_key':mapping[e['source']],'relation_type':e.get('type') or 'RELATED_TO','target_entity_key':mapping[e['target']],'start_chapter':e.get('chapter') or 0,'properties':e.get('properties') or {},'source':'import'})
        check=self.check(0,plan_entities,[],plan_rel)
        if dry_run or not check['ok']: return {'ok':check['ok'],'dry_run':True,'entity_count':len(plan_entities),'relation_count':len(plan_rel),'check':check}
        for x in plan_entities: self.upsert_entity(**x)
        for x in plan_rel: self.upsert_relation(**x)
        return {'ok':True,'dry_run':False,'entity_count':len(plan_entities),'relation_count':len(plan_rel),'check':check}
