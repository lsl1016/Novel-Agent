from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

NODE_TYPES = {
    "Chapter", "Arc", "NarrativeThread", "ThreadMergeCandidate",
    "Event", "Mystery", "Clue", "Foreshadowing", "Reveal", "Payoff",
    "EmotionDebt", "Fact", "BeliefState",
    "Character", "Faction", "Location", "Artifact", "Concept",
}

EDGE_TYPES = {
    "BELONGS_TO", "PARTICIPATES_IN", "LOCATED_AT", "INVOLVES", "OWNS", "MEMBER_OF",
    "RAISES", "CONTAINS_CLUE", "CONTAINS_REVEAL", "CREATES_DEBT", "CONTAINS_PAYOFF",
    "HINTS_AT", "SUPPORTS", "OPPOSES", "ANSWERS", "PARTIALLY_ANSWERS", "EXPANDS",
    "COMPLICATES", "REINTERPRETS", "DEEPENS", "CONTRADICTS", "SUPERSEDES",
    "PAYS_OFF", "RESOLVES", "FULFILLS", "BELIEF_ABOUT", "KNOWN_BY", "HIDDEN_FROM",
    "PART_OF_THREAD", "NEXT_STAGE", "POSSIBLE_SAME_THREAD", "POSSIBLE_PAYOFF",
    "CHANGES_CAPABILITY", "LINKS_THREADS", "CALLBACK_TO",
}

ALLOWED_STATUS = {"candidate", "inferred", "verified", "rejected"}
STORY_TYPES = {
    "Event", "Mystery", "Clue", "Foreshadowing", "Reveal", "Payoff",
    "EmotionDebt", "Fact", "BeliefState",
}

@dataclass
class ValidationIssue:
    level: str
    message: str
    item_id: str | None = None

@dataclass
class ValidationResult:
    payload: dict[str, Any]
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(x.level == "error" for x in self.issues)


def _clamp_conf(v: Any, default: float = 0.65) -> float:
    try:
        x = float(v)
    except Exception:
        return default
    return max(0.0, min(1.0, x))


def validate_llm_payload(payload: Any, *, allow_verified: bool = False) -> ValidationResult:
    """校验并净化模型产出的章节抽取结果。

    不信任模型自行将节点标记为 verified。verified 状态须由后续的显式回指、
    人工精审或确定性的跨章证据来获得。
    """
    issues: list[ValidationIssue] = []
    if not isinstance(payload, dict):
        return ValidationResult({"nodes": [], "edges": []}, [ValidationIssue("error", "payload must be an object")])

    raw_nodes = payload.get("nodes", [])
    raw_edges = payload.get("edges", [])
    if not isinstance(raw_nodes, list):
        issues.append(ValidationIssue("error", "nodes must be a list"))
        raw_nodes = []
    if not isinstance(raw_edges, list):
        issues.append(ValidationIssue("error", "edges must be a list"))
        raw_edges = []

    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, raw in enumerate(raw_nodes, 1):
        if not isinstance(raw, dict):
            issues.append(ValidationIssue("warning", f"node #{i} ignored: not an object"))
            continue
        nid = str(raw.get("id", "")).strip() or f"node_{i}"
        if nid in seen:
            nid = f"{nid}_{i}"
            issues.append(ValidationIssue("warning", "duplicate node id renamed", nid))
        seen.add(nid)
        typ = str(raw.get("type", "Concept")).strip()
        if typ not in NODE_TYPES:
            issues.append(ValidationIssue("warning", f"unknown node type {typ}; downgraded to Concept", nid))
            typ = "Concept"
        status = str(raw.get("status", "candidate")).strip()
        if status not in ALLOWED_STATUS:
            status = "candidate"
        if status == "verified" and not allow_verified:
            status = "candidate"
            issues.append(ValidationIssue("warning", "LLM self-verification downgraded to candidate", nid))
        props = raw.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        evidence = props.get("evidence")
        if evidence is not None and not isinstance(evidence, (str, list)):
            props["evidence"] = str(evidence)
        nodes.append({
            "id": nid,
            "type": typ,
            "name": str(raw.get("name", typ)).strip()[:160],
            "confidence": _clamp_conf(raw.get("confidence")),
            "status": status,
            "properties": props,
        })

    valid_ids = {n["id"] for n in nodes}
    edges: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_edges, 1):
        if not isinstance(raw, dict):
            continue
        s = str(raw.get("source", "")).strip()
        t = str(raw.get("target", "")).strip()
        if s not in valid_ids or t not in valid_ids:
            issues.append(ValidationIssue("warning", f"edge #{i} ignored: dangling endpoint"))
            continue
        typ = str(raw.get("type", "INVOLVES")).strip().upper()
        if typ not in EDGE_TYPES:
            issues.append(ValidationIssue("warning", f"unknown edge type {typ}; using INVOLVES"))
            typ = "INVOLVES"
        props = raw.get("properties", {})
        if not isinstance(props, dict):
            props = {}
        edges.append({
            "source": s,
            "target": t,
            "type": typ,
            "confidence": _clamp_conf(raw.get("confidence")),
            "properties": props,
        })

    return ValidationResult({"nodes": nodes, "edges": edges}, issues)
