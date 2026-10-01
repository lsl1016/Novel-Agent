"""集中式数据库 schema 与迁移框架。

所有 DDL 收敛在此处的有序迁移列表中,由 StoryStore 启动时按
``PRAGMA user_version`` 依序应用。规则:

* 迁移只追加,不修改已发布的历史迁移(v0.7 遗留库 user_version=0,
  迁移 1 依赖 IF NOT EXISTS / INSERT OR IGNORE 保持幂等以兼容它们);
* 每个迁移在单事务内执行并连同版本号一起提交,中途失败整体回滚;
* 新增能力通过新迁移(版本号 +1)表达,禁止改写旧迁移。

模块不再各自持有 DDL;story/writing/planning/run/context 各表都在
迁移 1 基线中建立,后续演进按迁移号追加。
"""
from __future__ import annotations

import sqlite3

# (version, name, sql)
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, 'v0.7 baseline: story/narrative/entity/planning/writing/run/context tables', r'''
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chapters(chapter INTEGER PRIMARY KEY,title TEXT NOT NULL,arc TEXT,pov TEXT,summary TEXT,body TEXT NOT NULL,committed_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS threads(thread_key TEXT PRIMARY KEY,name TEXT NOT NULL,thread_type TEXT DEFAULT 'narrative',status TEXT DEFAULT 'open',introduced_chapter INTEGER,target_min INTEGER,target_max INTEGER,main_goal TEXT,notes TEXT);
CREATE TABLE IF NOT EXISTS stages(id INTEGER PRIMARY KEY AUTOINCREMENT,thread_key TEXT NOT NULL,chapter INTEGER NOT NULL,stage_type TEXT NOT NULL,content TEXT NOT NULL,strength REAL DEFAULT 0,visibility TEXT DEFAULT 'reader',holder TEXT,status TEXT DEFAULT 'verified',callback_key TEXT,source TEXT DEFAULT 'author_declared',metadata_json TEXT DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_stages_thread_chapter ON stages(thread_key,chapter);
CREATE INDEX IF NOT EXISTS idx_stages_type_chapter ON stages(stage_type,chapter);
CREATE TABLE IF NOT EXISTS mysteries(mystery_key TEXT PRIMARY KEY,thread_key TEXT NOT NULL,name TEXT NOT NULL,status TEXT DEFAULT 'open',introduced_chapter INTEGER NOT NULL,target_min INTEGER,target_max INTEGER,resolved_chapter INTEGER,notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS world_facts(fact_key TEXT PRIMARY KEY,truth_json TEXT,secrecy TEXT DEFAULT 'secret',reveal_after INTEGER,notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS beliefs(id INTEGER PRIMARY KEY AUTOINCREMENT,fact_key TEXT NOT NULL,holder TEXT NOT NULL,chapter INTEGER NOT NULL,stance TEXT NOT NULL,value_json TEXT,confidence REAL DEFAULT 1,source TEXT DEFAULT 'author_declared');
CREATE UNIQUE INDEX IF NOT EXISTS idx_belief_unique ON beliefs(fact_key,holder,chapter);
CREATE TABLE IF NOT EXISTS debts(debt_key TEXT PRIMARY KEY,thread_key TEXT NOT NULL,name TEXT NOT NULL,emotion_type TEXT NOT NULL,intensity REAL NOT NULL,created_chapter INTEGER NOT NULL,target_holder TEXT,status TEXT DEFAULT 'open',resolved_chapter INTEGER,resolution TEXT,notes TEXT DEFAULT '',consequence TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,chapter INTEGER NOT NULL,event_key TEXT,name TEXT NOT NULL,event_type TEXT DEFAULT 'event',thread_key TEXT,status TEXT DEFAULT 'verified',metadata_json TEXT DEFAULT '{}');
CREATE TABLE IF NOT EXISTS character_states(id INTEGER PRIMARY KEY AUTOINCREMENT,character_key TEXT NOT NULL,chapter INTEGER NOT NULL,state_json TEXT NOT NULL,source TEXT DEFAULT 'author_declared');
CREATE TABLE IF NOT EXISTS extraction_candidates(id INTEGER PRIMARY KEY AUTOINCREMENT,chapter INTEGER NOT NULL,node_type TEXT,name TEXT,status TEXT DEFAULT 'candidate',payload_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS entities(entity_key TEXT PRIMARY KEY,entity_type TEXT NOT NULL,name TEXT NOT NULL,status TEXT DEFAULT 'active',introduced_chapter INTEGER,retired_chapter INTEGER,description TEXT DEFAULT '',properties_json TEXT DEFAULT '{}',source TEXT DEFAULT 'author_declared',created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS idx_entities_type_status ON entities(entity_type,status);
CREATE TABLE IF NOT EXISTS entity_aliases(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_key TEXT NOT NULL,alias TEXT NOT NULL,alias_type TEXT DEFAULT 'alias',secrecy TEXT DEFAULT 'public',reveal_after INTEGER,fact_key TEXT,source TEXT DEFAULT 'author_declared',UNIQUE(entity_key,alias),FOREIGN KEY(entity_key) REFERENCES entities(entity_key));
CREATE INDEX IF NOT EXISTS idx_entity_aliases_alias ON entity_aliases(alias);
CREATE TABLE IF NOT EXISTS entity_attributes(id INTEGER PRIMARY KEY AUTOINCREMENT,entity_key TEXT NOT NULL,attr_key TEXT NOT NULL,value_json TEXT,start_chapter INTEGER NOT NULL DEFAULT 0,end_chapter INTEGER,secrecy TEXT DEFAULT 'public',reveal_after INTEGER,fact_key TEXT,source TEXT DEFAULT 'author_declared',confidence REAL DEFAULT 1,UNIQUE(entity_key,attr_key,start_chapter),FOREIGN KEY(entity_key) REFERENCES entities(entity_key));
CREATE INDEX IF NOT EXISTS idx_entity_attrs_key_chapter ON entity_attributes(entity_key,attr_key,start_chapter,end_chapter);
CREATE TABLE IF NOT EXISTS entity_relations(id INTEGER PRIMARY KEY AUTOINCREMENT,source_entity_key TEXT NOT NULL,relation_type TEXT NOT NULL,target_entity_key TEXT NOT NULL,start_chapter INTEGER NOT NULL DEFAULT 0,end_chapter INTEGER,status TEXT DEFAULT 'active',secrecy TEXT DEFAULT 'public',reveal_after INTEGER,fact_key TEXT,properties_json TEXT DEFAULT '{}',source TEXT DEFAULT 'author_declared',UNIQUE(source_entity_key,relation_type,target_entity_key,start_chapter),FOREIGN KEY(source_entity_key) REFERENCES entities(entity_key),FOREIGN KEY(target_entity_key) REFERENCES entities(entity_key));
CREATE INDEX IF NOT EXISTS idx_entity_rel_src ON entity_relations(source_entity_key,relation_type,start_chapter,end_chapter);
CREATE INDEX IF NOT EXISTS idx_entity_rel_dst ON entity_relations(target_entity_key,relation_type,start_chapter,end_chapter);
CREATE TABLE IF NOT EXISTS narrative_entity_links(id INTEGER PRIMARY KEY AUTOINCREMENT,narrative_type TEXT NOT NULL,narrative_key TEXT NOT NULL,entity_key TEXT NOT NULL,role TEXT DEFAULT 'involves',chapter INTEGER NOT NULL DEFAULT 0,properties_json TEXT DEFAULT '{}',source TEXT DEFAULT 'author_declared',UNIQUE(narrative_type,narrative_key,entity_key,role,chapter),FOREIGN KEY(entity_key) REFERENCES entities(entity_key));
CREATE INDEX IF NOT EXISTS idx_narrative_entity_key ON narrative_entity_links(narrative_type,narrative_key);
CREATE INDEX IF NOT EXISTS idx_narrative_entity_entity ON narrative_entity_links(entity_key);
CREATE TABLE IF NOT EXISTS planning_blueprint(
  id INTEGER PRIMARY KEY CHECK(id=1),
  version INTEGER NOT NULL DEFAULT 1,
  payload_json TEXT NOT NULL DEFAULT '{}',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS arc_plans(
  arc_key TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  order_no INTEGER DEFAULT 0,
  start_chapter INTEGER,
  target_end_chapter INTEGER,
  status TEXT DEFAULT 'planned',
  primary_goal TEXT DEFAULT '',
  surface_conflict TEXT DEFAULT '',
  hidden_functions_json TEXT DEFAULT '[]',
  allowed_reveals_json TEXT DEFAULT '[]',
  forbidden_facts_json TEXT DEFAULT '[]',
  inherited_thread_keys_json TEXT DEFAULT '[]',
  exit_conditions_json TEXT DEFAULT '[]',
  notes TEXT DEFAULT '',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_arc_plans_range ON arc_plans(start_chapter,target_end_chapter);
CREATE TABLE IF NOT EXISTS planning_milestones(
  milestone_key TEXT PRIMARY KEY,
  arc_key TEXT,
  name TEXT NOT NULL,
  min_chapter INTEGER,
  max_chapter INTEGER,
  status TEXT DEFAULT 'planned',
  thread_keys_json TEXT DEFAULT '[]',
  success_conditions_json TEXT DEFAULT '[]',
  metadata_json TEXT DEFAULT '{}',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_planning_milestones_arc ON planning_milestones(arc_key,min_chapter,max_chapter);
CREATE TABLE IF NOT EXISTS thread_schedule(
  schedule_key TEXT PRIMARY KEY,
  thread_key TEXT NOT NULL,
  stage_type TEXT NOT NULL,
  min_chapter INTEGER,
  max_chapter INTEGER,
  purpose TEXT DEFAULT '',
  status TEXT DEFAULT 'planned',
  constraints_json TEXT DEFAULT '{}',
  metadata_json TEXT DEFAULT '{}',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_thread_schedule_thread ON thread_schedule(thread_key,min_chapter,max_chapter);
CREATE TABLE IF NOT EXISTS rolling_plan_items(
  chapter INTEGER PRIMARY KEY,
  arc_key TEXT,
  tier TEXT NOT NULL,
  status TEXT DEFAULT 'planned',
  primary_goal TEXT DEFAULT '',
  plan_json TEXT DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_rolling_plan_tier ON rolling_plan_items(tier,chapter);
CREATE TABLE IF NOT EXISTS chapter_plans(
  chapter INTEGER PRIMARY KEY,
  arc_key TEXT,
  pov_holder TEXT DEFAULT 'reader',
  status TEXT DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  plan_json TEXT NOT NULL,
  validation_status TEXT DEFAULT 'unchecked',
  validation_json TEXT DEFAULT '{}',
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS chapter_drafts(
  chapter INTEGER NOT NULL,
  version INTEGER NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  arc TEXT DEFAULT '',
  pov TEXT DEFAULT '',
  summary TEXT DEFAULT '',
  declared_updates_json TEXT NOT NULL DEFAULT '{}',
  source TEXT DEFAULT 'external',
  model TEXT DEFAULT '',
  parent_version INTEGER,
  status TEXT DEFAULT 'draft',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(chapter,version)
);
CREATE INDEX IF NOT EXISTS idx_chapter_drafts_status ON chapter_drafts(chapter,status,version);
CREATE TABLE IF NOT EXISTS chapter_reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chapter INTEGER NOT NULL,
  draft_version INTEGER NOT NULL,
  reviewer_type TEXT NOT NULL,
  verdict TEXT NOT NULL,
  score REAL,
  findings_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chapter_reviews_draft ON chapter_reviews(chapter,draft_version,reviewer_type,id);
CREATE TABLE IF NOT EXISTS writing_workflow(
  chapter INTEGER PRIMARY KEY,
  active_draft_version INTEGER,
  status TEXT DEFAULT 'planned',
  last_review_verdict TEXT,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS novel_runs(
  run_id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'created',
  start_chapter INTEGER NOT NULL,
  current_chapter INTEGER NOT NULL,
  last_committed_chapter INTEGER,
  chapters_committed INTEGER NOT NULL DEFAULT 0,
  config_json TEXT NOT NULL DEFAULT '{}',
  stop_reason_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_novel_runs_status ON novel_runs(status,updated_at);
CREATE TABLE IF NOT EXISTS novel_run_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  chapter INTEGER,
  phase TEXT NOT NULL,
  status TEXT NOT NULL,
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_novel_run_events ON novel_run_events(run_id,id);
CREATE TABLE IF NOT EXISTS novel_run_decisions(
  decision_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  chapter INTEGER,
  decision_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open',
  prompt TEXT NOT NULL,
  context_json TEXT NOT NULL DEFAULT '{}',
  resolution_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_novel_run_decisions ON novel_run_decisions(run_id,status,created_at);
CREATE TABLE IF NOT EXISTS novel_run_reports(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL,
  from_chapter INTEGER,
  to_chapter INTEGER,
  report_json TEXT NOT NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS context_snapshots(
  snapshot_id TEXT PRIMARY KEY,
  chapter INTEGER NOT NULL,
  snapshot_chapter INTEGER NOT NULL,
  role TEXT NOT NULL,
  holder TEXT NOT NULL,
  max_tokens INTEGER NOT NULL,
  estimated_tokens INTEGER NOT NULL,
  payload_json TEXT NOT NULL,
  trace_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_context_snapshots_chapter_role ON context_snapshots(chapter,role,created_at);
INSERT OR IGNORE INTO planning_blueprint(id,version,payload_json) VALUES(1,1,'{}');
'''),
    (2, 'v0.8 A0: extraction candidate review columns', r'''
ALTER TABLE extraction_candidates ADD COLUMN resolution TEXT;
ALTER TABLE extraction_candidates ADD COLUMN resolved_at TEXT;
ALTER TABLE extraction_candidates ADD COLUMN promoted_target TEXT;
ALTER TABLE extraction_candidates ADD COLUMN review_note TEXT DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_extraction_candidates_status ON extraction_candidates(status,chapter,id);
'''),
    (3, 'v0.9 Entity Graph V2 core: identity profiles, first-class events, assertions, cause traceability', r'''
CREATE TABLE IF NOT EXISTS identity_profiles(
  profile_key TEXT PRIMARY KEY,
  entity_key TEXT NOT NULL,
  kind TEXT NOT NULL,
  value TEXT NOT NULL,
  scope_key TEXT,
  secrecy TEXT DEFAULT 'public',
  reveal_after INTEGER,
  fact_key TEXT,
  start_chapter INTEGER NOT NULL DEFAULT 0,
  end_chapter INTEGER,
  parent_profile_key TEXT,
  notes TEXT DEFAULT '',
  source TEXT DEFAULT 'author_declared',
  confidence REAL DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(entity_key) REFERENCES entities(entity_key)
);
CREATE INDEX IF NOT EXISTS idx_identity_profiles_entity ON identity_profiles(entity_key,start_chapter,end_chapter);
CREATE TABLE IF NOT EXISTS event_participants(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL,
  entity_key TEXT NOT NULL,
  participant_role TEXT DEFAULT 'participant',
  outcome_state_json TEXT DEFAULT '{}',
  FOREIGN KEY(event_id) REFERENCES events(id) ON DELETE CASCADE,
  FOREIGN KEY(entity_key) REFERENCES entities(entity_key),
  UNIQUE(event_id,entity_key,participant_role)
);
CREATE INDEX IF NOT EXISTS idx_event_participants_event ON event_participants(event_id);
CREATE INDEX IF NOT EXISTS idx_event_participants_entity ON event_participants(entity_key);
CREATE TABLE IF NOT EXISTS fact_assertions(
  assertion_id INTEGER PRIMARY KEY AUTOINCREMENT,
  subject_type TEXT NOT NULL DEFAULT 'entity',
  subject_key TEXT NOT NULL,
  predicate TEXT NOT NULL,
  object_value TEXT,
  chapter INTEGER NOT NULL,
  source_span TEXT,
  extractor TEXT DEFAULT 'author_declared',
  confidence REAL DEFAULT 1,
  evidence TEXT,
  truth_status TEXT NOT NULL DEFAULT 'candidate',
  superseded_by INTEGER,
  event_id INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(event_id) REFERENCES events(id)
);
CREATE INDEX IF NOT EXISTS idx_fact_assertions_subject ON fact_assertions(subject_type,subject_key,predicate);
CREATE INDEX IF NOT EXISTS idx_fact_assertions_status ON fact_assertions(truth_status);
ALTER TABLE entity_attributes ADD COLUMN cause_event_id INTEGER REFERENCES events(id);
ALTER TABLE entity_relations ADD COLUMN cause_event_id INTEGER REFERENCES events(id);
ALTER TABLE events ADD COLUMN cause_event_id INTEGER REFERENCES events(id);
ALTER TABLE events ADD COLUMN outcome TEXT DEFAULT '';
ALTER TABLE events ADD COLUMN consequence TEXT DEFAULT '';
ALTER TABLE events ADD COLUMN location_key TEXT;
'''),
    (4, 'v0.10 dual-time disclosures + professional subgraph support', r'''
CREATE TABLE IF NOT EXISTS fact_disclosures(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  fact_key TEXT NOT NULL,
  holder TEXT NOT NULL,
  known_from_chapter INTEGER NOT NULL,
  channel TEXT DEFAULT '',
  source TEXT DEFAULT 'author_declared',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(fact_key,holder)
);
CREATE INDEX IF NOT EXISTS idx_fact_disclosures_fact ON fact_disclosures(fact_key);
INSERT OR IGNORE INTO fact_disclosures(fact_key,holder,known_from_chapter,source)
  SELECT fact_key,'reader',reveal_after,'migrated_reveal_after' FROM world_facts WHERE reveal_after IS NOT NULL;
'''),
    (5, 'v0.10.1 explicit foreshadowing callbacks', r'''
UPDATE stages SET callback_key='stage_'||id WHERE stage_type IN ('Clue','Foreshadowing') AND callback_key IS NULL;
'''),
]

LATEST_VERSION = MIGRATIONS[-1][0]


def apply_migrations(db: sqlite3.Connection) -> int:
    """按 user_version 依序应用未执行的迁移,返回当前版本。

    每个迁移与版本号写入在同一个事务中:要么 schema 与版本号一起落库,
    要么一起回滚,避免出现"表已建但版本号未记"的半迁移状态。
    """
    current = int(db.execute('PRAGMA user_version').fetchone()[0])
    for version, _name, sql in MIGRATIONS:
        if version <= current:
            continue
        db.executescript('BEGIN;\n' + sql + f'\nPRAGMA user_version={version};\nCOMMIT;')
        current = version
    return current
