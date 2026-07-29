# -*- coding: utf-8 -*-
"""Environment / dependency checks for Tarrafa."""
from __future__ import annotations

import importlib.util
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any


def _mod_ok(name: str) -> tuple[bool, str]:
    try:
        spec = importlib.util.find_spec(name)
        if spec is None:
            return False, "not installed"
        mod = importlib.import_module(name)
        ver = getattr(mod, "__version__", getattr(mod, "VERSION", None))
        if ver is None:
            try:
                ver = metadata.version(name.replace("_", "-"))
            except metadata.PackageNotFoundError:
                ver = "installed (version unknown)"
        return True, str(ver)
    except Exception as e:
        return False, f"error: {e}"


_HINTS: dict[str, str] = {
    "python": "-> use Python ≥ 3.10",
    "playwright": "-> pip install playwright && playwright install chromium",
    "httpx": "-> pip install 'httpx>=0.27,<1'",
    "trafilatura": "-> pip install 'trafilatura>=1.6,<3'",
    "feedparser": "-> pip install 'feedparser>=6,<7'",
    "chromium": "-> playwright install chromium",
    "scrapy": "-> pip install -e '.[site]'  (optional)",
    "yt-dlp": "-> pip install -e '.[av]'  (optional for tarrafa video --download)",
    "ffmpeg": "-> install ffmpeg and add to PATH (optional for video frames)",
    "storage_state.json": "-> tarrafa ig … --save-storage ./storage_state.json (optional, IG only)",
    "PLAYWRIGHT_MCP_EXTENSION_TOKEN": "-> put token in ~/.tarrafa/.env or <repo>/.env (optional)",
    "tomllib": "-> Python ≥ 3.11 or pip install tomli  (for tarrafa.toml)",
    "skills": "-> tarrafa skills install  (ensina a Tarrafa aos hosts de IA desta máquina)",
    "search-provider": (
        "-> configure BRAVE_SEARCH_API_KEY ou SEARXNG_URL em ~/.tarrafa/.env ou <repo>/.env"
    ),
}


def _default_storage_hint() -> Path:
    return Path.cwd() / "storage_state.json"


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

    from tarrafa.core.media import has_yt_dlp, which

    ff = which("ffmpeg")
    add("ffmpeg", bool(ff), ff or "not in PATH (needed for video frames from file)", required=False)
    ytd = which("yt-dlp")
    ytd_detail = ytd or ("python package ok" if has_yt_dlp() else "not installed (optional for tarrafa video --download)")
    add("yt-dlp", has_yt_dlp(), ytd_detail, required=False)

    if storage_hint is None:
        storage_hint = _default_storage_hint()
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

    # Descoberta web (opcional): ao menos um provedor configurado.
    import os

    brave_search = bool(
        os.environ.get("TARRAFA_BRAVE_SEARCH_API_KEY")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
    )
    searxng = bool(os.environ.get("TARRAFA_SEARXNG_URL") or os.environ.get("SEARXNG_URL"))
    configured = [
        label
        for label, present in (("Brave", brave_search), ("SearXNG", searxng))
        if present
    ]
    add(
        "search-provider",
        bool(configured),
        ", ".join(configured) if configured else "nenhum provedor configurado",
        required=False,
    )

    # Skill de IA instalada nos hosts detectados (optional)
    try:
        from tarrafa.core.skills import status as skills_status

        rows = [r for r in skills_status() if r.get("detected")]
        if not rows:
            add("skills", True, "nenhum host de IA detectado (opcional)", required=False)
        else:
            labels = {
                "current": "atualizada",
                "stale": "desatualizada",
                "missing": "ausente",
                "manual": "editada à mão",
            }
            parts = [f"{r['label']}: {labels.get(r['state'], r['state'])}" for r in rows]
            ok = all(r["state"] in ("current", "manual") for r in rows)
            add("skills", ok, " · ".join(parts), required=False)
    except Exception as e:
        add("skills", False, f"erro ao checar: {e}", required=False)

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
        mark = "OK " if c["ok"] else ("FAIL" if c["required"] else "OPT ")
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
