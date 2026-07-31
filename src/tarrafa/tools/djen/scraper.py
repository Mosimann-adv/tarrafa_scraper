# -*- coding: utf-8 -*-
"""
tarrafa djen — comunicações do DJEN (ComunicaAPI pública).

Uso típico — advogado (OAB):

  tarrafa djen --oab 12345 --uf SP --out djen.json
  tarrafa djen --papel advogado --oab 12345 --uf SP --from 2026-01-01 --out djen.json

Uso típico — parte (busca no teor; sem pós-filtro OAB):

  tarrafa djen --papel parte --cpf "<CPF>" --out djen.json
  tarrafa djen --papel parte --nome "Nome Completo" --out djen.json
  tarrafa djen --papel parte --texto "handle_exemplo" --max-items 50 --out djen.json
  tarrafa djen --papel parte --cpf "<CPF>" --follow-datajud --datajud-out datajud.json

API: GET https://comunicaapi.pje.jus.br/api/v1/comunicacao
Swagger: https://comunicaapi.pje.jus.br/swagger/index.html (djen.yml)

Notas:
  - itensPorPagina só aceita 5 ou 100.
  - API limita consultas a 10.000 resultados no total.
  - papel=advogado: pós-filtra OAB/nome em destinatarioadvogados e texto.
  - papel=parte: --cpf tem prioridade sobre nome/texto e exige correspondência exata local;
    sem CPF, extrai identity_hints do teor e o nexo exige outra âncora.
  - Não é inventário completo de processos — só publicações no diário.
"""
from __future__ import annotations

import argparse
import html as html_lib
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import DEFAULT_TIMEOUT, DEFAULT_UA, ensure_httpx
from tarrafa.core.identity_extract import (
    cpf_has_valid_dv,
    digits_only,
    extract_identity_hints,
    format_cpf,
    merge_hints,
)
from tarrafa.core.writers import write_json

BASE_URL = "https://comunicaapi.pje.jus.br/api/v1/comunicacao"
MAX_API_TOTAL = 10_000


def strip_html(text: str) -> str:
    if not text:
        return ""
    t = html_lib.unescape(text)
    t = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", t)
    t = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def normalize_oab(oab: str) -> str:
    return re.sub(r"\D", "", oab or "")


def normalize_cpf(cpf: str) -> str | None:
    """Normaliza CPF para a forma usada na consulta textual da ComunicaAPI."""
    return format_cpf(cpf)


def mask_cpf(cpf: str) -> str | None:
    """Mascara CPF para metadados sem repetir o identificador completo."""
    digits = digits_only(cpf)
    if len(digits) != 11:
        return None
    return f"***.***.***-{digits[-2:]}"


def cpf_query_variants(cpf: str) -> list[tuple[str, str]]:
    """Retorna consultas textuais em ordem de prioridade, sem duplicatas."""
    formatted = normalize_cpf(cpf)
    if not formatted:
        return []
    variants = [
        ("cpf_formatado", formatted),
        ("cpf_digitos", digits_only(cpf)),
    ]
    unique: list[tuple[str, str]] = []
    for kind, value in variants:
        if value not in [existing for _, existing in unique]:
            unique.append((kind, value))
    return unique


def item_matches_cpf(item: dict[str, Any], cpf: str) -> bool:
    """Confere CPF exato no teor ou no destinatário estruturado retornado pela API."""
    target = digits_only(cpf)
    if len(target) != 11:
        return False

    for destinatario in item.get("destinatarios") or []:
        if not isinstance(destinatario, dict):
            continue
        if digits_only(str(destinatario.get("cpf_cnpj") or "")) == target:
            return True

    texto = strip_html(str(item.get("texto") or ""))
    flexible = r"(?<!\d)" + r"[\s./-]*".join(re.escape(d) for d in target) + r"(?!\d)"
    return re.search(flexible, texto) is not None


