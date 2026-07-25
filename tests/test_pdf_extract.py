# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter

from tarrafa.tools.pdf_extract.scraper import extract_pdf_text, list_pdfs, main


def _blank_pdf(path: Path) -> None:
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        w.write(f)


def test_list_pdfs(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.pdf").write_bytes(b"%PDF-1.4\n")
    (tmp_path / "c.txt").write_text("x")
    found = list_pdfs(files=[], directory=tmp_path, recursive=True)
    names = {p.name for p in found}
    assert "a.pdf" in names
    assert "b.pdf" in names


def test_extract_blank_ok(tmp_path: Path):
    pdf = tmp_path / "blank.pdf"
    _blank_pdf(pdf)
    res = extract_pdf_text(pdf)
    assert res["ok"] is True
    assert res["pages"] == 1


def test_main_with_mocked_text(tmp_path: Path):
    pdf = tmp_path / "qualificacao.pdf"
    _blank_pdf(pdf)
    fake = {
        "ok": True,
        "path": str(pdf),
        "name": pdf.name,
        "pages": 1,
        "pages_extracted": 1,
        "text_len": 120,
        "text": (
            "MARIA EXEMPLO CPF 529.982.247-25 email parte.exemplo@example.com "
            "@exemplo_handle processo 0001234-56.2024.8.26.0100"
        ),
        "text_truncated": False,
        "identity_hints": {
            "cpfs": ["529.982.247-25"],
            "rgs": [],
            "datas_nascimento": [],
            "emails": ["parte.exemplo@example.com"],
            "phones": [],
            "handles": ["exemplo_handle"],
            "cnjs": ["0001234-56.2024.8.26.0100"],
            "ceps": [],
            "addresses": [],
        },
        "errors": [],
    }
    out = tmp_path / "out.json"
    with patch("tarrafa.tools.pdf_extract.scraper.extract_pdf_text", return_value=fake):
        code = main(["--file", str(pdf), "--out", str(out)])
    assert code == 0
    env = json.loads(out.read_text(encoding="utf-8"))
    assert env["tool"] == "pdf-extract"
    kinds = [i.get("kind") for i in env["items"]]
    assert "pdf_extract_summary" in kinds
    assert "pdf_document" in kinds
    summary = next(i for i in env["items"] if i.get("kind") == "pdf_extract_summary")
    assert "529.982.247-25" in (summary["identity_hints"].get("cpfs") or [])
