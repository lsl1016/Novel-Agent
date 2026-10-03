from __future__ import annotations
import hashlib,json,os,re,sys
from pathlib import Path
from typing import Any
from .store import StoryStore,jl
from .reference import ReferenceLibrary
from .planning import PlanningStore
from .entity_graph import EntityGraph, ENTITY_TYPES
from .repositories import WorldRepository, CanonRepository, CandidateRepository
from .world_model import WorldModel
from .context_compiler import ContextCompiler
from .writing import WritingStore, call_writer_model, overall_verdict
from .planner_ai import call_planner_model, planner_model_configured
from .architecture_check import check as _architecture_check
from .run_controller import NovelRunController
from .semantic_review import (
    SEMANTIC_REVIEWER_TYPES, call_semantic_reviewer, call_revision_model,
    normalize_semantic_reviews, redact_hidden_values, semantic_reviewer_configured,
    revision_model_configured,
)

# 抽取候选节点类型 → 晋升目标的默认归类。
_FACT_NODE_TYPES={'Fact','BeliefState'}
_NARRATIVE_NODE_TYPES={'Mystery','Clue','Foreshadowing','Reveal','Payoff','EmotionDebt','NarrativeThread','ThreadMergeCandidate'}

# declared_updates 各组的必填字段(形状契约)。提交路径按此校验,畸形条目直接 BLOCK。
_DECLARED_SHAPES={
 'belief_updates':('fact_key','holder','stance'),
 'clues':('thread_key','content'),
 'reveals':('thread_key','content'),
 'payoffs':('content',),
 'world_facts':('fact_key','truth'),
 'mysteries':('mystery_key','name','thread_key'),
 'emotion_debts':('debt_key','thread_key','name','emotion_type','intensity'),
 'character_states':('character_key',),
 'entities':('entity_key','entity_type','name'),
 'entity_aliases':('entity_key','alias'),
 'entity_attributes':('entity_key','attr_key'),
 'entity_relations':('source_entity_key','relation_type','target_entity_key'),
 'narrative_entity_links':('narrative_type','narrative_key','entity_key'),
 'threads':('thread_key',),
 'events':('name',),
}
_BELIEF_STANCES={'unknown','suspects','believes','confirmed','disbelieves'}

_STRIP_RE=re.compile(r'[^0-9A-Za-z\u3400-\u9fff]+')
def _truth_leaks_in_prose(truth:str,body:str)->bool:
    """字面量包含,或去标点/空白归一化后的包含(防'玄冥、圣君'式变体写入)。"""
    if truth in body: return True
    nt=_STRIP_RE.sub('',truth); nb=_STRIP_RE.sub('',body)
    return len(nt)>=2 and nt in nb

def _normalize_declared(u:dict)->dict:
    """宽容归一化(与校验/应用层的既定契约对齐):

    * character_states: 模型常用 entity_key 指称角色 → character_key;
    * threads.advance/maintain/sleep: 模型偶尔输出 {"thread_key":...} 对象 → 归一为字符串,
      避免下游 set()/join 操作抛 unhashable;无法提取 thread_key 的条目原样保留,由形状校验报错。
    """
    items=u.get('character_states')
    if isinstance(items,list):
        for x in items:
            if isinstance(x,dict) and 'character_key' not in x and x.get('entity_key'):
                x['character_key']=x['entity_key']
    threads=u.get('threads')
    if isinstance(threads,dict):
        for group in ('advance','maintain','sleep'):
            seq=threads.get(group)
            if isinstance(seq,list):
                out=[]
                for x in seq:
                    if isinstance(x,dict):
                        k=x.get('thread_key') or x.get('key')
                        out.append(k if isinstance(k,str) and k else x)
                    else:
                        out.append(x)
                threads[group]=out
    return u

def _check_declared_shapes(u:dict,errors:list):
    """校验 declared_updates/ChapterPlan 中各组条目的形状;畸形条目是提交路径的崩溃源,直接 BLOCK。"""
    threads=u.get('threads')
    if isinstance(threads,dict):
        for group in ('advance','maintain','sleep'):
            seq=threads.get(group)
            if isinstance(seq,list):
                for i,x in enumerate(seq):
                    if not isinstance(x,str) or not x.strip():
                        errors.append({'code':'MALFORMED_DECLARED_UPDATE','group':f'threads.{group}','index':i,'message':'entry must be a thread_key string or {"thread_key": "..."}'})
    for group,required in _DECLARED_SHAPES.items():
        items=u.get(group)
        if not isinstance(items,list): continue
        for i,x in enumerate(items):
            if not isinstance(x,dict):
                errors.append({'code':'MALFORMED_DECLARED_UPDATE','group':group,'index':i,'message':'entry must be an object, not a bare string'}); continue
            missing=[k for k in required if k not in x]
            if group=='payoffs' and 'debt_key' not in x and 'thread_key' not in x:
                missing.append('debt_key|thread_key')
            if missing:
                errors.append({'code':'MALFORMED_DECLARED_UPDATE','group':group,'index':i,'missing':missing})
            if group=='belief_updates' and x.get('stance') not in _BELIEF_STANCES:
                errors.append({'code':'MALFORMED_DECLARED_UPDATE','group':group,'index':i,'message':f"stance must be one of {sorted(_BELIEF_STANCES)}"})

