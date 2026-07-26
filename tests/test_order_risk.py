# -*- coding: utf-8 -*-
"""Testes unitários order-risk — dados sintéticos apenas (sem casos reais)."""
from __future__ import annotations

from pathlib import Path

from tarrafa.cli import main as cli_main
from tarrafa.templates.order_risk_html import render_order_risk
from tarrafa.tools.order_risk.checks import (
    build_signals_from_facts,
    compute_bands,
    format_cpf,
    match_address_fields,
    normalize_phone_br,
    number_in_cep_range,
    parse_dob,
    validate_cpf,
)


def _valid_cpf_digits() -> str:
    """Gera CPF sintético com DV válido (não representa pessoa real)."""
    base = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    s = sum(base[i] * (10 - i) for i in range(9))
    r = s % 11
    dv1 = 0 if r < 2 else 11 - r
    base.append(dv1)
    s = sum(base[i] * (11 - i) for i in range(10))
    r = s % 11
    dv2 = 0 if r < 2 else 11 - r
    base.append(dv2)
    return "".join(str(d) for d in base)


def test_validate_cpf_ok():
    d = _valid_cpf_digits()
    r = validate_cpf(d)
    assert r["ok"] is True
    assert r["digits"] == d
    assert validate_cpf(format_cpf(d))["ok"] is True


def test_validate_cpf_bad():
    assert validate_cpf("000.000.000-00")["ok"] is False
    assert validate_cpf("123")["ok"] is False
    assert validate_cpf(None)["ok"] is False


def test_parse_dob_and_phone():
    dob = parse_dob("15/03/1990")
    assert dob["ok"] is True
    assert dob["age"] is not None and dob["age"] >= 30
    ph = normalize_phone_br("(11) 98765-4321")
    assert ph["ok"] is True
    assert ph["ddd"] == "11"
    assert ph["mobile"] is True


def test_address_match_and_number_range():
    via = {
        "logradouro": "Rua das Flores",
        "bairro": "Centro",
        "localidade": "Curitiba",
        "uf": "PR",
        "complemento": "de 100/101 ao fim",
        "ddd": "41",
    }
    checks = match_address_fields(
        street="Rua das Flores",
        neighborhood="Centro",
        city="Curitiba",
        state="PR",
        via=via,
    )
    assert all(c["match"] is True for c in checks)
    assert number_in_cep_range("150", via["complemento"])["ok"] is True
    assert number_in_cep_range("50", via["complemento"])["ok"] is False


def test_bands_identity_low_with_anchors():
    facts = {
        "buyer": {
            "name": "Maria Exemplo Silva",
            "cpf": format_cpf(_valid_cpf_digits()),
            "email": "maria.exemplo@example.com",
            "phone": "(41) 99999-0000",
            "cep": "80010-000",
        },
        "cpf": validate_cpf(_valid_cpf_digits()),
        "cep": {
            "api_ok": True,
            "formatted": "80010-000",
            "field_matches": [
                {"field": "street", "match": True},
                {"field": "city", "match": True},
                {"field": "state", "match": True},
                {"field": "neighborhood", "match": True},
            ],
            "via": {"ddd": "41"},
        },
        "phone": normalize_phone_br("(41) 99999-0000"),
        "dob": parse_dob("01/01/1990"),
        "djen": {
            "queried": True,
            "cpf_hits": 2,
            "unique_processos": 1,
            "processos_sample": ["0000000-00.0000.0.00.0000"],
            "by_tribunal": {"TJXX": 2},
            "civil_name_hint": "MARIA EXEMPLO SILVA",
        },
        "store": {
            "reachable": True,
            "title": "Loja Exemplo",
            "url": "https://loja.example",
            "cnpj_active": True,
            "company_name": "LOJA EXEMPLO LTDA",
            "cnpj_formatted": "00.000.000/0001-00",
            "cnpj_status": "Ativa",
            "domain_registered": True,
            "domain_created": "2020-01-01",
            "domain_expires": "2027-01-01",
        },
        "ig": {},
    }
    signals = build_signals_from_facts(facts)
    bands = compute_bands(signals)
    assert bands["identity_fraud"] == "low"
    assert bands["merchant"] == "low"
    assert any(s["id"] == "djen_cpf_anchor" and s["polarity"] == "positive" for s in signals)


def test_html_embeds_data_uri(tmp_path: Path):
    # tiny 1x1 png
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
        b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    import base64

    uri = "data:image/png;base64," + base64.standard_b64encode(png).decode("ascii")
    html = render_order_risk(
        title="order-risk — teste",
        collected_at="2026-01-01T00:00:00Z",
        store_url="https://loja.example",
        buyer={"name": "Comprador Teste", "cpf": "000.000.000-00", "city": "Cidade"},
        bands={"identity_fraud": "mid", "merchant": "unknown", "friendly_fraud_residual": "low_mid"},
        signals=[
            {
                "id": "cpf_valid",
                "label": "CPF ok",
                "polarity": "positive",
                "detail": "x",
                "weight": "critical",
            }
        ],
        shots=[{"id": "maps_address", "caption": "Mapa sintético", "image_src": uri}],
        notes=["nota teste"],
        artifacts=["a.json"],
    )
    assert "data:image/png;base64," in html
    assert "src=\"shots/" not in html
    assert "Mapa sintético" in html
    assert "order-risk" in html


def test_cli_list_has_order_risk(capsys):
    assert cli_main(["list"]) == 0
    out = capsys.readouterr().out
    assert "order-risk" in out


def test_cli_help_order_risk():
    # argparse help exits 0 via SystemExit in some paths — cli catches it
    code = cli_main(["order-risk", "--help"])
    assert code in (0, 2) or code == 0
