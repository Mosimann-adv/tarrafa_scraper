# -*- coding: utf-8 -*-
"""Tarrafa config layers: flags → env → ./tarrafa.toml → ~/.tarrafa/config.toml."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "tarrafa.toml"

DEFAULT_PATHS: dict[str, str] = {
    "raw": "raw",
    "shots": "shots",
    "html": "html",
    "logs": "logs",
    "meta": "meta",
}


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            return {}
    try:
        data = tomllib.loads(text)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def user_config_path() -> Path:
    return Path.home() / ".tarrafa" / "config.toml"


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Walk up from start (or cwd) looking for tarrafa.toml."""
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for _ in range(12):
        if (cur / CONFIG_FILENAME).is_file():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    env = os.environ.get("TARRAFA_WORKSPACE") or os.environ.get("TARRAFA_CASE")
    if env:
        p = Path(env).expanduser().resolve()
        if (p / CONFIG_FILENAME).is_file() or p.is_dir():
            return p
    return None


@dataclass
class TarrafaConfig:
    """Merged configuration (workspace-aware defaults)."""

    case_name: str = ""
    case_tags: list[str] = field(default_factory=list)
    case_notes: str = ""
    paths: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PATHS))
    timeout: float | None = None
    force: bool = False
    no_clobber: bool = False
    record_runs: bool = True
    workspace: Path | None = None
    sources: list[str] = field(default_factory=list)

    def path(self, key: str) -> Path | None:
        """Resolve a named workspace path (raw/shots/…). None if no workspace."""
        if not self.workspace:
            return None
        rel = self.paths.get(key) or DEFAULT_PATHS.get(key) or key
        return (self.workspace / rel).resolve()


def _merge_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge_dict(out[k], v)  # type: ignore[arg-type]
        else:
            out[k] = v
    return out


def load_config(
    *,
    workspace: Path | None = None,
    start: Path | None = None,
) -> TarrafaConfig:
    """
    Load config layers (later overrides earlier for TOML values):

    1. built-in defaults
    2. ~/.tarrafa/config.toml
    3. <workspace>/tarrafa.toml
    4. env TARRAFA_* (timeout, force, no_clobber)
    """
    raw: dict[str, Any] = {
        "case": {},
        "defaults": {},
        "paths": dict(DEFAULT_PATHS),
    }
    sources: list[str] = []

    user_p = user_config_path()
    user_data = _load_toml(user_p)
    if user_data:
        raw = _merge_dict(raw, user_data)
        sources.append(str(user_p))

    ws = workspace if workspace is not None else find_workspace_root(start)
    if ws is not None:
        ws = ws.resolve()
        ws_data = _load_toml(ws / CONFIG_FILENAME)
        if ws_data:
            raw = _merge_dict(raw, ws_data)
            sources.append(str(ws / CONFIG_FILENAME))
        elif (ws / CONFIG_FILENAME).is_file() is False and not user_data:
            # bare workspace dir via env still counts
            pass

    case = raw.get("case") if isinstance(raw.get("case"), dict) else {}
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    paths_raw = raw.get("paths") if isinstance(raw.get("paths"), dict) else {}
    paths = dict(DEFAULT_PATHS)
    for k, v in paths_raw.items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            paths[k] = v.strip()

    timeout: float | None = None
    if defaults.get("timeout") is not None:
        try:
            timeout = float(defaults["timeout"])
        except (TypeError, ValueError):
            timeout = None

    force = bool(defaults.get("force", False))
    no_clobber = bool(defaults.get("no_clobber", False))
    record_runs = bool(defaults.get("record_runs", True))

    # env overrides (process)
    if os.environ.get("TARRAFA_TIMEOUT"):
        try:
            timeout = float(os.environ["TARRAFA_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("TARRAFA_FORCE", "").strip().lower() in ("1", "true", "yes"):
        force = True
    if os.environ.get("TARRAFA_NO_CLOBBER", "").strip().lower() in ("1", "true", "yes"):
        no_clobber = True
    if os.environ.get("TARRAFA_RECORD_RUNS", "").strip().lower() in ("0", "false", "no"):
        record_runs = False

    tags = case.get("tags") or []
    if not isinstance(tags, list):
        tags = [str(tags)]

    return TarrafaConfig(
        case_name=str(case.get("name") or (ws.name if ws else "") or ""),
        case_tags=[str(t) for t in tags],
        case_notes=str(case.get("notes") or ""),
        paths=paths,
        timeout=timeout,
        force=force,
        no_clobber=no_clobber,
        record_runs=record_runs,
        workspace=ws,
        sources=sources,
    )


def default_workspace_toml(*, name: str, notes: str = "") -> str:
    """Canonical tarrafa.toml content for `tarrafa init`."""
    safe_name = name.strip() or "case"
    notes_line = notes.replace("\n", " ").strip()
    return f"""# Tarrafa workspace — optional context for defaults & run history.
# Tools still work with free --out / --out-dir outside any workspace.

[case]
name = "{safe_name}"
tags = []
notes = "{notes_line}"

[defaults]
# timeout = 30.0
force = false
no_clobber = false
record_runs = true

[paths]
raw = "raw"
shots = "shots"
html = "html"
logs = "logs"
meta = "meta"
"""
