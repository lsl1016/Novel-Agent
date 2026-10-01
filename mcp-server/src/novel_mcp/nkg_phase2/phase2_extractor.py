from __future__ import annotations
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from .llm import call_openai_compatible
from .models import Chapter, Extraction, Node, Edge
from .phase2_prompt import PROMPT_VERSION, SYSTEM_PROMPT_V2, chunk_user_prompt
from .schema_v2 import validate_llm_payload
from .textutil import chunk_text

JsonCaller = Callable[[str, str | None, str | None], dict]


def _safe_id(raw: str, typ: str, chapter: int, chunk: int, idx: int) -> str:
    token = "".join(c for c in raw if c.isalnum() or c in "_-")[:64]
    if token:
        return f"S2_{chapter:04d}_{chunk:02d}_{token}"
    seed = f"{typ}|{chapter}|{chunk}|{idx}|{raw}"
    return f"S2_{typ[:3].upper()}_{chapter:04d}_{chunk:02d}_{idx:03d}_{hashlib.md5(seed.encode()).hexdigest()[:8]}"


def _semantic_key(n: Node) -> str:
    p = n.properties
    for k in ("semantic_key", "fact_key", "mystery_key", "debt_key", "callback_key"):
        if p.get(k):
            return f"{n.type}|{p[k]}"
    name = "".join(ch.lower() for ch in n.name if ch.isalnum())
    return f"{n.type}|{name}"


def _merge_nodes(nodes: list[Node]) -> tuple[list[Node], dict[str, str]]:
    by_key: dict[str, Node] = {}
    remap: dict[str, str] = {}
    for n in nodes:
        k = _semantic_key(n)
        if k not in by_key:
            by_key[k] = n
            remap[n.id] = n.id
            continue
        dst = by_key[k]
        remap[n.id] = dst.id
        dst.confidence = max(dst.confidence, n.confidence)
        # 合并简短证据和列表型的语义提示字段。
        for pk, pv in n.properties.items():
            if pk not in dst.properties or dst.properties[pk] in (None, "", []):
                dst.properties[pk] = pv
            elif isinstance(pv, list) and isinstance(dst.properties.get(pk), list):
                dst.properties[pk] = list(dict.fromkeys(dst.properties[pk] + pv))
    return list(by_key.values()), remap


def _serialize_extraction(ex: Extraction, meta: dict) -> dict:
    return {"meta": meta, "chapter_id": ex.chapter_id,
            "nodes": [asdict(n) for n in ex.nodes], "edges": [asdict(e) for e in ex.edges]}


def _deserialize_extraction(obj: dict) -> Extraction:
    return Extraction(obj["chapter_id"], [Node(**x) for x in obj.get("nodes", [])], [Edge(**x) for x in obj.get("edges", [])])


