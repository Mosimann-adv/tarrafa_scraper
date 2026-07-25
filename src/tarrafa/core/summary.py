# -*- coding: utf-8 -*-
"""Stdout / NDJSON summaries for CLI tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.runtime import get_runtime


def emit_json_log(event: str, **fields: Any) -> None:
    rt = get_runtime()
    if not rt.json_logs:
        return
    row = {"event": event, **fields}
    if rt.run is not None:
        row.setdefault("run_id", rt.run.run_id)
    print(json.dumps(row, ensure_ascii=False), file=sys.stderr if rt.quiet else sys.stdout)


def print_summary(
    tool: str,
    *,
    ok: bool,
    count: int | None = None,
    path: Path | str | None = None,
    run_id: str | None = None,
    extra: str = "",
    errors: list[str] | None = None,
    exit_code: int | None = None,
) -> None:
    """One-line human summary (suppressed by --quiet)."""
    rt = get_runtime()
    rid = run_id or (rt.run.run_id if rt.run else None)
    emit_json_log(
        "summary",
        tool=tool,
        ok=ok,
        count=count,
        path=str(path) if path else None,
        run_id=rid,
        exit_code=exit_code,
        errors=errors or [],
        extra=extra or None,
    )
    if rt.quiet:
        return

    status = "ok" if ok else "fail"
    parts = [f"{tool}:", status]
    if count is not None:
        parts.append(f"count={count}")
    if path:
        parts.append(f"→ {path}")
    if rid and rt.verbose:
        parts.append(f"run={rid}")
    if extra:
        parts.append(extra)
    print(" · ".join(parts))
    if errors and (rt.verbose or not ok):
        for e in errors[:8]:
            print(f"  warn: {e}", file=sys.stderr)
