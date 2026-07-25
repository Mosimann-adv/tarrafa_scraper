# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import normalize_link, same_registrable_host
from tarrafa.core.writers import utc_now_iso, write_json, write_jsonl
from tarrafa.core.extract import extract_article
from tarrafa.core.crawl import _canon


def test_utc_now_iso_format():
    s = utc_now_iso()
    assert s.endswith("Z")
    assert "T" in s


def test_build_envelope_count():
    env = build_envelope("page", source="https://example.com", items=[{"a": 1}, {"b": 2}])
    assert env["tool"] == "page"
    assert env["count"] == 2
    assert env["source"]["url"] == "https://example.com"
    assert "version" in env
    assert "collected_at" in env


def test_write_json_roundtrip(tmp_path: Path):
    p = tmp_path / "out.json"
    payload = {"hello": "世界", "n": 1}
    write_json(p, payload)
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["hello"] == "世界"
    assert data["n"] == 1


def test_write_jsonl(tmp_path: Path):
    p = tmp_path / "rows.jsonl"
    write_jsonl(p, [{"a": 1}, {"b": 2}])
    lines = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_same_host():
    assert same_registrable_host("https://www.example.com/a", "https://example.com/b")
    assert not same_registrable_host("https://a.com", "https://b.com")


def test_normalize_link():
    assert normalize_link("https://ex.com/x/", "/y") == "https://ex.com/y"
    assert normalize_link("https://ex.com", "javascript:void(0)") is None
    assert normalize_link("https://ex.com", "#frag") is None


def test_extract_article_basic():
    html = """
    <html><head><title>Hello Title</title></head>
    <body><h1>Hello</h1><p>This is a long enough paragraph about legal evidence capture for testing.</p>
    <a href="/next">Next</a></body></html>
    """
    art = extract_article(html, "https://example.com/page")
    assert art["title"] == "Hello Title" or art["title"]  # trafilatura may refine
    assert art["links_count"] >= 1
    assert any("example.com" in u for u in art["links"])


def test_extract_structured_facts_change_org_like():
    """UI chrome (counter + creator) lives in meta/JSON-LD/JSON — not in article body."""
    html = """
    <html><head>
      <title>Petition</title>
      <meta property="og:title" content="419 pessoas assinaram e ajudaram esta petição a conseguir vitória" />
      <script type="application/ld+json">
      {"@context":"https://schema.org","@graph":[
        {"@type":"Article","headline":"Exigir retirada"},
        {"@type":"Person","name":"Julia Neves","url":"https://www.change.org/u/1"}
      ]}
      </script>
    </head>
    <body>
      <p>O Outdoor está localizado em uma área escolar, em frente a uma pista de Skate Pública.</p>
      <script>
        window.__STATE__ = {"petition":{"id":"491419761","user":{"displayName":"Julia Neves"},
        "signatureCount":{"displayed":419,"total":419,"goal":500}}};
      </script>
    </body></html>
    """
    art = extract_article(html, "https://www.change.org/p/example", enrich=True)
    kinds = {f["kind"]: f["value"] for f in art["structured_facts"]}
    assert kinds.get("signature_count") == 419
    assert "Julia Neves" in str(kinds.get("person") or kinds.get("display_name") or "")
    # Enriched text must carry facts even when trafilatura body omits them
    assert "419" in (art["text"] or "")
    assert "Julia Neves" in (art["text"] or "")
    assert art.get("author") == "Julia Neves"
    assert "og:title" in (art.get("meta_tags") or {})


def test_canon_strips_fragment():
    assert "#" not in _canon("https://example.com/a#x")
