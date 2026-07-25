# -*- coding: utf-8 -*-
"""Run manifest — material chain for each CLI invocation."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tarrafa.core.media import file_sha256
from tarrafa.core.writers import utc_now_iso, write_json

_SENSITIVE = re.compile(
    (
        r"(token|password|passwd|secret|authorization|cookie|credential|"
        r"storage[-_.]?state|api[-_.]?key|session(?:id)?)"
    ),
    re.I,
)


def sanitize_argv(argv: list[str]) -> list[str]:
    """Redact likely secrets in argv for durable logs."""
    out: list[str] = []
    hide_next = False
    for a in argv:
        if hide_next:
            out.append("***")
            hide_next = False
            continue
        key = a.lstrip("-").split("=", 1)[0]
        if a.startswith("-") and _SENSITIVE.search(key):
            if "=" in a:
                k, _, _ = a.partition("=")
                out.append(f"{k}=***")
            else:
                out.append(a)
                hide_next = True
            continue
        out.append(a)
    return out


def artifact_info(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    info: dict[str, Any] = {
        "path": str(p.resolve()) if p.exists() else str(p),
        "exists": p.is_file() or p.is_dir(),
    }
    if p.is_file():
        try:
            info["bytes"] = p.stat().st_size
            info["sha256"] = file_sha256(p)
        except OSError:
            pass
    return info


@dataclass
class RunSession:
    run_id: str
    tool: str
    argv: list[str]
    started_at: str
    t0: float
    workspace: Path | None = None
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    finished: bool = False
    path: Path | None = None

    def add_artifact(self, path: Path | str, *, kind: str | None = None) -> None:
        info = artifact_info(path)
        if kind:
            info["kind"] = kind
        # de-dupe by path
        rp = info.get("path")
        for existing in self.artifacts:
            if existing.get("path") == rp:
                existing.update(info)
                return
        self.artifacts.append(info)


def new_run_id(tool: str) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    short = uuid.uuid4().hex[:8]
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", tool)[:24]
    return f"{stamp}Z-{safe}-{short}"


def start_run(
    tool: str,
    argv: list[str],
    *,
    workspace: Path | None = None,
    meta: dict[str, Any] | None = None,
) -> RunSession:
    return RunSession(
        run_id=new_run_id(tool),
        tool=tool,
        argv=sanitize_argv(list(argv)),
        started_at=utc_now_iso(),
        t0=time.perf_counter(),
        workspace=workspace.resolve() if workspace else None,
        meta=dict(meta or {}),
    )


def finish_run(
    session: RunSession,
    exit_code: int,
    *,
    record: bool = True,
    rehash: bool = True,
) -> Path | None:
    """Write meta/runs/<run_id>.json when workspace + record. Returns path or None."""
    if session.finished:
        return session.path
    session.finished = True

    if rehash:
        refreshed: list[dict[str, Any]] = []
        for art in session.artifacts:
            p = art.get("path")
            if p:
                info = artifact_info(p)
                if art.get("kind"):
                    info["kind"] = art["kind"]
                refreshed.append(info)
            else:
                refreshed.append(art)
        session.artifacts = refreshed

    duration_ms = int((time.perf_counter() - session.t0) * 1000)
    payload: dict[str, Any] = {
        "run_id": session.run_id,
        "tool": session.tool,
        "version": None,
        "started_at": session.started_at,
        "finished_at": utc_now_iso(),
        "duration_ms": duration_ms,
        "exit_code": int(exit_code),
        "argv": session.argv,
        "workspace": str(session.workspace) if session.workspace else None,
        "artifacts": session.artifacts,
        "notes": session.notes,
        "meta": session.meta,
    }
    try:
        from tarrafa import __version__

        payload["version"] = __version__
    except Exception:
        pass

    if not record or not session.workspace:
        return None

    runs_dir = session.workspace / "meta" / "runs"
    out = runs_dir / f"{session.run_id}.json"
    write_json(out, payload, register_run=False)
    session.path = out
    return out


def register_artifact(path: Path | str, *, kind: str | None = None) -> None:
    from tarrafa.core.runtime import get_runtime

    run = get_runtime().run
    if run is not None:
        run.add_artifact(path, kind=kind)
