# -*- coding: utf-8 -*-
"""
tarrafa — multi-tool CLI

  tarrafa [global flags] <tool> [tool args]
  tarrafa init [dir]
  tarrafa skills [list|install|show]
  tarrafa list | version | doctor
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = [
    ("init", "Create optional workspace (tarrafa.toml + raw/shots/html/logs/meta)"),
    ("ig", "Inventário de perfil IG ou comentários -> JSON (permalinks /c/)"),
    ("page", "Single public page capture (HTTP / browser + structured facts)"),
    ("site", "Concurrent same-host crawl -> multi-page envelope"),
    ("feed", "RSS/Atom feed inventory (optional entry fetch)"),
    ("search", "Descoberta web: encontra URLs candidatas via Brave/SearXNG"),
    ("profile", "Perfil web aprofundado: Instagram acoplado, site, artigos e HTML"),
    ("shot", "High-quality page screenshot -> PNG + JSON"),
    ("video", "Video meta + frames (+ optional yt-dlp download)"),
    ("album", "Compile shots/frames into print-ready HTML album"),
    ("dossier", "Ficha HTML perfil: avatar + achados + fontes + prints seletivos"),
    ("cnpj", "Consulta CNPJ (API open CNPJá /office) -> envelope JSON"),
    ("djen", "Comunicações DJEN — advogado (OAB) ou parte (prioridade por --cpf)"),
    ("datajud", "Capa/movimentos Datajud (API pública CNJ) por CNJ -> envelope"),
    ("stj", "STJ SCON inteiro teor (PDF) — Cloudflare-aware (warmup/headed/CDP)"),
    ("pdf-extract", "Texto + identity hints (CPF/CNJ/endereço/…) de PDFs judiciais"),
    (
        "order-risk",
        "Triagem chargeback e-commerce (CPF/CEP/DJEN/loja) → JSON + HTML com imagens embutidas",
    ),
    ("verify", "Reconfere o SHA-256 dos artefatos capturados contra os manifestos de execução"),
    ("doctor", "Check Python deps, Chromium, ffmpeg, yt-dlp, storage_state, MCP token"),
    ("skills", "Instala a skill da Tarrafa nos hosts de IA (Claude, Grok) com caminhos resolvidos"),
    ("list", "List tools"),
    ("version", "Print version"),
]


def _configure_stdio() -> None:
    """Keep CLI output usable on legacy Windows code pages.

    Python may expose a strict cp1252 stdout/stderr even in modern Windows
    terminals. Tarrafa's human-readable output uses a few typographic Unicode
    characters, so replace only unencodable characters instead of crashing.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="replace")
            except (AttributeError, OSError, ValueError):
                pass


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
    from tarrafa.core.runtime import get_runtime

    storage = None
    if "--storage" in argv:
        i = argv.index("--storage")
        if i + 1 < len(argv):
            storage = Path(argv[i + 1])
    report = run_doctor(
        storage_hint=storage,
        workspace_hint=get_runtime().workspace,
    )
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
    print(f"init: workspace -> {summary['root']}")
    print(f"  name: {summary['name']}")
    if summary["created"]:
        print("  created:", ", ".join(summary["created"][:12]))
    if summary["skipped"]:
        print("  exists:", ", ".join(list(summary["skipped"])[:8]))
    print("  Tools still accept free --out / --out-dir; workspace is optional context.")
    return 0


