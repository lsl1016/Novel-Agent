from pathlib import Path
import json, tempfile
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.service import NovelService
from novel_mcp.stdio_compat import handle

REF=Path(__file__).resolve().parents[2]/'reference-example'

def make(tmp):
    s=NovelService(Path(tmp)/'story.db',REF,'/mnt/data/narrative-kg')
    s.store.set_meta('main_goal','调查失踪真相')
    s.store.set_meta('current_arc','北境篇')
    s.store.set_world_fact('hero_father_identity','玄冥圣君','secret',500)
    s.store.add_belief(fact_key='hero_father_identity',holder='reader',chapter=1,stance='unknown',value=None)
    s.store.add_belief(fact_key='hero_father_identity',holder='hero',chapter=1,stance='believes',value='父亲已死')
    s.store.add_belief(fact_key='hero_father_identity',holder='villain',chapter=1,stance='confirmed',value='玄冥圣君')
    s.store.upsert_thread('hero_origin','主角身世',introduced_chapter=3,target_min=300,target_max=500)
    return s

def test_state_and_beliefs(tmp_path):
    s=make(tmp_path)
    st=s.story_get_state(200)
    assert st['main_goal']=='调查失踪真相'
    assert any(x['fact_key']=='hero_father_identity' for x in st['forbidden_world_truths'])
    b=s.belief_get('hero_father_identity',200)
    assert b['world_truth']['value']=='玄冥圣君'
    assert b['holders']['hero']['value']=='父亲已死'
    assert b['holders']['villain']['stance']=='confirmed'

def test_plan_leak_and_arc_rule(tmp_path):
    s=make(tmp_path)
    r=s.chapter_plan_check(200,{'reveals':[{'fact_key':'hero_father_identity','thread_key':'hero_origin','content':'身份揭示','recipients':['reader']} ]})
    assert not r['ok'] and any(e['code']=='WORLD_TRUTH_LEAK' for e in r['errors'])
    r=s.chapter_plan_check(200,{'arc_transition':{'is_new_arc':True,'inherited_thread_keys':[]}})
    assert not r['ok'] and any(e['code']=='ARC_WITHOUT_INHERITED_THREAD' for e in r['errors'])
    r=s.chapter_plan_check(500,{'reveals':[{'fact_key':'hero_father_identity','thread_key':'hero_origin','content':'身份揭示','recipients':['reader']} ]})
    assert r['ok']

def test_mystery_clue_debt_pressure(tmp_path):
    s=make(tmp_path)
    s.mystery_create(mystery_key='jade_origin',name='玉佩来源',thread_key='hero_origin',introduced_chapter=52,target_min_chapter=300,target_max_chapter=500,notes='')
    s.clue_add('hero_origin',81,'长老看到玉佩后短暂失态','reader',0.15)
    s.emotion_debt_create(debt_key='master_humiliation',thread_key='master_arc',name='师父受辱',emotion_type='humiliation',intensity=.8,created_chapter=40)
    p=s.story_pressure_check(350, mystery_age=200, foreshadow_age=100, debt_age=200)
    assert p['stale_mysteries']>=1
    assert p['stale_foreshadowing']>=1
    assert p['overdue_emotion_debts']>=1
    s.emotion_debt_resolve('master_humiliation',380,'主角在同一地点击败对手','full','引出更大势力')
    p2=s.story_pressure_check(400,debt_age=200)
    assert p2['overdue_emotion_debts']==0

def test_pattern_search_structural_only(tmp_path):
    s=make(tmp_path)
    r=s.narrative_pattern_search('identity_mystery',300,['partial_reveal','payoff'],10)
    assert r['source']=='REFERENCE_GRAPH'
    assert r['results']
    assert all('stage_sequence' in x for x in r['results'])
    serialized=json.dumps(r,ensure_ascii=False)
    # 结构化响应刻意排除原文/证据引文以及节点名称。
    assert 'source prose' not in serialized.lower()
    assert all('name' not in stage for x in r['results'] for stage in x['stage_sequence'])

def test_commit_declared_updates(tmp_path):
    s=make(tmp_path)
    body='主角在旧宅发现一枚陌生玉佩。'
    updates={
      'events':[{'name':'发现玉佩','event_key':'find_jade','thread_key':'hero_origin'}],
      'mysteries':[{'mystery_key':'jade_origin','name':'玉佩来自哪里','thread_key':'hero_origin','target_min_chapter':300,'target_max_chapter':500}],
      'clues':[{'thread_key':'hero_origin','content':'玉佩背面有缺失纹章','strength':0.2}],
      'belief_updates':[{'fact_key':'jade_owner','holder':'hero','stance':'unknown','value':None}],
      'character_states':[{'character_key':'hero','state':{'alive':True,'location':'旧宅'}}]
    }
    r=s.chapter_commit(52,'旧宅玉佩',body,'北境篇','hero','发现玉佩',updates,False)
    assert r['committed'] and r['ok']
    t=s.narrative_thread_get('hero_origin')
    assert any(x['stage_type']=='Mystery' for x in t['stages'])

def test_continuity_world_fact(tmp_path):
    s=make(tmp_path)
    r=s.continuity_check(100,[{'fact_key':'hero_father_identity','value':'另一个人','claim_world_truth':True}],[])
    assert not r['ok']
    assert r['errors'][0]['code']=='WORLD_FACT_CONTRADICTION'

