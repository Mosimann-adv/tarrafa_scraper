# -*- coding: utf-8 -*-
"""Workspace layout: tarrafa init + path helpers."""
from __future__ import annotations

from pathlib import Path

from tarrafa.core.config import (
    CONFIG_FILENAME,
    DEFAULT_PATHS,
    default_workspace_toml,
    load_config,
)


def init_workspace(
    root: Path | str,
    *,
    name: str | None = None,
    notes: str = "",
    force: bool = False,
) -> dict[str, object]:
    """
    Create workspace layout (idempotent). Returns summary dict.

    Layout:
      tarrafa.toml
      raw/ shots/ html/ logs/ meta/ meta/runs/
    """
    root = Path(root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    case_name = (name or root.name).strip() or "case"
    toml_path = root / CONFIG_FILENAME
    created: list[str] = []
    skipped: list[str] = []

    if toml_path.exists() and not force:
        skipped.append(CONFIG_FILENAME)
    else:
        toml_path.write_text(
            default_workspace_toml(name=case_name, notes=notes),
            encoding="utf-8",
        )
        created.append(CONFIG_FILENAME)

    cfg = load_config(workspace=root)
    for key, rel in {**DEFAULT_PATHS, **cfg.paths}.items():
        d = root / rel
        if key == "meta":
            targets = [d, d / "runs"]
        else:
            targets = [d]
        for t in targets:
            if t.is_dir():
                skipped.append(str(t.relative_to(root)).replace("\\", "/"))
            else:
                t.mkdir(parents=True, exist_ok=True)
                # keep empty dirs visible in git if user commits case later
                keep = t / ".gitkeep"
                if not keep.exists():
                    keep.write_text("", encoding="utf-8")
                created.append(str(t.relative_to(root)).replace("\\", "/"))

    return {
        "root": str(root),
        "name": case_name,
        "toml": str(toml_path),
        "created": created,
        "skipped": skipped,
    }


def resolve_out_path(
    path: Path | str,
    *,
    workspace: Path | None = None,
    out_dir: Path | None = None,
) -> Path:
    """Resolve relative output path against --out-dir / workspace / cwd."""
    p = Path(path)
    if p.is_absolute():
        return p
    if out_dir is not None:
        return (out_dir / p).resolve()
    if workspace is not None:
        return (workspace / p).resolve()
    return p.resolve()
