from __future__ import annotations
import re
from dataclasses import dataclass

@dataclass
class TextChunk:
    index: int
    start: int
    end: int
    text: str

PARA_RE = re.compile(r"\n\s*\n+")
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])")


def _hard_split(text: str, max_chars: int) -> list[str]:
    out: list[str] = []
    cur = ""
    for s in SENT_SPLIT_RE.split(text):
        if not s:
            continue
        if len(cur) + len(s) <= max_chars:
            cur += s
        else:
            if cur:
                out.append(cur)
            while len(s) > max_chars:
                out.append(s[:max_chars])
                s = s[max_chars:]
            cur = s
    if cur:
        out.append(cur)
    return out


def chunk_text(text: str, max_chars: int = 12000, overlap_chars: int = 500) -> list[TextChunk]:
    """将章节切分为稳定的分块,不丢失中文标点。

    重叠部分取自上一个分块的尾部,使跨边界的线索保持可见。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [TextChunk(0, 0, len(text), text)]

    paras = [p.strip() for p in PARA_RE.split(text) if p.strip()]
    pieces: list[str] = []
    for p in paras:
        if len(p) <= max_chars:
            pieces.append(p)
        else:
            pieces.extend(_hard_split(p, max_chars))

    chunks: list[TextChunk] = []
    cur = ""
    cursor = 0
    chunk_start = 0
    for p in pieces:
        addition = p if not cur else "\n\n" + p
        if cur and len(cur) + len(addition) > max_chars:
            end = chunk_start + len(cur)
            chunks.append(TextChunk(len(chunks), chunk_start, end, cur))
            tail = cur[-overlap_chars:] if overlap_chars > 0 else ""
            cur = tail + ("\n\n" if tail else "") + p
            chunk_start = max(0, end - len(tail))
        else:
            if not cur:
                chunk_start = cursor
            cur += addition
        cursor += len(addition)
    if cur:
        chunks.append(TextChunk(len(chunks), chunk_start, min(len(text), chunk_start + len(cur)), cur))
    return chunks