def item_matches_lawyer(
    item: dict[str, Any],
    *,
    oab: str | None,
    uf: str | None,
    nome: str | None,
) -> bool:
    """Prefer structured destinatarioadvogados; fallback to plain text."""
    oab_d = normalize_oab(oab or "")
    uf_u = (uf or "").strip().upper()
    nome_n = (nome or "").strip().casefold()

    dest = item.get("destinatarioadvogados") or []
    if isinstance(dest, list) and dest:
        for d in dest:
            adv = (d or {}).get("advogado") or {}
            n_oab = normalize_oab(str(adv.get("numero_oab") or ""))
            n_uf = str(adv.get("uf_oab") or "").strip().upper()
            n_nome = str(adv.get("nome") or "").casefold()
            oab_ok = (not oab_d) or (n_oab == oab_d) or (n_oab.lstrip("0") == oab_d.lstrip("0"))
            uf_ok = (not uf_u) or (n_uf == uf_u)
            nome_ok = (not nome_n) or (nome_n in n_nome)
            if oab_ok and uf_ok and (nome_ok if nome_n else True):
                if oab_d or nome_n:
                    return True
        # structured list present but no match
        if oab_d or nome_n:
            # still allow text fallback
            pass

    text = strip_html(str(item.get("texto") or ""))
    text_cf = text.casefold()
    if oab_d:
        # SP12345, 12345, 12.345
        patterns = [
            re.escape(oab_d),
            re.escape(oab_d.zfill(6)),
            re.escape(oab_d.lstrip("0") or oab_d),
        ]
        if not any(re.search(p, text, re.I) for p in patterns):
            if nome_n and nome_n in text_cf:
                return True
            return False
        if uf_u and uf_u.casefold() not in text_cf and f"oab {uf_u}".casefold() not in text_cf:
            # OAB number found; UF optional in text
            pass
        return True
    if nome_n:
        return nome_n in text_cf
    return True


def resolve_papel(
    papel: str | None,
    *,
    oab: str | None,
    nome: str | None,
    texto: str | None,
    cpf: str | None = None,
) -> str:
    """Return 'advogado' | 'parte'."""
    p = (papel or "auto").strip().lower()
    if p in ("parte", "party", "parte_interessada"):
        return "parte"
    if p in ("advogado", "lawyer", "oab"):
        return "advogado"
    # auto
    if cpf:
        return "parte"
    if oab or nome:
        return "advogado"
    if texto:
        return "parte"
    return "advogado"


def summarize_item(item: dict[str, Any], *, extract_hints: bool = False) -> dict[str, Any]:
    dest_adv = []
    for d in item.get("destinatarioadvogados") or []:
        adv = (d or {}).get("advogado") or {}
        dest_adv.append(
            {
                "nome": adv.get("nome"),
                "numero_oab": adv.get("numero_oab"),
                "uf_oab": adv.get("uf_oab"),
            }
        )
    texto_plain = strip_html(str(item.get("texto") or ""))
    out: dict[str, Any] = {
        "kind": "djen_comunicacao",
        "id": item.get("id"),
        "hash": item.get("hash"),
        "data_disponibilizacao": item.get("data_disponibilizacao") or item.get("datadisponibilizacao"),
        "sigla_tribunal": item.get("siglaTribunal"),
        "tipo": item.get("tipoComunicacao"),
        "orgao": item.get("nomeOrgao"),
        "classe": item.get("nomeClasse"),
        "codigo_classe": item.get("codigoClasse"),
        "numero_processo": item.get("numero_processo"),
        "numero_processo_mascara": item.get("numeroprocessocommascara"),
        "meio": item.get("meio") or item.get("meiocompleto"),
        "link": item.get("link"),
        "advogados_destinatarios": dest_adv,
        "texto_plain": texto_plain[:2000],
        "texto_len": len(texto_plain),
    }
    if extract_hints:
        # Use longer plain text for hints (same strip, more chars)
        full_plain = texto_plain if len(texto_plain) >= 2000 else strip_html(str(item.get("texto") or ""))
        # Prefer full strip up to 12k for extraction
        full_plain = strip_html(str(item.get("texto") or ""))[:12000]
        out["identity_hints"] = extract_identity_hints(full_plain)
    return out


