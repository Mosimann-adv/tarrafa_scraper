# -*- coding: utf-8 -*-
from __future__ import annotations

from tarrafa.core.identity_extract import (
    extract_identity_hints,
    format_cnj,
    format_cpf,
    merge_hints,
)


def test_format_cpf_cnj():
    assert format_cpf("52998224725") == "529.982.247-25"
    assert format_cnj("00012345620248260100") == "0001234-56.2024.8.26.0100"


def test_extract_from_sample_text():
    text = """
    MARIA EXEMPLO DA SILVA, CPF nº 529.982.247-25, RG 12.345.678-SSP/SP,
    Data de Nascimento: 15/03/1985, e-mail parte.exemplo@example.com,
    fone (11) 98888-7777, perfil @exemplo_handle,
    processo 0001234-56.2024.8.26.0100,
    Rua Exemplo, 100, CEP 01310-100, São Paulo.
    """
    h = extract_identity_hints(text)
    assert "529.982.247-25" in h["cpfs"]
    assert any("12.345.678" in r for r in h["rgs"])
    assert "15/03/1985" in h["datas_nascimento"]
    assert "parte.exemplo@example.com" in h["emails"]
    assert any("98888" in p for p in h["phones"])
    assert "exemplo_handle" in h["handles"]
    assert any(c.startswith("0001234") for c in h["cnjs"])
    assert any("01310-100" in c for c in h["ceps"])
    assert any("Exemplo" in a for a in h["addresses"])


def test_merge_hints():
    a = extract_identity_hints("CPF 529.982.247-25 @exemplo_handle")
    b = extract_identity_hints("CPF 529.982.247-25 e outro 111.444.777-35")
    m = merge_hints([a, b])
    assert "529.982.247-25" in m["cpfs"]
    assert m["counts"]["cpfs"].get("529.982.247-25", 0) >= 2
