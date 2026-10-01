from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from novel_mcp.service import NovelService

REF=Path(__file__).resolve().parents[2]/'reference-example'

def make(tmp_path):
    s=NovelService(tmp_path/'story.db',REF,None)
    s.entity_upsert('hero','Character','林渊',1,properties={'gender':'male'})
    s.entity_upsert('father','Character','黑衣人',1)
    s.entity_upsert('north_city','Location','北境城',1)
    s.store.set_world_fact('hero_father_identity','father','secret',500)
    s.store.add_belief(fact_key='hero_father_identity',holder='reader',chapter=1,stance='unknown',value=None)
    s.store.add_belief(fact_key='hero_father_identity',holder='hero',chapter=1,stance='believes',value='父亲已死')
    s.entity_alias_add('father','玄冥圣君','true_identity','secret',500,'hero_father_identity')
    s.entity_relation_upsert('father','PARENT_OF','hero',1,secrecy='secret',reveal_after=500,fact_key='hero_father_identity')
    s.entity_relation_upsert('hero','LOCATED_IN','north_city',1)
    s.entity_attribute_set('hero','realm','灵海境',1)
    return s

def test_safe_and_author_entity_views(tmp_path):
    s=make(tmp_path)
    safe=s.entity_get('father',200,'hero')
    assert all(x['alias']!='玄冥圣君' for x in safe['aliases'])
    assert all(x['relation_type']!='PARENT_OF' for x in safe['relations'])
    author=s.entity_author_get('father',200)
    assert any(x['alias']=='玄冥圣君' for x in author['aliases'])
    assert any(x['relation_type']=='PARENT_OF' for x in author['relations'])
    revealed=s.entity_get('father',500,'reader')
    assert any(x['alias']=='玄冥圣君' for x in revealed['aliases'])
    assert any(x['relation_type']=='PARENT_OF' for x in revealed['relations'])

def test_search_no_secret_alias_side_channel(tmp_path):
    s=make(tmp_path)
    assert s.entity_search('玄冥圣君',chapter=200,holder='reader')==[]
    assert s.entity_search('黑衣人',chapter=200,holder='reader')[0]['entity_key']=='father'

def test_temporal_attribute_and_relation(tmp_path):
    s=make(tmp_path)
    s.entity_attribute_set('hero','realm','神府境',100)
    assert s.entity_get('hero',50)['attributes']['realm']['value']=='灵海境'
    assert s.entity_get('hero',100)['attributes']['realm']['value']=='神府境'
    s.entity_relation_end('hero','LOCATED_IN','north_city',120)
    assert any(x['relation_type']=='LOCATED_IN' for x in s.entity_get('hero',120)['relations'])
    assert not any(x['relation_type']=='LOCATED_IN' for x in s.entity_get('hero',121)['relations'])

def test_neighbors_path_and_narrative_link(tmp_path):
    s=make(tmp_path)
    s.store.upsert_thread('hero_origin','主角身世',introduced_chapter=1)
    s.narrative_entity_link('thread','hero_origin','hero','subject',1)
    links=s.narrative_entity_links_get(entity_key='hero')
    assert links and links[0]['narrative_key']=='hero_origin'
    g=s.entity_neighbors('hero',200,depth=1)
    assert any(e['relation_type']=='LOCATED_IN' for e in g['edges'])
    assert not any(e['relation_type']=='PARENT_OF' for e in g['edges'])
    p=s.entity_path_find('hero','father',200)
    assert not p['found']
    assert s.entity_path_find('hero','father',500)['found']

def test_writer_context_uses_safe_entity_graph(tmp_path):
    s=make(tmp_path)
    s.blueprint_update({'genre':'玄幻'})
    s.arc_plan_create({'arc_key':'arc1','name':'开篇','start_chapter':1,'target_end_chapter':300,'primary_goal':'成长','inherited_thread_keys':['hero_origin']})
    s.store.upsert_thread('hero_origin','主角身世',introduced_chapter=1)
    plan={'primary_goal':'调查黑衣人','arc_key':'arc1','pov':'hero','entity_keys':['hero','father','north_city'],'threads':{'advance':['hero_origin'],'maintain':[],'sleep':[]}}
    r=s.chapter_plan_save(200,plan,pov_holder='hero',arc_key='arc1')
    assert r['saved']
    ctx=s.writer_context_get(200)
    serial=str(ctx['entity_context'])
    assert '玄冥圣君' not in serial
    assert 'PARENT_OF' not in serial
    assert 'LOCATED_IN' in serial

def test_commit_applies_entity_updates_and_links(tmp_path):
    s=NovelService(tmp_path/'story.db',REF,None)
    s.blueprint_update({'genre':'玄幻'})
    s.arc_plan_create({'arc_key':'arc1','name':'开篇','start_chapter':1,'target_end_chapter':50,'primary_goal':'起步','inherited_thread_keys':['artifact_line']})
    s.store.upsert_thread('artifact_line','古剑线',introduced_chapter=1)
    s.chapter_plan_save(1,{'primary_goal':'得到古剑','arc_key':'arc1','pov':'hero','threads':{'advance':['artifact_line'],'maintain':[],'sleep':[]}},'hero','arc1')
    updates={
      'entities':[{'entity_key':'hero','entity_type':'Character','name':'林渊'},{'entity_key':'sword','entity_type':'Artifact','name':'无名古剑'}],
      'entity_relations':[{'source_entity_key':'hero','relation_type':'OWNS','target_entity_key':'sword','start_chapter':1}],
      'narrative_entity_links':[{'narrative_type':'thread','narrative_key':'artifact_line','entity_key':'sword','role':'core_artifact'}],
    }
    r=s.chapter_commit(1,'得剑','林渊得到一柄无名古剑。','arc1','hero','',updates,False)
    assert r['committed']
    assert s.entity_get('hero',1)['relations'][0]['target_entity_key']=='sword'
    assert s.narrative_entity_links_get(narrative_key='artifact_line')[0]['entity_key']=='sword'

def test_entity_graph_import_dry_run_and_apply(tmp_path):
    s=NovelService(tmp_path/'story.db',REF,None)
    graph={'nodes':[{'id':'c1','type':'Character','name':'甲'},{'id':'f1','type':'Faction','name':'宗门'},{'id':'m1','type':'Mystery','name':'忽略'}], 'edges':[{'source':'c1','target':'f1','type':'MEMBER_OF'}]}
    dry=s.entity_graph_import(graph,'new',dry_run=True)
    assert dry['entity_count']==2 and dry['relation_count']==1
    assert s.entity_graph_stats()['counts']['entities']==0
    done=s.entity_graph_import(graph,'new',dry_run=False)
    assert done['ok'] and s.entity_graph_stats()['counts']['entities']==2
