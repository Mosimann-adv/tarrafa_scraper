# -*- coding: utf-8 -*-
"""
tarrafa datajud — capa + movimentos via API pública Datajud (CNJ).

  tarrafa datajud --tribunal tjpr --cnj 0000487-55.2026.8.16.0157 --out proc.json
  tarrafa datajud --tribunal trf4 --cnj 0001111-22.2024.4.03.6100 --out proc.json
  tarrafa datajud --cnj 0001111-22.2024.4.03.6100 --out proc.json   # infere tribunal do CNJ

Auth: header ``Authorization: APIKey <key>``
  - env ``DATAJUD_API_KEY`` (preferido)
  - fallback: chave pública documentada na wiki CNJ (pode mudar)

Docs: https://datajud-wiki.cnj.jus.br/api-publica/
Endpoints: https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search

Importante:
  - Índice público em geral **não** indexa nome de advogado/partes.
  - Serve para detalhar CNJs já obtidos (ex.: via DJEN), não para portfolio por OAB.
  - Orquestração perfil: usar só em perfis de advogado (após DJEN/outras fontes).
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import DEFAULT_TIMEOUT, DEFAULT_UA, ensure_httpx
from tarrafa.core.writers import write_json

# Chave pública publicada em https://datajud-wiki.cnj.jus.br/api-publica/acesso
# (CNJ pode rotacionar; preferir DATAJUD_API_KEY no .env)
DEFAULT_API_KEY = "cDZHYzlZa0JadVREZDJCendQbXY6SkJlTzNjLV9TRENyQk1RdnFKZGRQdw=="
BASE = "https://api-publica.datajud.cnj.jus.br"

# Justiça (J) → prefixo de alias Datajud
# TR codes for JF (J=4): 01..06 → trf1..trf6
# JE (J=8): 01=AC ... 26=TO, 27=DF → tjXX
# JT (J=5): 01..24 → trt1..trt24
UF_BY_JE = {
    1: "ac",
    2: "al",
    3: "ap",
    4: "am",
    5: "ba",
    6: "ce",
    7: "dft",
    8: "es",
    9: "go",
    10: "ma",
    11: "mt",
    12: "ms",
    13: "mg",
    14: "pa",
    15: "pb",
    16: "pr",
    17: "pe",
    18: "pi",
    19: "rj",
    20: "rn",
    21: "rs",
    22: "ro",
    23: "rr",
    24: "sc",
    25: "se",
    26: "sp",
    27: "to",
}


def digits_cnj(cnj: str) -> str:
    return re.sub(r"\D", "", cnj or "")


def format_cnj(digits: str) -> str:
    d = digits_cnj(digits)
    if len(d) != 20:
        return d
    return f"{d[0:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


def parse_cnj_parts(cnj: str) -> dict[str, Any] | None:
    d = digits_cnj(cnj)
    if len(d) != 20:
        return None
    return {
        "digits": d,
        "seq": d[0:7],
        "dv": d[7:9],
        "year": d[9:13],
        "justice": int(d[13]),
        "tribunal": int(d[14:16]),
        "origin": d[16:20],
        "formatted": format_cnj(d),
    }


def infer_tribunal_alias(cnj: str) -> str | None:
    """Infer Datajud alias from CNJ justice/tribunal digits."""
    parts = parse_cnj_parts(cnj)
    if not parts:
        return None
    j = parts["justice"]
    tr = parts["tribunal"]
    if j == 3:
        return "stj"
    if j == 4:
        if 1 <= tr <= 6:
            return f"trf{tr}"
        return None
    if j == 5:
        if 1 <= tr <= 24:
            return f"trt{tr}"
        return None
    if j == 8:
        uf = UF_BY_JE.get(tr)
        if uf:
            return f"tj{uf}"
        return None
    if j == 6:
        # eleitoral — tre-xx
        uf = UF_BY_JE.get(tr)
        if uf:
            return f"tre-{uf}"
        return None
    return None


def normalize_alias(tribunal: str) -> str:
    t = (tribunal or "").strip().lower().replace(" ", "")
    t = t.removeprefix("api_publica_")
    return t


def search_url(alias: str) -> str:
    a = normalize_alias(alias)
    return f"{BASE}/api_publica_{a}/_search"


def get_api_key() -> str:
    return (
        os.environ.get("DATAJUD_API_KEY")
        or os.environ.get("DATAJUD_APIKEY")
        or DEFAULT_API_KEY
    )


def build_cnj_query(cnj_digits: str) -> dict[str, Any]:
    # numeroProcesso no índice costuma ser sem máscara
    return {
        "size": 5,
        "query": {
            "bool": {
                "should": [
                    {"term": {"numeroProcesso": cnj_digits}},
                    {"match": {"numeroProcesso": cnj_digits}},
                ],
                "minimum_should_match": 1,
            }
        },
    }


def summarize_hit(src: dict[str, Any], *, tribunal_alias: str) -> dict[str, Any]:
    movimentos = src.get("movimentos") or []
    mov_sum = []
    for m in movimentos[:80]:
        if not isinstance(m, dict):
            continue
        mov_sum.append(
            {
                "codigo": m.get("codigo"),
                "nome": m.get("nome"),
                "dataHora": m.get("dataHora"),
            }
        )
    assuntos = []
    for a in src.get("assuntos") or []:
        if isinstance(a, dict):
            assuntos.append({"codigo": a.get("codigo"), "nome": a.get("nome")})
    classe = src.get("classe") or {}
    orgao = src.get("orgaoJulgador") or {}
    sistema = src.get("sistema") or {}
    formato = src.get("formato") or {}
    return {
        "kind": "datajud_processo",
        "tribunal_alias": tribunal_alias,
        "id": src.get("id"),
        "tribunal": src.get("tribunal"),
        "grau": src.get("grau"),
        "numero_processo": src.get("numeroProcesso"),
        "numero_processo_formatado": format_cnj(str(src.get("numeroProcesso") or "")),
        "data_ajuizamento": src.get("dataAjuizamento"),
        "nivel_sigilo": src.get("nivelSigilo"),
        "classe": classe.get("nome") if isinstance(classe, dict) else classe,
        "classe_codigo": classe.get("codigo") if isinstance(classe, dict) else None,
        "orgao_julgador": orgao.get("nome") if isinstance(orgao, dict) else orgao,
        "sistema": sistema.get("nome") if isinstance(sistema, dict) else sistema,
        "formato": formato.get("nome") if isinstance(formato, dict) else formato,
        "assuntos": assuntos,
        "movimentos_count": len(movimentos),
        "movimentos": mov_sum,
        "atualizado": src.get("dataHoraUltimaAtualizacao") or src.get("@timestamp"),
    }


def fetch_search(
    alias: str,
    body: dict[str, Any],
    *,
    api_key: str,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    httpx = ensure_httpx()
    url = search_url(alias)
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"APIKey {api_key}",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.post(url, json=body)
            try:
                data = r.json()
            except Exception:
                data = None
            if r.status_code != 200:
                return {
                    "ok": False,
                    "status": r.status_code,
                    "url": url,
                    "data": data,
                    "error": f"HTTP {r.status_code}",
                }
            return {"ok": True, "status": r.status_code, "url": url, "data": data, "error": None}
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "data": None,
            "error": f"{type(e).__name__}: {e}",
        }


def lookup_cnj(
    cnj: str,
    *,
    tribunal: str | None = None,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    digits = digits_cnj(cnj)
    if len(digits) != 20:
        return {
            "ok": False,
            "error": f"CNJ inválido (20 dígitos esperados): {cnj!r}",
            "items": [],
        }
    alias = normalize_alias(tribunal) if tribunal else infer_tribunal_alias(digits)
    if not alias:
        return {
            "ok": False,
            "error": "Não foi possível inferir tribunal do CNJ; informe --tribunal (ex.: tjpr, trf4)",
            "items": [],
            "cnj": digits,
        }
    key = api_key or get_api_key()
    res = fetch_search(alias, build_cnj_query(digits), api_key=key, timeout=timeout)
    if not res.get("ok"):
        return {
            "ok": False,
            "error": res.get("error"),
            "status": res.get("status"),
            "url": res.get("url"),
            "items": [],
            "cnj": digits,
            "tribunal_alias": alias,
        }
    data = res.get("data") or {}
    hits = ((data.get("hits") or {}).get("hits")) or []
    items = []
    for h in hits:
        src = h.get("_source") if isinstance(h, dict) else None
        if isinstance(src, dict):
            items.append(summarize_hit(src, tribunal_alias=alias))
    return {
        "ok": True,
        "cnj": digits,
        "cnj_formatted": format_cnj(digits),
        "tribunal_alias": alias,
        "url": res.get("url"),
        "total": ((data.get("hits") or {}).get("total") or {}),
        "items": items,
        "error": None if items else "zero hits",
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa datajud",
        description=(
            "Consulta capa/movimentos na API pública Datajud (por CNJ + tribunal). "
            "Não busca por nome de advogado."
        ),
    )
    ap.add_argument(
        "--cnj",
        action="append",
        dest="cnjs",
        required=True,
        help="Número CNJ (com ou sem máscara). Repetível.",
    )
    ap.add_argument(
        "--tribunal",
        default=None,
        help="Alias Datajud (tjpr, trf4, trt9…). Se omitido, tenta inferir do CNJ.",
    )
    ap.add_argument(
        "--api-key",
        default=None,
        help="APIKey Datajud (default: env DATAJUD_API_KEY ou chave wiki)",
    )
    ap.add_argument("--out", required=True, help="JSON envelope de saída")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)

    key = args.api_key or get_api_key()
    all_items: list[dict[str, Any]] = []
    errors: list[str] = []
    lookups = 0
    for raw in args.cnjs:
        lookups += 1
        result = lookup_cnj(
            raw,
            tribunal=args.tribunal,
            api_key=key,
            timeout=args.timeout,
        )
        if result.get("items"):
            all_items.extend(result["items"])
        if result.get("error"):
            errors.append(f"{digits_cnj(raw)}: {result['error']}")

    envelope = build_envelope(
        "datajud",
        source={
            "url": f"{BASE}/api_publica_{{tribunal}}/_search",
            "provider": "datajud_api_publica",
            "cnjs": [digits_cnj(c) for c in args.cnjs],
            "tribunal": normalize_alias(args.tribunal) if args.tribunal else None,
        },
        items=all_items,
        meta={
            "provider": "datajud",
            "lookups": lookups,
            "ok_count": len(all_items),
            "api_key_source": (
                "cli"
                if args.api_key
                else ("env" if os.environ.get("DATAJUD_API_KEY") or os.environ.get("DATAJUD_APIKEY") else "wiki_default")
            ),
        },
        errors=errors,
        notes=[
            "Datajud API pública: metadados de capa e movimentos; sem partes/advogados no índice típico.",
            "Busca por OAB/nome não é suportada de forma confiável — use tarrafa djen para advogados.",
            "Chave: DATAJUD_API_KEY no .env ou chave pública da wiki CNJ.",
            "Docs: https://datajud-wiki.cnj.jus.br/api-publica/",
        ],
    )
    out = Path(args.out)
    write_json(out, envelope)
    print(
        f"datajud: wrote {out}  ok={len(all_items)}/{lookups}  "
        f"errors={len(errors)}"
    )
    if not all_items:
        for e in errors:
            print(f"datajud: error: {e}", file=sys.stderr)
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
