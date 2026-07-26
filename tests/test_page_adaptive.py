# -*- coding: utf-8 -*-
"""Focused checks for page's HTTP -> browser decision, without a real browser."""
from __future__ import annotations

from typing import Any

from tarrafa.tools.page import scraper


def _article(text_main: str, *, facts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "text_main": text_main,
        "text": text_main,
        "text_len": len(text_main),
        "text_main_len": len(text_main),
        "links_count": 0,
        "structured_facts": facts or [],
        "enrich_notes": [],
        "author": None,
    }


def test_auto_renders_spa_once_and_selects_materially_better_browser(monkeypatch):
    calls = 0

    monkeypatch.setattr(
        scraper,
        "fetch_url",
        lambda *_args, **_kwargs: {
            "error": None,
            "text": '<div id="root"></div>',
            "final_url": "https://example.test/page",
            "status": 200,
        },
    )

    def fake_browser(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "error": None,
            "text": "browser-html",
            "visible_text": "Rendered page",
            "final_url": "https://example.test/page",
            "status": 200,
        }

    monkeypatch.setattr(scraper, "_fetch_browser", fake_browser)
    monkeypatch.setattr(
        scraper,
        "extract_article",
        lambda html, *_args, **_kwargs: _article(
            "Rendered content " * 20 if html == "browser-html" else "shell"
        ),
    )

    result = scraper.capture_page("https://example.test/page")

    assert calls == 1
    assert result["meta"]["browser_reason"] == ["spa_shell"]
    assert result["meta"]["browser_decision"] == "selected_browser"
    assert result["meta"]["final_choice"] == "browser"
    assert result["items"][0]["text_main"].startswith("Rendered content")


def test_auto_keeps_better_http_capture_when_browser_is_worse(monkeypatch):
    http_html = "x" * 1000
    monkeypatch.setattr(
        scraper,
        "fetch_url",
        lambda *_args, **_kwargs: {
            "error": None,
            "text": http_html,
            "final_url": "https://example.test/page",
            "status": 200,
        },
    )
    monkeypatch.setattr(
        scraper,
        "_fetch_browser",
        lambda *_args, **_kwargs: {
            "error": None,
            "text": "browser-html",
            "visible_text": "",
            "final_url": "https://example.test/page",
            "status": 200,
        },
    )
    monkeypatch.setattr(
        scraper,
        "extract_article",
        lambda html, *_args, **_kwargs: _article("short" if html == http_html else "worse"),
    )

    result = scraper.capture_page("https://example.test/page")

    assert result["meta"]["browser_reason"] == ["thin_http_extract"]
    assert result["meta"]["browser_decision"] == "kept_http_better"
    assert result["meta"]["final_choice"] == "http"
    assert result["items"][0]["text_main"] == "short"


def test_http_mode_never_launches_browser(monkeypatch):
    monkeypatch.setattr(
        scraper,
        "fetch_url",
        lambda *_args, **_kwargs: {
            "error": None,
            "text": "http-html",
            "final_url": "https://example.test/page",
            "status": 200,
        },
    )
    monkeypatch.setattr(scraper, "extract_article", lambda *_args, **_kwargs: _article("HTTP content"))
    monkeypatch.setattr(
        scraper,
        "_fetch_browser",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("browser must not run")),
    )

    result = scraper.capture_page("https://example.test/page", mode="http")

    assert result["meta"]["browser_decision"] == "disabled_http_mode"
    assert result["meta"]["final_choice"] == "http"
