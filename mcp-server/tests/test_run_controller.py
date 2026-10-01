from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

from novel_mcp.service import NovelService


def make(tmp_path):
    s=NovelService(tmp_path/'story.db')
    s.store.set_meta('main_goal','调查旧王朝覆灭真相')
    s.blueprint_update({'genre':'玄幻','core_promise':'长线谜题、延迟兑现','protagonist':'hero'})
    s.store.set_world_fact('hidden_king','玄冥圣君','secret',100)
    s.store.add_belief(fact_key='hidden_king',holder='reader',chapter=0,stance='unknown',value=None)
    s.store.add_belief(fact_key='hidden_king',holder='hero',chapter=0,stance='unknown',value=None)
    s.arc_plan_create({'arc_key':'arc_01','name':'北境篇','order_no':1,'start_chapter':1,'target_end_chapter':10,
        'primary_goal':'北境立足','forbidden_facts':['hidden_king'],'inherited_thread_keys':[]})
    return s


def install_fake_pipeline(s, monkeypatch):
    def fake_plan(chapter, model=None, save=True, allow_blocked=False):
        result=s.chapter_plan_save(chapter,{
            'title':f'第{chapter}章','primary_goal':f'推进第{chapter}章主线','arc_key':'arc_01','pov':'hero',
            'threads':{'advance':[],'maintain':[],'sleep':[]},'forbidden_truths':['hidden_king']
        },pov_holder='hero',arc_key='arc_01',allow_blocked=False)
        result['model']='fake-planner'; return result
    def fake_draft(chapter,title=None,model=None,declared_updates=None,summary=''):
        d=s.chapter_draft_save(chapter,title or f'第{chapter}章',f'主角完成了第{chapter}章的当前行动，但仍不知道真正的幕后身份。',
            arc='arc_01',pov='hero',summary=f'第{chapter}章推进',declared_updates={},source='model',model='fake-writer')['draft']
        return {'ok':True,'draft':d,'preflight':{'knowledge_leak':{'ok':True,'errors':[]}}}
    def fake_loop(chapter,version=None,max_rounds=3,require_semantic=True,reviewer_model=None,revision_model=None,finalize=False,allow_warnings=True,auto_extract=False):
        s.chapter_review_all(chapter,version)
        f=s.chapter_finalize(chapter,version,allow_warnings=allow_warnings,auto_extract=auto_extract,require_semantic=False)
        return {'ok':bool(f.get('committed')),'status':'committed' if f.get('committed') else 'finalize_failed','chapter':chapter,'draft_version':version,'revision_rounds':0,'history':[],'finalize':f}
    monkeypatch.setattr(s,'chapter_plan_generate',fake_plan)
    monkeypatch.setattr(s,'chapter_draft_generate',fake_draft)
    monkeypatch.setattr(s,'chapter_auto_revision_loop',fake_loop)


def test_planner_context_is_author_layer(tmp_path):
    s=make(tmp_path)
    ctx=s.planner_context_get(1)
    assert ctx['layer']=='AUTHOR_PLANNING_CONTEXT'
    assert any(x['fact_key']=='hidden_king' and x['truth']=='玄冥圣君' for x in ctx['world_truth_ledger'])


def test_chapter_plan_generate_can_stop_for_author_question(tmp_path,monkeypatch):
    import novel_mcp.service as service_mod
    s=make(tmp_path)
    monkeypatch.setattr(service_mod,'planner_model_configured',lambda: True)
    monkeypatch.setattr(service_mod,'call_planner_model',lambda context,model=None: ({
        'primary_goal':'需要先决定神器来源','arc_key':'arc_01','pov':'hero','author_questions':['神器是否来自上古王朝？']
    },'fake-planner'))
    r=s.chapter_plan_generate(1,model='fake')
    assert not r['ok'] and r['needs_author_decision']
    assert r['author_questions']


def test_run_controller_commits_bounded_target(tmp_path,monkeypatch):
    s=make(tmp_path); install_fake_pipeline(s,monkeypatch)
    started=s.novel_run_start(start_chapter=1,target_chapter=2,require_semantic=False,stop_on_pressure=False,report_every=1)
    run_id=started['run']['run_id']
    r=s.novel_run_continue(run_id,max_steps=5)
    assert r['run']['run']['status']=='completed'
    assert r['run']['run']['last_committed_chapter']==2
    assert r['run']['run']['chapters_committed']==2
    with s.store.connect() as db:
        assert db.execute('SELECT COUNT(*) n FROM chapters WHERE chapter IN (1,2)').fetchone()['n']==2
        assert db.execute('SELECT COUNT(*) n FROM novel_run_reports WHERE run_id=?',(run_id,)).fetchone()['n']>=2