def extract_chapter_semantic(
    ch: Chapter,
    *,
    model: str | None = None,
    max_chunk_chars: int = 12000,
    overlap_chars: int = 500,
    cache_dir: str | Path | None = None,
    force: bool = False,
    caller: JsonCaller | None = None,
) -> tuple[Extraction, dict]:
    """高质量的二阶段章节抽取,带校验与断点续跑缓存。"""
    resolved_model = model or os.environ.get("NKG_LLM_MODEL") or None
    cache_path: Path | None = None
    if cache_dir:
        cache_path = Path(cache_dir) / f"{ch.id}.json"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        if cache_path.exists() and not force:
            obj = json.loads(cache_path.read_text(encoding="utf-8"))
            meta = obj.get("meta", {})
            same_model = (not resolved_model) or meta.get("model") == resolved_model
            if meta.get("source_sha256") == ch.sha256 and meta.get("prompt_version") == PROMPT_VERSION and same_model:
                return _deserialize_extraction(obj), {**meta, "cache_hit": True}

    caller = caller or (lambda prompt, model_name, system: call_openai_compatible(prompt, model=model_name, system_prompt=system))
    chunks = chunk_text(ch.text, max_chars=max_chunk_chars, overlap_chars=overlap_chars)
    all_nodes: list[Node] = []
    all_edges: list[Edge] = []
    issues: list[dict] = []

    for chunk in chunks:
        raw = caller(chunk_user_prompt(ch.number, ch.title, ch.volume_title, chunk.index, len(chunks), chunk.text), model, SYSTEM_PROMPT_V2)
        validated = validate_llm_payload(raw, allow_verified=False)
        for x in validated.issues:
            issues.append({"chunk": chunk.index, "level": x.level, "message": x.message, "item_id": x.item_id})
        local_map: dict[str, str] = {}
        for i, n in enumerate(validated.payload["nodes"], 1):
            nid = _safe_id(n["id"], n["type"], ch.number, chunk.index, i)
            local_map[n["id"]] = nid
            props = dict(n["properties"])
            evidence = props.get("evidence")
            if isinstance(evidence, list):
                evidence = next((str(x) for x in evidence if str(x).strip()), "")
            if isinstance(evidence, str) and evidence.strip():
                pos = chunk.text.find(evidence.strip())
                if pos >= 0:
                    props["evidence_start"] = chunk.start + pos
                    props["evidence_end"] = chunk.start + pos + len(evidence.strip())
            props.update({
                "extractor": "semantic_llm_v2",
                "prompt_version": PROMPT_VERSION,
                "chunk_index": chunk.index,
                "chunk_start": chunk.start,
                "chunk_end": chunk.end,
            })
            all_nodes.append(Node(nid, n["type"], n["name"], ch.number, n["confidence"], n["status"], props))
        for i, e in enumerate(validated.payload["edges"], 1):
            s = local_map.get(e["source"]); t = local_map.get(e["target"])
            if not s or not t:
                continue
            all_edges.append(Edge(
                f"S2E_{ch.number:04d}_{chunk.index:02d}_{i:03d}", s, t, e["type"], ch.number,
                e["confidence"], {**e["properties"], "extractor": "semantic_llm_v2"}
            ))

    merged_nodes, remap = _merge_nodes(all_nodes)
    edge_seen: set[tuple[str, str, str]] = set()
    merged_edges: list[Edge] = []
    for e in all_edges:
        s = remap.get(e.source, e.source); t = remap.get(e.target, e.target)
        if s == t:
            continue
        k = (s, t, e.type)
        if k in edge_seen:
            continue
        edge_seen.add(k)
        e.source = s; e.target = t
        merged_edges.append(e)

    # 确定性地添加章节节点,以及章节到各结构节点的边。
    chapter_node = Node(ch.id, "Chapter", f"第{ch.number}章 {ch.title}" if ch.number else "序章", ch.number, 1.0, "verified",
                        {"volume_id": ch.volume_id, "volume_title": ch.volume_title})
    merged_nodes.insert(0, chapter_node)
    rel_for = {
        "Mystery": "RAISES", "Clue": "CONTAINS_CLUE", "Foreshadowing": "CONTAINS_CLUE",
        "Reveal": "CONTAINS_REVEAL", "EmotionDebt": "CREATES_DEBT", "Payoff": "CONTAINS_PAYOFF",
        "Event": "INVOLVES", "Fact": "INVOLVES", "BeliefState": "INVOLVES",
    }
    for n in merged_nodes[1:]:
        rel = rel_for.get(n.type)
        if rel:
            merged_edges.append(Edge(f"S2E_{ch.id}_{n.id}", ch.id, n.id, rel, ch.number, n.confidence,
                                     {"extractor": "semantic_llm_v2"}))

    ex = Extraction(ch.id, merged_nodes, merged_edges)
    meta = {
        "source_sha256": ch.sha256,
        "prompt_version": PROMPT_VERSION,
        "model": resolved_model,
        "chunk_count": len(chunks),
        "issue_count": len(issues),
        "issues": issues,
        "cache_hit": False,
    }
    if cache_path:
        cache_path.write_text(json.dumps(_serialize_extraction(ex, meta), ensure_ascii=False, indent=2), encoding="utf-8")
    return ex, meta
