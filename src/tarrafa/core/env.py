# -*- coding: utf-8 -*-
"""Local env loading for Tarrafa (Playwright MCP token, etc.).

Load order (later does not override earlier, except process env wins last
only if already set before load — standard dotenv: file fills missing keys):

1. ``%USERPROFILE%\\.tarrafa\\.env`` (user-global, gitignored)
2. ``<repo>/.env`` (project-local, gitignored)
3. Existing ``os.environ`` is never overwritten by files.

Call ``load_tarrafa_env()`` once at CLI startup.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

# Public name used by Playwright MCP extension mode
PLAYWRIGHT_MCP_EXTENSION_TOKEN = "PLAYWRIGHT_MCP_EXTENSION_TOKEN"

_LOADED = False


def repo_root() -> Path:
    """…/tarrafa_scraper (parent of src/)."""
    return Path(__file__).resolve().parents[3]


def user_tarrafa_dir() -> Path:
    return Path.home() / ".tarrafa"


def env_file_candidates() -> list[Path]:
    """User file first, then project .env (project fills only missing keys if load order is user→repo with no-override)."""
    return [
        user_tarrafa_dir() / ".env",
        repo_root() / ".env",
    ]


def parse_dotenv(text: str) -> dict[str, str]:
    """Minimal KEY=VALUE parser. No export, no multiline, no shell expansion."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        out[key] = val
    return out


def load_dotenv_file(path: Path, *, override: bool = False) -> dict[str, str]:
    """Load one .env into os.environ. Returns keys applied."""
    applied: dict[str, str] = {}
    if not path.is_file():
        return applied
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return applied
    for key, val in parse_dotenv(text).items():
        if not override and key in os.environ and os.environ[key] != "":
            continue
        os.environ[key] = val
        applied[key] = val
    return applied


def load_tarrafa_env(*, force: bool = False) -> list[str]:
    """
    Load user + project .env files into os.environ (no override of existing).

    Returns list of file paths that contributed at least one key.
    """
    global _LOADED
    if _LOADED and not force:
        return []
    used: list[str] = []
    # User first, then project — both no-override so process/shell wins;
    # between files, first wins for a given key (user preferred).
    for path in env_file_candidates():
        applied = load_dotenv_file(path, override=False)
        if applied:
            used.append(str(path))
    _LOADED = True
    return used


def get_env(name: str, default: str | None = None) -> str | None:
    load_tarrafa_env()
    val = os.environ.get(name)
    if val is None or val == "":
        return default
    return val


def playwright_extension_token() -> str | None:
    """PLAYWRIGHT_MCP_EXTENSION_TOKEN if set (after loading local .env)."""
    return get_env(PLAYWRIGHT_MCP_EXTENSION_TOKEN)


def mask_secret(value: str | None, *, keep: int = 4) -> str:
    if not value:
        return "(absent)"
    if len(value) <= keep * 2:
        return "***"
    return f"{value[:keep]}…{value[-keep:]} (len={len(value)})"


def token_status() -> dict[str, object]:
    """For doctor / diagnostics (never prints full token)."""
    load_tarrafa_env()
    raw = os.environ.get(PLAYWRIGHT_MCP_EXTENSION_TOKEN) or ""
    sources: list[str] = []
    for path in env_file_candidates():
        if not path.is_file():
            continue
        try:
            parsed = parse_dotenv(path.read_text(encoding="utf-8-sig"))
        except OSError:
            continue
        if PLAYWRIGHT_MCP_EXTENSION_TOKEN in parsed and parsed[PLAYWRIGHT_MCP_EXTENSION_TOKEN]:
            sources.append(str(path))
    if raw and PLAYWRIGHT_MCP_EXTENSION_TOKEN in os.environ:
        # could also be process/User env only
        if not sources:
            sources.append("process environment")
    return {
        "name": PLAYWRIGHT_MCP_EXTENSION_TOKEN,
        "present": bool(raw),
        "masked": mask_secret(raw if raw else None),
        "sources": sources,
        "candidates": [str(p) for p in env_file_candidates()],
    }


def ensure_user_env_dir() -> Path:
    d = user_tarrafa_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_env_key(
    path: Path,
    key: str,
    value: str,
    *,
    comment_lines: Iterable[str] | None = None,
) -> None:
    """Upsert KEY=value in a .env file. Preserves other lines when possible."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8-sig").splitlines()

    new_lines: list[str] = []
    found = False
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue
        work = stripped[7:].strip() if stripped.lower().startswith("export ") else stripped
        if "=" not in work:
            new_lines.append(line)
            continue
        k = work.split("=", 1)[0].strip()
        if k == key:
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        if comment_lines:
            for c in comment_lines:
                new_lines.append(c if c.startswith("#") else f"# {c}")
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