def test_stdio_tools_list_and_call(tmp_path,monkeypatch):
    monkeypatch.setenv('NOVEL_STORY_DB',str(tmp_path/'stdio.db'))
    monkeypatch.setenv('NOVEL_REFERENCE_ROOT',str(REF))
    import novel_mcp.runtime as rt
    rt._SERVICE=None
    out=handle({'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}})
    assert len(out['result']['tools'])==91
    out=handle({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'story_get_state','arguments':{'chapter':1}}})
    assert 'structuredContent' in out['result']

def test_commit_blocks_secret_literal_leak(tmp_path):
    s=make(tmp_path)
    r=s.chapter_commit(200,'不该泄露','黑衣人玄冥圣君望着远方。','北境篇','hero','',{},False)
    assert not r['committed']
    assert r['prose_leak_check']['errors'][0]['code']=='SECRET_LITERAL_IN_PROSE'
    r2=s.chapter_commit(500,'允许揭晓','黑衣人玄冥圣君望着远方。','北境篇','hero','',{'reveals':[{'fact_key':'hero_father_identity','thread_key':'hero_origin','content':'身份正式揭晓','recipients':['reader','hero']}]},False)
    assert r2['committed']

def test_http_facade_wraps_object_and_array_results(tmp_path,monkeypatch):
    monkeypatch.setenv('NOVEL_STORY_DB',str(tmp_path/'facade.db'))
    monkeypatch.setenv('NOVEL_REFERENCE_ROOT',str(REF))
    import novel_mcp.runtime as rt
    rt._SERVICE=None
    from novel_mcp.http_compat import facade_call
    status,out=facade_call('story_get_state',{'chapter':1})
    assert status==200 and out['errNo']==0 and isinstance(out['data'],dict)
    status,out=facade_call('narrative_thread_search',{'query':''})
    assert status==200 and out['errNo']==0 and isinstance(out['data'],list)
    status,out=facade_call('tool_does_not_exist',{})
    assert status==200 and out['errNo']!=0 and out['data'] is None


def test_malformed_declared_updates_are_blocked(tmp_path):
    s = make(tmp_path)
    bad = {
        'belief_updates': [{'entity_key': 'hero', 'change': '自由格式,缺 fact_key/holder/stance'}],
        'events': ['纯字符串事件,非对象'],
    }
    r = s.chapter_plan_check(52, bad)
    assert not r['ok']
    assert sum(1 for e in r['errors'] if e['code'] == 'MALFORMED_DECLARED_UPDATE') >= 2
    c = s.chapter_commit(52, '坏更新', '正文内容。', '北境篇', 'hero', '', bad, False)
    assert not c['committed'] and 'plan_check' in c


def test_commit_persists_columns_in_right_order(tmp_path):
    s = make(tmp_path)
    r = s.chapter_commit(52, '旧宅玉佩', '这是正文内容，应当落在 body 列。', '北境篇', 'hero', '发现玉佩', {}, False)
    assert r['committed']
    with s.store.connect() as db:
        row = db.execute('SELECT title,arc,pov,summary,body FROM chapters WHERE chapter=52').fetchone()
    assert row['title'] == '旧宅玉佩' and row['arc'] == '北境篇'
    assert row['pov'] == 'hero' and row['summary'] == '发现玉佩'
    assert row['body'] == '这是正文内容，应当落在 body 列。'


def test_threads_dict_entries_are_normalized(tmp_path):
    # 复现第3章崩溃形状:threads.advance 为对象列表 + 存在 due schedule 时 set() 崩
    s = make(tmp_path)
    s.thread_schedule_update({'schedule_key': 'sch_due', 'thread_key': 'hero_origin', 'stage_type': 'Clue',
                              'min_chapter': 2, 'max_chapter': 8})
    plan = {'threads': {'advance': [{'thread_key': 'hero_origin'}, {'key': 'master_arc'}], 'maintain': [], 'sleep': []},
            'clues': []}
    r = s.chapter_plan_check(3, plan)  # 不应抛 unhashable
    assert not any(e['code'] == 'MALFORMED_DECLARED_UPDATE' and e['group'].startswith('threads') for e in r['errors'])
    assert r['checked_chapter'] == 3
    # 完全无法提取 thread_key 的条目仍要报错
    r2 = s.chapter_plan_check(3, {'threads': {'advance': [{'foo': 1}], 'maintain': [], 'sleep': []}})
    assert any(e['code'] == 'MALFORMED_DECLARED_UPDATE' and e['group'] == 'threads.advance' for e in r2['errors'])


def test_secret_variant_leak_and_explicit_foreshadowing(tmp_path):
    s = make(tmp_path)
    # 变体泄密:插入标点的真值也要被拦
    r = s.chapter_commit(200, '变体泄露', '黑衣人玄冥、圣君望着远方。', '北境篇', 'hero', '', {}, False)
    assert not r['committed'] and r['prose_leak_check']['errors']
    # 伏笔回收必须显式配对:不带 callback_key 的 payoff 不再自动回收
    cl = s.clue_add('hero_origin', 81, '玉佩背面有缺失纹章')
    ck = cl['callback_key']
    assert ck  # 未提供时自动落自指键
    s.store.add_stage('hero_origin', 120, 'Payoff', '无关的偿付', strength=.8)
    assert any(x['id'] == cl['stage_id'] for x in s.foreshadowing_list_open(150, 10, 50)), 'unrelated payoff must not recycle the clue'
    s.store.add_stage('hero_origin', 130, 'Payoff', '纹章补全,玉佩合璧', callback_key=ck, strength=.8)
    assert not any(x['id'] == cl['stage_id'] for x in s.foreshadowing_list_open(150, 10, 50)), 'explicit callback must recycle'
