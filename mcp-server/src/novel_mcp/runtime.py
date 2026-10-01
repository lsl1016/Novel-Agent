from __future__ import annotations
import json,os
from pathlib import Path
from .service import NovelService
from .tooldefs import TOOLS,TOOL_BY_NAME

_SERVICE=None

def service():
    global _SERVICE
    if _SERVICE is None:
        db=os.environ.get('NOVEL_STORY_DB','./story-data/story.db')
        ref=os.environ.get('NOVEL_REFERENCE_ROOT') or None
        nkg=os.environ.get('NARRATIVE_KG_ROOT') or None
        _SERVICE=NovelService(db,ref,nkg)
    return _SERVICE

def call_tool(name,args):
    if name not in TOOL_BY_NAME: raise KeyError(f'unknown tool: {name}')
    fn=getattr(service(),name)
    return fn(**(args or {}))
