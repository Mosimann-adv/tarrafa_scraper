# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tarrafa.tools.cnpj.scraper import (
    digits_only,
    format_cnpj,
    main,
    summarize_office,
    validate_cnpj_length,
)


def test_digits_and_format():
    assert digits_only("11.222.333/0001-81") == "11222333000181"
    assert format_cnpj("11222333000181") == "11.222.333/0001-81"
    assert validate_cnpj_length("11222333000181")
    assert not validate_cnpj_length("123")


def test_summarize_office_members():
    data = {
        "taxId": "11222333000181",
        "founded": "2020-01-15",
        "alias": None,
        "head": True,
        "updated": "2026-01-01T00:00:00Z",
        "statusDate": "2020-01-15",
        "status": {"text": "Ativa"},
        "company": {
            "name": "EXEMPLO CONSULTORIA LTDA",
            "equity": 10000,
            "nature": {"text": "Sociedade Empresária Limitada"},
            "size": {"text": "Demais"},
            "simples": {"optant": True},
            "simei": {"optant": False},
            "members": [
                {
                    "since": "2020-01-15",
                    "person": {
                        "name": "Ana Exemplo",
                        "type": "NATURAL",
                        "taxId": "***982247**",
                        "age": "31-40",
                    },
                    "role": {"text": "Sócio-Administrador"},
                }
            ],
        },
        "address": {
            "street": "Rua Exemplo",
            "number": "100",
            "district": "Centro",
            "city": "São Paulo",
            "state": "SP",
            "zip": "01310100",
            "details": "Sala 1",
        },
        "phones": [{"type": "MOBILE", "area": "11", "number": "988887777"}],
        "emails": [{"address": "contato@example.com", "ownership": "PERSONAL", "domain": "example.com"}],
        "mainActivity": {"id": 7020400, "text": "Atividades de consultoria"},
    }
    s = summarize_office(data)
    assert s["company_name"] == "EXEMPLO CONSULTORIA LTDA"
    assert s["members"][0]["name"] == "Ana Exemplo"
    assert "São Paulo/SP" in s["address"] or "Sao Paulo/SP" in s["address"] or "SP" in s["address"]
    assert s["phones"][0]["e164_hint"] == "+5511988887777"


def test_main_invalid_cnpj(tmp_path: Path):
    out = tmp_path / "bad.json"
    code = main(["--cnpj", "123", "--out", str(out)])
    assert code == 6
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["tool"] == "cnpj"
    assert env["count"] == 0
    assert env["errors"]


def test_main_mock_success(tmp_path: Path):
    out = tmp_path / "ok.json"
    mock_data = {
        "taxId": "11222333000181",
        "founded": "2020-01-15",
        "status": {"text": "Ativa"},
        "company": {"name": "EXEMPLO CONSULTORIA LTDA", "members": []},
        "address": {"city": "São Paulo", "state": "SP"},
        "phones": [],
        "emails": [],
        "mainActivity": {"text": "Atividades de consultoria"},
    }
    with patch(
        "tarrafa.tools.cnpj.scraper.fetch_office",
        return_value={
            "ok": True,
            "status": 200,
            "url": "https://open.cnpja.com/office/11222333000181",
            "data": mock_data,
            "error": None,
        },
    ):
        code = main(["--cnpj", "11.222.333/0001-81", "--out", str(out)])
    assert code == 0
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["count"] == 1
    assert env["items"][0]["company_name"] == "EXEMPLO CONSULTORIA LTDA"
