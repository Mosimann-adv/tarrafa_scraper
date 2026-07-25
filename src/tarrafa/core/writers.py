# -*- coding: utf-8 -*-
"""Atomic-ish JSON / JSONL writers for forensic dumps."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def write_json(
    path: Path | str,
    payload: dict[str, Any] | list[Any],
    *,
    indent: int = 2,
    register_run: bool = True,
    force: bool | None = None,
) -> Path:
    """Write UTF-8 JSON (object or list). Creates parents. Atomic replace when possible.

    When runtime.no_clobber is set and the file exists, refuses unless force/runtime.force.
    Successful writes register the path on the active run (if any).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from tarrafa.core.runtime import get_runtime

        rt = get_runtime()
        use_force = rt.force if force is None else force
        if path.exists() and rt.no_clobber and not use_force:
            raise FileExistsError(
                f"refusing to overwrite {path} (no_clobber; pass --force or set defaults.force)"
            )
    except FileExistsError:
        raise
    except Exception:
        rt = None  # noqa: F841 — runtime optional during early import

    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if indent:
        text += "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        # Fallback non-atomic
        path.write_text(text, encoding="utf-8")

    if register_run:
        try:
            from tarrafa.core.run import register_artifact

            register_artifact(path, kind="json")
        except Exception:
            pass
    return path


def write_jsonl(path: Path | str, rows: Iterable[dict[str, Any]], *, append: bool = False) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path
