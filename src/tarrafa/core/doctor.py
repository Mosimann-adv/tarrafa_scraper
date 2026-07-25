# -*- coding: utf-8 -*-
"""Environment / dependency checks for Tarrafa."""
from __future__ import annotations

import importlib.util
import platform
import sys
from pathlib import Path
from typing import Any


def _mod_ok(name: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(name)
        if spec is None:
            return False, "not installed"
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
        return True, str(ver)
    except Exception as e:
        return False, f"error: {e}"


_HINTS: dict[str, str] = {
    "python": "→ use Python ≥ 3.10",
    "playwright": "→ pip install playwright && playwright install chromium",
    "httpx": "→ pip install 'httpx>=0.27,<1'",
    "trafilatura": "→ pip install 'trafilatura>=1.6,<3'",
    "feedparser": "→ pip install 'feedparser>=6,<7'",
    "chromium": "→ playwright install chromium",
    "scrapy": "→ pip install -e '.[site]'  (optional)",
    "yt_dlp": "→ pip install -e '.[av]'  (optional for tarrafa video --download)",
    "ffmpeg": "→ install ffmpeg and add to PATH (optional for video frames)",
    "storage_state.json": "→ tarrafa ig … --save-storage ./storage_state.json (optional, IG only)",
    "PLAYWRIGHT_MCP_EXTENSION_TOKEN": "→ put token in ~/.tarrafa/.env or <repo>/.env (optional)",
    "tomllib": "→ Python ≥ 3.11 or pip install tomli  (for tarrafa.toml)",
}


def run_doctor(*, storage_hint: Path | None = None) -> dict[str, Any]:
    from tarrafa import __version__

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str, required: bool = True) -> None:
        hint = None if ok else _HINTS.get(name)
        checks.append(
            {
                "name": name,
                "ok": ok,
                "detail": detail,
                "required": required,
                "hint": hint,
            }
        )

    add("python", sys.version_info >= (3, 10), f"{sys.version.split()[0]} ({platform.system()})")
    add("tarrafa", True, __version__)

    for mod, req in (
        ("playwright", True),
        ("httpx", True),
        ("trafilatura", True),
        ("feedparser", True),
        ("scrapy", False),
        ("yt_dlp", False),
    ):
        ok, detail = _mod_ok(mod)
        add(mod, ok, detail, required=req)

    # TOML support (stdlib 3.11+ or tomli)
    toml_ok = False
    toml_detail = "missing"
    try:
        import tomllib  # noqa: F401

        toml_ok = True
        toml_detail = "stdlib tomllib"
    except ModuleNotFoundError:
        try:
            import tomli  # noqa: F401

            toml_ok = True
            toml_detail = "tomli"
        except ModuleNotFoundError:
            toml_detail = "install tomli for Python 3.10"
    add("tomllib", toml_ok, toml_detail, required=True)

    # Playwright browser binary (best-effort)
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            path = p.chromium.executable_path
            exists = Path(path).exists()
            add("chromium", exists, path if exists else f"missing: {path}")
    except Exception as e:
        add("chromium", False, str(e))

    from tarrafa.core.media import has_ffmpeg, has_yt_dlp, which

    ff = which("ffmpeg")
    add("ffmpeg", bool(ff), ff or "not in PATH (needed for video frames from file)", required=False)
    ytd = which("yt-dlp")
    ytd_detail = ytd or ("python package ok" if has_yt_dlp() else "not installed (optional for tarrafa video --download)")
    add("yt-dlp", has_yt_dlp(), ytd_detail, required=False)

    if storage_hint is None:
        storage_hint = Path(__file__).resolve().parents[3] / "storage_state.json"
    add(
        "storage_state.json",
        storage_hint.is_file(),
        str(storage_hint) if storage_hint.is_file() else f"absent (ok if not scraping IG): {storage_hint}",
        required=False,
    )

    # Local env: Playwright MCP extension token
    from tarrafa.core.env import load_tarrafa_env, token_status

    load_tarrafa_env()
    tok = token_status()
    if tok["present"]:
        src = ", ".join(tok["sources"]) if tok["sources"] else "env"
        detail = f"set · {tok['masked']} · from {src}"
    else:
        cands = " | ".join(tok["candidates"])
        detail = f"absent (optional; put PLAYWRIGHT_MCP_EXTENSION_TOKEN in {cands})"
    add("PLAYWRIGHT_MCP_EXTENSION_TOKEN", bool(tok["present"]), detail, required=False)

    # Workspace (optional)
    from tarrafa.core.config import find_workspace_root

    ws = find_workspace_root()
    if ws:
        add("workspace", True, str(ws), required=False)
    else:
        add(
            "workspace",
            True,
            "none in cwd (optional: tarrafa init ./meu-caso)",
            required=False,
        )

    required_fail = [c for c in checks if c["required"] and not c["ok"]]
    return {
        "ok": len(required_fail) == 0,
        "checks": checks,
        "failed_required": [c["name"] for c in required_fail],
    }


def print_doctor(report: dict[str, Any]) -> int:
    print("Tarrafa doctor\n")
    for c in report["checks"]:
        mark = "OK " if c["ok"] else "FAIL"
        req = "" if c["required"] else " (optional)"
        print(f"  [{mark}] {c['name']}{req}: {c['detail']}")
        if not c["ok"] and c.get("hint"):
            print(f"         {c['hint']}")
    print()
    if report["ok"]:
        print("All required checks passed.")
        return 0
    print("Failed required:", ", ".join(report["failed_required"]))
    print("Quick fix: pip install -e \".[dev]\" && playwright install chromium")
    if sys.version_info < (3, 11):
        print("Python 3.10: pip install tomli  (for tarrafa.toml)")
    return 1
