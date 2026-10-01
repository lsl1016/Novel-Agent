from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.service import NovelService


def make(tmp_path):
    s=NovelService(tmp_path/'story.db')
    s.store.set_meta('main_goal','追查天门覆灭真相')
    s.store.set_world_fact('father_identity','玄冥圣君','secret',500)
    s.store.add_belief(fact_key='father_identity',holder='reader',chapter=1,stance='unknown',value=None)
    s.store.upsert_thread('hero_origin','主角身世',introduced_chapter=1,target_min=300,target_max=600)
    return s


def test_blueprint_version_and_patch(tmp_path):
    s=make(tmp_path)
    b=s.blueprint_get()
    assert b['version']==1
    r=s.blueprint_update({'genre':'玄幻','core_promise':'身世谜题与世界真相'},expected_version=1)
    assert r['version']==2 and r['blueprint']['genre']=='玄幻'
    r2=s.blueprint_update({'protagonist':{'desire':'寻找父母'}},expected_version=2)
    assert r2['blueprint']['genre']=='玄幻'
    assert r2['blueprint']['protagonist']['desire']=='寻找父母'
    with pytest.raises(ValueError):
        s.blueprint_update({'x':1},expected_version=1)


def architecture():
    return {
      'blueprint':{'genre':'玄幻','core_promise':'旧剧情不断升值','ending_truth':'世界并非最初认知'},
      'world_facts':[{'fact_key':'sword_creator','truth':'失踪师父','secrecy':'secret','reveal_after':420}],
      'threads':[{'thread_key':'ancient_sword','name':'古剑来历','introduced_chapter':7,'target_min_chapter':300,'target_max_chapter':500}],
      'mysteries':[{'mystery_key':'sword_origin','name':'古剑是谁打造','thread_key':'ancient_sword','introduced_chapter':7,'target_min_chapter':300,'target_max_chapter':500}],
      'emotion_debts':[{'debt_key':'master_loss','thread_key':'ancient_sword','name':'师父失踪','emotion_type':'loss','intensity':0.8,'created_chapter':18}],
      'arcs':[{'arc_key':'arc_01','name':'北境篇','order_no':1,'start_chapter':1,'target_end_chapter':110,'primary_goal':'在北境立足','surface_conflict':'宗门争斗','hidden_functions':['建立古剑谜题'],'forbidden_facts':['sword_creator'],'inherited_thread_keys':['hero_origin'],'exit_conditions':['主角离开北境']}],
      'milestones':[{'milestone_key':'m_first_sword_echo','arc_key':'arc_01','name':'古剑第一次异常','min_chapter':20,'max_chapter':35,'thread_keys':['ancient_sword'],'success_conditions':['读者意识到古剑不普通']}],
      'thread_schedule':[{'schedule_key':'sched_sword_clue_1','thread_key':'ancient_sword','stage_type':'Clue','min_chapter':25,'max_chapter':35,'purpose':'第一次强化古剑异常'}],
    }


def test_architect_dry_run_apply_and_idempotency(tmp_path):
    s=make(tmp_path)
    a=architecture()
    dry=s.story_architect_apply(a,True)
    assert dry['ok'] and dry['dry_run']
    assert s.story_architect_get()['canonical_counts']['mysteries']==0
    r=s.story_architect_apply(a,False)
    assert r['ok'] and r['applied']['arcs']==1
    assert s.arc_plan_get('arc_01')['forbidden_facts']==['sword_creator']
    # 重复应用架构不得复制出重复的 Mystery 生命周期阶段。
    s.story_architect_apply(a,False)
    t=s.narrative_thread_get('ancient_sword')
    assert sum(1 for x in t['stages'] if x['stage_type']=='Mystery')==1


def test_rolling_window_tiers(tmp_path):
    s=make(tmp_path)
    s.story_architect_apply(architecture())
    w=s.planning_rebuild_window(100,5,20,50,[
        {'chapter':100,'arc_key':'arc_01','primary_goal':'查验古剑纹路'},
        {'chapter':101,'arc_key':'arc_01','primary_goal':'追查锻造师'},
    ])
    assert len(w['items'])==50
    assert w['counts']=={'hard':5,'medium':15,'soft':30}
    assert w['items'][0]['primary_goal']=='查验古剑纹路'


def test_chapter_plan_validator_and_forbidden_reveal(tmp_path):
    s=make(tmp_path)
    s.story_architect_apply(architecture())
    s.planning_rebuild_window(30,5,20,50,[{'chapter':30,'arc_key':'arc_01','primary_goal':'调查古剑'}])
    blocked=s.chapter_plan_save(30,{
      'primary_goal':'调查古剑',
      'arc_key':'arc_01',
      'threads':{'advance':['ancient_sword']},
      'reveals':[{'fact_key':'sword_creator','recipients':['reader']}]
    },'hero','arc_01')
    assert blocked['saved'] and not blocked['ok']
    assert any(x['code']=='ARC_FORBIDDEN_REVEAL' for x in blocked['validation']['errors'])
    ready=s.chapter_plan_save(30,{
      'primary_goal':'调查古剑',
      'arc_key':'arc_01',
      'threads':{'advance':['ancient_sword']},
      'clues':[{'thread_key':'ancient_sword','content':'剑纹与禁地石刻相似','strength':0.2}],
      'forbidden_truths':['sword_creator']
    },'hero','arc_01')
    assert ready['ok'] and ready['chapter_plan']['validation_status'] in {'ready','warning'}


def test_planning_pressure_and_commit_marks_plan(tmp_path):
    s=make(tmp_path)
    s.story_architect_apply(architecture())
    s.planning_rebuild_window(40,5,20,50,[{'chapter':40+i,'arc_key':'arc_01','primary_goal':f'目标{i}'} for i in range(5)])
    # 尚无任何章节计划 => 压力检查应捕获硬窗口缺口。
    p=s.planning_pressure_check(40,5)
    assert any(x['code']=='HARD_WINDOW_CHAPTER_PLAN_MISSING' for x in p['planning_pressure']['risks'])
    plan={'primary_goal':'查验旧伤','arc_key':'arc_01','threads':{'advance':['hero_origin']}}
    s.chapter_plan_save(40,plan,'hero','arc_01')
    r=s.chapter_commit(40,'旧伤','他重新检查了旧伤。','北境篇','hero','检查旧伤',{},False)
    assert r['committed']
    assert s.chapter_plan_get(40)['status']=='committed'


def test_story_state_includes_planning_snapshot(tmp_path):
    s=make(tmp_path)
    s.story_architect_apply(architecture())
    s.planning_rebuild_window(20,5,20,50,[{'chapter':20,'arc_key':'arc_01','primary_goal':'发现异常'}])
    st=s.story_get_state(20)
    assert st['planning']['blueprint_version']>=2
    assert st['planning']['current_arc_plan']['arc_key']=='arc_01'