def _cmd_skills(argv: list[str]) -> int:
    from tarrafa.core import skills as sk

    ap = argparse.ArgumentParser(
        prog="tarrafa skills",
        description=(
            "Instala a skill da Tarrafa nos hosts de IA desta máquina, "
            "com os caminhos já resolvidos."
        ),
    )
    ap.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "install", "show"],
        help="list: estado por host (padrão) · install: grava · show: imprime o conteúdo",
    )
    ap.add_argument(
        "--host",
        action="append",
        default=None,
        help="Limita a um host (claude, grok). Repetível. Padrão: todos os detectados",
    )
    ap.add_argument(
        "--dest",
        default=None,
        help="Pasta raiz de skills adicional (grava DEST/tarrafa/SKILL.md)",
    )
    ap.add_argument(
        "--shell",
        default="auto",
        choices=["auto", "powershell", "bash"],
        help="Sintaxe dos exemplos (padrão: auto, pelo sistema)",
    )
    ap.add_argument("--force", action="store_true", help="Sobrescreve arquivo editado à mão")
    ap.add_argument("--dry-run", action="store_true", help="Mostra o que faria, sem gravar")
    ap.add_argument("--all", action="store_true", help="Inclui hosts não detectados")
    args = ap.parse_args(argv)

    if args.action == "show":
        print(sk.render(shell=args.shell))
        return 0

    hosts = sk.detect_hosts()
    if args.host:
        wanted = {h.lower() for h in args.host}
        known = {h.key for h in hosts}
        unknown = wanted - known
        if unknown:
            print(
                f"error: host desconhecido: {', '.join(sorted(unknown))} "
                f"(conhecidos: {', '.join(sorted(known))})",
                file=sys.stderr,
            )
            return 2
        hosts = [h for h in hosts if h.key in wanted]

    if args.action == "list":
        print("Tarrafa skills\n")
        for row in sk.status(shell=args.shell):
            if row.get("state") == "error":
                print(f"  [ERRO] {row['detail']}")
                continue
            mark = {
                "current": "OK  ",
                "stale": "VELHA",
                "missing": "----",
                "manual": "MANUAL",
            }[row["state"]]
            seen = "detectado" if row["detected"] else "não detectado"
            print(f"  [{mark}] {row['label']} ({seen}): {row['path']}")
        print(f"\nBinário: {sk.resolve_bin()}")
        print("Instalar/atualizar: tarrafa skills install")
        return 0

    # --dest sozinho significa "só este destino"; combinar com --host/--all para somar.
    dest_only = bool(args.dest) and not args.host and not args.all
    targets = [] if dest_only else [h for h in hosts if h.detected or args.all]
    if args.dest:
        dest_root = Path(args.dest).expanduser().resolve()
        targets.append(
            sk.Host(
                key="dest",
                label="destino manual",
                root=dest_root,
                target=dest_root / sk.SKILL_DIRNAME / sk.SKILL_FILENAME,
            )
        )

    if not targets:
        print("Nenhum host de IA detectado nesta máquina.")
        print("Use --all para instalar mesmo assim, ou --dest DIR para uma pasta específica.")
        print("Hosts que leem o AGENTS.md do repo (Codex, entre outros) não precisam de instalação.")
        return 0

    results = sk.install(targets, shell=args.shell, force=args.force, dry_run=args.dry_run)
    prefix = "[dry-run] " if args.dry_run else ""
    for entry in results:
        print(f"  {prefix}{entry['action']:9} {entry['label']}: {entry['path']}")
        if entry.get("reason"):
            print(f"            {entry['reason']}")

    skipped = [e for e in results if e["action"] == "skipped"]
    changed = [e for e in results if e["action"] in ("created", "updated")]
    print()
    if args.dry_run:
        print(f"dry-run: {len(changed)} arquivo(s) seriam gravados.")
    else:
        print(f"{len(changed)} arquivo(s) gravados.")
    if changed and not args.dry_run:
        print("Reinicie a sessão do host para ele carregar a skill.")
    return 1 if skipped else 0


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
    _configure_stdio()
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
    from tarrafa.core.run import finish_run, start_run
    from tarrafa.core.runtime import Runtime, reset_runtime, set_runtime

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
        if tool == "skills":
            return _cmd_skills(rest)

        dispatch = {
            "ig": "tarrafa.tools.ig.scraper",
            "page": "tarrafa.tools.page.scraper",
            "site": "tarrafa.tools.site.scraper",
            "feed": "tarrafa.tools.feed.scraper",
            "search": "tarrafa.tools.search.scraper",
            "profile": "tarrafa.tools.profile.scraper",
            "shot": "tarrafa.tools.shot.scraper",
            "video": "tarrafa.tools.video.scraper",
            "album": "tarrafa.tools.album.scraper",
            "dossier": "tarrafa.tools.dossier.scraper",
            "cnpj": "tarrafa.tools.cnpj.scraper",
            "djen": "tarrafa.tools.djen.scraper",
            "datajud": "tarrafa.tools.datajud.scraper",
            "stj": "tarrafa.tools.stj.scraper",
            "pdf-extract": "tarrafa.tools.pdf_extract.scraper",
            "pdf_extract": "tarrafa.tools.pdf_extract.scraper",
            "order-risk": "tarrafa.tools.order_risk.scraper",
            "order_risk": "tarrafa.tools.order_risk.scraper",
            "verify": "tarrafa.tools.verify.scraper",
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
        except OSError as e:
            # Gravação recusada (destino travado, disco cheio): mensagem legível
            # em vez de traceback — o arquivo anterior segue intacto.
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
