# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tarrafa.tools.djen.scraper import (
    cpf_query_variants,
    item_matches_cpf,
    item_matches_lawyer,
    main,
    mask_cpf,
    resolve_papel,
    strip_html,
    summarize_item,
)


def _cpf_teste() -> tuple[str, str]:
    """Gera um CPF válido sem armazenar identificador completo no repositório."""
    numeros = list(range(1, 10))
    for peso_inicial in (10, 11):
        soma = sum(numero * (peso_inicial - indice) for indice, numero in enumerate(numeros))
        resto = soma % 11
        numeros.append(0 if resto < 2 else 11 - resto)
    digitos = "".join(str(numero) for numero in numeros)
    formatado = f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return digitos, formatado


def test_strip_html():
    assert "ANA" in strip_html("<p>ADVOGADO: ANA &amp; X</p>")


def test_item_matches_structured_oab():
    item = {
        "texto": "sem oab no texto",
        "destinatarioadvogados": [
            {"advogado": {"nome": "ANA EXEMPLO ADVOGADA", "numero_oab": "12345", "uf_oab": "SP"}}
        ],
    }
    assert item_matches_lawyer(item, oab="12345", uf="SP", nome=None)
    assert not item_matches_lawyer(item, oab="99999", uf="SP", nome=None)


def test_item_matches_text_fallback():
    item = {
        "texto": "ADVOGADO(A) : ANA EXEMPLO ADVOGADA (OAB SP12345)",
        "destinatarioadvogados": [],
    }
    assert item_matches_lawyer(item, oab="12345", uf="SP", nome=None)


def test_item_matches_cpf_no_teor_ou_destinatario():
    cpf_digitos, cpf = _cpf_teste()
    assert item_matches_cpf({"texto": f"Parte CPF {cpf}"}, cpf)
    assert item_matches_cpf({"texto": f"Parte CPF {cpf_digitos}"}, cpf)
    assert item_matches_cpf(
        {"texto": "sem CPF no teor", "destinatarios": [{"cpf_cnpj": cpf_digitos}]},
        cpf,
    )
    assert not item_matches_cpf({"texto": "Parte Maria Exemplo, sem documento"}, cpf)


def test_variantes_e_mascara_de_cpf():
    cpf_digitos, cpf = _cpf_teste()
    assert cpf_query_variants(cpf) == [
        ("cpf_formatado", cpf),
        ("cpf_digitos", cpf_digitos),
    ]
    assert mask_cpf(cpf) == f"***.***.***-{cpf_digitos[-2:]}"


def test_summarize_item():
    s = summarize_item(
        {
            "id": 1,
            "siglaTribunal": "TJSP",
            "tipoComunicacao": "Intimação",
            "numeroprocessocommascara": "0001234-56.2024.8.26.0100",
            "numero_processo": "00012345620248260100",
            "texto": "<b>x</b>",
            "destinatarioadvogados": [],
        }
    )
    assert s["sigla_tribunal"] == "TJSP"
    assert s["numero_processo_mascara"].startswith("0001234")


def test_resolve_papel():
    cpf_digitos, _ = _cpf_teste()
    assert resolve_papel("auto", oab="12345", nome=None, texto=None) == "advogado"
    assert resolve_papel("auto", oab=None, nome=None, texto="exemplo_handle") == "parte"
    assert resolve_papel("parte", oab="1", nome=None, texto=None) == "parte"
    assert resolve_papel("auto", oab=None, nome="Maria Exemplo", texto=None, cpf=cpf_digitos) == "parte"


def test_summarize_with_hints():
    _, cpf = _cpf_teste()
    s = summarize_item(
        {
            "id": 2,
            "siglaTribunal": "TJSP",
            "tipoComunicacao": "Intimação",
            "numeroprocessocommascara": "0009876-54.2025.8.26.0100",
            "texto": f"REQUERIDO JOAO EXEMPLO CPF {cpf} @exemplo_handle",
            "destinatarioadvogados": [],
        },
        extract_hints=True,
    )
    assert "identity_hints" in s
    assert cpf in s["identity_hints"]["cpfs"]
    assert "exemplo_handle" in s["identity_hints"]["handles"]


def test_main_mock(tmp_path: Path):
    out = tmp_path / "djen.json"
    page = {
        "ok": True,
        "status": 200,
        "url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao",
        "data": {
            "count": 2,
            "items": [
                {
                    "id": 10,
                    "data_disponibilizacao": "2026-07-24",
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                    "nomeOrgao": "VF",
                    "texto": "ADVOGADO ANA (OAB SP12345)",
                    "numero_processo": "00012345620248260100",
                    "numeroprocessocommascara": "0001234-56.2024.8.26.0100",
                    "destinatarioadvogados": [
                        {
                            "advogado": {
                                "nome": "ANA EXEMPLO ADVOGADA",
                                "numero_oab": "12345",
                                "uf_oab": "SP",
                            }
                        }
                    ],
                },
                {
                    "id": 11,
                    "texto": "outro sem oab",
                    "destinatarioadvogados": [],
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                },
            ],
        },
        "error": None,
    }
    with patch("tarrafa.tools.djen.scraper.fetch_page", return_value=page):
        code = main(["--oab", "12345", "--uf", "SP", "--max-items", "10", "--out", str(out)])
    assert code == 0
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["tool"] == "djen"
    kinds = [i.get("kind") for i in env["items"]]
    assert "djen_summary" in kinds
    assert kinds.count("djen_comunicacao") == 1