def build_summary(
    items: list[dict[str, Any]],
    *,
    api_count: int | None,
    papel: str = "advogado",
) -> dict[str, Any]:
    tribunais = Counter()
    tipos = Counter()
    classes = Counter()
    processos: set[str] = set()
    hint_list: list[dict[str, Any]] = []
    for it in items:
        tribunais[str(it.get("sigla_tribunal") or "?")] += 1
        tipos[str(it.get("tipo") or "?")] += 1
        if it.get("classe"):
            classes[str(it.get("classe"))] += 1
        cnj = it.get("numero_processo_mascara") or it.get("numero_processo")
        if cnj:
            processos.add(str(cnj))
        if isinstance(it.get("identity_hints"), dict):
            hint_list.append(it["identity_hints"])
    summary: dict[str, Any] = {
        "api_count_reported": api_count,
        "items_kept": len(items),
        "unique_processos": len(processos),
        "processos_sample": sorted(processos)[:50],
        "by_tribunal": dict(tribunais.most_common(30)),
        "by_tipo": dict(tipos.most_common(20)),
        "by_classe": dict(classes.most_common(20)),
        "papel": papel,
    }
    if hint_list:
        summary["identity_hints"] = merge_hints(hint_list)
    return summary


def fetch_page(
    params: dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    httpx = ensure_httpx()
    qs = urlencode({k: v for k, v in params.items() if v is not None and v != ""})
    url = f"{BASE_URL}?{qs}"
    headers = {"User-Agent": DEFAULT_UA, "Accept": "application/json"}
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
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
            if not isinstance(data, dict):
                return {
                    "ok": False,
                    "status": r.status_code,
                    "url": url,
                    "data": None,
                    "error": "Resposta não-JSON",
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


def collect_comunicacoes(
    *,
    oab: str | None = None,
    uf: str | None = None,
    nome: str | None = None,
    texto: str | None = None,
    cpf: str | None = None,
    numero_processo: str | None = None,
    tribunal: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    max_items: int = 200,
    page_size: int = 100,
    post_filter: bool = True,
    papel: str = "advogado",
    extract_hints: bool | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    if page_size not in (5, 100):
        page_size = 100
    max_items = max(1, min(max_items, MAX_API_TOTAL))
    if extract_hints is None:
        extract_hints = papel == "parte"

    cpf_normalizado = normalize_cpf(cpf or "") if cpf else None
    if cpf and not cpf_normalizado:
        raise ValueError("CPF inválido: informe 11 dígitos não repetidos")

    base_params: dict[str, Any] = {
        "itensPorPagina": page_size,
    }
    if oab:
        base_params["numeroOab"] = normalize_oab(oab)
    if uf:
        base_params["ufOab"] = uf.strip().upper()
    if nome and papel == "advogado":
        base_params["nomeAdvogado"] = nome.strip()
    if texto and not cpf_normalizado:
        base_params["texto"] = texto
    elif nome and papel == "parte" and not cpf_normalizado:
        base_params["nomeParte"] = nome.strip()
    if numero_processo:
        base_params["numeroProcesso"] = re.sub(r"\D", "", numero_processo)
    if tribunal:
        base_params["siglaTribunal"] = tribunal.strip().upper()
    if date_from:
        base_params["dataDisponibilizacaoInicio"] = date_from
    if date_to:
        base_params["dataDisponibilizacaoFim"] = date_to

    kept: list[dict[str, Any]] = []
    raw_fetched = 0
    api_count: int | None = None
    api_counts: dict[str, int | None] = {}
    errors: list[str] = []
    pages = 0
    seen_ids: set[Any] = set()
    query_specs = (
        cpf_query_variants(cpf_normalizado)
        if cpf_normalizado
        else [("consulta_padrao", None)]
    )
    queries_requested: list[str] = []
    # Over-fetch a bit because post_filter may discard rows
    max_pages = max(1, min(100, (max_items * 3 + page_size - 1) // page_size + 2))
    for query_kind, query_text in query_specs:
        if len(kept) >= max_items:
            break
        queries_requested.append(query_kind)
        query_raw_fetched = 0
        query_seen_ids: set[Any] = set()
        query_count: int | None = None
        for page in range(1, max_pages + 1):
            if len(kept) >= max_items:
                break
            params = dict(base_params)
            if query_text:
                params["texto"] = query_text
            params["pagina"] = page
            params["itensPorPagina"] = page_size
            res = fetch_page(params, timeout=timeout)
            pages += 1
            if not res.get("ok"):
                errors.append(f"{query_kind}: {res.get('error') or 'fetch failed'}")
                break
            data = res["data"] or {}
            try:
                query_count = int(data.get("count") or 0)
            except Exception:
                query_count = None
            if query_kind not in api_counts:
                api_counts[query_kind] = query_count
            items = data.get("items") or []
            if not items:
                break
            page_ids = [it.get("id") for it in items if isinstance(it, dict)]
            if page_ids and all(i in query_seen_ids for i in page_ids if i is not None):
                # pagination stuck / repeated page within the same query variant
                break
            query_raw_fetched += len(items)
            raw_fetched += len(items)
            for it in items:
                if not isinstance(it, dict):
                    continue
                iid = it.get("id")
                if iid is not None:
                    query_seen_ids.add(iid)
                    if iid in seen_ids:
                        continue
                    seen_ids.add(iid)
                if cpf_normalizado and not item_matches_cpf(it, cpf_normalizado):
                    continue
                if post_filter and papel == "advogado" and (oab or nome):
                    if not item_matches_lawyer(it, oab=oab, uf=uf, nome=nome):
                        continue
                kept.append(summarize_item(it, extract_hints=extract_hints))
                if len(kept) >= max_items:
                    break
            if len(items) < page_size:
                break
            if query_count is not None and query_raw_fetched >= min(query_count, MAX_API_TOTAL):
                break
    known_counts = [count for count in api_counts.values() if count is not None]
    api_count = max(known_counts) if known_counts else None
    summary = build_summary(kept, api_count=api_count, papel=papel)
    public_params = {k: v for k, v in base_params.items() if k != "itensPorPagina"}
    if cpf_normalizado:
        public_params["cpf"] = mask_cpf(cpf_normalizado)
    return {
        "items": kept,
        "summary": summary,
        "errors": errors,
        "meta": {
            "api_count_reported": api_count,
            "raw_fetched": raw_fetched,
            "pages_requested": pages,
            "page_size": page_size,
            "max_items": max_items,
            "post_filter": post_filter and papel == "advogado",
            "cpf_exact_filter": bool(cpf_normalizado),
            "search_priority": "cpf" if cpf_normalizado else "default",
            "query_variants": queries_requested,
            "api_counts_reported": api_counts,
            "papel": papel,
            "extract_hints": extract_hints,
            "params": public_params,
        },
    }


def _follow_datajud(
    cnjs: list[str],
    *,
    out_path: Path,
    max_cnj: int,
    timeout: float,
) -> dict[str, Any]:
    from tarrafa.tools.datajud.scraper import digits_cnj, get_api_key, lookup_cnj

    key = get_api_key()
    selected = cnjs[: max(1, max_cnj)]
    all_items: list[dict[str, Any]] = []
    errors: list[str] = []
    for raw in selected:
        result = lookup_cnj(raw, api_key=key, timeout=timeout)
        if result.get("items"):
            all_items.extend(result["items"])
        if result.get("error"):
            errors.append(f"{digits_cnj(raw)}: {result['error']}")
    envelope = build_envelope(
        "datajud",
        source={
            "provider": "datajud_api_publica",
            "from": "djen_follow",
            "cnjs": [digits_cnj(c) for c in selected],
        },
        items=all_items,
        meta={
            "provider": "datajud",
            "lookups": len(selected),
            "ok_count": len(all_items),
            "requested_cnjs": selected,
        },
        errors=errors,
        notes=[
            "Gerado via tarrafa djen --follow-datajud a partir de processos_sample do DJEN.",
            "Datajud não lista partes; nexo de identidade vem do teor DJEN / outras fontes.",
        ],
    )
    write_json(out_path, envelope)
    return {"path": str(out_path), "ok": len(all_items), "lookups": len(selected), "errors": errors}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa djen",
        description=(
            "Consulta comunicações do DJEN (ComunicaAPI). "
            "Advogado: --oab + --uf. Parte: priorize --cpf; nome/handle usam --nome/--texto. "
            "Material-only; não é lista completa de processos."
        ),
    )
    ap.add_argument(
        "--papel",
        choices=["auto", "advogado", "parte"],
        default="auto",
        help=(
            "advogado = pós-filtro OAB/nome; parte = busca teor sem filtro OAB + identity_hints; "
            "auto = cpf->parte, oab/nome->advogado, só texto->parte (default)"
        ),
    )
    ap.add_argument("--oab", default=None, help="Número OAB (só dígitos ou máscara)")
    ap.add_argument("--uf", default=None, help="UF da OAB (ex.: PR)")
    ap.add_argument(
        "--cpf",
        default=None,
        help="CPF da parte; tem prioridade sobre --nome/--texto e recebe conferência exata local",
    )
    ap.add_argument(
        "--nome",
        default=None,
        help="Nome (advogado: filtro API+pós-filtro; parte: filtro nomeParte se texto omitido)",
    )
    ap.add_argument("--texto", default=None, help="Busca livre no teor (recomendado para partes)")
    ap.add_argument("--processo", default=None, dest="numero_processo", help="Número do processo")
    ap.add_argument("--tribunal", default=None, help="Sigla tribunal (ex.: TJPR, TRF4)")
    ap.add_argument("--from", dest="date_from", default=None, help="Data início yyyy-mm-dd")
    ap.add_argument("--to", dest="date_to", default=None, help="Data fim yyyy-mm-dd")
    ap.add_argument(
        "--max-items",
        type=int,
        default=200,
        help="Máximo de comunicações a reter após filtro (default 200)",
    )
    ap.add_argument(
        "--page-size",
        type=int,
        default=100,
        choices=[5, 100],
        help="itensPorPagina da API (5 ou 100)",
    )
    ap.add_argument(
        "--no-post-filter",
        action="store_true",
        help="Não pós-filtrar por OAB/nome (só relevante em papel=advogado)",
    )
    ap.add_argument(
        "--no-hints",
        action="store_true",
        help="Não extrair identity_hints do teor (default: extrai em papel=parte)",
    )
    ap.add_argument(
        "--follow-datajud",
        action="store_true",
        help="Após DJEN, consultar Datajud nos CNJs de processos_sample",
    )
    ap.add_argument(
        "--datajud-out",
        default=None,
        help="Saída JSON do Datajud (default: <out> com sufixo .datajud.json)",
    )
    ap.add_argument(
        "--max-cnj",
        type=int,
        default=15,
        help="Máximo de CNJs a enviar ao Datajud com --follow-datajud (default 15)",
    )
    ap.add_argument("--out", required=True, help="JSON envelope de saída")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    args = ap.parse_args(argv)

    if not any([args.oab, args.nome, args.texto, args.cpf, args.numero_processo]):
        print(
            "djen: informe ao menos --oab, --cpf, --nome, --texto ou --processo",
            file=sys.stderr,
        )
        return 2

    papel = resolve_papel(
        args.papel, oab=args.oab, nome=args.nome, texto=args.texto, cpf=args.cpf
    )
    cpf_normalizado = normalize_cpf(args.cpf or "") if args.cpf else None
    if args.cpf and not cpf_normalizado:
        print("djen: --cpf inválido: informe 11 dígitos não repetidos", file=sys.stderr)
        return 2
    if cpf_normalizado and not cpf_has_valid_dv(cpf_normalizado):
        # Não bloqueia: a consulta segue. Mas zero resultados de um CPF com dígito
        # verificador errado é sintoma de digitação, não ausência de processos.
        print(
            f"djen: aviso: --cpf {mask_cpf(cpf_normalizado)} tem dígito verificador "
            "inválido; zero resultados aqui provavelmente indica erro de digitação",
            file=sys.stderr,
        )
    if args.cpf and papel != "parte":
        print("djen: --cpf só pode ser usado com --papel parte (ou --papel auto)", file=sys.stderr)
        return 2
    if args.oab and not args.uf and papel == "advogado":
        print("djen: aviso: --oab sem --uf costuma ser mais ruidoso", file=sys.stderr)
    if papel == "parte" and not (args.cpf or args.texto or args.nome or args.numero_processo):
        print(
            "djen: papel=parte: priorize --cpf; alternativamente use --nome ou --texto",
            file=sys.stderr,
        )
        return 2

    # Party mode: never lawyer post-filter unless user forces (not exposed; use advogado)
    post_filter = (not args.no_post_filter) and papel == "advogado"
    extract_hints = (papel == "parte") and (not args.no_hints)
    if papel == "advogado" and not args.no_hints:
        # optional light hints off by default for lawyer noise; keep off
        extract_hints = False

    result = collect_comunicacoes(
        oab=args.oab,
        uf=args.uf,
        nome=args.nome,
        texto=args.texto,
        cpf=args.cpf,
        numero_processo=args.numero_processo,
        tribunal=args.tribunal,
        date_from=args.date_from,
        date_to=args.date_to,
        max_items=args.max_items,
        page_size=args.page_size,
        post_filter=post_filter,
        papel=papel,
        extract_hints=extract_hints,
        timeout=args.timeout,
    )

    items = result["items"]
    # summary item first for quick consumption
    envelope_items: list[dict[str, Any]] = [
        {"kind": "djen_summary", **result["summary"]},
        *items,
    ]
    notes = [
        "DJEN/ComunicaAPI: publicações de comunicações processuais, não autos completos.",
        "API reporta count global; items são amostra paginada + pós-filtro local (se advogado).",
        "Swagger: https://comunicaapi.pje.jus.br/swagger/index.html",
    ]
    if papel == "advogado":
        notes.append(
            "papel=advogado: preferir --oab + --uf; pós-filtro em destinatarioadvogados/texto."
        )
    else:
        notes.extend(
            [
                "papel=parte: busca no teor; sem pós-filtro OAB; identity_hints no summary/itens.",
                "Não fundir processos só por nome curto — cruzar handle, CPF, cidade ou CNPJ.",
                "Homônimo: trate processos sem âncora de nexo como gap, não como fato.",
            ]
        )
        if cpf_normalizado:
            notes.append(
                "CPF priorizado: --nome/--texto não foram usados na consulta; "
                "foram consultadas as formas formatada e sem pontuação, com "
                "deduplicação e conferência local pelo CPF exato."
            )

    envelope = build_envelope(
        "djen",
        source={
            "url": BASE_URL,
            "provider": "comunicaapi_djen",
            "papel": papel,
            "oab": normalize_oab(args.oab) if args.oab else None,
            "uf": (args.uf or "").upper() or None,
            "cpf": mask_cpf(cpf_normalizado or "") if cpf_normalizado else None,
            "nome": args.nome,
            "texto": args.texto,
            "search_priority": "cpf" if cpf_normalizado else "default",
        },
        items=envelope_items,
        meta=result["meta"],
        errors=result["errors"],
        notes=notes,
    )
    out = Path(args.out)
    write_json(out, envelope)
    s = result["summary"]
    print(
        f"djen: wrote {out}  papel={papel}  kept={s['items_kept']}  "
        f"api_count={s.get('api_count_reported')}  "
        f"processos~{s['unique_processos']}  "
        f"errors={len(result['errors'])}"
    )

    if args.follow_datajud:
        sample = list(s.get("processos_sample") or [])
        if not sample:
            print("djen: --follow-datajud: nenhum CNJ em processos_sample", file=sys.stderr)
        else:
            dj_out = Path(args.datajud_out) if args.datajud_out else out.with_suffix(".datajud.json")
            if dj_out.resolve() == out.resolve():
                dj_out = out.with_name(out.stem + ".datajud.json")
            try:
                follow = _follow_datajud(
                    sample,
                    out_path=dj_out,
                    max_cnj=args.max_cnj,
                    timeout=args.timeout,
                )
                print(
                    f"djen: datajud follow -> {follow['path']}  "
                    f"ok={follow['ok']}/{follow['lookups']}  "
                    f"errors={len(follow['errors'])}"
                )
            except Exception as e:
                print(f"djen: follow-datajud falhou: {type(e).__name__}: {e}", file=sys.stderr)
                return 2

    if not items and result["errors"]:
        return 6
    if not items:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
