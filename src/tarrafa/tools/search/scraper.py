# -*- coding: utf-8 -*-
"""
tarrafa search — descoberta material-only de URLs candidatas.

  tarrafa search --query '"Nome Completo" cidade' --out search.json
  tarrafa search --queries-file queries.txt --urls-out urls.txt --out search.json
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import DEFAULT_TIMEOUT
from tarrafa.core.writers import write_json
from tarrafa.tools.search.providers import (
    BaseSearchProvider,
    SearchProviderConfigurationError,
    SearchProviderError,
    resolve_provider,
)

_CPF_RE = re.compile(r"(?<!\d)\d{3}\.?\d{3}\.?\d{3}-?\d{2}(?!\d)")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?55[\s.-]*)?\(?\d{2}\)?[\s.-]*9?\d{4}[\s.-]*\d{4}(?!\d)"
)
_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "ref_src",
}


def query_sha256(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def sensitive_query_kinds(query: str) -> list[str]:
    kinds: list[str] = []
    if _CPF_RE.search(query):
        kinds.append("cpf")
    if _EMAIL_RE.search(query):
        kinds.append("email")
    if _PHONE_RE.search(query):
        kinds.append("telefone")
    return kinds


def redact_sensitive_query(query: str) -> str:
    text = _CPF_RE.sub("<CPF>", query)
    text = _EMAIL_RE.sub("<EMAIL>", text)
    return _PHONE_RE.sub("<TELEFONE>", text)


def canonicalize_url(url: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return None
    host = (parts.hostname or "").lower()
    if not host:
        return None
    try:
        port = parts.port
    except ValueError:
        return None
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        low = key.lower()
        if low.startswith("utm_") or low in _TRACKING_KEYS:
            continue
        query_pairs.append((key, value))
    query_pairs.sort()
    return urlunsplit(
        (
            parts.scheme.lower(),
            host,
            path,
            urlencode(query_pairs, doseq=True),
            "",
        )
    )


def _read_queries(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _query_records(queries: list[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, query in enumerate(queries, start=1):
        kinds = sensitive_query_kinds(query)
        records.append(
            {
                "id": f"Q{index:03d}",
                "query": query,
                "display": redact_sensitive_query(query) if kinds else query,
                # CPF tem espaço de busca pequeno: um SHA-256 público ainda permitiria
                # reidentificação por força bruta. Consultas sensíveis não recebem hash.
                "sha256": None if kinds else query_sha256(query),
                "sensitive_kinds": kinds,
            }
        )
    return records


def collect_search(
    provider: BaseSearchProvider,
    query_records: list[dict[str, Any]],
    *,
    max_results: int,
    country: str,
    language: str,
    freshness: str | None,
    safesearch: str,
) -> dict[str, Any]:
    candidates: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    requests = 0
    raw_results = 0
    max_pages = min(
        provider.max_pages,
        max(1, (max_results + provider.page_size - 1) // provider.page_size),
    )

    for query_record in query_records:
        query = str(query_record["query"])
        query_id = str(query_record["id"])
        accepted_for_query = 0
        seen_page_urls: set[str] = set()
        for page_number in range(1, max_pages + 1):
            try:
                result_page = provider.search_page(
                    query,
                    page=page_number,
                    country=country,
                    language=language,
                    freshness=freshness,
                    safesearch=safesearch,
                )
            except SearchProviderError as exc:
                errors.append(f"{query_id}: {exc}")
                break
            requests += 1
            raw_results += len(result_page.items)
            if not result_page.items:
                break
            new_on_page = 0
            for provider_rank, raw in enumerate(result_page.items, start=1):
                canonical = canonicalize_url(str(raw.get("url") or ""))
                if not canonical or canonical in seen_page_urls:
                    continue
                seen_page_urls.add(canonical)
                new_on_page += 1
                accepted_for_query += 1
                discovery = {
                    "query_id": query_id,
                    "provider_rank": (page_number - 1) * provider.page_size + provider_rank,
                    "page": page_number,
                }
                if canonical in candidates:
                    candidates[canonical]["discovered_by"].append(discovery)
                    continue
                split = urlsplit(canonical)
                candidates[canonical] = {
                    "kind": "search_candidate",
                    "provider": provider.name,
                    "url": str(raw.get("url") or canonical),
                    "canonical_url": canonical,
                    "domain": (split.hostname or "").lower(),
                    "title": str(raw.get("title") or ""),
                    "snippet": str(raw.get("snippet") or ""),
                    "published_at": raw.get("published_at"),
                    "language": raw.get("language"),
                    "engine": raw.get("engine"),
                    "provider_meta": raw.get("provider_meta") or {},
                    "discovered_by": [discovery],
                }
                if accepted_for_query >= max_results:
                    break
            if accepted_for_query >= max_results:
                break
            if not result_page.has_more or new_on_page == 0:
                break

    items = list(candidates.values())
    items.sort(
        key=lambda item: min(
            int(discovery["provider_rank"]) for discovery in item["discovered_by"]
        )
    )
    for rank, item in enumerate(items, start=1):
        item["rank"] = rank
    return {
        "items": items,
        "errors": errors,
        "meta": {
            "provider": provider.name,
            "queries": len(query_records),
            "requests": requests,
            "raw_results": raw_results,
            "deduplicated_results": len(items),
            "duplicates_removed": max(0, raw_results - len(items)),
            "max_results_per_query": max_results,
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa search",
        description=(
            "Busca web material-only: encontra URLs candidatas e registra a proveniência. "
            "Não confirma identidade nem captura o conteúdo das páginas."
        ),
    )
    ap.add_argument("--query", action="append", default=[], help="Consulta; repetível")
    ap.add_argument(
        "--queries-file",
        default=None,
        help="Arquivo UTF-8 com uma consulta por linha (# comentário)",
    )
    ap.add_argument("--provider", choices=["auto", "brave", "searxng"], default="auto")
    ap.add_argument(
        "--api-key",
        default=None,
        help="Chave Brave; prefira BRAVE_SEARCH_API_KEY no ambiente",
    )
    ap.add_argument(
        "--searxng-url",
        default=None,
        help="Endpoint da instância; ou configure SEARXNG_URL",
    )
    ap.add_argument("--max-results", type=int, default=20, help="Máximo por consulta")
    ap.add_argument("--country", default="BR", help="País de busca (default BR)")
    ap.add_argument("--language", default="pt-br", help="Idioma (default pt-br)")
    ap.add_argument(
        "--freshness",
        choices=["pd", "pw", "pm", "py"],
        default=None,
        help="Recência: pd=dia, pw=semana, pm=mês, py=ano",
    )
    ap.add_argument(
        "--safesearch",
        choices=["off", "moderate", "strict"],
        default="moderate",
    )
    ap.add_argument(
        "--allow-sensitive-query",
        action="store_true",
        help="Autoriza enviar CPF, e-mail ou telefone ao provedor externo",
    )
    ap.add_argument("--urls-out", default=None, help="Grava URLs canônicas, uma por linha")
    ap.add_argument("--out", required=True, help="Envelope JSON de saída")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    queries = list(args.query or [])
    if args.queries_file:
        query_path = Path(args.queries_file)
        if not query_path.is_file():
            print(f"search: arquivo de consultas não encontrado: {query_path}", file=sys.stderr)
            return 2
        try:
            queries.extend(_read_queries(query_path))
        except (OSError, UnicodeError) as exc:
            print(
                f"search: não foi possível ler o arquivo de consultas ({type(exc).__name__})",
                file=sys.stderr,
            )
            return 2
    seen_queries: set[str] = set()
    unique_queries: list[str] = []
    for raw_query in queries:
        query = raw_query.strip()
        if query and query not in seen_queries:
            seen_queries.add(query)
            unique_queries.append(query)
    queries = unique_queries
    if not queries:
        print("search: informe --query e/ou --queries-file", file=sys.stderr)
        return 2
    if args.max_results < 1 or args.max_results > 200:
        print("search: --max-results deve estar entre 1 e 200", file=sys.stderr)
        return 2
    out = Path(args.out)
    urls_out = Path(args.urls_out) if args.urls_out else None
    if urls_out and urls_out.resolve() == out.resolve():
        print("search: --out e --urls-out devem apontar para arquivos diferentes", file=sys.stderr)
        return 2

    query_records = _query_records(queries)
    sensitive = [record for record in query_records if record["sensitive_kinds"]]
    if sensitive and not args.allow_sensitive_query:
        details = ", ".join(
            f"{record['id']} ({'/'.join(record['sensitive_kinds'])})" for record in sensitive
        )
        print(
            "search: consulta sensível bloqueada. "
            f"Detectado: {details}. Use --allow-sensitive-query se o envio for intencional.",
            file=sys.stderr,
        )
        return 2

    try:
        provider = resolve_provider(
            args.provider,
            api_key=args.api_key,
            searxng_url=args.searxng_url,
            timeout=args.timeout,
        )
    except SearchProviderConfigurationError as exc:
        print(f"search: {exc}", file=sys.stderr)
        return 2

    result = collect_search(
        provider,
        query_records,
        max_results=args.max_results,
        country=args.country,
        language=args.language,
        freshness=args.freshness,
        safesearch=args.safesearch,
    )
    public_queries = [
        {
            "id": record["id"],
            "display": record["display"],
            "sha256": record["sha256"],
            "sensitive_kinds": record["sensitive_kinds"],
        }
        for record in query_records
    ]
    envelope = build_envelope(
        "search",
        source={"provider": provider.name, "queries": public_queries},
        items=result["items"],
        meta={
            **result["meta"],
            "country": args.country.upper(),
            "language": args.language,
            "freshness": args.freshness,
            "safesearch": args.safesearch,
            "urls_out": str(urls_out) if urls_out else None,
        },
        errors=result["errors"],
        notes=[
            "Resultados de busca são candidatos, não fatos nem confirmação de identidade.",
            "Capture e valide as páginas antes de citar qualquer achado.",
            "Consultas sensíveis são mascaradas no envelope e bloqueadas por padrão.",
        ],
    )
    if urls_out and urls_out.exists():
        try:
            from tarrafa.core.runtime import get_runtime

            runtime = get_runtime()
            if runtime.no_clobber and not runtime.force:
                raise FileExistsError(
                    f"refusing to overwrite {urls_out} "
                    "(no_clobber; pass --force or set defaults.force)"
                )
        except FileExistsError:
            raise
        except Exception:
            pass
    write_json(out, envelope)
    if urls_out:
        urls_out.parent.mkdir(parents=True, exist_ok=True)
        urls_out.write_text(
            "".join(f"{item['canonical_url']}\n" for item in result["items"]),
            encoding="utf-8",
        )
        try:
            from tarrafa.core.run import register_artifact

            register_artifact(urls_out, kind="urls")
        except Exception:
            pass

    print(
        f"search: wrote {out}  provider={provider.name}  "
        f"queries={len(query_records)}  candidates={len(result['items'])}  "
        f"errors={len(result['errors'])}"
    )
    if result["errors"]:
        for error in result["errors"][:10]:
            print(f"  warn: {error}", file=sys.stderr)
    if result["items"] and result["errors"]:
        return 1
    if not result["items"] and result["errors"]:
        return 1
    if not result["items"]:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
