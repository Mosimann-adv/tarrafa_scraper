# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path

from tarrafa.core import env as envmod


def test_parse_dotenv_basic():
    text = """
# comment
FOO=bar
export BAZ=qux
QUOTED="hello world"
EMPTY=
"""
    d = envmod.parse_dotenv(text)
    assert d["FOO"] == "bar"
    assert d["BAZ"] == "qux"
    assert d["QUOTED"] == "hello world"
    assert d["EMPTY"] == ""


def test_load_dotenv_file_no_override(tmp_path: Path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("ALPHA=fromfile\nBETA=fileonly\n", encoding="utf-8")
    monkeypatch.setenv("ALPHA", "fromprocess")
    monkeypatch.delenv("BETA", raising=False)
    applied = envmod.load_dotenv_file(p, override=False)
    assert os.environ["ALPHA"] == "fromprocess"
    assert "BETA" in applied
    assert os.environ["BETA"] == "fileonly"


def test_write_env_key_upsert(tmp_path: Path):
    p = tmp_path / ".env"
    p.write_text("A=1\nB=2\n", encoding="utf-8")
    envmod.write_env_key(p, "B", "9")
    envmod.write_env_key(p, "C", "3", comment_lines=["new key"])
    text = p.read_text(encoding="utf-8")
    assert "B=9" in text
    assert "A=1" in text
    assert "C=3" in text


def test_mask_secret():
    assert envmod.mask_secret(None) == "(absent)"
    # synthetic token-shaped string only (not a real secret)
    assert "…" in envmod.mask_secret("dummy_token_abcdefghijklmnopqr")
    assert len(envmod.secret_fingerprint("dummy_token_abcdefghijklmnopqr") or "") == 12


def test_playwright_token_helper(monkeypatch):
    monkeypatch.setenv(envmod.PLAYWRIGHT_MCP_EXTENSION_TOKEN, "tok123456789")
    envmod._LOADED = True  # skip file reload path noise
    assert envmod.playwright_extension_token() == "tok123456789"


def test_token_status_detects_conflicting_files_without_exposing_values(
    tmp_path: Path,
    monkeypatch,
):
    first = tmp_path / "user.env"
    second = tmp_path / "project.env"
    first.write_text("PLAYWRIGHT_MCP_EXTENSION_TOKEN=synthetic_token_alpha\n", encoding="utf-8")
    second.write_text("PLAYWRIGHT_MCP_EXTENSION_TOKEN=synthetic_token_beta\n", encoding="utf-8")
    monkeypatch.setattr(envmod, "env_file_candidates", lambda: [first, second])
    monkeypatch.setenv(
        envmod.PLAYWRIGHT_MCP_EXTENSION_TOKEN,
        "synthetic_token_alpha",
    )
    envmod._LOADED = True

    status = envmod.token_status()

    assert status["conflicting_sources"] is True
    assert status["active_matches_file"] is True
    assert "synthetic_token_alpha" not in repr(status)
    assert "synthetic_token_beta" not in repr(status)
