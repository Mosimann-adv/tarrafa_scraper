# -*- coding: utf-8 -*-
"""Testes unitários order-risk — dados sintéticos apenas (sem casos reais)."""
from __future__ import annotations

from pathlib import Path

from tarrafa.cli import main as cli_main
from tarrafa.templates.order_risk_html import render_order_risk
from tarrafa.tools.order_risk import scraper as order_risk_scraper
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


def test_address_match_rejects_different_street_kind():
    checks = match_address_fields(
        street="Rua das Flores",
        neighborhood="Centro",
        city="Curitiba",
        state="PR",
        via={
            "logradouro": "Avenida das Flores",
            "bairro": "Centro",
            "localidade": "Curitiba",
            "uf": "PR",
        },
    )
    assert checks[0]["field"] == "street"
    assert checks[0]["match"] is False


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


def test_bands_identity_stays_mid_without_djen_anchor():
    facts = {
        "buyer": {
            "name": "Maria Exemplo Silva",
            "cpf": format_cpf(_valid_cpf_digits()),
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
            ],
            "via": {"ddd": "41"},
        },
        "phone": normalize_phone_br("(41) 99999-0000"),
        "dob": {},
        "djen": {"queried": False, "error": "skip"},
        "store": {},
        "ig": {},
    }
    bands = compute_bands(build_signals_from_facts(facts))
    assert bands["identity_fraud"] == "mid"


def test_store_timeout_is_unknown_not_high():
    facts = {
        "buyer": {},
        "cpf": {},
        "cep": {},
        "phone": {},
        "dob": {},
        "djen": {},
        "store": {
            "url": "https://loja.example",
            "reachable": None,
            "error": "Timeout",
        },
        "ig": {},
    }
    signals = build_signals_from_facts(facts)
    assert any(s["id"] == "store_reachable" and s["polarity"] == "gap" for s in signals)
    assert compute_bands(signals)["merchant"] == "unknown"


def test_store_verified_inactive_is_high():
    facts = {
        "buyer": {},
        "cpf": {},
        "cep": {},
        "phone": {},
        "dob": {},
        "djen": {},
        "store": {
            "url": "https://loja.example",
            "reachable": True,
            "cnpjs_found": ["00000000000191"],
            "cnpj_verified": True,
            "cnpj_inactive": True,
            "cnpj_status": "BAIXADA",
        },
        "ig": {},
    }
    signals = build_signals_from_facts(facts)
    assert compute_bands(signals)["merchant"] == "high"


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
    assert cli_main(["order-risk", "--help"]) == 0


def test_run_order_risk_orchestrates_sources(monkeypatch, tmp_path: Path):
    cpf = _valid_cpf_digits()
    monkeypatch.setattr(
        order_risk_scraper,
        "fetch_viacep",
        lambda cep, timeout: {
            "ok": True,
            "error": None,
            "via": {
                "logradouro": "Rua das Flores",
                "bairro": "Centro",
                "localidade": "Curitiba",
                "uf": "PR",
                "ddd": "41",
            },
        },
    )
    monkeypatch.setattr(
        order_risk_scraper,
        "_capture_store_page",
        lambda url, timeout, out_json: {
            "ok": True,
            "error": None,
            "text": "Loja Exemplo LTDA — CNPJ 00.000.000/0001-91",
            "title": "Loja Exemplo",
            "url": url,
            "envelope_path": None,
        },
    )
    monkeypatch.setattr(
        order_risk_scraper,
        "_lookup_cnpj",
        lambda cnpj, timeout, out_json: {
            "ok": True,
            "cnpj": "00000000000191",
            "cnpj_formatted": "00.000.000/0001-91",
            "company_name": "LOJA EXEMPLO LTDA",
            "status": "ATIVA",
        },
    )
    monkeypatch.setattr(
        order_risk_scraper,
        "_run_djen_cpf",
        lambda cpf, max_items, timeout, raw_dir: {
            "queried": True,
            "cpf_hits": 1,
            "unique_processos": 1,
            "processos_sample": ["0000000-00.0000.0.00.0000"],
            "by_tribunal": {"TJXX": 1},
            "civil_name_hint": "MARIA EXEMPLO SILVA",
            "error": None,
        },
    )

    out_dir = tmp_path / "report"
    env = order_risk_scraper.run_order_risk(
        store_url="https://loja.example",
        buyer={
            "name": "Maria Exemplo Silva",
            "cpf": cpf,
            "phone": "(41) 99999-0000",
            "street": "Rua das Flores",
            "neighborhood": "Centro",
            "city": "Curitiba",
            "state": "PR",
            "cep": "80010-000",
        },
        out_dir=out_dir,
    )

    assert env["errors"] == []
    assert env["meta"]["bands"]["identity_fraud"] == "low"
    assert env["meta"]["bands"]["merchant"] == "low"
    assert (out_dir / "order_risk.json").is_file()
    assert (out_dir / "order_risk.html").is_file()


def test_main_returns_nonzero_for_partial_collection(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        order_risk_scraper,
        "run_order_risk",
        lambda **kwargs: {
            "meta": {
                "bands": {"identity_fraud": "unknown", "merchant": "unknown"},
                "signal_counts": {},
                "html": None,
                "shots_embedded": 0,
            },
            "errors": ["viacep: timeout"],
        },
    )
    code = order_risk_scraper.main(
        [
            "--name",
            "Comprador Teste",
            "--out-dir",
            str(tmp_path / "report"),
            "--skip-djen",
            "--skip-store",
        ]
    )
    assert code == 1
