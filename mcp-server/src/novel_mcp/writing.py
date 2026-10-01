from __future__ import annotations

import json
import os
from typing import Any

from .store import StoryStore, jd, jl


def _draft_row(row: Any) -> dict[str, Any]:
    d = dict(row)
    d['declared_updates'] = jl(d.pop('declared_updates_json')) or {}
    return d


class WritingStore:
    """正文草稿与审校证据的持久化。

    权威故事状态仍保存在 StoryStore 中。在 chapter_finalize 触发提交门之前,
    草稿绝不修改权威状态。表结构由 novel_mcp.schema 迁移统一管理。
    """

    def __init__(self, story: StoryStore):
        self.story = story

    def save_draft(
        self,
        chapter: int,
        title: str,
        body: str,
        *,
        arc: str = '',
        pov: str = '',
        summary: str = '',
        declared_updates: dict[str, Any] | None = None,
        source: str = 'external',
        model: str = '',
        parent_version: int | None = None,
        status: str = 'draft',
    ) -> dict[str, Any]:
        if not title or not body:
            raise ValueError('title and body are required')
        with self.story.connect() as db:
            version = int(db.execute('SELECT COALESCE(MAX(version),0)+1 n FROM chapter_drafts WHERE chapter=?', (chapter,)).fetchone()['n'])
            db.execute('''INSERT INTO chapter_drafts(
              chapter,version,title,body,arc,pov,summary,declared_updates_json,source,model,parent_version,status
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (
                chapter, version, title, body, arc, pov, summary, jd(declared_updates or {}), source, model, parent_version, status
            ))
            db.execute('''INSERT INTO writing_workflow(chapter,active_draft_version,status)
              VALUES(?,?,?) ON CONFLICT(chapter) DO UPDATE SET active_draft_version=excluded.active_draft_version,
              status=excluded.status,last_review_verdict=NULL,updated_at=CURRENT_TIMESTAMP''', (chapter, version, status))
        return self.get_draft(chapter, version)

    def get_draft(self, chapter: int, version: int | None = None) -> dict[str, Any] | None:
        with self.story.connect() as db:
            if version is None:
                r = db.execute('SELECT * FROM chapter_drafts WHERE chapter=? ORDER BY version DESC LIMIT 1', (chapter,)).fetchone()
            else:
                r = db.execute('SELECT * FROM chapter_drafts WHERE chapter=? AND version=?', (chapter, version)).fetchone()
        return _draft_row(r) if r else None

    def list_drafts(self, chapter: int) -> list[dict[str, Any]]:
        with self.story.connect() as db:
            rows = db.execute('SELECT * FROM chapter_drafts WHERE chapter=? ORDER BY version', (chapter,)).fetchall()
        return [_draft_row(r) for r in rows]

    def replace_reviews(self, chapter: int, draft_version: int, reviews: list[dict[str, Any]], replace_types: list[str] | None = None) -> None:
        """替换某一精确草稿版本的全部审校结果,或仅替换所提供的审校者类型。

        v0.4 将确定性审校与语义审校证据并列保存,因此重跑其中一个
        审校家族时不得抹掉另一个家族。
        """
        with self.story.connect() as db:
            if replace_types:
                qs=','.join('?' for _ in replace_types)
                db.execute(f'DELETE FROM chapter_reviews WHERE chapter=? AND draft_version=? AND reviewer_type IN ({qs})',
                           (chapter, draft_version, *replace_types))
            else:
                db.execute('DELETE FROM chapter_reviews WHERE chapter=? AND draft_version=?', (chapter, draft_version))
            for r in reviews:
                db.execute('''INSERT INTO chapter_reviews(chapter,draft_version,reviewer_type,verdict,score,findings_json,metadata_json)
                  VALUES(?,?,?,?,?,?,?)''', (
                    chapter, draft_version, r['reviewer_type'], r['verdict'], r.get('score'), jd(r.get('findings', [])), jd(r.get('metadata', {}))
                ))
            rows=db.execute('SELECT verdict FROM chapter_reviews WHERE chapter=? AND draft_version=?',(chapter,draft_version)).fetchall()
            overall=overall_verdict([{'verdict':r['verdict']} for r in rows]) if rows else 'NOT_REVIEWED'
            db.execute('''INSERT INTO writing_workflow(chapter,active_draft_version,status,last_review_verdict)
              VALUES(?,?,?,?) ON CONFLICT(chapter) DO UPDATE SET active_draft_version=excluded.active_draft_version,
              status=excluded.status,last_review_verdict=excluded.last_review_verdict,updated_at=CURRENT_TIMESTAMP''',
              (chapter, draft_version, 'reviewed', overall))

    def get_reviews(self, chapter: int, draft_version: int) -> list[dict[str, Any]]:
        with self.story.connect() as db:
            rows = db.execute('SELECT * FROM chapter_reviews WHERE chapter=? AND draft_version=? ORDER BY id', (chapter, draft_version)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d['findings'] = jl(d.pop('findings_json')) or []
            d['metadata'] = jl(d.pop('metadata_json')) or {}
            out.append(d)
        return out

    def set_status(self, chapter: int, version: int, status: str) -> None:
        with self.story.connect() as db:
            db.execute('UPDATE chapter_drafts SET status=? WHERE chapter=? AND version=?', (status, chapter, version))
            db.execute('''INSERT INTO writing_workflow(chapter,active_draft_version,status)
              VALUES(?,?,?) ON CONFLICT(chapter) DO UPDATE SET active_draft_version=excluded.active_draft_version,
              status=excluded.status,updated_at=CURRENT_TIMESTAMP''', (chapter, version, status))

    def workflow(self, chapter: int) -> dict[str, Any]:
        with self.story.connect() as db:
            r = db.execute('SELECT * FROM writing_workflow WHERE chapter=?', (chapter,)).fetchone()
        return dict(r) if r else {'chapter': chapter, 'active_draft_version': None, 'status': 'not_started', 'last_review_verdict': None}


def overall_verdict(reviews: list[dict[str, Any]]) -> str:
    verdicts = [r.get('verdict', 'PASS') for r in reviews]
    if 'BLOCK' in verdicts:
        return 'BLOCK'
    if 'WARN' in verdicts:
        return 'WARN'
    return 'PASS'


def call_writer_model(system_prompt: str, user_prompt: str, model: str | None = None, timeout: int = 240) -> tuple[str, str]:
    """零依赖文本生成,支持 OpenAI 兼容与 Anthropic Message 双协议。

    Uses NOVEL_WRITER_* first and falls back to NKG_LLM_* so the writer can be
    routed independently from the Phase-2 extractor.
    """
    from .llm_client import chat
    temperature = float(os.environ.get('NOVEL_WRITER_TEMPERATURE', '0.75'))
    return chat(system_prompt, user_prompt, prefix='NOVEL_WRITER', fallback_prefixes=('NKG_LLM',),
                model=model, temperature=temperature, json_mode=False, timeout=timeout)
