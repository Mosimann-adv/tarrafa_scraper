# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from tarrafa.tools.dossier.scraper import (
    build_dossier,
    parse_meta,
    parse_shot_spec,
    parse_source_spec,
    parse_timeline_spec,
)


def test_parse_meta():
    assert parse_meta("Nome: Fulano") == ("Nome", "Fulano")
    assert parse_meta("só label") == ("só label", "")


def test_parse_shot_spec():
    s = parse_shot_spec("ig=shots/a.png::Perfil IG")
    assert s["id"] == "ig"
    assert s["path"] == "shots/a.png"
    assert s["caption"] == "Perfil IG"
    s2 = parse_shot_spec("only.png")
    assert s2["id"] == "only"
    assert s2["path"] == "only.png"


def test_parse_source_spec():
    s = parse_source_spec("Lattes | http://lattes.cnpq.br/1 | desatualizado")
    assert s["label"] == "Lattes"
    assert s["url"] == "http://lattes.cnpq.br/1"
    assert s["note"] == "desatualizado"
    s2 = parse_source_spec("IG: https://instagram.com/x")
    assert s2["label"] == "IG"
    assert s2["url"] == "https://instagram.com/x"


def test_parse_timeline_spec():
    t = parse_timeline_spec("2022 | Professor em X")
    assert t["when"] == "2022"
    assert "Professor" in t["text"]


def test_build_dossier_perfil_theme(tmp_path: Path):
    png = tmp_path / "face.png"
    png.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    shot = tmp_path / "page.png"
    shot.write_bytes(png.read_bytes())
    out = tmp_path / "ficha.html"
    env = build_dossier(
        title="Teste Pessoa",
        subtitle="Overview",
        out_html=out,
        avatar=png,
        meta=["Nome: Teste", "Cidade: X"],
        facts=["Formado em Y (fonte: Lattes)"],
        sources=[{"label": "Lattes", "url": "http://example.com", "note": "ok"}],
        shots=[{"id": "web", "path": str(shot), "caption": "Print web", "url": "https://example.com"}],
        timeline=[{"when": "2020", "text": "Início"}],
        gaps=["Sem telefone"],
        notes=["Fixture sintética para teste"],
        chips=["chip-a"],
        quote="Resumo curto.",
        embed=True,
        base_dir=tmp_path,
    )
    assert out.is_file()
    html = out.read_text(encoding="utf-8")
    assert "Teste Pessoa" in html
    assert "data:image/png;base64," in html
    assert "Sem telefone" in html
    assert "Fixture sintética para teste" in html
    assert "Formado em Y" in html
    assert "avatar-wrap" in html  # tema perfil (Custódio)
    assert "Síntese" in html or "sintese" in html
    assert "Fontes abertas" in html
    assert "Linha do tempo" in html
    assert env["tool"] == "dossier"
    assert env["items"][0]["shots"] == 1
    assert env["items"][0]["facts"] == 1


def test_build_dossier_manifest_sections(tmp_path: Path):
    out = tmp_path / "sec.html"
    manifest = {
        "title": "Fulano",
        "subtitle": "Advogado",
        "meta": ["Nome: Fulano"],
        "sections": [
            {
                "id": "atuacao",
                "title": "Atuação profissional",
                "rows": [["Cargo", "Advogado"], ["Cidade", "São Paulo/PR"]],
                "items": ["Área cível"],
            }
        ],
        "facts": ["OAB citada em fonte X"],
        "gaps": ["Sem Lattes"],
    }
    env = build_dossier(
        title="Fulano",
        out_html=out,
        embed=False,
        base_dir=tmp_path,
        manifest=manifest,
    )
    html = out.read_text(encoding="utf-8")
    assert "Atuação profissional" in html
    assert "Área cível" in html
    assert env["items"][0]["sections"] == 1
