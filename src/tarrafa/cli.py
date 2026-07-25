# -*- coding: utf-8 -*-
"""
tarrafa — multi-tool CLI

  tarrafa [global flags] <tool> [tool args]
  tarrafa init [dir]
  tarrafa list | version | doctor
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


TOOLS = [
    ("init", "Create optional workspace (tarrafa.toml + raw/shots/html/logs/meta)"),
    ("ig", "Instagram post/reel comments → forensic JSON (permalinks /c/)"),
    ("page", "Single public page capture (HTTP / browser + structured facts)"),
    ("site", "Controlled same-host BFS crawl → multi-page envelope"),
    ("feed", "RSS/Atom feed inventory (optional entry fetch)"),
    ("shot", "High-quality page screenshot → PNG + JSON"),
    ("video", "Video meta + frames (+ optional yt-dlp download)"),
    ("album", "Compile shots/frames into print-ready HTML album"),
    ("dossier", "Ficha HTML perfil: avatar + achados + fontes + prints seletivos"),
    ("cnpj", "Consulta CNPJ (API open CNPJá /office) → envelope JSON"),
    ("djen", "Comunicações DJEN (ComunicaAPI) — advogado (OAB) ou parte (--papel parte --texto)"),
    ("datajud", "Capa/movimentos Datajud (API pública CNJ) por CNJ → envelope"),
    ("pdf-extract", "Texto + identity hints (CPF/CNJ/endereço/…) de PDFs judiciais"),
    ("doctor", "Check Python deps, Chromium, ffmpeg, yt-dlp, storage_state, MCP token"),
    ("list", "List tools"),
    ("version", "Print version"),
]


def _cmd_version() -> int:
    from tarrafa import __version__

    print(f"tarrafa {__version__}")
    return 0


def _cmd_list() -> int:
    print("Available tools:\n")
    for name, desc in TOOLS:
        if name in ("list", "version"):
            continue
        print(f"  {name:12}  {desc}")
    print("\nUsage: tarrafa [global flags] <tool> --help")
    print("Global: -v/--verbose --quiet --force --no-clobber --timeout SEC")
    print("        --out-dir DIR --workspace DIR --json-logs")
    return 0


def _cmd_doctor(argv: list[str]) -> int:
    from tarrafa.core.doctor import print_doctor, run_doctor

    storage = None
    if "--storage" in argv:
        i = argv.index("--storage")
        if i + 1 < len(argv):
            storage = Path(argv[i + 1])
    report = run_doctor(storage_hint=storage)
    return print_doctor(report)


def _cmd_init(argv: list[str]) -> int:
    from tarrafa.core.runtime import get_runtime
    from tarrafa.core.workspace import init_workspace

    ap = argparse.ArgumentParser(
        prog="tarrafa init",
        description="Create an optional Tarrafa workspace (tarrafa.toml + folders).",
    )
    ap.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Target directory (default: current dir)",
    )
    ap.add_argument("--name", default=None, help="Case name (default: directory name)")
    ap.add_argument("--notes", default="", help="Short notes stored in tarrafa.toml")
    args = ap.parse_args(argv)

    rt = get_runtime()
    summary = init_workspace(
        args.directory,
        name=args.name,
        notes=args.notes,
        force=rt.force,
    )
    print(f"init: workspace → {summary['root']}")
    print(f"  name: {summary['name']}")
    if summary["created"]:
        print("  created:", ", ".join(summary["created"][:12]))
    if summary["skipped"]:
        print("  exists:", ", ".join(list(summary["skipped"])[:8]))
    print("  Tools still accept free --out / --out-dir; workspace is optional context.")
    return 0


def _dispatch_tool(mod_path: str, main_name: str, argv: list[str]) -> int:
    import importlib

    mod = importlib.import_module(mod_path)
    fn = getattr(mod, main_name)
    return int(fn(argv))


def _build_global_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tarrafa",
        description=(
            "Tarrafa — joga a rede e puxa a prova. "
            "Multi-source CLI for open-web capture and legal inventory."
        ),
        add_help=False,
    )
    p.add_argument("-h", "--help", action="store_true")
    p.add_argument("-v", "--verbose", action="count", default=0)
    p.add_argument("-q", "--quiet", action="store_true")
    p.add_argument("--force", action="store_true", help="Allow overwrite when no_clobber is set")
    p.add_argument(
        "--no-clobber",
        action="store_true",
        help="Refuse to overwrite existing output files (unless --force)",
    )
    p.add_argument("--timeout", type=float, default=None, help="Default timeout (seconds) for tools")
    p.add_argument(
        "--out-dir",
        default=None,
        help="Default base directory for relative tool outputs",
    )
    p.add_argument(
        "--workspace",
        default=None,
        help="Workspace root (dir with tarrafa.toml); else walk cwd / TARRAFA_WORKSPACE",
    )
    p.add_argument(
        "--json-logs",
        action="store_true",
        help="Emit machine-readable summary lines (JSON)",
    )
    p.add_argument(
        "tool",
        nargs="?",
        default=None,
        help="Tool name (see tarrafa list)",
    )
    p.add_argument("tool_args", nargs=argparse.REMAINDER, help=argparse.SUPPRESS)
    return p


def _inject_defaults(tool: str, rest: list[str], rt) -> list[str]:
    """Inject --timeout / workspace path defaults when tool did not pass them."""
    out = list(rest)
    # strip leading -- that argparse.REMAINDER keeps when using `--`
    if out and out[0] == "--":
        out = out[1:]

    if rt.timeout is not None and "--timeout" not in out:
        out = ["--timeout", str(rt.timeout), *out]

    # Convenience: if workspace known and shot without --out-dir → shots/
    if tool == "shot" and "--out-dir" not in out and rt.workspace is not None:
        shots = (rt.config.path("shots") if rt.config else None) or (rt.workspace / "shots")
        out = ["--out-dir", str(shots), *out]

    # Convenience: album default dir html/ only when --out missing — skip (album requires --out)

    if rt.out_dir is not None:
        # Apply global --out-dir as default for shot if still missing
        if tool == "shot" and "--out-dir" not in out:
            out = ["--out-dir", str(rt.out_dir), *out]

    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Load ~/.tarrafa/.env and <repo>/.env (never override existing process env)
    try:
        from tarrafa.core.env import load_tarrafa_env

        load_tarrafa_env()
    except Exception:
        pass

    gparser = _build_global_parser()
    tool, rest, gflags = _split_global_argv(argv)

    from tarrafa.core.config import load_config
    from tarrafa.core.runtime import Runtime, reset_runtime, set_runtime
    from tarrafa.core.run import finish_run, start_run

    ws_arg = gflags.get("workspace")
    workspace = Path(ws_arg).expanduser().resolve() if ws_arg else None
    cfg = load_config(workspace=workspace)

    rt = Runtime(
        verbose=int(gflags.get("verbose") or 0),
        quiet=bool(gflags.get("quiet")),
        force=bool(gflags.get("force")) or cfg.force,
        no_clobber=bool(gflags.get("no_clobber")) or cfg.no_clobber,
        timeout=gflags.get("timeout") if gflags.get("timeout") is not None else cfg.timeout,
        out_dir=Path(gflags["out_dir"]).expanduser().resolve() if gflags.get("out_dir") else None,
        json_logs=bool(gflags.get("json_logs")),
        config=cfg,
    )
    set_runtime(rt)

    try:
        if gflags.get("help") or tool in (None, "", "help"):
            gparser.print_help()
            print()
            return _cmd_list()

        if tool in ("list", "ls"):
            return _cmd_list()
        if tool in ("version", "-V", "--version"):
            return _cmd_version()
        if tool == "doctor":
            return _cmd_doctor(rest)
        if tool == "init":
            return _cmd_init(rest)

        dispatch = {
            "ig": "tarrafa.tools.ig.scraper",
            "page": "tarrafa.tools.page.scraper",
            "site": "tarrafa.tools.site.scraper",
            "feed": "tarrafa.tools.feed.scraper",
            "shot": "tarrafa.tools.shot.scraper",
            "video": "tarrafa.tools.video.scraper",
            "album": "tarrafa.tools.album.scraper",
            "dossier": "tarrafa.tools.dossier.scraper",
            "cnpj": "tarrafa.tools.cnpj.scraper",
            "djen": "tarrafa.tools.djen.scraper",
            "datajud": "tarrafa.tools.datajud.scraper",
            "pdf-extract": "tarrafa.tools.pdf_extract.scraper",
            "pdf_extract": "tarrafa.tools.pdf_extract.scraper",
        }
        if tool not in dispatch:
            print(f"Unknown tool: {tool!r}. Try: tarrafa list", file=sys.stderr)
            return 2

        rest = _inject_defaults(tool, rest, rt)
        session = start_run(tool, rest, workspace=rt.workspace)
        rt.run = session
        set_runtime(rt)

        try:
            code = _dispatch_tool(dispatch[tool], "main", rest)
        except FileExistsError as e:
            print(f"error: {e}", file=sys.stderr)
            code = 2
        except SystemExit as e:
            code = int(e.code) if e.code is not None else 0

        is_help = any(a in ("-h", "--help") for a in rest)
        record = bool(cfg.record_runs and rt.workspace and not is_help)
        run_path = finish_run(session, code, record=record)
        if run_path and rt.verbose and not rt.quiet:
            print(f"run: {run_path}")
        return int(code)
    finally:
        reset_runtime()


def _split_global_argv(argv: list[str]) -> tuple[str | None, list[str], dict]:
    """Parse global flags that appear before the tool name."""
    flags: dict = {
        "help": False,
        "verbose": 0,
        "quiet": False,
        "force": False,
        "no_clobber": False,
        "timeout": None,
        "out_dir": None,
        "workspace": None,
        "json_logs": False,
    }
    i = 0
    n = len(argv)
    while i < n:
        a = argv[i]
        if a in ("-h", "--help"):
            flags["help"] = True
            i += 1
            continue
        if a in ("-v", "--verbose"):
            flags["verbose"] = int(flags["verbose"] or 0) + 1
            i += 1
            continue
        if a.startswith("-v") and set(a[1:]) == {"v"}:
            flags["verbose"] = int(flags["verbose"] or 0) + (len(a) - 1)
            i += 1
            continue
        if a in ("-q", "--quiet"):
            flags["quiet"] = True
            i += 1
            continue
        if a == "--force":
            flags["force"] = True
            i += 1
            continue
        if a == "--no-clobber":
            flags["no_clobber"] = True
            i += 1
            continue
        if a == "--json-logs":
            flags["json_logs"] = True
            i += 1
            continue
        if a == "--timeout" and i + 1 < n:
            flags["timeout"] = float(argv[i + 1])
            i += 2
            continue
        if a.startswith("--timeout="):
            flags["timeout"] = float(a.split("=", 1)[1])
            i += 1
            continue
        if a == "--out-dir" and i + 1 < n:
            flags["out_dir"] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--out-dir="):
            flags["out_dir"] = a.split("=", 1)[1]
            i += 1
            continue
        if a == "--workspace" and i + 1 < n:
            flags["workspace"] = argv[i + 1]
            i += 2
            continue
        if a.startswith("--workspace="):
            flags["workspace"] = a.split("=", 1)[1]
            i += 1
            continue
        # first non-global token = tool
        if a.startswith("-"):
            # unknown global — treat as start of tool args only if tool already chosen
            # here we haven't chosen tool yet → leave to tool (e.g. tarrafa -V handled?)
            if a in ("-V", "--version"):
                return "version", [], flags
            # unknown flag before tool: stop and treat rest as tool path? better error later
            return a.lstrip("-"), argv[i + 1 :], flags
        return a, argv[i + 1 :], flags
    return None, [], flags


if __name__ == "__main__":
    raise SystemExit(main())