def test_main_parte_mock(tmp_path: Path):
    _, cpf = _cpf_teste()
    out = tmp_path / "djen_parte.json"
    page = {
        "ok": True,
        "status": 200,
        "url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao",
        "data": {
            "count": 1,
            "items": [
                {
                    "id": 99,
                    "data_disponibilizacao": "2026-06-22",
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                    "nomeClasse": "PROCEDIMENTO COMUM",
                    "texto": (
                        f"Parte: Maria Exemplo da Silva CPF {cpf} "
                        "processo 0001234-56.2024.8.26.0100 @exemplo_handle"
                    ),
                    "numero_processo": "00012345620248260100",
                    "numeroprocessocommascara": "0001234-56.2024.8.26.0100",
                    "destinatarioadvogados": [],
                }
            ],
        },
        "error": None,
    }
    with patch("tarrafa.tools.djen.scraper.fetch_page", return_value=page):
        code = main(
            [
                "--papel",
                "parte",
                "--texto",
                "Maria Exemplo da Silva",
                "--max-items",
                "10",
                "--out",
                str(out),
            ]
        )
    assert code == 0
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["source"]["papel"] == "parte"
    summary = next(i for i in env["items"] if i.get("kind") == "djen_summary")
    assert summary.get("papel") == "parte"
    assert "identity_hints" in summary
    assert cpf in (summary["identity_hints"].get("cpfs") or [])


def test_main_prioriza_cpf_e_filtra_correspondencia_exata(tmp_path: Path):
    cpf_digitos, cpf = _cpf_teste()
    out = tmp_path / "djen_cpf.json"
    page = {
        "ok": True,
        "status": 200,
        "url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao",
        "data": {
            "count": 2,
            "items": [
                {
                    "id": 201,
                    "texto": f"Parte: Maria Exemplo CPF {cpf}",
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                    "destinatarioadvogados": [],
                },
                {
                    "id": 202,
                    "texto": "Parte: Maria Exemplo sem CPF",
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                    "destinatarioadvogados": [],
                },
            ],
        },
        "error": None,
    }
    with patch("tarrafa.tools.djen.scraper.fetch_page", return_value=page) as fetch:
        code = main(
            [
                "--papel",
                "parte",
                "--cpf",
                cpf_digitos,
                "--nome",
                "Maria Exemplo",
                "--texto",
                "consulta menos confiável",
                "--out",
                str(out),
            ]
        )

    assert code == 0
    consultas = [call.args[0] for call in fetch.call_args_list]
    assert [params["texto"] for params in consultas] == [cpf, cpf_digitos]
    assert all("nomeParte" not in params for params in consultas)
    env = json.loads(out.read_text(encoding="utf-8"))
    comunicacoes = [i for i in env["items"] if i.get("kind") == "djen_comunicacao"]
    assert [i["id"] for i in comunicacoes] == [201]
    assert env["source"]["search_priority"] == "cpf"
    assert env["source"]["cpf"] == mask_cpf(cpf)
    assert env["meta"]["cpf_exact_filter"] is True
    assert env["meta"]["query_variants"] == ["cpf_formatado", "cpf_digitos"]
    assert env["meta"]["params"]["cpf"] == mask_cpf(cpf)
    meta_json = json.dumps(env["meta"], ensure_ascii=False)
    assert cpf not in meta_json
    assert cpf_digitos not in meta_json


def test_main_encontra_cpf_sem_pontuacao_na_segunda_consulta(tmp_path: Path):
    cpf_digitos, cpf = _cpf_teste()
    out = tmp_path / "djen_cpf_digitos.json"

    def fake_fetch(params, *, timeout):
        items = []
        if params["texto"] == cpf_digitos:
            items = [
                {
                    "id": 301,
                    "texto": f"Parte: Maria Exemplo CPF {cpf_digitos}",
                    "siglaTribunal": "TJSP",
                    "tipoComunicacao": "Intimação",
                    "destinatarioadvogados": [],
                }
            ]
        return {
            "ok": True,
            "status": 200,
            "url": "https://comunicaapi.pje.jus.br/api/v1/comunicacao",
            "data": {"count": len(items), "items": items},
            "error": None,
        }

    with patch("tarrafa.tools.djen.scraper.fetch_page", side_effect=fake_fetch) as fetch:
        code = main(["--papel", "parte", "--cpf", cpf, "--out", str(out)])

    assert code == 0
    assert [call.args[0]["texto"] for call in fetch.call_args_list] == [cpf, cpf_digitos]
    env = json.loads(out.read_text(encoding="utf-8"))
    comunicacoes = [item for item in env["items"] if item.get("kind") == "djen_comunicacao"]
    assert [item["id"] for item in comunicacoes] == [301]


def test_main_rejeita_cpf_invalido(tmp_path: Path):
    out = tmp_path / "djen_cpf_invalido.json"
    code = main(["--cpf", "000", "--out", str(out)])
    assert code == 2
    assert not out.exists()
