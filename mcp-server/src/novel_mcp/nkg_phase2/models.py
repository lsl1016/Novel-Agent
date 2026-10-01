from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any


def to_dict(obj: Any) -> dict[str, Any]:
    return asdict(obj)


@dataclass
class Chapter:
    id: str
    number: int
    title: str
    volume_id: str
    volume_title: str
    text: str
    char_count: int
    sha256: str
    source_start: int
    source_end: int


@dataclass
class Node:
    id: str
    type: str
    name: str
    chapter: int | None = None
    confidence: float = 1.0
    status: str = "verified"
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    id: str
    source: str
    target: str
    type: str
    chapter: int | None = None
    confidence: float = 1.0
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Extraction:
    chapter_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
