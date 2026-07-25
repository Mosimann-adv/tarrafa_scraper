# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tarrafa.cli import main as cli_main


def test_cli_version(capsys):
    assert cli_main(["version"]) == 0
    out = capsys.readouterr().out
    assert "tarrafa" in out


def test_cli_list(capsys):
    assert cli_main(["list"]) == 0
    out = capsys.readouterr().out
    for name in ("ig", "page", "site", "feed", "shot", "video", "album", "doctor"):
        assert name in out


def test_cli_unknown():
    assert cli_main(["nope"]) == 2


def test_page_http_example(tmp_path: Path):
    out = tmp_path / "page.json"
    code = cli_main(
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
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tool"] == "page"
    assert data["count"] == 1
    assert data["items"][0].get("text_len", 0) > 0 or data["items"][0].get("title")


def test_site_example_shallow(tmp_path: Path):
    out = tmp_path / "site.json"
    code = cli_main(
        [
            "site",
            "--url",
            "https://example.com",
            "--out",
            str(out),
            "--max-pages",
            "2",
            "--max-depth",
            "0",
        ]
    )
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tool"] == "site"
    assert data["count"] >= 1


def test_feed_bbc_world(tmp_path: Path):
    """Public RSS; skip if network blocked."""
    out = tmp_path / "feed.json"
    code = cli_main(
        [
            "feed",
            "--url",
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "--out",
            str(out),
            "--max-entries",
            "3",
        ]
    )
    if code == 6:
        pytest.skip("feed unreachable or empty")
    assert code == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["tool"] == "feed"
    assert data["count"] >= 1
    assert data["items"][0].get("title") or data["items"][0].get("link")


def test_doctor_runs():
    # may fail if deps missing; after install should pass required checks
    code = cli_main(["doctor"])
    assert code in (0, 1)


def test_ig_help(capsys):
    # CLI catches argparse SystemExit and returns the code
    code = cli_main(["ig", "--help"])
    assert code == 0
    out = capsys.readouterr().out.lower()
    assert "url" in out or "instagram" in out


def test_shot_and_album_example(tmp_path: Path):
    shots = tmp_path / "shots"
    code = cli_main(
        [
            "shot",
            "--url",
            "https://example.com",
            "--out-dir",
            str(shots),
            "--id",
            "EX01",
            "--dpr",
            "1",
            "--clip",
            "main",
            "--wait-ms",
            "500",
        ]
    )
    assert code == 0
    assert (shots / "EX01.png").is_file()
    assert (shots / "EX01.json").is_file()
    data = json.loads((shots / "EX01.json").read_text(encoding="utf-8"))
    assert data["tool"] == "shot"
    assert data["count"] == 1
    assert (data.get("meta") or {}).get("clip") == "main"

    html = tmp_path / "album.html"
    code2 = cli_main(
        [
            "album",
            "--dir",
            str(shots),
            "--out",
            str(html),
            "--title",
            "Album EX",
            "--kicker",
            "Inventario visual",
            "--meta",
            "Itens: 1",
        ]
    )
    assert code2 == 0
    text = html.read_text(encoding="utf-8")
    assert "Album EX" in text
    assert "EX01" in text
