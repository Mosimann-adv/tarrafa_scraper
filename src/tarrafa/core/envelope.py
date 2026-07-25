# -*- coding: utf-8 -*-
"""Forensic job envelope shared by tools (page / site / feed / future)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tarrafa import __version__
from tarrafa.core.writers import utc_now_iso


@dataclass
class JobEnvelope:
    """Material-only capture envelope (no classifiers)."""

    tool: str
    source: dict[str, Any]
    items: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    collected_at: str | None = None
    version: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "version": self.version or __version__,
            "collected_at": self.collected_at or utc_now_iso(),
            "source": self.source,
            "meta": self.meta,
            "count": len(self.items),
            "items": self.items,
            "errors": self.errors,
            "notes": self.notes,
        }


def build_envelope(
    tool: str,
    *,
    source: dict[str, Any] | str,
    items: list[dict[str, Any]] | None = None,
    meta: dict[str, Any] | None = None,
    errors: list[str] | None = None,
    notes: list[str] | None = None,
    collected_at: str | None = None,
) -> dict[str, Any]:
    if isinstance(source, str):
        source = {"url": source}
    env = JobEnvelope(
        tool=tool,
        source=source,
        items=list(items or []),
        meta=dict(meta or {}),
        errors=list(errors or []),
        notes=list(notes or []),
        collected_at=collected_at,
    )
    return env.to_dict()
