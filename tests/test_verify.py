# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from tarrafa.core.media import file_sha256
from tarrafa.tools.verify.scraper import main as verify_main
from tarrafa.tools.verify.scraper import verify_artifact, verify_manifests


def _capture(workspace: Path, name: str = "prova.txt", body: str = "conteudo") -> Path:
    """Simula uma captura: grava o arquivo e o manifesto que registra seu hash."""
    artifact = workspace / "raw" / name
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(body, encoding="utf-8")

    runs_dir = workspace / "meta" / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    manifest = runs_dir / f"20260731T000000Z-page-{name}.json"
    manifest.write_text(
        json.dumps(
            {
                "run_id": f"20260731T000000Z-page-{name}",
                "tool": "page",
                "version": "0.4.0",
                "started_at": "2026-07-31T00:00:00.000Z",
                "finished_at": "2026-07-31T00:00:01.000Z",
                "exit_code": 0,
                "argv": ["page", "--url", "https://example.com"],
                "workspace": str(workspace),
                "artifacts": [
                    {
                        "path": str(artifact),
                        "exists": True,
                        "bytes": len(body.encode()),
                        "sha256": file_sha256(artifact),
                        "kind": "text",
                    }
                ],
                "notes": [],
                "meta": {},
            }
        ),
        encoding="utf-8",
    )
    return artifact


def test_intact_artifact_passes(tmp_path: Path):
    _capture(tmp_path)
    result = verify_manifests(
        sorted((tmp_path / "meta" / "runs").glob("*.json")), current_workspace=tmp_path
    )
    assert result["summary"]["intact"] is True
    assert result["summary"]["counts"]["ok"] == 1
    assert verify_main(["--workspace", str(tmp_path)]) == 0


def test_modified_artifact_is_caught(tmp_path: Path):
    artifact = _capture(tmp_path)
    artifact.write_text("conteudo adulterado", encoding="utf-8")

    result = verify_manifests(
        sorted((tmp_path / "meta" / "runs").glob("*.json")), current_workspace=tmp_path
    )
    assert result["summary"]["intact"] is False
    item = result["items"][0]
    assert item["status"] == "modified"
    assert item["sha256_now"] != item["sha256_recorded"]
    # Divergência precisa ser visível para quem chama por script.
    assert verify_main(["--workspace", str(tmp_path)]) == 1


def test_missing_artifact_is_caught(tmp_path: Path):
    artifact = _capture(tmp_path)
    artifact.unlink()

    result = verify_manifests(
        sorted((tmp_path / "meta" / "runs").glob("*.json")), current_workspace=tmp_path
    )
    assert result["items"][0]["status"] == "missing"
    assert verify_main(["--workspace", str(tmp_path)]) == 1


def test_moved_case_folder_is_not_reported_as_loss(tmp_path: Path):
    """Pasta de caso movida (OneDrive, outra máquina) não é perda de material."""
    original = tmp_path / "caso"
    original.mkdir()
    _capture(original)

    moved = tmp_path / "caso_movido"
    original.rename(moved)

    result = verify_manifests(
        sorted((moved / "meta" / "runs").glob("*.json")), current_workspace=moved
    )
    item = result["items"][0]
    assert item["status"] == "ok"
    assert item["relocated_to"] == str(moved / "raw" / "prova.txt")
    assert verify_main(["--workspace", str(moved)]) == 0


def test_moved_folder_still_catches_tampering(tmp_path: Path):
    """Relocar não pode virar desculpa para deixar passar arquivo alterado."""
    original = tmp_path / "caso"
    original.mkdir()
    _capture(original)
    moved = tmp_path / "caso_movido"
    original.rename(moved)
    (moved / "raw" / "prova.txt").write_text("adulterado", encoding="utf-8")

    result = verify_manifests(
        sorted((moved / "meta" / "runs").glob("*.json")), current_workspace=moved
    )
    assert result["items"][0]["status"] == "modified"


def test_no_manifests_returns_zero_items_code(tmp_path: Path):
    (tmp_path / "meta" / "runs").mkdir(parents=True)
    assert verify_main(["--workspace", str(tmp_path)]) == 6


def test_without_workspace_is_bad_args(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert verify_main([]) == 2


def test_broken_manifest_is_reported_not_ignored(tmp_path: Path):
    runs_dir = tmp_path / "meta" / "runs"
    runs_dir.mkdir(parents=True)
    (runs_dir / "quebrado.json").write_text("{nao é json", encoding="utf-8")

    result = verify_manifests([runs_dir / "quebrado.json"], current_workspace=tmp_path)
    assert result["errors"]
    assert verify_main(["--workspace", str(tmp_path)]) == 1


def test_out_writes_envelope(tmp_path: Path):
    _capture(tmp_path)
    out = tmp_path / "verificacao.json"
    assert verify_main(["--workspace", str(tmp_path), "--out", str(out)]) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["tool"] == "verify"
    assert envelope["meta"]["intact"] is True
    assert envelope["items"][0]["kind"] == "verify_summary"
    assert any("não é assinatura digital" in n for n in envelope["notes"])


def test_artifact_without_recorded_hash_is_not_a_pass(tmp_path: Path):
    """Sem hash gravado não há o que conferir — não pode contar como íntegro."""
    target = tmp_path / "pasta"
    target.mkdir()
    item = verify_artifact({"path": str(target), "exists": True})
    assert item["status"] == "no_hash"

    f = tmp_path / "sem_hash.txt"
    f.write_text("x", encoding="utf-8")
    assert verify_artifact({"path": str(f), "exists": True})["status"] == "no_hash"