def test_run_stops_for_pressure_and_resumes_after_decision(tmp_path,monkeypatch):
    s=make(tmp_path); install_fake_pipeline(s,monkeypatch)
    # threshold=1 时,一条叙事风险就足以触发拦截。
    for i in range(5):
        s.mystery_create(mystery_key=f'm{i}',name=f'旧谜题{i}',thread_key=f't{i}',introduced_chapter=1)
    started=s.novel_run_start(start_chapter=250,max_chapters=1,require_semantic=False,stop_on_pressure=True,pressure_risk_limit=1)
    run_id=started['run']['run_id']
    step=s.novel_run_step(run_id)
    assert step['status']=='needs_author_decision'
    decisions=s.novel_run_decision_list(run_id)
    assert len(decisions)==1 and decisions[0]['decision_type']=='story_pressure'
    resolved=s.novel_run_decision_submit(run_id,decisions[0]['decision_id'],{'action':'resume','config_patch':{'stop_on_pressure':False}})
    assert resolved['run']['run']['status']=='running'
    done=s.novel_run_continue(run_id,max_steps=2)
    assert done['run']['run']['status']=='completed'
    assert done['run']['run']['last_committed_chapter']==250


def test_run_missing_plan_creates_decision_when_autoplan_off(tmp_path):
    s=make(tmp_path)
    started=s.novel_run_start(start_chapter=1,max_chapters=1,require_semantic=False,auto_plan=False,stop_on_pressure=False)
    run_id=started['run']['run_id']
    r=s.novel_run_step(run_id)
    assert r['status']=='needs_author_decision'
    d=s.novel_run_decision_list(run_id)[0]
    assert d['decision_type']=='chapter_plan_required'
    # 由人工补好计划并解决该决策后,运行即可继续。
    s.planning_rebuild_window(1,5,20,50,[{'chapter':1,'arc_key':'arc_01','primary_goal':'人工计划'}])
    saved=s.chapter_plan_save(1,{'primary_goal':'人工计划','arc_key':'arc_01','threads':{'advance':[]}},'hero','arc_01',allow_blocked=False)
    assert saved['ok']
    out=s.novel_run_decision_submit(run_id,d['decision_id'],{'action':'resume'})
    assert out['run']['run']['status']=='running'


def test_pause_resume_and_report(tmp_path):
    s=make(tmp_path)
    started=s.novel_run_start(start_chapter=1,max_chapters=1,require_semantic=False,stop_on_pressure=False)
    run_id=started['run']['run_id']
    paused=s.novel_run_pause(run_id,'作者要调整第二幕')
    assert paused['run']['status']=='paused'
    resumed=s.novel_run_resume(run_id)
    assert resumed['run']['status']=='running'
    report=s.novel_run_report(run_id,persist=True)
    assert report['run_id']==run_id
    with s.store.connect() as db:
        assert db.execute('SELECT COUNT(*) n FROM novel_run_reports WHERE run_id=?',(run_id,)).fetchone()['n']==1


def test_pipeline_exception_becomes_decision_not_crash(tmp_path):
    s = make(tmp_path)
    s.chapter_plan_save(1, {'title': '第1章', 'primary_goal': '推进', 'arc_key': 'arc_01', 'pov': 'hero',
                            'threads': {'advance': [], 'maintain': [], 'sleep': []}},
                        pov_holder='hero', arc_key='arc_01', allow_blocked=False)
    d = s.chapter_draft_save(1, '第1章', '主角完成了当前行动，但不知道幕后身份。', arc='arc_01', pov='hero',
                             declared_updates={}, source='model')['draft']
    from novel_mcp.writing import WritingStore
    WritingStore.replace_reviews(s.writing, 1, d['version'], [
        {'reviewer_type': t_, 'verdict': 'PASS', 'score': 1.0, 'findings': []}
        for t_ in ('knowledge_leak', 'continuity', 'narrative', 'character',
                   'semantic_knowledge_leak', 'semantic_character', 'semantic_narrative', 'semantic_pacing')])

    def boom(*a, **k): raise RuntimeError('synthetic pipeline failure')
    s.chapter_auto_revision_loop = boom  # 实例级补丁:模拟流水线任意异常

    run = s.novel_run_start(start_chapter=1, auto_plan=False, require_semantic=False, stop_on_pressure=False)
    rid = run['run']['run_id']
    r = s.novel_run_step(rid)
    assert r['status'] == 'needs_author_decision'
    dec = s.novel_run_decision_list(rid)[0]
    assert dec['decision_type'] == 'chapter_pipeline_error'
    assert 'synthetic pipeline failure' in str(dec['context'])
    assert s.canon.max_committed_chapter() is None, 'crash must leave canon untouched'
