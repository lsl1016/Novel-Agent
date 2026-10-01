from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.service import NovelService


def make(tmp_path):
    s=NovelService(tmp_path/'story.db')
    s.store.set_meta('main_goal','追查天门覆灭真相')
    s.blueprint_update({'genre':'玄幻','core_promise':'长线谜题与认知反转','style':'克制揭示'})
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


def _semantic_result(verdict='PASS', leak_finding=None):
    reviews=[]
    for typ in ('semantic_knowledge_leak','semantic_character','semantic_narrative','semantic_pacing'):
        v=verdict if typ=='semantic_knowledge_leak' else 'PASS'
        findings=[leak_finding] if typ=='semantic_knowledge_leak' and leak_finding else []
        reviews.append({'reviewer_type':typ,'verdict':v,'score':0.2 if v=='BLOCK' else 1.0,'findings':findings})
    return {'reviews':reviews,'summary':'ok'}


def test_semantic_review_catches_paraphrase_and_redacts_truth(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]}
    d=s.chapter_draft_save(10,'旧物','那位统御幽冥十二域的圣君望向少年时，眼底竟有父亲看孩子般的熟悉。',pov='hero',declared_updates=updates)['draft']
    # 基于字面量的确定性泄露检查无法察觉这条确切的秘密值。
    assert s._body_secret_leak_check(10,d['body'],'hero',updates)['ok']
    seen={}
    def fake(payload,model=None):
        seen['payload']=payload
        assert payload['hidden_truth_ledger']['father_identity']['truth']=='玄冥圣君'
        return _semantic_result('BLOCK',{
            'code':'SEMANTIC_SECRET_LEAK','fact_key':'father_identity',
            'message':'正文已通过同义描述暗示玄冥圣君就是父亲','evidence':'父亲看孩子般的熟悉'
        }), 'fake-reviewer'
    monkeypatch.setattr(service_mod,'call_semantic_reviewer',fake)
    r=s.chapter_semantic_review(10,d['version'],model='fake')
    assert r['overall_verdict']=='BLOCK'
    raw=json.dumps(r,ensure_ascii=False)
    assert '玄冥圣君' not in raw
    assert '[REDACTED_WORLD_TRUTH:father_identity]' in raw


def test_full_review_preserves_both_review_families(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]}
    d=s.chapter_draft_save(10,'旧物','他只看见纹章微微反光，尚无法确定其来历。',pov='hero',declared_updates=updates)['draft']
    monkeypatch.setattr(service_mod,'call_semantic_reviewer',lambda payload,model=None: (_semantic_result('PASS'),'fake-reviewer'))
    r=s.chapter_review_full(10,d['version'],semantic=True,model='fake')
    assert r['overall_verdict'] in {'PASS','WARN'}
    reviews=s.chapter_review_get(10,d['version'])['reviews']
    assert len(reviews)==8
    # 重跑确定性检查不得清除语义审查证据。
    s.chapter_review_all(10,d['version'])
    reviews=s.chapter_review_get(10,d['version'])['reviews']
    assert len(reviews)==8


def test_finalize_can_require_semantic_reviews(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]}
    d=s.chapter_draft_save(10,'旧物','他只看见纹章微微反光，尚无法确定其来历。',pov='hero',declared_updates=updates)['draft']
    s.chapter_review_all(10,d['version'])
    f=s.chapter_finalize(10,d['version'],require_semantic=True)
    assert not f['committed'] and f['error']['code']=='REVIEW_INCOMPLETE'
    monkeypatch.setattr(service_mod,'call_semantic_reviewer',lambda payload,model=None: (_semantic_result('PASS'),'fake-reviewer'))
    s.chapter_semantic_review(10,d['version'],model='fake')
    f=s.chapter_finalize(10,d['version'],require_semantic=True)
    assert f['committed']


def test_auto_revision_loop_creates_fresh_version_and_rechecks(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    updates={'clues':[{'thread_key':'hero_origin','content':'旧物纹章异常','strength':0.2}]}
    d=s.chapter_draft_save(10,'旧物','他几乎已经确定那个人就是自己的父亲。',pov='hero',declared_updates=updates)['draft']
    calls={'review':0,'revise':0}
    def fake_review(payload,model=None):
        calls['review']+=1
        body=payload['draft']['body']
        if '几乎已经确定' in body:
            return _semantic_result('BLOCK',{'code':'UNSUPPORTED_CERTAINTY','fact_key':'father_identity','message':'POV certainty exceeds current belief','evidence':'几乎已经确定'}),'fake-reviewer'
        return _semantic_result('PASS'),'fake-reviewer'
    def fake_revision(payload,model=None):
        calls['revise']+=1
        # 修订载荷须对 Writer 视角安全,不得包含隐藏真相的字面量。
        raw=json.dumps(payload,ensure_ascii=False)
        assert '玄冥圣君' not in raw
        return '他觉得那个人的目光有些熟悉，却没有任何证据能说明这种感觉意味着什么。','fake-reviser'
    monkeypatch.setattr(service_mod,'call_semantic_reviewer',fake_review)
    monkeypatch.setattr(service_mod,'call_revision_model',fake_revision)
    r=s.chapter_auto_revision_loop(10,d['version'],max_rounds=2,require_semantic=True,reviewer_model='fake',revision_model='fake',finalize=False)
    assert r['ok'] and r['status']=='ready_to_finalize'
    assert r['revision_rounds']==1
    assert r['draft_version']==d['version']+1
    assert calls['review']==2 and calls['revise']==1
    # 全新的版本拥有自己的审查结果集。
    assert len(s.chapter_review_get(10,r['draft_version'])['reviews'])==8
