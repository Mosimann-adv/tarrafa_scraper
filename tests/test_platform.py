# -*- coding: utf-8 -*-
"""Platform: workspace, config, run manifest, global flags, batch page."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarrafa.cli import main as cli_main
from tarrafa.core.config import load_config
from tarrafa.core.run import finish_run, sanitize_argv, start_run
from tarrafa.core.workspace import init_workspace


def test_init_workspace(tmp_path: Path):
    root = tmp_path / "caso"
    summary = init_workspace(root, name="Caso Teste", notes="unit")
    assert Path(summary["toml"]).is_file()
    assert (root / "raw").is_dir()
    assert (root / "shots").is_dir()
    assert (root / "html").is_dir()
    assert (root / "logs").is_dir()
    assert (root / "meta" / "runs").is_dir()
    text = (root / "tarrafa.toml").read_text(encoding="utf-8")
    assert "Caso Teste" in text
    assert 'raw = "raw"' in text


def test_cli_init(tmp_path: Path, capsys):
    root = tmp_path / "ws"
    assert cli_main(["init", str(root), "--name", "Demo"]) == 0
    out = capsys.readouterr().out
    assert "workspace" in out.lower() or "init" in out
    assert (root / "tarrafa.toml").is_file()


def test_load_config_workspace(tmp_path: Path):
    init_workspace(tmp_path, name="Cfg")
    cfg = load_config(workspace=tmp_path)
    assert cfg.workspace == tmp_path.resolve()
    assert cfg.case_name == "Cfg"
    assert cfg.path("raw") == (tmp_path / "raw").resolve()


def test_sanitize_argv_redacts_sensitive_options():
    out = sanitize_argv(
        [
            "--storage-state",
            "secret.json",
            "--api-key=super-secret-key",
            "--authorization",
            "Bearer synthetic",
            "--url",
            "https://x",
            "--query",
            '"Pessoa Exemplo"',
            "--queries-file=consultas.txt",
        ]
    )
    assert out == [
        "--storage-state",
        "***",
        "--api-key=***",
        "--authorization",
        "***",
        "--url",
        "https://x",
        "--query",
        "***",
        "--queries-file=***",
    ]


def test_run_manifest_records_artifact(tmp_path: Path):
    init_workspace(tmp_path, name="Run")
    session = start_run("page", ["--url", "https://example.com", "--out", "x.json"], workspace=tmp_path)
    art = tmp_path / "raw" / "sample.json"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text('{"ok": true}\n', encoding="utf-8")
    session.add_artifact(art, kind="json")
    path = finish_run(session, 0, record=True)
    assert path is not None and path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tool"] == "page"
    assert data["exit_code"] == 0
    assert data["run_id"]
    assert data["artifacts"]
    assert data["artifacts"][0]["sha256"]


@pytest.mark.integration
def test_cli_page_records_run_in_workspace(tmp_path: Path):
    ws = tmp_path / "caso"
    assert cli_main(["init", str(ws), "--name", "Net"]) == 0
    out = ws / "raw" / "page.json"
    code = cli_main(
        [
            "--workspace",
            str(ws),
            "page",
            "--url",
            "https://example.com",
            "--out",
            str(out),
            "--mode",
            "http",
        ]
    )
    assert code == 0
    assert out.is_file()
    runs = list((ws / "meta" / "runs").glob("*.json"))
    assert len(runs) >= 1
    payload = json.loads(runs[-1].read_text(encoding="utf-8"))
    assert payload["tool"] == "page"
    assert payload["exit_code"] == 0
    # artifact path registered via write_json
    paths = [a.get("path", "") for a in payload.get("artifacts") or []]
    assert any(str(out.resolve()) in p or p.endswith("page.json") for p in paths)


@pytest.mark.integration
def test_page_batch_urls_file(tmp_path: Path):
    urls = tmp_path / "urls.txt"
    urls.write_text(
        "# comment\nhttps://example.com\nhttps://example.com\nhttps://example.org\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "pages"
    code = cli_main(
        [
            "page",
            "--urls-file",
            str(urls),
            "--out",
            str(out_dir),
            "--mode",
            "http",
        ]
    )
    assert code == 0
    files = list(out_dir.glob("*.json"))
    # de-dupe example.com → 2 urls
    assert len(files) == 2


@pytest.mark.integration
def test_no_clobber_refuses_overwrite(tmp_path: Path):
    out = tmp_path / "once.json"
    assert (
        cli_main(
            [
                "page",
                "--url",
                "https://example.com",
                "--out",
                str(out),
                "--mode",
                "http",
            ]
        )
        == 0
    )
    code = cli_main(
        [
            "--no-clobber",
            "page",
            "--url",
            "https://example.com",
            "--out",
            str(out),
            "--mode",
            "http",
        ]
    )
    assert code == 2


def test_list_includes_init(capsys):
    assert cli_main(["list"]) == 0
    output = capsys.readouterr().out
    assert "init" in output
    assert "search" in output
