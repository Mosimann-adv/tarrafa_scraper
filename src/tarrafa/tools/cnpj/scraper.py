# -*- coding: utf-8 -*-
"""
tarrafa cnpj — consulta pública de CNPJ via API open CNPJá.

  tarrafa cnpj --cnpj 11.222.333/0001-81 --out empresa.json
  tarrafa cnpj --cnpj 11222333000181 --out empresa.json

Fonte: GET https://open.cnpja.com/office/:cnpj (sem API key).
Não busca por nome de sócio — a open API exige o número do CNPJ.
Descoberta de CNPJ (busca web / usuário) fica na orquestração (skill perfil).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import DEFAULT_TIMEOUT, DEFAULT_UA, ensure_httpx
from tarrafa.core.writers import write_json

OPEN_OFFICE_URL = "https://open.cnpja.com/office/{cnpj}"


def digits_only(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")


def format_cnpj(digits: str) -> str:
    d = digits_only(digits)
    if len(d) != 14:
        return d
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def validate_cnpj_length(digits: str) -> bool:
    return len(digits) == 14 and digits.isdigit()


def fetch_office(cnpj: str, *, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """
    GET open.cnpja.com/office/:cnpj
    Returns {ok, status, url, data?, error?}
    """
    digits = digits_only(cnpj)
    if not validate_cnpj_length(digits):
        return {
            "ok": False,
            "status": None,
            "url": None,
            "data": None,
            "error": f"CNPJ inválido (precisa 14 dígitos): {cnpj!r}",
        }
    url = OPEN_OFFICE_URL.format(cnpj=digits)
    httpx = ensure_httpx()
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            text = r.text
            data = None
            try:
                data = r.json() if text else None
            except Exception:
                data = None
            if r.status_code == 200 and isinstance(data, dict):
                return {"ok": True, "status": r.status_code, "url": url, "data": data, "error": None}
            # rate limit / not found
            err = None
            if isinstance(data, dict) and data.get("message"):
                err = str(data.get("message"))
            elif text and len(text) < 400:
                err = text.strip()
            else:
                err = f"HTTP {r.status_code}"
            return {
                "ok": False,
                "status": r.status_code,
                "url": url,
                "data": data if isinstance(data, dict) else None,
                "error": err,
            }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "data": None,
            "error": f"{type(e).__name__}: {e}",
        }


def summarize_office(data: dict[str, Any]) -> dict[str, Any]:
    """Flatten useful fields for envelope item (material facts)."""
    company = data.get("company") or {}
    status = data.get("status") or {}
    address = data.get("address") or {}
    main = data.get("mainActivity") or {}
    members = []
    for m in company.get("members") or []:
        person = m.get("person") or {}
        role = m.get("role") or {}
        members.append(
            {
                "name": person.get("name"),
                "role": role.get("text"),
                "since": m.get("since"),
                "person_type": person.get("type"),
                # taxId comes masked from API — keep as-is
                "tax_id_masked": person.get("taxId"),
                "age_range": person.get("age"),
            }
        )
    phones = []
    for p in data.get("phones") or []:
        area = p.get("area") or ""
        num = p.get("number") or ""
        phones.append(
            {
                "type": p.get("type"),
                "e164_hint": f"+55{area}{num}" if area and num else None,
                "display": f"({area}) {num}" if area and num else num,
            }
        )
    emails = []
    for e in data.get("emails") or []:
        emails.append(
            {
                "address": e.get("address"),
                "ownership": e.get("ownership"),
                "domain": e.get("domain"),
            }
        )
    city = address.get("city")
    state = address.get("state")
    street = address.get("street")
    number = address.get("number")
    district = address.get("district")
    zipc = address.get("zip")
    details = address.get("details")
    addr_line = ", ".join(
        x
        for x in [
            f"{street}, {number}" if street else None,
            details,
            district,
            f"{city}/{state}" if city or state else None,
            f"CEP {zipc}" if zipc else None,
        ]
        if x
    )
    return {
        "cnpj": digits_only(str(data.get("taxId") or "")),
        "cnpj_formatted": format_cnpj(str(data.get("taxId") or "")),
        "company_name": company.get("name"),
        "alias": data.get("alias"),
        "founded": data.get("founded"),
        "status": status.get("text"),
        "status_date": data.get("statusDate"),
        "head": data.get("head"),
        "equity": company.get("equity"),
        "nature": (company.get("nature") or {}).get("text"),
        "size": (company.get("size") or {}).get("text"),
        "simples_optant": (company.get("simples") or {}).get("optant"),
        "simei_optant": (company.get("simei") or {}).get("optant"),
        "main_activity": main.get("text"),
        "main_activity_id": main.get("id"),
        "address": addr_line,
        "address_raw": address,
        "phones": phones,
        "emails": emails,
        "members": members,
        "updated": data.get("updated"),
        "source_api": "open.cnpja.com/office",
    }


def build_cnpj_envelope(
    *,
    cnpj: str,
    fetch_result: dict[str, Any],
) -> dict[str, Any]:
    digits = digits_only(cnpj)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    notes = [
        "API pública CNPJá open (sem autenticação): GET /office/:cnpj.",
        "Não pesquisa por nome de pessoa/sócio — informe o CNPJ.",
        "Dados cadastrais públicos; mascaramento de CPF de sócios vem da API.",
    ]
    if fetch_result.get("error"):
        errors.append(str(fetch_result["error"]))
    data = fetch_result.get("data")
    if fetch_result.get("ok") and isinstance(data, dict):
        summary = summarize_office(data)
        items.append(
            {
                "kind": "cnpj_office",
                "cnpj": summary["cnpj"],
                "cnpj_formatted": summary["cnpj_formatted"],
                "company_name": summary["company_name"],
                "summary": summary,
                "raw": data,
            }
        )
    url = fetch_result.get("url") or OPEN_OFFICE_URL.format(cnpj=digits or "????????????")
    return build_envelope(
        "cnpj",
        source={"url": url, "cnpj": digits, "provider": "cnpja_open"},
        items=items,
        meta={
            "provider": "cnpja",
            "api": "open",
            "endpoint": "office",
            "http_status": fetch_result.get("status"),
            "ok": bool(fetch_result.get("ok")),
        },
        errors=errors,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa cnpj",
        description=(
            "Consulta CNPJ na API open CNPJá (open.cnpja.com/office). "
            "Sem API key. Não busca por nome — só por número de CNPJ."
        ),
    )
    ap.add_argument(
        "--cnpj",
        action="append",
        dest="cnpjs",
        required=True,
        help="CNPJ (com ou sem máscara). Repetível para vários.",
    )
    ap.add_argument("--out", required=True, help="JSON de saída (envelope forense)")
    ap.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout segundos (default {DEFAULT_TIMEOUT})",
    )
    args = ap.parse_args(argv)

    # One envelope per run: multiple CNPJs → multiple items
    all_items: list[dict[str, Any]] = []
    all_errors: list[str] = []
    statuses: list[int | None] = []
    urls: list[str] = []

    for raw in args.cnpjs:
        fr = fetch_office(raw, timeout=args.timeout)
        statuses.append(fr.get("status"))
        if fr.get("url"):
            urls.append(fr["url"])
        env_one = build_cnpj_envelope(cnpj=raw, fetch_result=fr)
        all_items.extend(env_one.get("items") or [])
        all_errors.extend(env_one.get("errors") or [])

    envelope = build_envelope(
        "cnpj",
        source={
            "url": urls[0] if len(urls) == 1 else "https://open.cnpja.com/office/{cnpj}",
            "cnpjs": [digits_only(c) for c in args.cnpjs],
            "provider": "cnpja_open",
        },
        items=all_items,
        meta={
            "provider": "cnpja",
            "api": "open",
            "endpoint": "office",
            "requested": len(args.cnpjs),
            "ok_count": len(all_items),
            "http_statuses": statuses,
        },
        errors=all_errors,
        notes=[
            "API pública CNPJá open (sem autenticação): GET /office/:cnpj.",
            "Não pesquisa por nome de pessoa/sócio — informe o CNPJ.",
            "Docs: https://cnpja.com/api/open",
        ],
    )

    out = Path(args.out)
    write_json(out, envelope)
    ok = len(all_items)
    print(
        f"cnpj: wrote {out}  ok={ok}/{len(args.cnpjs)}  "
        f"errors={len(all_errors)}"
    )
    if ok == 0:
        for e in all_errors:
            print(f"cnpj: error: {e}", file=sys.stderr)
        return 6 if all_errors else 2
    # partial success still 0 if at least one
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
