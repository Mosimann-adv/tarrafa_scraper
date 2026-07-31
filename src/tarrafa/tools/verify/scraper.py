# -*- coding: utf-8 -*-
"""
tarrafa verify — reconfere a integridade do material já capturado.

Cada execução da Tarrafa grava um manifesto em `meta/runs/<run_id>.json` com o
SHA-256 de cada artefato no momento da captura. Este comando lê esses manifestos
e recalcula os hashes hoje, respondendo se os arquivos continuam idênticos.

Não é assinatura digital nem carimbo de tempo: prova que o arquivo não mudou
desde a captura registrada, não que a captura em si é autêntica.

  tarrafa verify --workspace ./caso
  tarrafa verify --run ./caso/meta/runs/20260731T000000Z-shot-abcd1234.json
  tarrafa verify --workspace ./caso --out ./caso/meta/verificacao.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import file_sha256
from tarrafa.core.writers import write_json

# Divergências que significam "o material não está como foi capturado".
BROKEN_STATUSES = ("modified", "missing", "unreadable")

STATUS_LABEL = {
    "ok": "OK",
    "modified": "MODIFICADO",
    "missing": "AUSENTE",
    "unreadable": "ILEGÍVEL",
    "no_hash": "SEM HASH",
}


class ManifestError(ValueError):
    """Manifesto de execução ilegível ou fora do formato."""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError) as exc:
        raise ManifestError(f"não foi possível ler ({type(exc).__name__})") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"JSON inválido: {exc.msg} (linha {exc.lineno})") from exc
    if not isinstance(payload, dict):
        raise ManifestError("o manifesto deve conter um objeto JSON no topo")
    if "artifacts" not in payload:
        raise ManifestError("sem a chave 'artifacts': não parece um manifesto de execução")
    return payload


def find_manifests(runs_dir: Path) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    return sorted(p for p in runs_dir.glob("*.json") if p.is_file())


def relocate_path(
    recorded: str,
    *,
    recorded_workspace: str | None,
    current_workspace: Path | None,
) -> Path | None:
    """Reencontra um artefato quando a pasta do caso mudou de lugar.

    O manifesto grava caminho absoluto. Pasta de caso movida, sincronizada por
    OneDrive ou aberta em outra máquina muda o caminho sem mudar o conteúdo —
    o material continua íntegro e a conferência não pode acusar ausência por isso.
    """
    if not (recorded_workspace and current_workspace):
        return None
    try:
        relative = Path(recorded).relative_to(Path(recorded_workspace))
    except ValueError:
        return None
    candidate = current_workspace / relative
    return candidate if candidate.exists() else None


def verify_artifact(
    artifact: dict[str, Any],
    *,
    recorded_workspace: str | None = None,
    current_workspace: Path | None = None,
) -> dict[str, Any]:
    """Compara o SHA-256 gravado na captura com o do arquivo hoje."""
    recorded_path = str(artifact.get("path") or "")
    recorded_sha = artifact.get("sha256")
    result: dict[str, Any] = {
        "kind": "verify_artifact",
        "path": recorded_path,
        "artifact_kind": artifact.get("kind"),
        "sha256_recorded": recorded_sha,
        "sha256_now": None,
        "bytes_recorded": artifact.get("bytes"),
        "bytes_now": None,
        "relocated_to": None,
        "status": "missing",
        "detail": "",
    }
    if not recorded_path:
        result["status"] = "unreadable"
        result["detail"] = "manifesto sem caminho de artefato"
        return result

    target = Path(recorded_path)
    if not target.exists():
        moved = relocate_path(
            recorded_path,
            recorded_workspace=recorded_workspace,
            current_workspace=current_workspace,
        )
        if moved is None:
            result["detail"] = "arquivo não encontrado no caminho registrado"
            return result
        target = moved
        result["relocated_to"] = str(moved)

    if target.is_dir():
        result["status"] = "no_hash"
        result["detail"] = "pasta: sem hash a conferir"
        return result

    if recorded_sha is None:
        result["status"] = "no_hash"
        result["detail"] = "captura não registrou hash para este artefato"
        return result

    try:
        result["sha256_now"] = file_sha256(target)
        result["bytes_now"] = target.stat().st_size
    except OSError as exc:
        result["status"] = "unreadable"
        result["detail"] = f"não foi possível ler o arquivo ({type(exc).__name__})"
        return result

    if result["sha256_now"] == recorded_sha:
        result["status"] = "ok"
        result["detail"] = "idêntico ao capturado"
    else:
        result["status"] = "modified"
        result["detail"] = "conteúdo diferente do capturado"
    return result


def verify_manifests(
    manifest_paths: list[Path],
    *,
    current_workspace: Path | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    runs: list[dict[str, Any]] = []

    for manifest_path in manifest_paths:
        try:
            payload = load_manifest(manifest_path)
        except ManifestError as exc:
            errors.append(f"{manifest_path}: {exc}")
            continue

        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append(f"{manifest_path}: 'artifacts' não é uma lista")
            continue

        recorded_workspace = payload.get("workspace")
        run_items = [
            {
                **verify_artifact(
                    artifact,
                    recorded_workspace=recorded_workspace,
                    current_workspace=current_workspace,
                ),
                "run_id": payload.get("run_id"),
                "tool": payload.get("tool"),
                "captured_at": payload.get("finished_at") or payload.get("started_at"),
                "manifest": str(manifest_path),
            }
            for artifact in artifacts
            if isinstance(artifact, dict)
        ]
        items.extend(run_items)
        runs.append(
            {
                "run_id": payload.get("run_id"),
                "tool": payload.get("tool"),
                "captured_at": payload.get("finished_at") or payload.get("started_at"),
                "tarrafa_version": payload.get("version"),
                "manifest": str(manifest_path),
                "artifacts": len(run_items),
            }
        )

    counts = {status: 0 for status in STATUS_LABEL}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1

    return {
        "items": items,
        "runs": runs,
        "errors": errors,
        "summary": {
            "kind": "verify_summary",
            "manifests": len(manifest_paths),
            "runs_read": len(runs),
            "artifacts": len(items),
            "counts": counts,
            "intact": all(item["status"] not in BROKEN_STATUSES for item in items),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa verify",
        description=(
            "Reconfere o SHA-256 dos artefatos gravados nos manifestos de execução. "
            "Responde se o material continua idêntico ao capturado."
        ),
    )
    ap.add_argument(
        "--workspace",
        default=None,
        help="Raiz do caso (padrão: workspace resolvido pelas flags globais)",
    )
    ap.add_argument(
        "--runs-dir",
        default=None,
        help="Pasta de manifestos (padrão: <workspace>/meta/runs)",
    )
    ap.add_argument(
        "--run",
        action="append",
        default=None,
        metavar="PATH",
        help="Manifesto específico. Repetível; ignora --runs-dir",
    )
    ap.add_argument("--out", default=None, help="Grava envelope JSON com o resultado")
    ap.add_argument(
        "--quiet-ok",
        action="store_true",
        help="Lista só as divergências (omite os artefatos íntegros)",
    )
    return ap


def _resolve_sources(args: argparse.Namespace) -> tuple[list[Path], Path | None, str | None]:
    """Retorna (manifestos, workspace, erro)."""
    from tarrafa.core.runtime import get_runtime

    if args.run:
        paths = [Path(p).expanduser().resolve() for p in args.run]
        missing = [str(p) for p in paths if not p.is_file()]
        if missing:
            return [], None, f"manifesto não encontrado: {', '.join(missing)}"
        return paths, None, None

    workspace = (
        Path(args.workspace).expanduser().resolve()
        if args.workspace
        else get_runtime().workspace
    )
    if args.runs_dir:
        runs_dir = Path(args.runs_dir).expanduser().resolve()
    elif workspace is not None:
        runs_dir = workspace / "meta" / "runs"
    else:
        return [], None, (
            "sem workspace: rode dentro da pasta do caso, ou use --workspace DIR, "
            "--runs-dir DIR ou --run ARQUIVO"
        )
    return find_manifests(runs_dir), workspace, None


def _print_report(result: dict[str, Any], *, quiet_ok: bool) -> None:
    summary = result["summary"]
    counts = summary["counts"]
    print(
        f"verify: {summary['runs_read']} execução(ões) · {summary['artifacts']} artefato(s)"
    )
    for status, label in STATUS_LABEL.items():
        if counts.get(status):
            print(f"  {label:11} {counts[status]}")

    for item in result["items"]:
        if quiet_ok and item["status"] == "ok":
            continue
        label = STATUS_LABEL.get(item["status"], item["status"])
        print(f"  [{label}] {item['path']}")
        if item["status"] != "ok":
            print(f"            {item['detail']}")
        if item.get("relocated_to"):
            print(f"            conferido em: {item['relocated_to']} (pasta movida)")
        if item["status"] == "modified":
            print(f"            capturado: {(item['sha256_recorded'] or '')[:16]}…")
            print(f"            agora:     {(item['sha256_now'] or '')[:16]}…")

    for err in result["errors"]:
        print(f"  [ERRO] {err}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    manifests, workspace, error = _resolve_sources(args)
    if error:
        print(f"verify: {error}", file=sys.stderr)
        return 2

    if not manifests:
        print(
            "verify: nenhum manifesto encontrado — a captura só grava manifesto "
            "quando roda dentro de um workspace (tarrafa init)",
            file=sys.stderr,
        )
        return 6

    result = verify_manifests(manifests, current_workspace=workspace)
    _print_report(result, quiet_ok=args.quiet_ok)

    if args.out:
        envelope = build_envelope(
            "verify",
            source={
                "workspace": str(workspace) if workspace else None,
                "manifests": [str(p) for p in manifests],
            },
            items=[result["summary"], *result["items"]],
            meta={
                "runs": result["runs"],
                "counts": result["summary"]["counts"],
                "intact": result["summary"]["intact"],
            },
            errors=result["errors"],
            notes=[
                "Compara o SHA-256 atual com o gravado no manifesto da captura.",
                "Prova que o arquivo não mudou desde a captura registrada — não é "
                "assinatura digital nem carimbo de tempo, e não atesta a autenticidade "
                "da fonte capturada.",
                "Artefato ausente pode ser arquivo movido: confira antes de tratar "
                "como perda.",
            ],
        )
        out_path = write_json(Path(args.out), envelope)
        print(f"verify: wrote {out_path}")

    broken = sum(result["summary"]["counts"].get(s, 0) for s in BROKEN_STATUSES)
    if result["errors"] or broken:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
