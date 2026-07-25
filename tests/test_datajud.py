# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tarrafa.tools.datajud.scraper import (
    digits_cnj,
    format_cnj,
    infer_tribunal_alias,
    main,
    parse_cnj_parts,
    summarize_hit,
)


def test_cnj_parse_and_infer():
    cnj = "0001111-22.2024.4.03.6100"
    assert digits_cnj(cnj) == "00011112220244036100"
    assert format_cnj(digits_cnj(cnj)).startswith("0001111-22")
    parts = parse_cnj_parts(cnj)
    assert parts is not None
    assert parts["justice"] == 4
    assert infer_tribunal_alias(cnj) == "trf3"
    assert infer_tribunal_alias("0001234-56.2024.8.26.0100") == "tjsp"


def test_summarize_hit():
    src = {
        "id": "x",
        "tribunal": "TRF3",
        "grau": "G1",
        "numeroProcesso": "00011112220244036100",
        "classe": {"codigo": 1, "nome": "PROCEDIMENTO DO JEC"},
        "orgaoJulgador": {"nome": "1ª VF"},
        "assuntos": [{"codigo": 1, "nome": "Assunto exemplo"}],
        "movimentos": [{"codigo": 26, "nome": "Distribuição", "dataHora": "2026-01-01T00:00:00Z"}],
        "sistema": {"nome": "Eproc"},
        "formato": {"nome": "Eletrônico"},
    }
    s = summarize_hit(src, tribunal_alias="trf3")
    assert s["tribunal_alias"] == "trf3"
    assert s["movimentos_count"] == 1
    assert s["classe"] == "PROCEDIMENTO DO JEC"


def test_main_mock(tmp_path: Path):
    out = tmp_path / "dj.json"
    mock = {
        "ok": True,
        "status": 200,
        "url": "https://api-publica.datajud.cnj.jus.br/api_publica_trf3/_search",
        "data": {
            "hits": {
                "total": {"value": 1, "relation": "eq"},
                "hits": [
                    {
                        "_source": {
                            "numeroProcesso": "00011112220244036100",
                            "tribunal": "TRF3",
                            "classe": {"nome": "JEC"},
                            "movimentos": [],
                            "assuntos": [],
                        }
                    }
                ],
            }
        },
        "error": None,
    }
    with patch("tarrafa.tools.datajud.scraper.fetch_search", return_value=mock):
        code = main(
            [
                "--cnj",
                "0001111-22.2024.4.03.6100",
                "--tribunal",
                "trf3",
                "--out",
                str(out),
            ]
        )
    assert code == 0
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["tool"] == "datajud"
    assert env["count"] >= 1