class NovelService:
    def __init__(self,story_db:str|Path,reference_root:str|Path|None=None,nkg_root:str|Path|None=None):
        self.store=StoryStore(story_db); self.reference=ReferenceLibrary(reference_root); self.nkg_root=Path(nkg_root) if nkg_root else None
        self.planning=PlanningStore(self.store)
        self.entity_graph=EntityGraph(self.store)
        self.writing=WritingStore(self.store)
        self.world=WorldRepository(self.store)
        self.canon=CanonRepository(self.store)
        self.candidates=CandidateRepository(self.store)
        self.world_model=WorldModel(self)
        self.context_compiler=ContextCompiler(self)
        self.runs=NovelRunController(self)
    def story_get_state(self,chapter:int,recent_window:int=10):
        s=self.store
        ch=self.canon.chapter_at_or_before(chapter)
        active=s.active_threads()
        mysteries=s.open_mysteries()
        debts=s.open_debts()
        events=self.canon.recent_events(max(0,chapter-recent_window),chapter)
        beliefs=[s.belief_snapshot(f['fact_key'],chapter) for f in self.world.all_facts()]
        forbidden=self.world.forbidden_facts(chapter,'reader')
        due=self.foreshadowing_list_open(chapter)
        return {'chapter':chapter,'current_arc':(ch.get('arc') if ch else s.get_meta('current_arc','')),'main_goal':s.get_meta('main_goal',''),'active_threads':active,'open_mysteries':mysteries,'emotion_debts':debts,'belief_states':beliefs,'forbidden_world_truths':forbidden,'due_foreshadowing':due,'recent_events':events,'character_states':self.canon.latest_character_states(chapter),'entity_graph':self.entity_graph.stats(),'planning':self.planning.planning_snapshot(chapter)}
    def narrative_thread_get(self,thread_key):
        x=self.store.thread(thread_key)
        if not x: raise KeyError(f'unknown thread_key: {thread_key}')
        return x
    def narrative_thread_search(self,query='',status=None,thread_type=None,limit=20):return self.store.search_threads(query,status,thread_type,limit)
    def mystery_create(self,**x):
        self.store.create_mystery(**x); return {'ok':True,'mystery_key':x['mystery_key'],'thread_key':x['thread_key']}
    def clue_add(self,thread_key,chapter,content,visibility='reader',strength=.2,holder=None,callback_key=None):
        sid=self.store.add_stage(thread_key,chapter,'Clue',content,visibility=visibility,strength=strength,holder=holder,callback_key=callback_key,metadata={'foreshadowing_status':'candidate_until_callback'})
        if not callback_key:
            with self.store.connect() as db:
                db.execute('UPDATE stages SET callback_key=? WHERE id=?',(f'stage_{sid}',sid))
        return {'ok':True,'stage_id':sid,'callback_key':callback_key or f'stage_{sid}','status':'clue','note':'not verified as Foreshadowing until an explicit later callback/payoff references this callback_key'}
    def foreshadowing_due_min_age(self,before_chapter:int)->int:
        # 伏笔"成熟"窗口按书长自适应:千章书仍允许慢热(封顶100章),短书按 chapter/8 缩短,
        # 否则 min_age 恒为 100 时,任何短于 100 章的书里到期线索列表永远为空
        return min(100, max(3, before_chapter // 8))
    def foreshadowing_list_open(self,before_chapter,min_age:int|None=None,limit=40):
        if min_age is None:
            min_age=self.foreshadowing_due_min_age(before_chapter)
        rows=self.store.open_clues(before_chapter-min_age,limit)
        for r in rows: r['age']=before_chapter-r['chapter']
        return rows
    def belief_get(self,fact_key,chapter):return self.store.belief_snapshot(fact_key,chapter)
    def belief_update(self,**x):self.store.add_belief(**x); return {'ok':True,**x}
    def emotion_debt_create(self,**x):self.store.create_debt(**x); return {'ok':True,'debt_key':x['debt_key']}
    def emotion_debt_resolve(self,debt_key:str,chapter:int,content:str,resolution:str='full',consequence:str=''):
        self.store.resolve_debt(debt_key,chapter,content,resolution,consequence)
        return {'ok':True,'debt_key':debt_key,'resolution':resolution}
    def narrative_pattern_search(self,pattern='',min_span=0,need=None,limit=10):return {'source':'REFERENCE_GRAPH','results':self.reference.search(pattern,min_span,need,limit),'copyright_boundary':'structural metadata only; verbatim text is omitted'}

    # ---- 检索与上下文编译器 v0.7 ----
    def entity_retrieve_relevant(self,chapter:int,role:str='writer',holder:str|None=None,limit:int=30,max_depth:int=2):
        return self.context_compiler.entity_retrieve_relevant(chapter,role,holder,None,limit,max_depth)

    def narrative_retrieve_relevant(self,chapter:int,role:str='writer',holder:str|None=None,limit:int=20):
        return self.context_compiler.narrative_retrieve_relevant(chapter,role,holder,None,limit)

    def context_compile(self,chapter:int,role:str='writer',holder:str|None=None,max_tokens:int|None=None,recent_window:int|None=None,excerpt_chars:int|None=None,include_reference:bool|None=None,persist:bool=False):
        return self.context_compiler.compile(chapter,role,holder,max_tokens,recent_window,excerpt_chars,include_reference,persist)

    def context_preview(self,chapter:int,role:str='writer',holder:str|None=None,max_tokens:int|None=None):
        return self.context_compiler.preview(chapter,role,holder,max_tokens)

    def context_snapshot_get(self,snapshot_id:str|None=None,chapter:int|None=None,role:str|None=None):
        return self.context_compiler.snapshot_get(snapshot_id,chapter,role)

    def context_explain(self,snapshot_id:str,item_key:str|None=None):
        return self.context_compiler.explain(snapshot_id,item_key)

    # ---- 实体图 / 世界模型 v0.6 ----
    def entity_get(self,entity_key:str,chapter:int,holder:str='reader'):
        x=self.entity_graph.get(entity_key,chapter,holder,author=False)
        if not x: raise KeyError(f'unknown or inactive entity_key: {entity_key}')
        return x

    def entity_author_get(self,entity_key:str,chapter:int):
        x=self.entity_graph.get(entity_key,chapter,'reader',author=True,include_inactive=True)
        if not x: raise KeyError(f'unknown entity_key: {entity_key}')
        return x

    def entity_search(self,query:str='',entity_type:str|None=None,status:str|None='active',chapter:int=0,holder:str='reader',limit:int=20):
        return self.entity_graph.search(query,entity_type,status,chapter,holder,False,limit)

    def entity_neighbors(self,entity_key:str,chapter:int,holder:str='reader',relation_types:list[str]|None=None,direction:str='both',depth:int=1,limit:int=100):
        return self.entity_graph.neighbors(entity_key,chapter,holder,False,relation_types,direction,depth,limit)

    def entity_path_find(self,source_entity_key:str,target_entity_key:str,chapter:int,holder:str='reader',relation_types:list[str]|None=None,max_depth:int=4):
        return self.entity_graph.path_find(source_entity_key,target_entity_key,chapter,holder,False,relation_types,max_depth)

    def entity_context_get(self,entity_keys:list[str],chapter:int,holder:str='reader',depth:int=1,limit:int=100):
        return self.entity_graph.context(entity_keys,chapter,holder,False,depth,limit)

    def entity_graph_stats(self): return self.entity_graph.stats()

    def entity_upsert(self,entity_key:str,entity_type:str,name:str,chapter:int|None=None,status:str='active',description:str='',properties:dict|None=None,source:str='author_declared'):
        return {'ok':True,'entity':self.entity_graph.upsert_entity(entity_key,entity_type,name,chapter,status,description,properties,source)}

    def entity_alias_add(self,entity_key:str,alias:str,alias_type:str='alias',secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,source:str='author_declared'):
        return self.entity_graph.add_alias(entity_key,alias,alias_type,secrecy,reveal_after,fact_key,source)

    def entity_attribute_set(self,entity_key:str,attr_key:str,value:Any,chapter:int=0,end_chapter:int|None=None,secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,source:str='author_declared',confidence:float=1.0,close_previous:bool=True,cause_event_id:int|None=None):
        return self.entity_graph.set_attribute(entity_key,attr_key,value,chapter,end_chapter,secrecy,reveal_after,fact_key,source,confidence,close_previous,cause_event_id)

    def entity_relation_upsert(self,source_entity_key:str,relation_type:str,target_entity_key:str,start_chapter:int=0,end_chapter:int|None=None,status:str='active',secrecy:str='public',reveal_after:int|None=None,fact_key:str|None=None,properties:dict|None=None,source:str='author_declared',cause_event_id:int|None=None):
        return self.entity_graph.upsert_relation(source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter,status,secrecy,reveal_after,fact_key,properties,source,cause_event_id)

    def entity_relation_end(self,source_entity_key:str,relation_type:str,target_entity_key:str,chapter:int):
        return self.entity_graph.end_relation(source_entity_key,relation_type,target_entity_key,chapter)

    def narrative_entity_link(self,narrative_type:str,narrative_key:str,entity_key:str,role:str='involves',chapter:int=0,properties:dict|None=None,source:str='author_declared'):
        return self.entity_graph.link_narrative(narrative_type,narrative_key,entity_key,role,chapter,properties,source)

    def narrative_entity_links_get(self,entity_key:str|None=None,narrative_type:str|None=None,narrative_key:str|None=None,limit:int=100):
        return self.entity_graph.narrative_links(entity_key,narrative_type,narrative_key,limit)

    def entity_graph_check(self,chapter:int,entities:list|None=None,attributes:list|None=None,relations:list|None=None):
        return self.entity_graph.check(chapter,entities,attributes,relations)

    def entity_graph_import(self,graph:dict,namespace:str='story',include_types:list[str]|None=None,dry_run:bool=True):
        return self.entity_graph.import_graph(graph,namespace,include_types,dry_run)
    # ---- 规划运行时 ----
    def blueprint_get(self):
        return self.planning.blueprint_get()

    def blueprint_update(self,patch:dict,replace:bool=False,expected_version:int|None=None):
        return self.planning.blueprint_update(patch,replace,expected_version)

    def story_architect_get(self):
        with self.store.connect() as db:
            counts={
                'world_facts':db.execute('SELECT COUNT(*) n FROM world_facts').fetchone()['n'],
                'threads':db.execute('SELECT COUNT(*) n FROM threads').fetchone()['n'],
                'mysteries':db.execute('SELECT COUNT(*) n FROM mysteries').fetchone()['n'],
                'emotion_debts':db.execute('SELECT COUNT(*) n FROM debts').fetchone()['n'],
                'entities':db.execute('SELECT COUNT(*) n FROM entities').fetchone()['n'],
                'entity_relations':db.execute('SELECT COUNT(*) n FROM entity_relations').fetchone()['n'],
                'narrative_entity_links':db.execute('SELECT COUNT(*) n FROM narrative_entity_links').fetchone()['n'],
            }
        return {
            'blueprint':self.planning.blueprint_get(),
            'arcs':self.planning.arc_list(),
            'milestones':self.planning.milestone_list(limit=200),
            'thread_schedule':self.planning.schedule_get(limit=200),
            'canonical_counts':counts,
        }

    def novel_architecture_generate(self,idea:str,options:dict|None=None):
        """一句话创意 → 完整 architecture(Phase C)。生成 ≠ 应用:产物仍须过 story_architect_apply。"""
        from .architect_ai import generate, architect_model_configured
        if not architect_model_configured():
            return {'ok':False,'error':{'code':'ARCHITECT_NOT_CONFIGURED','message':'configure NOVEL_ARCHITECT_* or NOVEL_PLANNER_*'}}
        try:
            return generate(idea, options or {})
        except Exception as exc:
            return {'ok':False,'error':{'code':'ARCHITECT_FAILED','message':str(exc)}}

    def story_architect_interview(self, idea: str, options: dict | None = None):
        from .architect_ai import interview
        return interview(idea, options)

    def story_architect_apply(self,architecture:dict,dry_run:bool=False):
        """把作者提供的高层架构编译为权威的规划/故事状态。

        这是确定性的应用操作,而非自主的故事生成。要求提供稳定键。
        """
        if not isinstance(architecture,dict): raise ValueError('architecture must be an object')
        errors=[]; warnings=[]
        for group,key in [('world_facts','fact_key'),('entities','entity_key'),('identity_profiles','profile_key'),('threads','thread_key'),('mysteries','mystery_key'),('emotion_debts','debt_key'),('arcs','arc_key'),('milestones','milestone_key'),('thread_schedule','schedule_key')]:
            vals=architecture.get(group,[]) or []
            if not isinstance(vals,list): errors.append({'code':'INVALID_GROUP','group':group,'message':'must be an array'}); continue
            seen=set()
            for i,x in enumerate(vals):
                if not isinstance(x,dict) or not x.get(key): errors.append({'code':'MISSING_STABLE_KEY','group':group,'index':i,'key':key}); continue
                if x[key] in seen: errors.append({'code':'DUPLICATE_STABLE_KEY','group':group,'key':x[key]})
                seen.add(x[key])
        eg_check=self.entity_graph.check(0,architecture.get('entities',[]) or [],architecture.get('entity_attributes',[]) or [],architecture.get('entity_relations',[]) or [])
        errors.extend(eg_check.get('errors',[])); warnings.extend(eg_check.get('warnings',[]))
        proposed_entity_keys={x.get('entity_key') for x in architecture.get('entities',[]) or [] if isinstance(x,dict) and x.get('entity_key')}
        for group in ('entity_aliases','narrative_entity_links','identity_profiles'):
            vals=architecture.get(group,[]) or []
            if not isinstance(vals,list): errors.append({'code':'INVALID_GROUP','group':group,'message':'must be an array'}); continue
            for i,x in enumerate(vals):
                if not isinstance(x,dict) or not x.get('entity_key'):
                    errors.append({'code':'ENTITY_REFERENCE_REQUIRED','group':group,'index':i}); continue
                if x['entity_key'] not in proposed_entity_keys and not self.entity_graph._exists(x['entity_key']):
                    errors.append({'code':'ENTITY_REFERENCE_MISSING','group':group,'index':i,'entity_key':x['entity_key']})
        arcs=architecture.get('arcs',[]) or []
        for a in arcs:
            if isinstance(a,dict) and int(a.get('order_no',0) or 0)>0 and not a.get('inherited_thread_keys'):
                warnings.append({'code':'ARC_WITHOUT_DECLARED_INHERITANCE','arc_key':a.get('arc_key')})
        # 跨引用校验(Phase C):生成器与外部作者走同一道闸门;known 提供库内已有键避免增量误报
        known={'threads':set(),'facts':set(),'entities':set(),'arcs':set()}
        with self.store.connect() as db:
            known['threads']={r[0] for r in db.execute('SELECT thread_key FROM threads')}
            known['facts']={r[0] for r in db.execute('SELECT fact_key FROM world_facts')}
            known['entities']={r[0] for r in db.execute('SELECT entity_key FROM entities')}
            known['arcs']={r[0] for r in db.execute('SELECT arc_key FROM arc_plans')}
        xref=_architecture_check(architecture,known=known)
        errors.extend(xref['errors']); warnings.extend(xref['warnings'])
        if errors or dry_run:
            return {'ok':not errors,'dry_run':dry_run,'errors':errors,'warnings':warnings,'applied':{}}
        applied={k:0 for k in ['blueprint','world_facts','entities','entity_aliases','identity_profiles','entity_attributes','entity_relations','narrative_entity_links','threads','mysteries','emotion_debts','arcs','milestones','thread_schedule']}
        if architecture.get('blueprint') is not None:
            self.planning.blueprint_update(architecture.get('blueprint') or {},replace=bool(architecture.get('replace_blueprint',False)))
            applied['blueprint']=1
        for x in architecture.get('world_facts',[]) or []:
            self.store.set_world_fact(x['fact_key'],x.get('truth'),x.get('secrecy','secret'),x.get('reveal_after'),x.get('notes','')); applied['world_facts']+=1
        for x in architecture.get('entities',[]) or []:
            self.entity_graph.upsert_entity(x['entity_key'],x['entity_type'],x['name'],x.get('chapter') or x.get('introduced_chapter'),x.get('status','active'),x.get('description',''),x.get('properties') or {},x.get('source','author_declared')); applied['entities']+=1
        for x in architecture.get('entity_aliases',[]) or []:
            self.entity_graph.add_alias(x['entity_key'],x['alias'],x.get('alias_type','alias'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('source','author_declared')); applied['entity_aliases']+=1
        for x in architecture.get('identity_profiles',[]) or []:
            self.entity_graph.identity_profile_put(x); applied['identity_profiles']+=1
        for x in architecture.get('entity_attributes',[]) or []:
            self.entity_graph.set_attribute(x['entity_key'],x['attr_key'],x.get('value'),x.get('chapter',0),x.get('end_chapter'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('source','author_declared'),x.get('confidence',1.0),x.get('close_previous',True)); applied['entity_attributes']+=1
        for x in architecture.get('entity_relations',[]) or []:
            self.entity_graph.upsert_relation(x['source_entity_key'],x['relation_type'],x['target_entity_key'],x.get('start_chapter',0),x.get('end_chapter'),x.get('status','active'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('properties') or {},x.get('source','author_declared')); applied['entity_relations']+=1
        for x in architecture.get('narrative_entity_links',[]) or []:
            self.entity_graph.link_narrative(x['narrative_type'],x['narrative_key'],x['entity_key'],x.get('role','involves'),x.get('chapter',0),x.get('properties') or {},x.get('source','author_declared')); applied['narrative_entity_links']+=1
        for x in architecture.get('threads',[]) or []:
            self.store.upsert_thread(x['thread_key'],x.get('name') or x['thread_key'],thread_type=x.get('thread_type','narrative'),status=x.get('status','open'),introduced_chapter=x.get('introduced_chapter'),target_min=x.get('target_min_chapter'),target_max=x.get('target_max_chapter'),main_goal=x.get('main_goal'),notes=x.get('notes')); applied['threads']+=1
        for x in architecture.get('mysteries',[]) or []:
            with self.store.connect() as db: exists=db.execute('SELECT 1 FROM mysteries WHERE mystery_key=?',(x['mystery_key'],)).fetchone()
            if not exists:
                self.mystery_create(**x)
            else:
                with self.store.connect() as db:
                    db.execute('''UPDATE mysteries SET thread_key=?,name=?,target_min=?,target_max=?,notes=? WHERE mystery_key=?''',(x['thread_key'],x['name'],x.get('target_min_chapter'),x.get('target_max_chapter'),x.get('notes',''),x['mystery_key']))
            applied['mysteries']+=1
        for x in architecture.get('emotion_debts',[]) or []:
            with self.store.connect() as db: exists=db.execute('SELECT 1 FROM debts WHERE debt_key=?',(x['debt_key'],)).fetchone()
            if not exists: self.emotion_debt_create(**x)
            else:
                with self.store.connect() as db:
                    db.execute('UPDATE debts SET name=?,emotion_type=?,intensity=?,target_holder=?,notes=? WHERE debt_key=?',(x['name'],x['emotion_type'],x['intensity'],x.get('target_holder'),x.get('notes',''),x['debt_key']))
            applied['emotion_debts']+=1
        for x in arcs: self.planning.arc_put(x); applied['arcs']+=1
        for x in architecture.get('milestones',[]) or []: self.planning.milestone_put(x); applied['milestones']+=1
        for x in architecture.get('thread_schedule',[]) or []: self.planning.schedule_put(x); applied['thread_schedule']+=1
        return {'ok':True,'dry_run':False,'errors':[],'warnings':warnings,'applied':applied,'architecture':self.story_architect_get()}

    def arc_plan_create(self,arc:dict):
        return {'ok':True,'arc':self.planning.arc_put(arc)}

    def arc_plan_get(self,arc_key:str):
        arc=self.planning.arc_get(arc_key)
        if not arc: raise KeyError(f'unknown arc_key: {arc_key}')
        return arc

    def arc_progress_get(self,arc_key:str,chapter:int|None=None):
        arc=self.arc_plan_get(arc_key)
        start=arc.get('start_chapter') or 0; end=arc.get('target_end_chapter')
        with self.store.connect() as db:
            q='SELECT COUNT(*) n,MAX(chapter) mx FROM chapters WHERE chapter>=?'; args=[start]
            if end is not None: q+=' AND chapter<=?'; args.append(end)
            row=db.execute(q,args).fetchone()
        current=chapter if chapter is not None else (row['mx'] if row['mx'] is not None else start)
        total=(end-start+1) if end is not None and end>=start else None
        elapsed=max(0,current-start+1)
        progress=(min(1.0,elapsed/total) if total else None)
        milestones=self.planning.milestone_list(arc_key=arc_key,limit=200)
        return {'arc':arc,'chapter':current,'committed_chapters':row['n'],'target_length':total,'elapsed_by_position':elapsed,'progress_ratio':progress,'milestones':milestones}

    def milestone_create(self,milestone:dict): return {'ok':True,'milestone':self.planning.milestone_put(milestone)}
    def milestone_list(self,arc_key:str|None=None,status:str|None=None,before_chapter:int|None=None,limit:int=100): return self.planning.milestone_list(arc_key,status,before_chapter,limit)
    def thread_schedule_update(self,schedule:dict): return {'ok':True,'schedule':self.planning.schedule_put(schedule)}
    def thread_schedule_get(self,schedule_key:str|None=None,thread_key:str|None=None,chapter:int|None=None,status:str|None=None,limit:int=100): return self.planning.schedule_get(schedule_key,thread_key,chapter,status,limit)

    def planning_rebuild_window(self,anchor_chapter:int,hard_horizon:int=5,medium_horizon:int=20,soft_horizon:int=50,proposals:list|None=None,preserve_existing:bool=True):
        return self.planning.rebuild_window(anchor_chapter,hard_horizon,medium_horizon,soft_horizon,proposals,preserve_existing)

    def planning_get_window(self,anchor_chapter:int,horizon:int=50): return self.planning.get_window(anchor_chapter,horizon)

    def chapter_plan_get(self,chapter:int):
        p=self.planning.chapter_plan_get(chapter)
        if not p: raise KeyError(f'no saved chapter plan: {chapter}')
        return p

    def chapter_plan_save(self,chapter:int,plan:dict,pov_holder:str='reader',arc_key:str|None=None,status:str='draft',allow_blocked:bool=True):
        if not isinstance(plan,dict): raise ValueError('plan must be an object')
        plan=_normalize_declared(dict(plan)); plan['_planning_runtime']=True
        if arc_key: plan.setdefault('arc_key',arc_key)
        validation=self.chapter_plan_check(chapter,plan,pov_holder)
        vstatus='blocked' if validation['errors'] else ('warning' if validation['warnings'] else 'ready')
        if vstatus=='blocked' and not allow_blocked:
            return {'ok':False,'saved':False,'validation':validation}
        saved=self.planning.chapter_plan_put(chapter,plan,arc_key or plan.get('arc_key'),pov_holder,status,vstatus,validation)
        return {'ok':vstatus!='blocked','saved':True,'chapter_plan':saved,'validation':validation}

    def planning_pressure_check(self,chapter:int,hard_lookahead:int=5):
        narrative=self.story_pressure_check(chapter)
        planning=self.planning.pressure(chapter,hard_lookahead)
        risks=[{'source':'narrative','code':x} for x in narrative.get('risks',[])]+[{'source':'planning',**x} for x in planning.get('risks',[])]
        return {'chapter':chapter,'ok':planning.get('ok',True),'narrative_pressure':narrative,'planning_pressure':planning,'risks':risks,'recommendations':list(dict.fromkeys((narrative.get('recommendations') or [])+(planning.get('recommendations') or [])))}

    def chapter_plan_check(self,chapter:int,plan:dict,pov_holder='reader'):
        errors=[]; warnings=[]
        plan=_normalize_declared(plan)
        _check_declared_shapes(plan,errors)
        # 计划中显式声明的知识/揭示断言。
        assertions=[]
        assertions += plan.get('knowledge_assertions',[]) if isinstance(plan.get('knowledge_assertions'),list) else []
        assertions += plan.get('reveals',[]) if isinstance(plan.get('reveals'),list) else []
        for a in assertions:
            if not isinstance(a,dict) or not a.get('fact_key'):continue
            fact=a['fact_key']; recipients=a.get('recipients') or [a.get('holder') or pov_holder]
            snap=self.store.belief_snapshot(fact,chapter)
            wt=snap.get('world_truth')
            for h in recipients:
                # 双时序:每个接收者有自己的计划知晓时刻(per-holder 披露 / reader 公开 / 旧 reveal_after 取最早)
                moment=self.store.fact_known_from(fact,h)
                if wt and wt.get('secrecy')!='public' and moment is not None and chapter<int(moment):
                    errors.append({'code':'WORLD_TRUTH_LEAK','fact_key':fact,'holder':h,'message':f'{fact} is not legally knowable by {h} until chapter {moment}'})
                prior=snap['holders'].get(h)
                if a.get('assume_known') and (not prior or prior.get('stance') not in {'confirmed','believes'}):
                    errors.append({'code':'KNOWLEDGE_WITHOUT_SUPPORT','fact_key':fact,'holder':h,'message':'plan assumes knowledge not present in current belief state'})
        # 卷(Arc)切换规则:新地图/新卷应至少继承一条旧叙事线。
        transition=plan.get('arc_transition')
        if isinstance(transition,dict) and transition.get('is_new_arc') and not transition.get('inherited_thread_keys'):
            errors.append({'code':'ARC_WITHOUT_INHERITED_THREAD','message':'a new arc/map must inherit at least one existing NarrativeThread'})
        # 叙事线兑现(payoff)窗口与伏笔销账纪律。
        for p in plan.get('payoffs',[]) if isinstance(plan.get('payoffs'),list) else []:
            tk=p.get('thread_key') if isinstance(p,dict) else None
            if not tk:continue
            t=self.store.thread(tk)
            if t and t.get('target_min') is not None and chapter<int(t['target_min']): warnings.append({'code':'EARLY_PAYOFF','thread_key':tk,'message':f'planned payoff is before target_min {t["target_min"]}'})
            if isinstance(p,dict) and not (p.get('callback_key') or '').strip():
                open_on_thread=[c for c in self.store.open_clues(chapter,50) if c.get('thread_key')==tk]
                if open_on_thread:
                    warnings.append({'code':'PAYOFF_WITHOUT_CALLBACK','thread_key':tk,'message':f'thread has {len(open_on_thread)} open clue(s); set payoff callback_key to the recycled clue callback_key (e.g. {open_on_thread[0]["callback_key"]})'})
        # 规划运行时检查只作用于结构化的已保存计划,以保持向后兼容。
        if plan.get('_planning_runtime'):
            if not plan.get('primary_goal'): errors.append({'code':'CHAPTER_GOAL_MISSING','message':'structured ChapterPlan requires primary_goal'})
            arc_key=plan.get('arc_key')
            arc=self.planning.arc_get(arc_key) if arc_key else self.planning.arc_for_chapter(chapter)
            if arc:
                forbidden=set(arc.get('forbidden_facts') or [])
                for a in assertions:
                    if isinstance(a,dict) and a.get('fact_key') in forbidden:
                        errors.append({'code':'ARC_FORBIDDEN_REVEAL','arc_key':arc['arc_key'],'fact_key':a['fact_key']})
            threads=plan.get('threads') or {}
            advancing=threads.get('advance',[]) if isinstance(threads,dict) else []
            if len(advancing)>3: warnings.append({'code':'TOO_MANY_THREADS_ADVANCED','count':len(advancing),'message':'prefer advancing no more than 2-3 narrative threads in one chapter'})
            mysteries=plan.get('mysteries') or {}
            if isinstance(mysteries,dict):
                created=set(mysteries.get('create',[]) or []); resolved=set(mysteries.get('resolve',[]) or [])
                overlap=created & resolved
                if overlap: warnings.append({'code':'SAME_CHAPTER_MYSTERY_OPEN_CLOSE','mystery_keys':sorted(overlap)})
            due=self.planning.schedule_get(chapter=chapter,status='planned',limit=100)
            scheduled_threads={x['thread_key'] for x in due}
            if scheduled_threads and not (scheduled_threads & set(advancing)):
                warnings.append({'code':'DUE_THREAD_NOT_ADVANCED','thread_keys':sorted(scheduled_threads),'message':'a scheduled narrative stage is due in this chapter window'})
        eg=self.entity_graph.check(chapter,plan.get('entities') or [],plan.get('entity_attributes') or [],plan.get('entity_relations') or [])
        errors.extend(eg.get('errors',[])); warnings.extend(eg.get('warnings',[]))
        return {'ok':not errors,'errors':errors,'warnings':warnings,'checked_chapter':chapter}
    def continuity_check(self,chapter:int,proposed_facts=None,character_states=None,entities=None,entity_attributes=None,entity_relations=None):
        proposed_facts=proposed_facts or []; character_states=character_states or []; errors=[]; warnings=[]
        for f in proposed_facts:
            key=f.get('fact_key'); value=f.get('value')
            if not key:continue
            snap=self.store.belief_snapshot(key,chapter)
            wt=snap.get('world_truth')
            if wt and f.get('claim_world_truth',False) and value!=wt.get('value'):
                errors.append({'code':'WORLD_FACT_CONTRADICTION','fact_key':key,'canonical':wt.get('value'),'proposed':value})
        for cs in character_states:
            ck=cs.get('character_key')
            if not ck:continue
            r=self.canon.character_state(ck,chapter)
            if r:
                old=r.get('state') or {}; new=cs.get('state',{})
                for k in ('alive','location','identity'):
                    if k in old and k in new and old[k]!=new[k] and not cs.get('transition_reason'):
                        warnings.append({'code':'CHARACTER_STATE_JUMP','character_key':ck,'field':k,'from':old[k],'to':new[k]})
        eg=self.entity_graph.check(chapter,entities or [],entity_attributes or [],entity_relations or [])
        errors.extend(eg.get('errors',[])); warnings.extend(eg.get('warnings',[]))
        return {'ok':not errors,'errors':errors,'warnings':warnings,'entity_graph':eg}
    def story_pressure_check(self,chapter:int,mystery_age=200,foreshadow_age=300,debt_age=200,recent_window=30):
        mysteries=self.store.open_mysteries()
        debts=self.store.open_debts()
        flow=self.store.mystery_flow(max(0,chapter-recent_window),chapter)
        opened=flow['opened']; resolved=flow['resolved']
        stale_m=[m for m in mysteries if chapter-m['introduced_chapter']>=mystery_age]
        stale_f=self.foreshadowing_list_open(chapter,foreshadow_age,100)
        stale_d=[d for d in debts if chapter-d['created_chapter']>=debt_age]
        risk=[]; rec=[]
        if len(stale_m)>=5:risk.append('mystery_backlog_high'); rec.append('close or partially answer at least 1-2 mature mysteries in the next 20 chapters')
        if opened>max(3,resolved*3):risk.append('opening_rate_exceeds_payoff_rate'); rec.append('reduce new mystery creation until payoff rate recovers')
        if stale_f:risk.append('stale_foreshadowing'); rec.append('reactivate selected old clues before adding more long-fuse clues')
        if stale_d:risk.append('emotion_debt_overdue'); rec.append('schedule a partial or full emotional payoff')
        return {'chapter':chapter,'open_mysteries':len(mysteries),'stale_mysteries':len(stale_m),'open_emotion_debts':len(debts),'overdue_emotion_debts':len(stale_d),'stale_foreshadowing':len(stale_f),'recent_window':recent_window,'new_mysteries':opened,'resolved_mysteries':resolved,'risks':risk,'recommendations':list(dict.fromkeys(rec))}
    def _body_secret_leak_check(self, chapter:int, body:str, pov:str, declared_updates:dict):
        errors=[]; allowed=set()
        for r in declared_updates.get('reveals',[]) if isinstance(declared_updates.get('reveals'),list) else []:
            if not isinstance(r,dict) or not r.get('fact_key'): continue
            recipients=r.get('recipients') or [r.get('holder') or 'reader']
            if 'reader' in recipients or (pov and pov in recipients): allowed.add(r['fact_key'])
        for f in self.world.secret_facts():
            if f['fact_key'] in allowed: continue
            # 正文面向读者:合法性只看 reader 的计划知晓时刻(per-holder 披露不能让 POV 私知变成可写正文)
            rkf=self.store.fact_known_from(f['fact_key'],'reader')
            if rkf is not None and chapter>=rkf: continue
            truth=f.get('truth')
            if not isinstance(truth,str) or len(truth)<2 or not _truth_leaks_in_prose(truth,body): continue
            snap=self.store.belief_snapshot(f['fact_key'],chapter)
            reader=snap['holders'].get('reader',{})
            pov_b=snap['holders'].get(pov,{}) if pov else {}
            if reader.get('stance')=='confirmed' or pov_b.get('stance')=='confirmed': continue
            errors.append({'code':'SECRET_LITERAL_IN_PROSE','fact_key':f['fact_key'],'message':'finished prose contains a hidden World Truth literal without a declared legal reveal'})
        return {'ok':not errors,'errors':errors}

    def _apply_declared(self,chapter:int,u:dict):
        applied=[]
        for x in u.get('threads',[]):
            self.store.upsert_thread(x['thread_key'],x.get('name') or x['thread_key'],thread_type=x.get('thread_type','narrative'),status=x.get('status','open'),introduced_chapter=x.get('introduced_chapter',chapter),target_min=x.get('target_min_chapter'),target_max=x.get('target_max_chapter'),main_goal=x.get('main_goal'),notes=x.get('notes')) ; applied.append('thread')
        for x in u.get('mysteries',[]): self.mystery_create(**{**x,'introduced_chapter':x.get('introduced_chapter',chapter)}); applied.append('mystery')
        for x in u.get('clues',[]): self.clue_add(x['thread_key'],chapter,x['content'],x.get('visibility','reader'),x.get('strength',.2),x.get('holder'),x.get('callback_key')); applied.append('clue')
        for x in u.get('reveals',[]):
            self.store.add_stage(x['thread_key'],chapter,'Reveal',x['content'],strength=x.get('strength',.7),visibility=x.get('visibility','reader'),callback_key=x.get('callback_key'),metadata={k:v for k,v in x.items() if k not in {'thread_key','content'}}); applied.append('reveal')
            if x.get('mystery_key') and x.get('resolution')=='full':
                with self.store.connect() as db: db.execute("UPDATE mysteries SET status='resolved',resolved_chapter=? WHERE mystery_key=?",(chapter,x['mystery_key']))
        for x in u.get('belief_updates',[]): self.belief_update(**{**x,'chapter':x.get('chapter',chapter)}); applied.append('belief')
        for x in u.get('emotion_debts',[]): self.emotion_debt_create(**{**x,'created_chapter':x.get('created_chapter',chapter)}); applied.append('emotion_debt')
        for x in u.get('payoffs',[]):
            if x.get('debt_key'): self.emotion_debt_resolve(x['debt_key'],chapter,x['content'],x.get('resolution','full'),x.get('consequence',''))
            else: self.store.add_stage(x['thread_key'],chapter,'Payoff',x['content'],strength=x.get('strength',.8),callback_key=x.get('callback_key'),metadata=x)
            applied.append('payoff')
        for x in u.get('world_facts',[]): self.store.set_world_fact(x['fact_key'],x.get('truth'),x.get('secrecy','secret'),x.get('reveal_after'),x.get('notes','')); applied.append('world_fact')
        for x in u.get('events',[]):
            self.world_model.event_create(x['name'],chapter,event_key=x.get('event_key'),event_type=x.get('event_type','event'),
                thread_key=x.get('thread_key'),location_key=x.get('location_key'),cause_event_id=x.get('cause_event_id'),
                cause_event_key=x.get('cause_event_key'),outcome=x.get('outcome',''),consequence=x.get('consequence',''),
                participants=x.get('participants'),metadata=x); applied.append('event')
        for x in u.get('character_states',[]): self.store.add_character_state(x['character_key'],chapter,x.get('state',{})); applied.append('character_state')
        for x in u.get('entities',[]): self.entity_graph.upsert_entity(x['entity_key'],x['entity_type'],x['name'],x.get('chapter',chapter),x.get('status','active'),x.get('description',''),x.get('properties') or {},x.get('source','author_declared')); applied.append('entity')
        for x in u.get('entity_aliases',[]): self.entity_graph.add_alias(x['entity_key'],x['alias'],x.get('alias_type','alias'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('source','author_declared')); applied.append('entity_alias')
        for x in u.get('entity_attributes',[]): self.entity_graph.set_attribute(x['entity_key'],x['attr_key'],x.get('value'),x.get('chapter',chapter),x.get('end_chapter'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('source','author_declared'),x.get('confidence',1.0),x.get('close_previous',True)); applied.append('entity_attribute')
        for x in u.get('entity_relations',[]): self.entity_graph.upsert_relation(x['source_entity_key'],x['relation_type'],x['target_entity_key'],x.get('start_chapter',chapter),x.get('end_chapter'),x.get('status','active'),x.get('secrecy','public'),x.get('reveal_after'),x.get('fact_key'),x.get('properties') or {},x.get('source','author_declared')); applied.append('entity_relation')
        for x in u.get('narrative_entity_links',[]): self.entity_graph.link_narrative(x['narrative_type'],x['narrative_key'],x['entity_key'],x.get('role','involves'),x.get('chapter',chapter),x.get('properties') or {},x.get('source','author_declared')); applied.append('narrative_entity_link')
        return applied
    def _auto_extract(self,chapter,title,body,arc):
        if self.nkg_root and str(self.nkg_root/'src') not in sys.path:sys.path.insert(0,str(self.nkg_root/'src'))
        try:
            from nkg.models import Chapter
            from nkg.phase2_extractor import extract_chapter_semantic
            extractor_source='external_narrative_kg'
        except Exception:
            from .nkg_phase2.models import Chapter
            from .nkg_phase2.phase2_extractor import extract_chapter_semantic
            extractor_source='bundled_phase2_subset'
        sha=hashlib.sha256(body.encode('utf-8')).hexdigest()
        c=Chapter(f'story_ch_{chapter:04d}',chapter,title,'story',arc or 'Story',body,len(body),sha,0,len(body))
        try: ex,meta=extract_chapter_semantic(c,cache_dir=Path(self.store.path).parent/'semantic_cache')
        except Exception as e:return {'status':'error','error':str(e),'candidate_count':0}
        count=0
        for n in ex.nodes:
            if n.type=='Chapter':continue
            self.candidates.add(chapter,n.type,n.name,{'node':{'id':n.id,'type':n.type,'name':n.name,'confidence':n.confidence,'status':n.status,'properties':n.properties}}); count+=1
        return {'status':'ok','candidate_count':count,'extract_meta':meta,'extractor_source':extractor_source}

    # ---- 抽取候选晋升闭环(A0) ----
    def candidate_list(self,chapter:int|None=None,node_type:str|None=None,status:str='candidate',limit:int=100):
        return self.candidates.list(chapter,node_type,status,limit)

    def candidate_promote(self,candidate_id:int,target:dict|None=None):
        """把一条抽取候选显式晋升为正典实体或 World Truth,并落证据链。

        候选永远不会静默变成 Canon:只有这个显式调用(或既有作者工具)能
        修改权威状态。证据链记录来源章节、抽取器、置信度与原文证据。
        """
        c=self.candidates.get(candidate_id)
        if not c: raise KeyError(f'unknown candidate_id: {candidate_id}')
        if c['status']!='candidate': raise ValueError(f"candidate {candidate_id} is already {c['status']}")
        target=dict(target or {})
        node=(c.get('payload') or {}).get('node') or {}
        props=node.get('properties') or {}
        evidence={
            'candidate_id':c['id'],'chapter':c['chapter'],'node_type':c['node_type'],
            'node_name':c['name'],'extractor':props.get('extractor') or 'phase2_extractor',
            'confidence':node.get('confidence'),'evidence':props.get('evidence'),
            'promoted_via':'candidate_promote',
        }
        kind=target.get('kind') or ('world_fact' if c['node_type'] in _FACT_NODE_TYPES else 'entity')
        if kind=='world_fact':
            fact_key=target.get('fact_key'); truth=target.get('truth',node.get('name'))
            if not fact_key or truth is None: raise ValueError('world_fact promotion requires fact_key and truth')
            self.world.set_fact(fact_key,truth,target.get('secrecy','secret'),target.get('reveal_after'),target.get('notes',f'promoted from candidate {candidate_id}'))
            promoted_target=fact_key
            applied={'world_fact':fact_key}
        elif kind=='entity':
            entity_type=target.get('entity_type') or (c['node_type'] if c['node_type'] in ENTITY_TYPES else None)
            if c['node_type'] in _NARRATIVE_NODE_TYPES and not target.get('entity_type'):
                raise ValueError(f"narrative node type {c['node_type']} is not promotable to an Entity; use mystery_create/clue_add/emotion_debt_create, or pass explicit target.entity_type")
            if not entity_type: raise ValueError('entity promotion requires entity_type (candidate node type is not an Entity type)')
            name=target.get('name') or node.get('name') or c['name']
            slug=''.join(ch for ch in name if ch.isalnum() or ch in '_-').lower()[:48]
            entity_key=target.get('entity_key') or f"ext_{entity_type.lower()}_{slug}"
            merged=dict(props); merged.pop('evidence',None)
            merged['evidence']=evidence
            self.entity_graph.upsert_entity(entity_key,entity_type,name,c['chapter'],target.get('status','active'),target.get('description',''),merged,'extraction_promote')
            promoted_target=entity_key
            applied={'entity':entity_key}
        else:
            raise ValueError("target.kind must be 'entity' or 'world_fact'")
        self.candidates.resolve(candidate_id,'promoted',promoted_target,target.get('note',''))
        # 作者晋升即确认:证据链从实体属性升级为一等断言(Assertion/Evidence)。
        assertion=self.world_model.assertion_create(
            subject_type=kind,subject_key=promoted_target,
            predicate='identity' if kind=='entity' else 'truth',
            object_value=name if kind=='entity' else truth,
            chapter=c['chapter'],source_span=f"candidate:{candidate_id}",
            extractor=evidence['extractor'],confidence=evidence['confidence'] or 1.0,
            evidence=evidence.get('evidence'),confirmed=True)
        return {'ok':True,'candidate_id':candidate_id,'resolution':'promoted','promoted_target':promoted_target,'applied':applied,'evidence':evidence,'assertion_id':assertion['assertion_id']}

    def candidate_reject(self,candidate_id:int,reason:str=''):
        c=self.candidates.get(candidate_id)
        if not c: raise KeyError(f'unknown candidate_id: {candidate_id}')
        if c['status']!='candidate': raise ValueError(f"candidate {candidate_id} is already {c['status']}")
        self.candidates.resolve(candidate_id,'rejected',None,reason)
        return {'ok':True,'candidate_id':candidate_id,'resolution':'rejected'}

    # ---- 世界模型 V2:Identity/Role、一等 Event、Assertion/Evidence ----
    def identity_profile_set(self,profile:dict):
        return {'ok':True,'profile':self.entity_graph.identity_profile_put(profile or {})}

    def event_create(self,name:str,chapter:int,event_key:str|None=None,event_type:str='event',thread_key:str|None=None,
                     location_key:str|None=None,cause_event_id:int|None=None,cause_event_key:str|None=None,
                     outcome:str='',consequence:str='',status:str='verified',participants:list|None=None,metadata:dict|None=None):
        return self.world_model.event_create(name,chapter,event_key,event_type,thread_key,location_key,cause_event_id,cause_event_key,outcome,consequence,status,participants,metadata)

    def event_get(self,event_key:str|None=None,event_id:int|None=None):
        return self.world_model.event_get(event_key,event_id)

    def event_timeline(self,entity_key:str|None=None,from_chapter:int|None=None,to_chapter:int|None=None,limit:int=100):
        return self.world_model.event_timeline(entity_key,from_chapter,to_chapter,limit)

    def assertion_create(self,subject_key:str,predicate:str,object_value:Any=None,chapter:int=0,subject_type:str='entity',
                         source_span:str|None=None,extractor:str='author_declared',confidence:float=1.0,
                         evidence:str|None=None,event_id:int|None=None):
        return self.world_model.assertion_create(subject_key,predicate,object_value,chapter,subject_type,source_span,extractor,confidence,evidence,event_id,confirmed=False)

    def assertion_list(self,subject_key:str|None=None,subject_type:str|None=None,predicate:str|None=None,truth_status:str|None=None,limit:int=100):
        return self.world_model.assertion_list(subject_key,subject_type,predicate,truth_status,limit)

    def assertion_resolve(self,assertion_id:int,truth_status:str,superseded_by:int|None=None):
        return self.world_model.assertion_resolve(assertion_id,truth_status,superseded_by)

    # ---- 双时序 per-holder 与专业子图(Phase A 第二批) ----
    def fact_disclosure_set(self,fact_key:str,holder:str,known_from_chapter:int,channel:str='',source:str='author_declared'):
        return self.world.set_disclosure(fact_key,holder,known_from_chapter,channel,source)

    def fact_disclosures_get(self,fact_key:str|None=None):
        return self.world.disclosures(fact_key)

    def power_context_get(self,entity_key:str,chapter:int):
        return self.entity_graph.power_context(entity_key,chapter)

    def artifact_history_get(self,entity_key:str):
        return self.entity_graph.artifact_history(entity_key)

    def geography_tree_get(self,root_entity_key:str,chapter:int,holder:str='reader',relation_types:list[str]|None=None,max_depth:int=4,limit:int=100):
        return self.entity_graph.geography_subtree(root_entity_key,chapter,holder,relation_types,max_depth,limit)
    def dormant_threads(self,chapter:int,limit:int=8)->list[dict]:
        """休眠线程清单:open 且最后登场距今超过自适应阈值(千章书~1/4书长,短书≥10章)。"""
        old=max(10,chapter//4)
        out=[]
        for r in self.store.thread_stage_recency(chapter,200):
            age=chapter-int(r['mc'] or 0)
            if age>old:
                t=self.store.thread(r['thread_key'])
                if t and t.get('status')=='open':
                    out.append({'thread_key':r['thread_key'],'name':t.get('name'),'dormant_for':age})
            if len(out)>=limit:break
        return out
    def aging_debts(self,chapter:int,limit:int=8)->list[dict]:
        """陈年情感债清单:未完全清偿且账龄超过自适应阈值,最老在前。"""
        old=max(10,chapter//4)
        rows=[d for d in self.store.open_debts() if chapter-int(d['created_chapter'])>=old]
        rows.sort(key=lambda d:int(d['created_chapter']))
        return [{'debt_key':d['debt_key'],'thread_key':d['thread_key'],'name':d['name'],
                 'emotion_type':d.get('emotion_type'),'status':d['status'],
                 'age':chapter-int(d['created_chapter'])} for d in rows[:limit]]
    def planner_context_get(self,chapter:int,recent_window:int=10):
        """由 v0.7 检索层编译的作者层规划上下文。"""
        compiled=self.context_compiler.compile(chapter,'planner','reader',max_tokens=24000,recent_window=recent_window,include_reference=True,persist=True)
        ctx=compiled['context']
        entity_items=(ctx.get('entity_context') or {}).get('items') or []
        ch=self.canon.chapter_at_or_before(chapter-1)
        return {
            'layer':'AUTHOR_PLANNING_CONTEXT',
            'chapter':chapter,
            'context_snapshot_id':compiled['snapshot_id'],
            'context_budget':compiled['budget'],
            'blueprint':ctx.get('blueprint'),
            'world_truth_ledger':ctx.get('world_truth_ledger') or [],
            'entity_graph_summary':self.entity_graph.stats(),
            'author_entity_context':{
                'chapter':compiled['snapshot_chapter'],'view':'author',
                'entities':[x.get('entity') for x in entity_items if x.get('entity')],
                'ranking':[{'entity_key':x.get('entity_key'),'score':x.get('score'),'reasons':x.get('reasons')} for x in entity_items],
            },
            'story_state':{
                'main_goal':self.store.get_meta('main_goal',''),
                'current_arc':(ch['arc'] if ch else self.store.get_meta('current_arc','')),
                'selected_thread_keys':(ctx.get('narrative_context') or {}).get('selected_thread_keys') or [],
            },
            'arc_plan':ctx.get('arc_plan'),
            'rolling_window':ctx.get('rolling_window'),
            'due_thread_schedule':ctx.get('due_thread_schedule') or [],
            'author_directive':ctx.get('author_directive'),
            # 40 章实测 0/129 显式回收的根因:此清单曾用默认 min_age=100,
            # 40 章规模内永远为空,planner 无从引用 callback_key。销账台账必须全量。
            'due_foreshadowing':self.foreshadowing_list_open(chapter, 0, 60),
            'dormant_threads':self.dormant_threads(chapter),
            'aging_debts':self.aging_debts(chapter),
            'milestones':ctx.get('milestones') or [],
            'planning_pressure':ctx.get('planning_pressure'),
            'recent_chapters':ctx.get('recent_canon') or [],
            'narrative_context':ctx.get('narrative_context') or {},
            'belief_context':ctx.get('belief_context') or [],
            'reference_patterns':ctx.get('reference_patterns') or [],
            'retrieval_trace':compiled.get('retrieval_trace') or [],
            'discipline':'Use World Truth for author planning only. Do not treat future plan knowledge as current Reader/POV knowledge.',
        }

    def chapter_plan_generate(self,chapter:int,model:str|None=None,save:bool=True,allow_blocked:bool=False):
        if not planner_model_configured() and model is None:
            return {'ok':False,'saved':False,'error':{'code':'PLANNER_NOT_CONFIGURED','message':'configure NOVEL_PLANNER_* or NOVEL_WRITER_*'}}
        context=self.planner_context_get(chapter)
        plan,used_model=call_planner_model(context,model=model)
        if not isinstance(plan,dict):
            return {'ok':False,'saved':False,'error':{'code':'INVALID_PLANNER_OUTPUT'}}
        questions=plan.get('author_questions') if isinstance(plan.get('author_questions'),list) else []
        # 模型可能返回 {"question": ...} 对象或纯字符串;统一归一化为字符串
        norm_questions=[]
        for q in questions:
            if isinstance(q,dict):
                q=(q.get('question') or q.get('q') or json.dumps(q,ensure_ascii=False)).strip()
            if isinstance(q,str) and q.strip():
                norm_questions.append(q.strip())
        questions=norm_questions
        if questions:
            return {'ok':False,'saved':False,'needs_author_decision':True,'author_questions':questions,'plan':plan,'model':used_model}
        arc=plan.get('arc_key') or ((context.get('arc_plan') or {}).get('arc_key'))
        pov=plan.get('pov') or 'reader'
        if not save:
            validation=self.chapter_plan_check(chapter,{**plan,'_planning_runtime':True},pov)
            return {'ok':validation['ok'],'saved':False,'plan':plan,'validation':validation,'model':used_model}
        result=self.chapter_plan_save(chapter,plan,pov_holder=pov,arc_key=arc,status='draft',allow_blocked=allow_blocked)
        result['model']=used_model
        result['generated_plan']=plan
        return result

    def novel_run_start(self,start_chapter:int|None=None,target_chapter:int|None=None,target_arc_key:str|None=None,max_chapters:int|None=None,
                        max_revision_rounds:int=3,require_semantic:bool=True,allow_warnings:bool=True,auto_extract:bool=False,
                        auto_plan:bool=True,stop_on_pressure:bool=True,pressure_risk_limit:int=4,report_every:int=10,
                        hard_horizon:int=5,medium_horizon:int=20,soft_horizon:int=50,planner_model:str|None=None,
                        writer_model:str|None=None,reviewer_model:str|None=None,revision_model:str|None=None,
                        steering_mode:bool=False,plan_review:bool=False):
        return self.runs.start(start_chapter=start_chapter,target_chapter=target_chapter,target_arc_key=target_arc_key,max_chapters=max_chapters,
            max_revision_rounds=max_revision_rounds,require_semantic=require_semantic,allow_warnings=allow_warnings,auto_extract=auto_extract,
            auto_plan=auto_plan,stop_on_pressure=stop_on_pressure,pressure_risk_limit=pressure_risk_limit,report_every=report_every,
            steering_mode=steering_mode,plan_review=plan_review,
            hard_horizon=hard_horizon,medium_horizon=medium_horizon,soft_horizon=soft_horizon,planner_model=planner_model,
            writer_model=writer_model,reviewer_model=reviewer_model,revision_model=revision_model)

    def novel_run_step(self,run_id:str): return self.runs.step(run_id)
    def novel_run_continue(self,run_id:str,max_steps:int=5): return self.runs.continue_run(run_id,max_steps)
    def novel_run_status(self,run_id:str): return self.runs.status(run_id)
    def novel_run_pause(self,run_id:str,reason:str=''): return self.runs.pause(run_id,reason)
    def novel_run_resume(self,run_id:str): return self.runs.resume(run_id)
    def novel_run_report(self,run_id:str,persist:bool=False): return self.runs.report(run_id,persist)
    def novel_run_decision_list(self,run_id:str,status:str|None='open'): return self.runs.decisions(run_id,status)
    def novel_run_decision_submit(self,run_id:str,decision_id:str,resolution:dict): return self.runs.submit_decision(run_id,decision_id,resolution)
    # ---- 写作 / 审校运行时 v0.4 ----
    @staticmethod
    def _declared_updates_from_plan(plan:dict|None):
        plan=plan or {}; out={}
        for key in ('threads','clues','reveals','belief_updates','emotion_debts','payoffs','world_facts','events','character_states','entities','entity_aliases','entity_attributes','entity_relations','narrative_entity_links'):
            value=plan.get(key)
            if isinstance(value,list) and all(isinstance(x,dict) for x in value): out[key]=value
        return out

    def writer_context_get(self,chapter:int,recent_window:int=8,excerpt_chars:int=500):
        """返回基于权威记忆编译、带 token 预算的正文安全上下文包。"""
        cp=self.planning.chapter_plan_get(chapter)
        if not cp: raise KeyError(f'no saved chapter plan: {chapter}')
        if cp.get('validation_status')=='blocked':
            raise ValueError(f'chapter plan {chapter} is blocked; fix planning errors before writing')
        plan=cp.get('plan') or {}
        pov=cp.get('pov_holder') or plan.get('pov') or 'reader'
        compiled=self.context_compiler.compile(chapter,'writer',pov,max_tokens=12000,recent_window=recent_window,excerpt_chars=excerpt_chars,include_reference=False,persist=True)
        ctx=compiled['context']
        entity_items=(ctx.get('entity_context') or {}).get('items') or []
        narrative_items=(ctx.get('narrative_context') or {}).get('items') or []
        mysteries=[]; debts=[]
        for t in narrative_items:
            for m in t.get('open_mysteries') or []:
                if not any(x.get('mystery_key')==m.get('mystery_key') for x in mysteries): mysteries.append(m)
            for d in t.get('open_emotion_debts') or []:
                if not any(x.get('debt_key')==d.get('debt_key') for x in debts): debts.append(d)
        threads=[]
        for t in narrative_items:
            stages=t.get('recent_stages') or []
            threads.append({'thread_key':t.get('thread_key'),'name':t.get('name'),'status':t.get('status'),'latest_stage':stages[-1] if stages else None,'target_min':t.get('target_min'),'target_max':t.get('target_max'),'relevance_score':t.get('score'),'relevance_reasons':t.get('reasons')})
        return {
            'chapter':chapter,
            'context_snapshot_id':compiled['snapshot_id'],
            'context_budget':compiled['budget'],
            'safety_model':'Writer receives only Reader/POV-visible, chapter-sliced and relevance-ranked memory. Hidden World Truth values and secret Entity Graph relations are absent.',
            'entity_context':{
                'chapter':compiled['snapshot_chapter'],'view':pov,
                'entities':[x.get('entity') for x in entity_items if x.get('entity')],
                'ranking':[{'entity_key':x.get('entity_key'),'score':x.get('score'),'reasons':x.get('reasons')} for x in entity_items],
                'subgraphs':[],
            },
            'chapter_plan':cp,
            'blueprint':ctx.get('blueprint'),
            'arc_plan':ctx.get('arc_plan'),
            'pov_holder':pov,
            'visible_beliefs':ctx.get('belief_context') or [],
            'forbidden_fact_keys':ctx.get('forbidden_fact_keys') or [],
            'active_thread_context':threads,
            'open_mysteries':mysteries,
            'open_emotion_debts':debts,
            'character_states':ctx.get('character_states') or [],
            'recent_chapters':ctx.get('recent_canon') or [],
            'due_thread_schedule':self.planning.schedule_get(chapter=chapter,status='planned',limit=100),
            'retrieval_trace':compiled.get('retrieval_trace') or [],
        }

    def chapter_draft_generate(self,chapter:int,title:str|None=None,model:str|None=None,declared_updates:dict|None=None,summary:str=''):
        ctx=self.writer_context_get(chapter)
        cp=ctx['chapter_plan']; plan=cp.get('plan') or {}; pov=cp.get('pov_holder') or 'reader'
        title=title or plan.get('title') or f'第{chapter}章'
        declared_updates=declared_updates if declared_updates is not None else self._declared_updates_from_plan(plan)
        system=(
          '你是长篇小说正文 Writer。只执行已批准的 ChapterPlan，不擅自改变 World Truth、终局设定或长期线程。'
          '只能使用上下文中的 Reader Knowledge 与当前 POV 可知信息。forbidden_fact_keys 只表示存在秘密，绝不能猜测、补全或写出其真实值。'
          '不要解释你的计划，不要输出分析，只输出可直接作为小说章节正文的文本。保持人物连续性，完成本章 primary_goal，并保留计划要求的悬念强度。若上下文 blueprint.writing_constraints 含 chapter_length_target，成文正文字数不得低于其 90%。'
        )
        user='以下是经过权限裁剪的写作上下文。严格遵守。\n'+json.dumps(ctx,ensure_ascii=False,indent=2)
        body,used_model=call_writer_model(system,user,model=model)
        saved=self.writing.save_draft(chapter,title,body,arc=(cp.get('arc_key') or ''),pov=pov,summary=summary,
            declared_updates=declared_updates,source='model',model=used_model,status='draft')
        leak=self._body_secret_leak_check(chapter,body,pov,declared_updates)
        return {'ok':True,'draft':saved,'preflight':{'knowledge_leak':leak}}

    def chapter_draft_save(self,chapter:int,title:str,body:str,arc:str='',pov:str='',summary:str='',declared_updates:dict|None=None,source:str='external',model:str='',parent_version:int|None=None):
        cp=self.planning.chapter_plan_get(chapter)
        if not cp: raise KeyError(f'no saved chapter plan: {chapter}')
        if cp.get('validation_status')=='blocked': raise ValueError('cannot draft from a blocked ChapterPlan')
        saved=self.writing.save_draft(chapter,title,body,arc=arc or (cp.get('arc_key') or ''),pov=pov or cp.get('pov_holder') or '',summary=summary,
            declared_updates=declared_updates if declared_updates is not None else self._declared_updates_from_plan(cp.get('plan') or {}),
            source=source,model=model,parent_version=parent_version,status='revision' if parent_version else 'draft')
        return {'ok':True,'draft':saved}

    def chapter_draft_get(self,chapter:int,version:int|None=None):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter} version {version or "latest"}')
        return d

    def _review_narrative(self,chapter:int,draft:dict,cp:dict|None):
        findings=[]; verdict='PASS'; score=1.0
        if not cp:
            return {'reviewer_type':'narrative','verdict':'BLOCK','score':0.0,'findings':[{'code':'CHAPTER_PLAN_MISSING','message':'cannot review narrative adherence without a saved ChapterPlan'}]}
        if cp.get('validation_status')=='blocked':
            findings.append({'code':'CHAPTER_PLAN_BLOCKED','message':'saved plan is blocked'}); verdict='BLOCK'; score=0.0
        plan=cp.get('plan') or {}; updates=draft.get('declared_updates') or {}
        # 章长纪律(40 章实测 25/40 低于目标 90%):确定性 WARN,让短章在审校面可见。
        target=(self.planning.blueprint_get().get('blueprint') or {}).get('chapter_length_target')
        body=draft.get('body') or ''
        if isinstance(target,(int,float)) and int(target)>0 and len(body)<int(target)*0.9:
            findings.append({'code':'SHORT_CHAPTER','actual':len(body),'target':int(target),'message':f'body is {len(body)} chars, below 90% of chapter_length_target {int(target)}'})
            if verdict!='BLOCK': verdict='WARN'; score=min(score,0.85)
        intended=set(((plan.get('threads') or {}).get('advance') or []))
        actual=set()
        for key in ('clues','reveals','payoffs','events'):
            for x in updates.get(key,[]) if isinstance(updates.get(key),list) else []:
                if isinstance(x,dict) and x.get('thread_key'): actual.add(x['thread_key'])
        missing=sorted(intended-actual)
        if missing:
            findings.append({'code':'PLANNED_THREAD_NOT_DECLARED','thread_keys':missing,'message':'plan advances these threads but draft declares no canonical update for them'})
            if verdict!='BLOCK': verdict='WARN'; score=min(score,0.8)
        planned_reveals={x.get('fact_key') for x in plan.get('reveals',[]) if isinstance(x,dict) and x.get('fact_key')}
        actual_reveals={x.get('fact_key') for x in updates.get('reveals',[]) if isinstance(x,dict) and x.get('fact_key')}
        missing_reveals=sorted(planned_reveals-actual_reveals)
        if missing_reveals:
            findings.append({'code':'PLANNED_REVEAL_NOT_DECLARED','fact_keys':missing_reveals,'message':'a planned Reveal must be explicitly declared before commit'})
            verdict='BLOCK'; score=min(score,0.4)
        planned_payoffs={x.get('debt_key') for x in plan.get('payoffs',[]) if isinstance(x,dict) and x.get('debt_key')}
        actual_payoffs={x.get('debt_key') for x in updates.get('payoffs',[]) if isinstance(x,dict) and x.get('debt_key')}
        missing_payoffs=sorted(planned_payoffs-actual_payoffs)
        if missing_payoffs:
            findings.append({'code':'PLANNED_PAYOFF_NOT_DECLARED','debt_keys':missing_payoffs})
            verdict='BLOCK'; score=min(score,0.4)
        return {'reviewer_type':'narrative','verdict':verdict,'score':score,'findings':findings}

    def _review_character(self,chapter:int,draft:dict,cp:dict|None):
        findings=[]; updates=draft.get('declared_updates') or {}; states=updates.get('character_states',[]) or []
        cont=self.continuity_check(chapter,[],states)
        findings.extend(cont.get('errors',[]) or []); findings.extend(cont.get('warnings',[]) or [])
        pov=draft.get('pov') or (cp or {}).get('pov_holder') or ''
        if pov and pov!='reader':
            st=self.canon.character_state(pov,chapter,inclusive=False)
            if st:
                state=st.get('state') or {}
                if state.get('alive') is False and not ((cp or {}).get('plan') or {}).get('allow_posthumous_pov'):
                    findings.append({'code':'DEAD_POV_CHARACTER','character_key':pov,'message':'POV character is canonically dead before this chapter'})
                    return {'reviewer_type':'character','verdict':'BLOCK','score':0.0,'findings':findings}
        verdict='BLOCK' if cont.get('errors') else ('WARN' if findings else 'PASS')
        return {'reviewer_type':'character','verdict':verdict,'score':0.5 if verdict=='BLOCK' else (0.8 if verdict=='WARN' else 1.0),'findings':findings}

    def chapter_review_all(self,chapter:int,version:int|None=None):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        cp=self.planning.chapter_plan_get(chapter)
        leak=self._body_secret_leak_check(chapter,d['body'],d.get('pov') or '',d.get('declared_updates') or {})
        knowledge={'reviewer_type':'knowledge_leak','verdict':'PASS' if leak['ok'] else 'BLOCK','score':1.0 if leak['ok'] else 0.0,'findings':leak.get('errors',[])}
        updates=d.get('declared_updates') or {}
        cont=self.continuity_check(chapter,updates.get('world_facts',[]) or [],updates.get('character_states',[]) or [],updates.get('entities',[]) or [],updates.get('entity_attributes',[]) or [],updates.get('entity_relations',[]) or [])
        cv='BLOCK' if cont.get('errors') else ('WARN' if cont.get('warnings') else 'PASS')
        continuity={'reviewer_type':'continuity','verdict':cv,'score':0.0 if cv=='BLOCK' else (0.8 if cv=='WARN' else 1.0),'findings':(cont.get('errors') or [])+(cont.get('warnings') or [])}
        narrative=self._review_narrative(chapter,d,cp)
        character=self._review_character(chapter,d,cp)
        reviews=[knowledge,continuity,narrative,character]
        self.writing.replace_reviews(chapter,d['version'],reviews,replace_types=['knowledge_leak','continuity','narrative','character'])
        return {'ok':overall_verdict(reviews)!='BLOCK','chapter':chapter,'draft_version':d['version'],'overall_verdict':overall_verdict(reviews),'reviews':reviews}

    def _semantic_review_payload(self,chapter:int,draft:dict,cp:dict|None):
        """构建作者感知的审校包。隐藏真相取值只保留在服务端,绝不返回给写作者工具。"""
        safe=self.writer_context_get(chapter)
        plan=(cp or {}).get('plan') or {}
        declared=draft.get('declared_updates') or {}
        allowed=set()
        for r in declared.get('reveals',[]) if isinstance(declared.get('reveals'),list) else []:
            if not isinstance(r,dict) or not r.get('fact_key'): continue
            recipients=r.get('recipients') or [r.get('holder') or 'reader']
            if 'reader' in recipients or (draft.get('pov') and draft.get('pov') in recipients):
                allowed.add(r['fact_key'])
        hidden={}
        for f in self.world.all_facts():
            truth=f.get('truth')
            snap=self.store.belief_snapshot(f['fact_key'],max(0,chapter-1))
            hidden[f['fact_key']]={
                'truth':truth,
                'secrecy':f.get('secrecy'),
                'reveal_after':f.get('reveal_after'),
                'reader_before':snap.get('holders',{}).get('reader',{'stance':'unknown'}),
                'pov_before':snap.get('holders',{}).get(draft.get('pov') or (cp or {}).get('pov_holder') or 'reader',{'stance':'unknown'}),
                'legal_reveal_declared_this_chapter':f['fact_key'] in allowed,
                'arc_forbidden':f['fact_key'] in set((safe.get('arc_plan') or {}).get('forbidden_facts') or []),
            }
        reviewer_holder=draft.get('pov') or (cp or {}).get('pov_holder') or 'reader'
        compiled_reviewer=self.context_compiler.compile(chapter,'reviewer',reviewer_holder,max_tokens=20000,include_reference=False,persist=True)
        reviewer_entities=((compiled_reviewer.get('context') or {}).get('entity_context') or {}).get('items') or []
        author_entity_context={
            'chapter':compiled_reviewer.get('snapshot_chapter'),'view':'author',
            'entities':[x.get('entity') for x in reviewer_entities if x.get('entity')],
            'ranking':[{'entity_key':x.get('entity_key'),'score':x.get('score'),'reasons':x.get('reasons')} for x in reviewer_entities],
        }
        return {
            'review_contract':'Author-aware semantic review. Hidden World Truth and author Entity Graph secrets are for comparison only and must never be echoed into findings.',
            'reviewer_context_snapshot_id':compiled_reviewer.get('snapshot_id'),
            'reviewer_context_budget':compiled_reviewer.get('budget'),
            'author_entity_context':author_entity_context,
            'chapter':chapter,
            'chapter_plan':cp,
            'draft':{k:draft.get(k) for k in ('chapter','version','title','body','arc','pov','summary','declared_updates')},
            'safe_writer_context':safe,
            'hidden_truth_ledger':hidden,
            'story_pressure':self.planning_pressure_check(chapter),
            'clue_strength_scale':{'0.1':'nearly subliminal','0.3':'noticeable to attentive readers','0.5':'clear but ambiguous','0.7':'strong implication','0.9':'near reveal'},
        }

    def chapter_semantic_review(self,chapter:int,version:int|None=None,model:str|None=None):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        cp=self.planning.chapter_plan_get(chapter)
        if not semantic_reviewer_configured() and model is None:
            return {'ok':False,'chapter':chapter,'draft_version':d['version'],'error':{'code':'SEMANTIC_REVIEWER_NOT_CONFIGURED','message':'configure NOVEL_REVIEWER_* or NOVEL_WRITER_*'}}
        payload=self._semantic_review_payload(chapter,d,cp)
        hidden_truths={k:v.get('truth') for k,v in payload['hidden_truth_ledger'].items()}
        raw,used_model=call_semantic_reviewer(payload,model=model)
        reviews=normalize_semantic_reviews(raw)
        # 审校者允许在内部查看作者真相,但其持久化/公开的证据会被脱敏。
        reviews=redact_hidden_values(reviews,hidden_truths)
        for r in reviews:
            r.setdefault('metadata',{})['model']=used_model
            r['metadata']['semantic']=True
        self.writing.replace_reviews(chapter,d['version'],reviews,replace_types=list(SEMANTIC_REVIEWER_TYPES))
        return {'ok':overall_verdict(reviews)!='BLOCK','chapter':chapter,'draft_version':d['version'],
                'overall_verdict':overall_verdict(reviews),'reviews':reviews,'model':used_model}

    def chapter_review_full(self,chapter:int,version:int|None=None,semantic:bool=True,model:str|None=None):
        deterministic=self.chapter_review_all(chapter,version)
        d=self.writing.get_draft(chapter,version)
        semantic_result=None
        if semantic:
            semantic_result=self.chapter_semantic_review(chapter,d['version'],model=model)
            if not semantic_result.get('ok') and semantic_result.get('error'):
                return {'ok':False,'chapter':chapter,'draft_version':d['version'],'overall_verdict':'INCOMPLETE',
                        'deterministic':deterministic,'semantic':semantic_result,
                        'error':semantic_result['error']}
        bundle=self.chapter_review_get(chapter,d['version'])
        return {'ok':bundle['overall_verdict']!='BLOCK','chapter':chapter,'draft_version':d['version'],
                'overall_verdict':bundle['overall_verdict'],'reviews':bundle['reviews'],
                'deterministic':deterministic,'semantic':semantic_result}

    def chapter_auto_revise(self,chapter:int,version:int|None=None,model:str|None=None,include_warnings:bool=True):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        reviews=self.writing.get_reviews(chapter,d['version'])
        if not reviews:
            raise ValueError('review the exact draft version before auto revision')
        actionable=[]
        for r in reviews:
            if r.get('verdict')=='BLOCK' or (include_warnings and r.get('verdict')=='WARN'):
                actionable.append({'reviewer_type':r['reviewer_type'],'verdict':r['verdict'],'findings':r.get('findings') or []})
        if not actionable:
            return {'ok':True,'revised':False,'reason':'NO_ACTIONABLE_FINDINGS','draft':d}
        safe=self.writer_context_get(chapter)
        payload={
            'chapter':chapter,
            'chapter_plan':safe.get('chapter_plan'),
            'safe_writer_context':safe,
            'current_draft':{k:d.get(k) for k in ('version','title','body','arc','pov','summary','declared_updates')},
            'review_findings':actionable,
            'revision_constraints':[
                'preserve declared_updates semantic intent unless the human changes the ChapterPlan',
                'do not introduce hidden World Truth or unscheduled Reveal',
                'produce a complete replacement chapter body',
            ],
        }
        body,used_model=call_revision_model(payload,model=model)
        if body.strip()==(d.get('body') or '').strip():
            return {'ok':False,'revised':False,'reason':'REVISION_NO_CHANGE','draft':d,'model':used_model}
        saved=self.writing.save_draft(chapter,d['title'],body,arc=d.get('arc') or '',pov=d.get('pov') or '',summary=d.get('summary') or '',
            declared_updates=d.get('declared_updates') or {},source='auto_revision',model=used_model,parent_version=d['version'],status='revision')
        return {'ok':True,'revised':True,'parent_version':d['version'],'draft':saved,'model':used_model}

    def chapter_auto_revision_loop(self,chapter:int,version:int|None=None,max_rounds:int=3,require_semantic:bool=True,
                                   reviewer_model:str|None=None,revision_model:str|None=None,finalize:bool=False,
                                   allow_warnings:bool=True,auto_extract:bool=False):
        if max_rounds<0 or max_rounds>8: raise ValueError('max_rounds must be between 0 and 8')
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        history=[]; current=d; revisions=0
        while True:
            if require_semantic:
                reviewed=self.chapter_review_full(chapter,current['version'],semantic=True,model=reviewer_model)
                if reviewed.get('error') or reviewed.get('overall_verdict')=='INCOMPLETE':
                    return {'ok':False,'status':'review_incomplete','chapter':chapter,'draft_version':current['version'],
                            'revision_rounds':revisions,'history':history,'review_result':reviewed}
            else:
                reviewed=self.chapter_review_all(chapter,current['version'])
            bundle=self.chapter_review_get(chapter,current['version'])
            verdict=bundle['overall_verdict']
            history.append({'version':current['version'],'verdict':verdict,'reviews':bundle['reviews']})
            acceptable=verdict=='PASS' or (verdict=='WARN' and allow_warnings)
            if acceptable:
                result={'ok':True,'status':'ready_to_finalize','chapter':chapter,'draft_version':current['version'],
                        'overall_verdict':verdict,'revision_rounds':revisions,'history':history}
                if finalize:
                    result['finalize']=self.chapter_finalize(chapter,current['version'],allow_warnings=allow_warnings,
                        auto_extract=auto_extract,require_semantic=require_semantic)
                    result['status']='committed' if result['finalize'].get('committed') else 'finalize_failed'
                    result['ok']=bool(result['finalize'].get('committed'))
                return result
            if revisions>=max_rounds:
                return {'ok':False,'status':'revision_limit_reached','chapter':chapter,'draft_version':current['version'],
                        'overall_verdict':verdict,'revision_rounds':revisions,'history':history}
            revised=self.chapter_auto_revise(chapter,current['version'],model=revision_model,include_warnings=True)
            if not revised.get('revised'):
                return {'ok':False,'status':'revision_stalled','chapter':chapter,'draft_version':current['version'],
                        'overall_verdict':verdict,'revision_rounds':revisions,'history':history,'revision_result':revised}
            current=revised['draft']; revisions+=1

    def chapter_review_get(self,chapter:int,version:int|None=None):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        reviews=self.writing.get_reviews(chapter,d['version'])
        return {'chapter':chapter,'draft_version':d['version'],'overall_verdict':overall_verdict(reviews) if reviews else 'NOT_REVIEWED','reviews':reviews}

    def chapter_revision_context_get(self,chapter:int,version:int|None=None):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        review=self.chapter_review_get(chapter,d['version'])
        return {'chapter':chapter,'draft':d,'review_bundle':review,'safe_writer_context':self.writer_context_get(chapter),
          'revision_instruction':'Fix BLOCK findings first, then WARN findings. Preserve approved ChapterPlan and do not introduce new World Truth or unscheduled Reveal.'}

    def writing_workflow_status(self,chapter:int):
        wf=self.writing.workflow(chapter); drafts=self.writing.list_drafts(chapter)
        latest=drafts[-1] if drafts else None
        reviews=self.writing.get_reviews(chapter,latest['version']) if latest else []
        cp=self.planning.chapter_plan_get(chapter)
        return {'chapter':chapter,'workflow':wf,'chapter_plan':cp,'drafts':[{'version':d['version'],'status':d['status'],'source':d['source'],'model':d['model'],'parent_version':d['parent_version'],'created_at':d['created_at']} for d in drafts],
          'latest_review_verdict':overall_verdict(reviews) if reviews else 'NOT_REVIEWED'}

    def chapter_finalize(self,chapter:int,version:int|None=None,allow_warnings:bool=True,auto_extract:bool=False,override_block:bool=False,override_reason:str='',require_semantic:bool=False):
        d=self.writing.get_draft(chapter,version)
        if not d: raise KeyError(f'no draft for chapter {chapter}')
        cp=self.planning.chapter_plan_get(chapter)
        if not cp: return {'ok':False,'committed':False,'error':{'code':'CHAPTER_PLAN_MISSING'}}
        p=dict(cp.get('plan') or {}); p['_planning_runtime']=True
        pv=self.chapter_plan_check(chapter,p,cp.get('pov_holder') or 'reader')
        if not pv['ok'] and not override_block:
            return {'ok':False,'committed':False,'error':{'code':'PLAN_REVALIDATION_BLOCKED','validation':pv}}
        reviews=self.writing.get_reviews(chapter,d['version'])
        required={'knowledge_leak','continuity','narrative','character'}
        if require_semantic: required.update(SEMANTIC_REVIEWER_TYPES)
        have={r['reviewer_type'] for r in reviews}
        if not required.issubset(have):
            return {'ok':False,'committed':False,'error':{'code':'REVIEW_INCOMPLETE','missing':sorted(required-have)}}
        ov=overall_verdict(reviews)
        if ov=='BLOCK' and not override_block:
            return {'ok':False,'committed':False,'error':{'code':'REVIEW_BLOCKED','reviews':reviews}}
        if ov=='WARN' and not allow_warnings:
            return {'ok':False,'committed':False,'error':{'code':'REVIEW_WARNINGS_REQUIRE_APPROVAL','reviews':reviews}}
        if override_block and not override_reason.strip():
            return {'ok':False,'committed':False,'error':{'code':'OVERRIDE_REASON_REQUIRED'}}
        result=self.chapter_commit(chapter,d['title'],d['body'],d.get('arc') or '',d.get('pov') or '',d.get('summary') or '',d.get('declared_updates') or {},auto_extract)
        if result.get('committed'):
            self.writing.set_status(chapter,d['version'],'committed')
            result['review_gate']={'overall_verdict':ov,'override_block':override_block,'override_reason':override_reason}
        return result

    def chapter_commit(self,chapter:int,title:str,body:str,arc='',pov='',summary='',declared_updates=None,auto_extract=False):
        """提交门内部实现:正典写入在单个环境事务中原子完成。

        LLM 抽取(auto_extract)是慢操作,刻意放在事务之外;抽取失败不
        影响已提交的正典。外部请使用 chapter_finalize 走完整审校门。
        """
        declared_updates=_normalize_declared(declared_updates or {})
        check=self.chapter_plan_check(chapter,declared_updates,pov or 'reader')
        if not check['ok']: return {'ok':False,'committed':False,'plan_check':check}
        leak=self._body_secret_leak_check(chapter,body,pov,declared_updates)
        if not leak['ok']: return {'ok':False,'committed':False,'plan_check':check,'prose_leak_check':leak}
        with self.store.transaction():
            self.canon.commit_chapter(chapter,title,body,arc,pov,summary)
            self.planning.mark_chapter_committed(chapter)
            applied=self._apply_declared(chapter,declared_updates)
        extract=self._auto_extract(chapter,title,body,arc) if auto_extract else {'status':'skipped','candidate_count':0}
        cont=self.continuity_check(chapter,declared_updates.get('world_facts',[]),declared_updates.get('character_states',[]),declared_updates.get('entities',[]),declared_updates.get('entity_attributes',[]),declared_updates.get('entity_relations',[]))
        return {'ok':cont['ok'],'committed':True,'chapter':chapter,'declared_updates_applied':applied,'auto_extraction':extract,'continuity':cont,'next_state_summary':self.story_pressure_check(chapter)}

    # ---- Web BFF 聚合读(Phase D1):只读,进程内直调,不经工具面 ----
    # 约定:这些方法只 SELECT + 复用既有只读方法,永不写库;"UI 永不绕闸门"
    # 的另一半在 web_api.py —— 写动作一律透传 facade_call。

    def _web_run_public(self, row) -> dict:
        r = dict(row)
        for src, dst in (('config_json', 'config'), ('stop_reason_json', 'stop_reason')):
            raw = r.pop(src, None)
            if raw:
                try: r[dst] = json.loads(raw)
                except Exception: r[dst] = raw
            else:
                r[dst] = None
        return r

    def web_architecture(self):
        """Read-only snapshot for before/after architecture review."""
        groups = {'world_facts': 'world_facts', 'entities': 'entities',
                  'identity_profiles': 'identity_profiles', 'entity_aliases': 'entity_aliases',
                  'entity_attributes': 'entity_attributes', 'entity_relations': 'entity_relations',
                  'narrative_entity_links': 'narrative_entity_links', 'threads': 'threads',
                  'mysteries': 'mysteries', 'emotion_debts': 'debts', 'arcs': 'arc_plans',
                  'milestones': 'planning_milestones', 'thread_schedule': 'thread_schedule'}
        out = {'blueprint': (self.planning.blueprint_get() or {}).get('blueprint') or {}}
        with self.store.connect() as db:
            for group, table in groups.items():
                rows = []
                for row in db.execute(f'SELECT * FROM {table}'):
                    value = dict(row)
                    for key in list(value):
                        if key.endswith('_json'):
                            value[key[:-5]] = jl(value.pop(key))
                    if group in ('threads', 'mysteries'):
                        value['target_min_chapter'] = value.pop('target_min', None)
                        value['target_max_chapter'] = value.pop('target_max', None)
                    if group == 'entities': value['chapter'] = value.pop('introduced_chapter', None)
                    if group == 'entity_attributes': value['chapter'] = value.pop('start_chapter', None)
                    rows.append(value)
                out[group] = rows
        return out

    def web_home(self, chapter: int | None = None):
        last = self.canon.max_committed_chapter() or 0
        at = int(chapter or last)
        bp = self.planning.blueprint_get()
        with self.store.connect() as db:
            agg = db.execute('SELECT COUNT(*) c, COALESCE(SUM(LENGTH(body)),0) s FROM chapters').fetchone()
            recent = [dict(r) for r in db.execute(
                'SELECT chapter,title,arc,pov,LENGTH(body) chars,committed_at FROM chapters ORDER BY chapter DESC LIMIT 7').fetchall()]
            inbox = {
                'open_decisions': db.execute("SELECT COUNT(*) c FROM novel_run_decisions WHERE status='open'").fetchone()['c'],
                'pending_candidates': db.execute("SELECT COUNT(*) c FROM extraction_candidates WHERE status='candidate'").fetchone()['c'],
                'active_draft_chapters': db.execute(
                    "SELECT COUNT(*) c FROM chapter_drafts d WHERE status NOT IN ('committed','rejected') "
                    "AND version=(SELECT MAX(version) FROM chapter_drafts WHERE chapter=d.chapter)").fetchone()['c'],
            }
            arcs = [dict(r) for r in db.execute(
                'SELECT arc_key,name,order_no,start_chapter,target_end_chapter,status FROM arc_plans ORDER BY order_no').fetchall()]
            run_row = db.execute('SELECT * FROM novel_runs ORDER BY created_at DESC LIMIT 1').fetchone()
        current_arc = next((a for a in arcs if a['start_chapter'] <= at and at <= (a['target_end_chapter'] or 10**9)), None)
        return {
            'book': {'title': (bp.get('blueprint') or {}).get('title') if isinstance(bp, dict) else None,
                     'target_total_chapters': (bp.get('blueprint') or {}).get('target_total_chapters') if isinstance(bp, dict) else None,
                     'genre': (bp.get('blueprint') or {}).get('genre') if isinstance(bp, dict) else None},
            'cursor_chapter': at,
            'progress': {'committed_chapters': agg['c'], 'total_chars': agg['s'], 'latest_chapter': last},
            'arcs': arcs, 'current_arc': current_arc,
            'pressure': self.story_pressure_check(at),
            'inbox': inbox,
            'recent_chapters': list(reversed(recent)),
            'run': self._web_run_public(run_row) if run_row else None,
        }

    def web_runs(self) -> list:
        with self.store.connect() as db:
            rows = db.execute('SELECT * FROM novel_runs ORDER BY created_at DESC LIMIT 50').fetchall()
        return [self._web_run_public(r) for r in rows]

    def web_run(self, run_id: str) -> dict:
        with self.store.connect() as db:
            row = db.execute('SELECT * FROM novel_runs WHERE run_id=?', (run_id,)).fetchone()
            if not row: raise KeyError(f'no such run: {run_id}')
            run = self._web_run_public(row)
            events = [dict(r) for r in db.execute(
                'SELECT * FROM novel_run_events WHERE run_id=? ORDER BY id DESC LIMIT 200', (run_id,)).fetchall()]
            for e in events:
                try: e['detail'] = json.loads(e.pop('detail_json') or 'null')
                except Exception: e['detail'] = None
            chapters = [dict(r) for r in db.execute(
                'SELECT chapter,title,LENGTH(body) chars,committed_at FROM chapters WHERE chapter>=? ORDER BY chapter',
                (run.get('start_chapter') or 1,)).fetchall()]
            decisions = [dict(r) for r in db.execute(
                "SELECT decision_id,chapter,decision_type,status,prompt,context_json,created_at FROM novel_run_decisions "
                "WHERE run_id=? ORDER BY created_at DESC LIMIT 50", (run_id,)).fetchall()]
        for d in decisions:
            try:
                ctx = json.loads(d.pop('context_json') or 'null') or {}
            except Exception:
                ctx = {}
            d['context'] = {k: ctx.get(k) for k in ('reason', 'decision_type', 'traceback', 'plan', 'mode', 'chapter') if ctx.get(k) is not None}
            qs = ((ctx.get('plan_result') or {}).get('author_questions')) or []
            if isinstance(qs, list) and qs:
                d['author_questions'] = [q if isinstance(q, str) else (q.get('question') or q.get('q') or '')
                                         for q in qs if isinstance(q, (str, dict)) and (q if isinstance(q, str) else (q.get('question') or q.get('q')))]
            else:
                d['author_questions'] = []
        return {'run': run, 'events': list(reversed(events)), 'chapters': chapters, 'open_decisions': decisions}

    def web_chapter(self, chapter: int, version: int | None = None) -> dict:
        with self.store.connect() as db:
            row = db.execute('SELECT chapter,title,arc,pov,summary,body,committed_at FROM chapters WHERE chapter=?', (int(chapter),)).fetchone()
        canon = dict(row) if row else None
        plan = self.planning.chapter_plan_get(int(chapter))
        drafts = [{'version': d['version'], 'status': d['status'], 'source': d['source'], 'model': d['model'],
                   'parent_version': d['parent_version'], 'created_at': d['created_at']}
                  for d in self.writing.list_drafts(int(chapter))]
        latest = self.writing.get_draft(int(chapter))
        selected = int(version) if version is not None else (latest['version'] if latest else None)
        reviews = self.writing.get_reviews(int(chapter), selected) if selected else []
        review_summary = [{'reviewer_type': r['reviewer_type'], 'verdict': r.get('verdict'), 'score': r.get('score'),
                           'findings': len(r.get('findings') or [])} for r in reviews]
        return {'chapter': int(chapter), 'canon': canon, 'chapter_plan': plan, 'drafts': drafts,
                'latest_draft_version': latest['version'] if latest else None,
                'reviews': review_summary, 'review_details': reviews,
                'reviewed_version': selected, 'gate': self._web_finalize_gate(int(chapter))}

    def _web_finalize_gate(self, chapter: int) -> dict:
        d = self.writing.get_draft(int(chapter))
        if not d:
            return {'ready': False, 'draft_version': None, 'checks': [{'key': 'draft_exists', 'ok': False}]}
        checks = [{'key': 'draft_exists', 'ok': True, 'draft_version': d['version']}]
        cp = self.planning.chapter_plan_get(int(chapter))
        checks.append({'key': 'plan_valid', 'ok': bool(cp) and cp.get('validation_status') != 'blocked'})
        reviews = self.writing.get_reviews(int(chapter), d['version'])
        required = {'knowledge_leak', 'continuity', 'narrative', 'character'}
        have = {r['reviewer_type'] for r in reviews}
        checks.append({'key': 'reviews_complete', 'ok': required.issubset(have), 'missing': sorted(required - have)})
        ov = overall_verdict(reviews) if reviews else 'NOT_REVIEWED'
        checks.append({'key': 'review_verdict_ok', 'ok': ov in ('PASS', 'WARN'), 'verdict': ov})
        return {'ready': all(c['ok'] for c in checks), 'draft_version': d['version'], 'checks': checks}

    def web_draft(self, chapter: int, version: int | None = None) -> dict:
        d = self.writing.get_draft(int(chapter), version)
        if not d: raise KeyError(f'no draft for chapter {chapter} version {version or "latest"}')
        return d

    # ---- Web BFF 聚合读(Phase D2):设定集/图谱/看板/时间线(作者层) ----

    def _web_at(self, chapter) -> int:
        return int(chapter or self.canon.max_committed_chapter() or 0)

    def web_entities(self, chapter=None, q='', entity_type=None, limit=200):
        at = self._web_at(chapter)
        rows = self.entity_graph.search(q or '', entity_type, 'active', at, 'reader', True, limit)
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.get('entity_type') or '?'] = counts.get(r.get('entity_type') or '?', 0) + 1
        return {'chapter': at, 'entities': rows, 'type_counts': counts}

    def web_entity(self, entity_key, chapter=None):
        at = self._web_at(chapter)
        with self.store.connect() as db:
            ent = db.execute('SELECT * FROM entities WHERE entity_key=?', (entity_key,)).fetchone()
            if not ent: raise KeyError(f'unknown entity: {entity_key}')
            out = dict(ent)
            out['properties'] = jl(out.pop('properties_json') or 'null')
            out['aliases'] = [dict(r) for r in db.execute(
                'SELECT alias,alias_type,secrecy,reveal_after,fact_key FROM entity_aliases WHERE entity_key=?', (entity_key,))]
            out['identity_profiles'] = [dict(r) for r in db.execute(
                'SELECT profile_key,kind,value,scope_key,secrecy,parent_profile_key,start_chapter,end_chapter,notes '
                'FROM identity_profiles WHERE entity_key=? ORDER BY kind', (entity_key,))]
            out['attributes'] = [dict(r) for r in db.execute(
                'SELECT attr_key,value_json,start_chapter,end_chapter,secrecy,fact_key,cause_event_id FROM entity_attributes '
                'WHERE entity_key=? AND start_chapter<=? ORDER BY attr_key, start_chapter', (entity_key, at))]
            for a in out['attributes']:
                a['value'] = jl(a.pop('value_json') or 'null')
            out['relations'] = [dict(r) for r in db.execute(
                'SELECT source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter,secrecy,fact_key,cause_event_id '
                'FROM entity_relations WHERE (source_entity_key=? OR target_entity_key=?) AND start_chapter<=? '
                'AND (end_chapter IS NULL OR end_chapter>=?)', (entity_key, entity_key, at, at))]
            out['narrative_links'] = [dict(r) for r in db.execute(
                'SELECT narrative_type,narrative_key,role,chapter FROM narrative_entity_links WHERE entity_key=? '
                'ORDER BY chapter', (entity_key,))]
            out['assertions'] = [dict(r) for r in db.execute(
                'SELECT assertion_id,predicate,object_value,chapter,source_span,truth_status,confidence FROM fact_assertions '
                'WHERE subject_type=? AND subject_key=? ORDER BY chapter DESC LIMIT 50', ('entity', entity_key))]
            for a in out['assertions']:
                try: a['object_value'] = jl(a['object_value']) if isinstance(a['object_value'], str) else a['object_value']
                except Exception: pass
        names = {r['entity_key']: r['name'] for r in self.entity_graph.search('', None, 'active', 10**9, 'reader', False, 500)}
        for r in out['relations']:
            r['source_name'] = names.get(r['source_entity_key'])
            r['target_name'] = names.get(r['target_entity_key'])
        with self.store.connect() as db:
            for l in out['narrative_links']:
                if l['narrative_type'] == 'thread':
                    t = db.execute('SELECT name FROM threads WHERE thread_key=?', (l['narrative_key'],)).fetchone()
                    l['narrative_name'] = t['name'] if t else l['narrative_key']
        out['chapter'] = at
        return out

    def web_graph(self, chapter=None):
        at = self._web_at(chapter)
        with self.store.connect() as db:
            nodes = [dict(r) for r in db.execute(
                "SELECT entity_key,name,entity_type,introduced_chapter FROM entities WHERE status='active' AND introduced_chapter<=?", (at,))]
            edges = [dict(r) for r in db.execute(
                'SELECT source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter,secrecy,reveal_from '
                'FROM (SELECT *, reveal_after AS reveal_from FROM entity_relations) '
                'WHERE start_chapter<=? AND (end_chapter IS NULL OR end_chapter>=?)', (at, at))]
        def visible(e):
            if e['secrecy'] == 'public': return True
            return e['reveal_from'] is not None and at >= e['reveal_from']
        return {'chapter': at,
                'nodes': [{'key': n['entity_key'], 'name': n['name'], 'type': n['entity_type']} for n in nodes],
                'edges': [{'source': e['source_entity_key'], 'type': e['relation_type'], 'target': e['target_entity_key'],
                           'secret': not visible(e)} for e in edges],
                'author_view': True}

    def web_board(self, chapter=None):
        at = self._web_at(chapter)
        with self.store.connect() as db:
            threads = [dict(r) for r in db.execute('SELECT * FROM threads ORDER BY introduced_chapter')]
            stages = [dict(r) for r in db.execute(
                'SELECT id,thread_key,chapter,stage_type,content,strength,status,callback_key FROM stages WHERE chapter<=? ORDER BY chapter', (at,))]
            mysteries = [dict(r) for r in db.execute('SELECT * FROM mysteries ORDER BY introduced_chapter')]
            debts = [dict(r) for r in db.execute(
                'SELECT debt_key,thread_key,name,emotion_type,intensity,created_chapter,status,resolved_chapter FROM debts WHERE created_chapter<=? '
                'ORDER BY created_chapter', (at,))]
            beliefs = [dict(r) for r in db.execute(
                'SELECT fact_key,holder,chapter,stance,value_json FROM beliefs WHERE chapter<=?', (at,))]
            facts = [dict(r) for r in db.execute('SELECT fact_key,truth_json,secrecy,reveal_after,notes FROM world_facts')]
            disclosures = [dict(r) for r in db.execute(
                'SELECT fact_key,holder,known_from_chapter FROM fact_disclosures WHERE known_from_chapter<=?', (at,))]
        # 信念矩阵:每个事实 × 持有者在该章的最新认知
        latest: dict[tuple, dict] = {}
        for b in beliefs:
            k = (b['fact_key'], b['holder'])
            if k not in latest or b['chapter'] >= latest[k]['chapter']:
                latest[k] = b
        holder_set = sorted({h for (_, h) in latest} | {'reader'})
        matrix = []
        for f in facts:
            holders = {}
            for h in holder_set:
                b = latest.get((f['fact_key'], h))
                disc = next((d for d in disclosures if d['fact_key'] == f['fact_key'] and d['holder'] == h), None)
                if b or disc:
                    holders[h] = {'stance': (b or {}).get('stance') or ('known' if disc else None),
                                  'value': jl(b['value_json']) if b and b.get('value_json') else None,
                                  'since': (b or {}).get('chapter')}
            matrix.append({'fact_key': f['fact_key'], 'truth': jl(f['truth_json']), 'secrecy': f['secrecy'],
                           'reveal_after': f['reveal_after'], 'holders': holders})
        # 伏笔-兑现配对:callback_key 相同的 Clue 与 Payoff/Reveal
        callbacks = [s for s in stages if s.get('callback_key')]
        paired = {s['callback_key'] for s in callbacks if s['stage_type'] in ('Payoff', 'Reveal')}
        clues = [{'stage_id': s['id'], 'thread_key': s['thread_key'], 'chapter': s['chapter'],
                  'callback_key': s['callback_key'], 'paid': s['callback_key'] in paired,
                  'content': (s['content'] or '')[:80]} for s in callbacks if s['stage_type'] == 'Clue']
        return {'chapter': at, 'threads': threads, 'stages': stages, 'mysteries': mysteries,
                'emotion_debts': debts, 'belief_matrix': matrix, 'clue_ledger': clues}

    def web_timeline(self, from_chapter=None, to_chapter=None, entity_key=None):
        at = self._web_at(None)
        lo = int(from_chapter or 1)
        hi = int(to_chapter or at)
        events = self.world_model.event_timeline(entity_key, lo, hi, 300)
        with self.store.connect() as db:
            if entity_key:
                attr_rows = db.execute(
                    'SELECT entity_key,attr_key,value_json,start_chapter FROM entity_attributes WHERE entity_key=? AND start_chapter BETWEEN ? AND ? ORDER BY start_chapter',
                    (entity_key, lo, hi)).fetchall()
                rel_rows = db.execute(
                    'SELECT source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter FROM entity_relations WHERE (source_entity_key=? OR target_entity_key=?) AND (start_chapter BETWEEN ? AND ? OR end_chapter BETWEEN ? AND ?) ORDER BY start_chapter',
                    (entity_key, entity_key, lo, hi, lo, hi)).fetchall()
            else:
                attr_rows = db.execute(
                    'SELECT entity_key,attr_key,value_json,start_chapter FROM entity_attributes WHERE start_chapter BETWEEN ? AND ? ORDER BY start_chapter LIMIT 200', (lo, hi)).fetchall()
                rel_rows = db.execute(
                    'SELECT source_entity_key,relation_type,target_entity_key,start_chapter,end_chapter FROM entity_relations WHERE start_chapter BETWEEN ? AND ? ORDER BY start_chapter LIMIT 200', (lo, hi)).fetchall()
        attrs = [dict(r) | {'value': jl(r['value_json'])} for r in attr_rows]
        for a in attrs: a.pop('value_json', None)
        return {'from': lo, 'to': hi, 'entity_key': entity_key,
                'events': events, 'attribute_changes': attrs, 'relation_changes': [dict(r) for r in rel_rows]}

    def web_decision_answer(self, run_id: str, decision_id: str, answers: list) -> dict:
        """Web HITL:把作者对 planner 提问的回答写入 blueprint.author_decisions,
        然后以 resume 裁决该决策(与 scripts/stress/common.py 的自动作答同构,
        只是答案来自人)。answers: [{question, answer}]。
        """
        if not isinstance(answers, list):
            raise ValueError('answers must be an array of {question, answer}')
        bp = self.planning.blueprint_get()
        qa = (bp.get('blueprint') or {}).get('author_decisions') or []
        answered = {x.get('question') for x in qa if isinstance(x, dict)}
        added = 0
        for a in answers:
            if not isinstance(a, dict) or not a.get('question') or not str(a.get('answer', '')).strip():
                continue
            if a['question'] in answered:
                qa = [x if x.get('question') != a['question'] else {**x, 'answer': str(a['answer'])} for x in qa]
            else:
                qa.append({'question': a['question'], 'answer': str(a['answer'])})
            added += 1
        if added:
            self.planning.blueprint_update({'author_decisions': qa})
        return self.runs.submit_decision(run_id, decision_id, {'action': 'resume'})

    # ---- Web BFF 聚合读(Phase D3):审校中心 / 规划器 / 设置 ----

    def web_reviews(self, from_chapter=None, to_chapter=None):
        at = self.canon.max_committed_chapter() or 0
        lo, hi = int(from_chapter or 1), int(to_chapter or max(at, 1))
        with self.store.connect() as db:
            rows = db.execute(
                'SELECT chapter,draft_version,reviewer_type,verdict,score,findings_json,created_at '
                'FROM chapter_reviews WHERE chapter BETWEEN ? AND ? ORDER BY chapter, draft_version, id', (lo, hi)).fetchall()
            latest = {r['chapter']: r['version'] for r in db.execute(
                'SELECT chapter, MAX(version) AS version FROM chapter_drafts '
                'WHERE chapter BETWEEN ? AND ? GROUP BY chapter', (lo, hi))}
        per_chapter: dict[int, list] = {}
        for r in rows:
            f = dict(r)
            try:
                findings = json.loads(f.pop('findings_json') or '[]') or []
            except Exception:
                findings = []
            f['findings'] = [{k: x.get(k) for k in ('code', 'message', 'evidence', 'suggestion', 'paragraph', 'source_span', 'severity') if x.get(k) is not None}
                             for x in findings if isinstance(x, dict)]
            per_chapter.setdefault(f['chapter'], []).append(f)
        # 修订收敛:同一章多版本的发现数序列
        convergence = {}
        for ch, revs in per_chapter.items():
            versions = sorted({r['draft_version'] for r in revs})
            if len(versions) > 1:
                convergence[ch] = [{'version': v, 'findings': sum(len(r['findings']) for r in revs if r['draft_version'] == v)} for v in versions]
        return {'from': lo, 'to': hi, 'chapters': [
            {'chapter': ch, 'latest_draft_version': latest.get(ch), 'reviews': per_chapter.get(ch, [])}
            for ch in sorted(set(latest) | set(per_chapter))
        ], 'convergence': convergence}

    def web_plan(self, chapter=None):
        at = self._web_at(chapter)
        with self.store.connect() as db:
            arcs = [dict(r) for r in db.execute('SELECT * FROM arc_plans ORDER BY order_no').fetchall()]
            for a in arcs:
                for src, dst in (('hidden_functions_json', 'hidden_functions'), ('allowed_reveals_json', 'allowed_reveals'),
                                 ('forbidden_facts_json', 'forbidden_facts'), ('inherited_thread_keys_json', 'inherited_thread_keys'),
                                 ('exit_conditions_json', 'exit_conditions')):
                    a[dst] = jl(a.pop(src) or 'null') or []
            milestones = [dict(r) for r in db.execute('SELECT * FROM planning_milestones ORDER BY min_chapter').fetchall()]
            for m in milestones:
                m['thread_keys'] = jl(m.pop('thread_keys_json') or 'null') or []
                m['success_conditions'] = jl(m.pop('success_conditions_json') or 'null') or []
            schedule = [dict(r) for r in db.execute('SELECT * FROM thread_schedule ORDER BY min_chapter').fetchall()]
            rolling = [dict(r) for r in db.execute(
                'SELECT chapter,arc_key,tier,status,primary_goal FROM rolling_plan_items WHERE chapter>=? ORDER BY chapter, tier', (max(1, at - 10),)).fetchall()]
            plans = [dict(r) for r in db.execute(
                "SELECT p.chapter,p.arc_key,p.status,p.validation_status,p.version, "
                "EXISTS(SELECT 1 FROM chapter_drafts d WHERE d.chapter=p.chapter AND d.status NOT IN ('committed','rejected') "
                "AND d.version=(SELECT MAX(version) FROM chapter_drafts WHERE chapter=p.chapter)) active_draft "
                "FROM chapter_plans p ORDER BY p.chapter").fetchall()]
            threads = [dict(r) for r in db.execute(
                'SELECT thread_key,name,thread_type,status,introduced_chapter,target_min,target_max FROM threads ORDER BY introduced_chapter').fetchall()]
        return {'chapter': at, 'arcs': arcs, 'milestones': milestones, 'thread_schedule': schedule,
                'rolling_window': rolling, 'chapter_plans': plans, 'threads': threads}

    # ---- 导演位(章节前人工引导,v0.11) ----

    def chapter_directive_set(self, chapter: int, directive: str, source: str = 'author') -> dict:
        """为第 N 章设置作者引导指令(空串清除)。指令注入 planner 上下文,
        在该章计划生成成功后自动销账(consumed),不泄漏到后续章节。"""
        ch = int(chapter)
        if not str(directive or '').strip():
            with self.store.connect() as db:
                db.execute('DELETE FROM chapter_directives WHERE chapter=?', (ch,))
            return {'ok': True, 'chapter': ch, 'cleared': True}
        with self.store.connect() as db:
            db.execute('''INSERT INTO chapter_directives(chapter,directive,source) VALUES(?,?,?)
                          ON CONFLICT(chapter) DO UPDATE SET directive=excluded.directive,
                          source=excluded.source, status='pending', consumed_at=NULL, created_at=CURRENT_TIMESTAMP''',
                       (ch, str(directive).strip(), source))
        return {'ok': True, 'chapter': ch, 'directive': str(directive).strip()}

    def chapter_directive_get(self, chapter: int) -> dict | None:
        with self.store.connect() as db:
            r = db.execute("SELECT * FROM chapter_directives WHERE chapter=? AND status='pending'", (int(chapter),)).fetchone()
        return dict(r) if r else None

    def chapter_directive_consume(self, chapter: int) -> None:
        with self.store.connect() as db:
            db.execute("UPDATE chapter_directives SET status='consumed', consumed_at=CURRENT_TIMESTAMP WHERE chapter=? AND status='pending'", (int(chapter),))

    def chapter_direction_propose(self, chapter: int, count: int = 3, focus: str = '') -> dict:
        """导演位的共创模式:让模型基于当前故事状态提出 N 个下一章走向候选。

        走 NOVEL_DIRECTOR_ → NOVEL_ARCHITECT_ → NOVEL_PLANNER_ 回退链
        (architect 通常配直出快模型,提案 20-60 秒)。候选仅是提案,
        作者选定/改写后才经 chapter_directive_set 成为正式指令。
        """
        if not 1 <= int(count) <= 5:
            raise ValueError('count must be between 1 and 5')
        ctx = self.planner_context_get(int(chapter))
        state = {
            'chapter': chapter,
            'blueprint': ctx.get('blueprint'),
            'current_arc': ctx.get('arc_plan'),
            'story_state': ctx.get('story_state'),
            'selected_threads': ctx.get('story_state', {}).get('selected_thread_keys'),
            'due_thread_schedule': ctx.get('due_thread_schedule'),
            'due_foreshadowing': ctx.get('due_foreshadowing'),
            'dormant_threads': ctx.get('dormant_threads'),
            'aging_debts': ctx.get('aging_debts'),
            'rolling_window': ctx.get('rolling_window'),
        }
        from .llm_client import chat_json, configured
        prefix = 'NOVEL_DIRECTOR'
        if not configured(prefix, ('NOVEL_ARCHITECT', 'NOVEL_PLANNER')):
            raise RuntimeError('Set NOVEL_DIRECTOR_/NOVEL_ARCHITECT_/NOVEL_PLANNER_ model config to propose directions')
        system = (
            '你是长篇小说的联合导演。基于当前故事状态,为下一章提出几个可走的走向候选。'
            '每个候选必须:1) 与既有叙事线/谜团/情感债衔接(优先兑现到期义务、唤醒休眠线);'
            '2) 有明确的冲突升级或信息推进,不是过渡章;3) 互不重叠,代表真正不同的取舍。'
            '只输出 JSON 对象:{"options":[{"title":"8字内标题","sketch":"80字内走向概要",'
            '"threads":["将推进的线程键"],"beats":["2-4个情节要点"],"risk":"该选择的代价/风险,40字内"}]}'
        )
        user = f'下一章是第 {chapter} 章。当前故事状态(JSON):\n{json.dumps(state, ensure_ascii=False, default=str)[:12000]}\n'
        if str(focus or '').strip():
            user += f'\n作者补充的关注点:{focus.strip()}\n'
        user += f'\n提出 {int(count)} 个候选。'
        obj, model = chat_json(system, user, prefix=prefix, fallback_prefixes=('NOVEL_ARCHITECT', 'NOVEL_PLANNER'), temperature=0.8)
        options = obj.get('options') if isinstance(obj, dict) else None
        if not isinstance(options, list) or not options:
            raise ValueError('model did not return direction options')
        return {'chapter': int(chapter), 'model': model, 'options': [o for o in options if isinstance(o, dict)][:int(count)]}
