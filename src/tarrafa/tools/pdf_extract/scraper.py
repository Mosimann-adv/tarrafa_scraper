# -*- coding: utf-8 -*-
"""
tarrafa pdf-extract — extrai texto e identity hints de PDFs (autos, certidões).

  tarrafa pdf-extract --file auto.pdf --out extract.json
  tarrafa pdf-extract --dir CASO/raw/obtidos_adv --out extract.json
  tarrafa pdf-extract --dir CASO/raw/obtidos_adv --out extract.json --max-pages 80

Material-only: não classifica ofensas nem inventa biografia.
Depende de pypdf (dependency do pacote).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.identity_extract import extract_identity_hints, merge_hints
from tarrafa.core.writers import write_json

PDF_SUFFIXES = {".pdf", ".PDF"}


def ensure_pypdf():
    try:
        from pypdf import PdfReader  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "pdf-extract: pypdf não instalado. pip install pypdf  (ou reinstal tarrafa)"
        ) from e
    from pypdf import PdfReader

    return PdfReader


def list_pdfs(*, files: list[Path], directory: Path | None, recursive: bool) -> list[Path]:
    found: list[Path] = []
    for f in files:
        p = Path(f)
        if p.is_file() and p.suffix.lower() == ".pdf":
            found.append(p.resolve())
    if directory:
        d = Path(directory)
        if not d.is_dir():
            raise FileNotFoundError(f"diretório não encontrado: {d}")
        pattern = "**/*" if recursive else "*"
        for p in sorted(d.glob(pattern)):
            if p.is_file() and p.suffix.lower() == ".pdf":
                found.append(p.resolve())
    # unique preserve order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def extract_pdf_text(path: Path, *, max_pages: int | None = None) -> dict[str, Any]:
    PdfReader = ensure_pypdf()
    errors: list[str] = []
    pages_text: list[str] = []
    try:
        reader = PdfReader(str(path))
        n = len(reader.pages)
        limit = n if max_pages is None else min(n, max(1, max_pages))
        for i in range(limit):
            try:
                t = reader.pages[i].extract_text() or ""
            except Exception as e:
                errors.append(f"page {i + 1}: {type(e).__name__}: {e}")
                t = ""
            pages_text.append(t)
        full = "\n".join(pages_text)
        # normalize whitespace lightly for hints, keep page breaks in full
        full_norm = re.sub(r"[ \t]+", " ", full)
        hints = extract_identity_hints(full_norm)
        return {
            "ok": True,
            "path": str(path),
            "name": path.name,
            "pages": n,
            "pages_extracted": limit,
            "text_len": len(full),
            "text": full[:200_000],  # cap envelope size
            "text_truncated": len(full) > 200_000,
            "identity_hints": hints,
            "errors": errors,
        }
    except Exception as e:
        return {
            "ok": False,
            "path": str(path),
            "name": path.name,
            "pages": 0,
            "pages_extracted": 0,
            "text_len": 0,
            "text": "",
            "text_truncated": False,
            "identity_hints": extract_identity_hints(""),
            "errors": [f"{type(e).__name__}: {e}"],
        }


def collect(
    paths: list[Path],
    *,
    max_pages: int | None = None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    hint_list: list[dict[str, Any]] = []
    for p in paths:
        res = extract_pdf_text(p, max_pages=max_pages)
        item = {
            "kind": "pdf_document",
            "path": res["path"],
            "name": res["name"],
            "ok": res["ok"],
            "pages": res["pages"],
            "pages_extracted": res["pages_extracted"],
            "text_len": res["text_len"],
            "text_truncated": res["text_truncated"],
            "identity_hints": res["identity_hints"],
            "text_excerpt": (res["text"] or "")[:4000],
            "errors": res["errors"],
        }
        items.append(item)
        if res.get("identity_hints"):
            hint_list.append(res["identity_hints"])
        if not res["ok"]:
            errors.append(f"{p.name}: " + "; ".join(res["errors"] or ["fail"]))
        elif res["errors"]:
            errors.extend(f"{p.name}: {e}" for e in res["errors"])

    merged = merge_hints(hint_list)
    summary = {
        "kind": "pdf_extract_summary",
        "files": len(paths),
        "ok_files": sum(1 for i in items if i.get("ok")),
        "identity_hints": merged,
    }
    return {"summary": summary, "items": items, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa pdf-extract",
        description=(
            "Extrai texto e identity hints (CPF, RG, e-mail, telefone, CNJ, endereço, handle) "
            "de PDFs judiciais. Material-only."
        ),
    )
    ap.add_argument(
        "--file",
        action="append",
        dest="files",
        default=[],
        help="PDF individual (repetível)",
    )
    ap.add_argument("--dir", dest="directory", default=None, help="Diretório com PDFs")
    ap.add_argument(
        "--recursive",
        action="store_true",
        help="Com --dir, incluir subpastas",
    )
    ap.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Máximo de páginas por PDF (default: todas)",
    )
    ap.add_argument(
        "--full-text",
        action="store_true",
        help="Incluir texto completo de cada PDF no item (até 200k chars; default só excerpt)",
    )
    ap.add_argument("--out", required=True, help="JSON envelope de saída")
    args = ap.parse_args(argv)

    if not args.files and not args.directory:
        print("pdf-extract: informe --file e/ou --dir", file=sys.stderr)
        return 2

    try:
        ensure_pypdf()
    except SystemExit:
        raise
    except Exception as e:
        print(f"pdf-extract: {e}", file=sys.stderr)
        return 2

    try:
        paths = list_pdfs(
            files=[Path(f) for f in args.files],
            directory=Path(args.directory) if args.directory else None,
            recursive=args.recursive,
        )
    except FileNotFoundError as e:
        print(f"pdf-extract: {e}", file=sys.stderr)
        return 2

    if not paths:
        print("pdf-extract: nenhum PDF encontrado", file=sys.stderr)
        return 6

    result = collect(paths, max_pages=args.max_pages)

    # Optionally attach more text
    if args.full_text:
        for item, p in zip(result["items"], paths):
            if item.get("ok"):
                # re-read already capped in extract
                full = extract_pdf_text(p, max_pages=args.max_pages)
                item["text"] = full.get("text") or ""

    envelope_items: list[dict[str, Any]] = [result["summary"], *result["items"]]
    envelope = build_envelope(
        "pdf-extract",
        source={
            "files": [str(p) for p in paths],
            "dir": str(args.directory) if args.directory else None,
            "recursive": bool(args.recursive),
        },
        items=envelope_items,
        meta={
            "files": len(paths),
            "max_pages": args.max_pages,
            "full_text": bool(args.full_text),
        },
        errors=result["errors"],
        notes=[
            "Extração via pypdf (texto embutido). PDFs só-imagem exigem OCR externo.",
            "identity_hints são heurísticas sobre o texto — validar antes de usar em peça.",
            "cpfs traz apenas sequências com dígito verificador válido; as demais, "
            "normalmente protocolo/conta/guia, ficam em cpfs_rejected.",
            "Não fundir identidade só por homônimo de nome em PDF de terceiro.",
        ],
    )
    out = Path(args.out)
    write_json(out, envelope)
    s = result["summary"]
    hints = s.get("identity_hints") or {}
    print(
        f"pdf-extract: wrote {out}  files={s['ok_files']}/{s['files']}  "
        f"cpfs={len(hints.get('cpfs') or [])}"
        f"(-{len(hints.get('cpfs_rejected') or [])} dv)  "
        f"cnjs={len(hints.get('cnjs') or [])}  "
        f"emails={len(hints.get('emails') or [])}  "
        f"addresses={len(hints.get('addresses') or [])}  "
        f"errors={len(result['errors'])}"
    )
    if s["ok_files"] == 0:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
