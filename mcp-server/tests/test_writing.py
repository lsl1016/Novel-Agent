from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.service import NovelService


def make(tmp_path):
    s=NovelService(tmp_path/'story.db')
    s.store.set_meta('main_goal','追查天门覆灭真相')
    s.blueprint_update({'genre':'玄幻','core_promise':'长线谜题与认知反转','style':'克制揭示，强调旧剧情升值'})
    s.store.set_world_fact('father_identity','玄冥圣君','secret',500)
    s.store.add_belief(fact_key='father_identity',holder='reader',chapter=1,stance='unknown',value=None)
    s.store.add_belief(fact_key='father_identity',holder='hero',chapter=1,stance='believes',value='父亲已死')
    s.store.upsert_thread('hero_origin','主角身世',introduced_chapter=1,target_min=300,target_max=600)
    s.arc_plan_create({'arc_key':'arc_01','name':'北境篇','order_no':1,'start_chapter':1,'target_end_chapter':110,
        'primary_goal':'北境立足','forbidden_facts':['father_identity'],'inherited_thread_keys':['hero_origin']})
    s.planning_rebuild_window(10,5,20,50,[{'chapter':10,'arc_key':'arc_01','primary_goal':'发现父亲旧物异常'}])
    s.chapter_plan_save(10,{
        'primary_goal':'发现父亲旧物异常','arc_key':'arc_01',
        'threads':{'advance':['hero_origin']},
        'clues':[{'thread_key':'hero_origin','content':'旧物上的纹章与敌人佩饰相似','strength':0.2}],
        'forbidden_truths':['father_identity']
    },'hero','arc_01')
    return s


def test_safe_writer_context_withholds_world_truth(tmp_path):
    s=make(tmp_path)
    ctx=s.writer_context_get(10)
    raw=json.dumps(ctx,ensure_ascii=False)
    assert '玄冥圣君' not in raw
    assert any(x['fact_key']=='father_identity' for x in ctx['forbidden_fact_keys'])
    belief=next(x for x in ctx['visible_beliefs'] if x['fact_key']=='father_identity')
    assert belief['pov']['value']=='父亲已死'


def test_leak_reviewer_blocks_hidden_truth(tmp_path):
    s=make(tmp_path)
    d=s.chapter_draft_save(10,'旧物','他忽然明白，自己的父亲就是玄冥圣君。',pov='hero',
        declared_updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]})['draft']
    r=s.chapter_review_all(10,d['version'])
    assert r['overall_verdict']=='BLOCK'
    leak=next(x for x in r['reviews'] if x['reviewer_type']=='knowledge_leak')
    assert any(x['code']=='SECRET_LITERAL_IN_PROSE' for x in leak['findings'])
    f=s.chapter_finalize(10,d['version'])
    assert not f['committed'] and f['error']['code']=='REVIEW_BLOCKED'


def test_clean_draft_review_and_finalize(tmp_path):
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物上的纹章与敌人佩饰相似','strength':0.2}]}
    d=s.chapter_draft_save(10,'旧物','他摩挲着旧物上的纹章。那纹路与白日见过的佩饰有几分相似，却还不足以下结论。',pov='hero',summary='发现旧物纹章异常',declared_updates=updates)['draft']
    before=s.chapter_finalize(10,d['version'])
    assert before['error']['code']=='REVIEW_INCOMPLETE'
    r=s.chapter_review_all(10,d['version'])
    assert r['overall_verdict'] in {'PASS','WARN'}
    f=s.chapter_finalize(10,d['version'])
    assert f['committed']
    assert s.chapter_draft_get(10,d['version'])['status']=='committed'
    with s.store.connect() as db:
        row=db.execute('SELECT * FROM chapters WHERE chapter=10').fetchone()
    assert row and row['title']=='旧物'


def test_revision_requires_fresh_reviews(tmp_path):
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]}
    d1=s.chapter_draft_save(10,'旧物','他只看到一道模糊纹章。',pov='hero',declared_updates=updates)['draft']
    s.chapter_review_all(10,d1['version'])
    d2=s.chapter_draft_save(10,'旧物','他看清了纹章，却仍无法确认它意味着什么。',pov='hero',declared_updates=updates,parent_version=d1['version'],source='revision')['draft']
    assert d2['version']==d1['version']+1
    f=s.chapter_finalize(10,d2['version'])
    assert f['error']['code']=='REVIEW_INCOMPLETE'
    status=s.writing_workflow_status(10)
    assert status['workflow']['active_draft_version']==d2['version']
    assert status['latest_review_verdict']=='NOT_REVIEWED'


def test_narrative_reviewer_requires_planned_reveal_declaration(tmp_path):
    s=make(tmp_path)
    # 为本独立测试把揭示窗口提前,并使该揭示在本卷中不受禁止。
    s.store.set_world_fact('public_secret','真相A','secret',10)
    s.store.add_belief(fact_key='public_secret',holder='reader',chapter=9,stance='unknown',value=None)
    s.chapter_plan_save(10,{
        'primary_goal':'揭开局部真相','arc_key':'arc_01','threads':{'advance':['hero_origin']},
        'reveals':[{'fact_key':'public_secret','thread_key':'hero_origin','content':'公开秘密揭示','recipients':['reader']}]
    },'hero','arc_01')
    d=s.chapter_draft_save(10,'揭示','众人终于得到一个局部答案。',pov='hero',declared_updates={'clues':[{'thread_key':'hero_origin','content':'补充线索'}]})['draft']
    r=s.chapter_review_all(10,d['version'])
    narr=next(x for x in r['reviews'] if x['reviewer_type']=='narrative')
    assert narr['verdict']=='BLOCK'
    assert any(x['code']=='PLANNED_REVEAL_NOT_DECLARED' for x in narr['findings'])


def test_dead_pov_character_is_blocked(tmp_path):
    s=make(tmp_path)
    s.store.add_character_state('hero',9,{'alive':False,'location':'北境'})
    d=s.chapter_draft_save(10,'死者视角','他睁开眼，看向北境的雪。',pov='hero',declared_updates={'clues':[{'thread_key':'hero_origin','content':'异常'}]})['draft']
    r=s.chapter_review_all(10,d['version'])
    char=next(x for x in r['reviews'] if x['reviewer_type']=='character')
    assert char['verdict']=='BLOCK'
    assert any(x['code']=='DEAD_POV_CHARACTER' for x in char['findings'])

def test_model_generation_receives_safe_context(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    seen={}
    def fake_writer(system,user,model=None):
        seen['system']=system; seen['user']=user
        assert '玄冥圣君' not in user
        return '他只看见旧物上的纹章微微反光，心中多了一层疑问。','fake-writer'
    monkeypatch.setattr(service_mod,'call_writer_model',fake_writer)
    r=s.chapter_draft_generate(10,title='旧物')
    assert r['draft']['model']=='fake-writer'
    assert r['draft']['status']=='draft'
    assert 'forbidden_fact_keys' in seen['user']
