"""Public project access. Legacy tokens no longer restrict access.

Model context roles describe narrative knowledge, not user permissions.
Validation and canonical commit gates remain in the service layer.
"""
from __future__ import annotations


def auth_enabled() -> bool:
    return False


def resolve_role(headers: dict[str, str]) -> tuple[str, int]:
    return 'admin', 0


def tool_allowed(role: str, name: str, args: dict | None = None) -> tuple[bool, None]:
    return True, None
