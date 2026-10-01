"""压测脚本共用:env 加载与 planner 作者提问的自动拍板。"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ANSWER = "作者代理拍板:采用与现有正典自洽、且不立为新 World Truth 的处理;正文层面自行取舍。"


def load_env(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f'env file not found: {path}')
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        if v.strip() and not v.strip().startswith('#'):
            os.environ.setdefault(k.strip(), v.strip())


def answer_planner_questions(svc, questions: list, preset: dict | None = None) -> int:
    """把 planner 的作者提问以 Q/A 形式写入 blueprint.author_decisions。

    该字段会进入后续 planner 上下文,配合 prompt 规则避免重复提问。
    问题可能是字符串或 {"question": ...} 对象,统一归一化。
    返回本次回答的问题数。
    """
    norm = []
    for q in questions or []:
        if isinstance(q, dict):
            q = (q.get('question') or q.get('q') or json.dumps(q, ensure_ascii=False)).strip()
        if isinstance(q, str) and q.strip():
            norm.append(q.strip())
    if not norm:
        return 0
    import json as _json
    preset = preset or {}
    bp = svc.blueprint_get()
    qa = (bp['blueprint'] or {}).get('author_decisions') or []
    answered = {x.get('question') for x in qa if isinstance(x, dict)}
    added = 0
    for q in norm:
        if q in answered:
            continue
        qa.append({'question': q, 'answer': preset.get(q, DEFAULT_ANSWER)})
        added += 1
    if added:
        svc.blueprint_update({'author_decisions': qa})
    return added
