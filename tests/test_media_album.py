# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path

from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import id_from_url, slugify
from tarrafa.core.writers import write_json
from tarrafa.templates.album_html import render_album
from tarrafa.tools.album.scraper import build_album, collect_items_from_dir


def test_slugify():
    assert "hello_world" in slugify("Hello World!!")


def test_id_from_url():
    assert id_from_url("https://example.com/foo/bar-baz") == "bar_baz"


def test_render_album_contains_title_and_print():
    html = render_album(
        title="Álbum teste",
        kicker="Inventário visual",
        meta_lines=["Itens: 1"],
        items=[
            {
                "id": "EX01",
                "caption": "Exemplo",
                "url": "https://example.com",
                "collected_at": "2026-01-01T00:00:00Z",
                "image": "ex.png",
                "kind": "shot",
            }
        ],
    )
    assert "Álbum teste" in html
    assert "Imprimir / PDF" in html
    assert "EX01" in html
    assert 'class="sheet"' in html


def test_album_from_dir_embed(tmp_path: Path):
    # minimal shot envelope + fake png
    png = tmp_path / "EX01.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
    env = build_envelope(
        "shot",
        source="https://example.com",
        items=[
            {
                "id": "EX01",
                "kind": "shot",
                "image": "EX01.png",
                "caption": "Example page",
                "url": "https://example.com",
                "collected_at": "2026-07-25T00:00:00Z",
            }
        ],
    )
    write_json(tmp_path / "EX01.json", env)
    items = collect_items_from_dir(tmp_path)
    assert len(items) == 1
    assert items[0]["id"] == "EX01"

    out = tmp_path / "album.html"
    index = build_album(
        directory=tmp_path,
        out_html=out,
        title="Test album",
        kicker="Kicker",
        meta_lines=["Interessada: X"],
        embed=True,
    )
    assert out.is_file()
    assert index["count"] == 1
    assert index["embed"] is True
    text = out.read_text(encoding="utf-8")
    assert "Test album" in text
    assert "data:image/png;base64," in text
    # index must not carry huge data URIs
    assert "image_src" not in json.dumps(index["items"])


def test_album_no_embed(tmp_path: Path):
    png = tmp_path / "EX01.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    env = build_envelope(
        "shot",
        source="https://example.com",
        items=[{"id": "EX01", "kind": "shot", "image": "EX01.png", "caption": "c"}],
    )
    write_json(tmp_path / "EX01.json", env)
    out = tmp_path / "album.html"
    index = build_album(directory=tmp_path, out_html=out, embed=False)
    text = out.read_text(encoding="utf-8")
    assert index["embed"] is False
    assert 'src="EX01.png"' in text
    assert "data:image" not in text
