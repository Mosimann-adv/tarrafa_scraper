# -*- coding: utf-8 -*-
"""tarrafa profile — descoberta iterativa e expansão de presença pública.

O comando não produz biografia nem classifica pessoas. Ele:

1. gera consultas diversificadas a partir de âncoras não sensíveis;
2. registra resultados de Brave/SearXNG ou de um repasse externo;
3. captura candidatos públicos sem sessão autenticada;
4. extrai pivôs seguros e executa novas rodadas quando há provedor;
5. identifica domínios próprios prováveis e faz crawl same-host;
6. inventaria conteúdo autoral, emite uma matriz de cobertura e gera HTML.

CPF, e-mail completo e telefone não são aceitos como âncoras de busca.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

from tarrafa.core.crawl import crawl
from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import fetch_url, same_registrable_host
from tarrafa.core.writers import write_json
from tarrafa.tools.dossier.scraper import build_dossier
from tarrafa.tools.ig.scraper import (
    instagram_media_urls,
    instagram_profile_url,
    shortcode_from_url,
)
from tarrafa.tools.ig.scraper import main as ig_main
from tarrafa.tools.page.scraper import capture_page
from tarrafa.tools.search.providers import (
    BaseSearchProvider,
    SearchProviderConfigurationError,
    resolve_provider,
)
from tarrafa.tools.search.scraper import (
    _query_records,
    canonicalize_url,
    collect_from_agent,
    collect_search,
    read_agent_handoff,
    sensitive_query_kinds,
)

_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+\-]{3,})@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
_OAB_RE = re.compile(
    r"\bOAB\s*[/\-]?\s*([A-Z]{2})?\s*[\s.:#-]*([0-9][0-9.\-]{2,})\b",
    re.IGNORECASE,
)
_SITEMAP_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_ROBOTS_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_ARTICLE_PATH_RE = re.compile(
    r"/(?:blog|artigos?|articles?|noticias?|publicacoes?|insights?|conteudos?|author|autor)(?:/|$)",
    re.IGNORECASE,
)
_ARTICLE_TITLE_RE = re.compile(
    r"\b(?:artigo|análise|guia|entenda|perspectiva|comentário|informativo)\b",
    re.IGNORECASE,
)

_NAME_PARTICLES = {"da", "das", "de", "do", "dos", "e"}
_PUBLIC_OR_PLATFORM_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "youtube.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "jusbrasil.com.br",
    "escavador.com",
    "google.com",
}
_INSTITUTIONAL_SUFFIXES = (
    ".gov.br",
    ".jus.br",
    ".leg.br",
    ".mp.br",
    ".edu.br",
)
_PROFESSIONAL_DIRECTORY_HINTS = (
    "linkedin.",
    "juriscorrespondente.",
    "advogados",
    "oab-",
    ".oab.",
    "conselho",
    "profissionais",
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value))


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _root_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme or "https", parts.netloc, "/", "", ""))


def _host_matches(host: str, expected: str) -> bool:
    host = host.lower().removeprefix("www.")
    expected = expected.lower().removeprefix("www.")
    return host == expected or host.endswith(f".{expected}")


def _is_platform_host(host: str) -> bool:
    return any(_host_matches(host, known) for known in _PUBLIC_OR_PLATFORM_HOSTS)


def _is_institutional_host(host: str) -> bool:
    return host.endswith(_INSTITUTIONAL_SUFFIXES)


def _name_parts(name: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", name or "")
        if _fold(token) not in _NAME_PARTICLES
    ]


def _short_name(name: str) -> str:
    parts = _name_parts(name)
    if len(parts) >= 2:
        return f"{parts[0]} {parts[-1]}"
    return " ".join(parts) or name.strip()


def _handle_value(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").strip()


def _query_input_has_sensitive_data(values: Iterable[str]) -> list[str]:
    kinds: set[str] = set()
    for value in values:
        kinds.update(sensitive_query_kinds(value or ""))
    return sorted(kinds)


def generate_initial_queries(
    *,
    name: str,
    handle: str | None = None,
    profession: str | None = None,
    location: str | None = None,
    organization: str | None = None,
    keywords: Iterable[str] = (),
) -> list[str]:
    """Gera uma matriz curta que combina nome civil, nome curto e contexto."""
    short = _short_name(name)
    quoted_name = f'"{name.strip()}"'
    quoted_short = f'"{short}"'
    handle_value = _handle_value(handle)
    context = _unique([profession or "", location or "", organization or "", *keywords])

    queries = [
        quoted_name,
        quoted_short,
        f"{quoted_name} {profession}" if profession else "",
        f"{quoted_short} {profession}" if profession else "",
        f"{quoted_name} {location}" if location else "",
        f"{quoted_short} {location}" if location else "",
        f"{quoted_name} autor OR artigo",
        f"{quoted_short} blog OR artigo OR autor",
        f"{quoted_short} entrevista OR palestra OR evento",
    ]
    for value in context[:4]:
        queries.append(f"{quoted_short} {value}")
    if handle_value:
        queries.extend(
            [
                f'"{handle_value}"',
                f'"{handle_value}" {quoted_short}',
            ]
        )
    if organization:
        queries.append(f'{quoted_short} "{organization}"')
    return _unique(queries)


def _candidate_text(candidate: dict[str, Any]) -> str:
    return " ".join(
        str(candidate.get(key) or "")
        for key in ("url", "canonical_url", "domain", "title", "snippet")
    )


def classify_domain(host: str) -> str:
    folded = _fold(host)
    if _is_platform_host(host):
        return "social_or_platform"
    if _is_institutional_host(host):
        return "institutional"
    if any(hint in folded for hint in _PROFESSIONAL_DIRECTORY_HINTS):
        return "professional_directory"
    return "independent"


def score_candidate(
    candidate: dict[str, Any],
    *,
    name: str,
    handle: str | None = None,
    profession: str | None = None,
    organization: str | None = None,
    keywords: Iterable[str] = (),
) -> dict[str, Any]:
    """Pontua nexo sem transformar candidato em fato confirmado."""
    text = _fold(_candidate_text(candidate))
    host = _host(str(candidate.get("canonical_url") or candidate.get("url") or ""))
    host_compact = _compact(host)
    full_compact = _compact(name)
    short = _short_name(name)
    short_compact = _compact(short)
    surname = _compact((_name_parts(name) or [""])[-1])
    handle_compact = _compact(_handle_value(handle))
    score = 0
    reasons: list[str] = []

    if full_compact and full_compact in _compact(text):
        score += 45
        reasons.append("nome_completo")
    elif short_compact and short_compact in _compact(text):
        score += 32
        reasons.append("nome_curto")
    else:
        parts = [_fold(part) for part in _name_parts(name)]
        matches = sum(1 for part in parts if len(part) >= 3 and part in text)
        if matches >= 2:
            score += 18
            reasons.append("partes_do_nome")

    if handle_compact and handle_compact in _compact(text):
        score += 35
        reasons.append("handle")
    if surname and surname in host_compact:
        score += 22
        reasons.append("sobrenome_no_dominio")
    if profession and _fold(profession) in text:
        score += 12
        reasons.append("profissao")
    if organization and _fold(organization) in text:
        score += 12
        reasons.append("organizacao")
    for keyword in _unique(keywords):
        if len(keyword) >= 3 and _fold(keyword) in text:
            score += 4
            reasons.append(f"palavra_chave:{keyword}")

    domain_class = classify_domain(host)
    if domain_class == "social_or_platform":
        score -= 8
    elif domain_class == "institutional":
        score -= 4
    elif domain_class == "independent":
        score += 5

    enriched = dict(candidate)
    enriched["domain"] = host
    enriched["domain_class"] = domain_class
    enriched["identity_score"] = max(0, score)
    enriched["score_reasons"] = reasons
    return enriched


def rank_candidates(
    candidates: Iterable[dict[str, Any]],
    *,
    name: str,
    handle: str | None = None,
    profession: str | None = None,
    organization: str | None = None,
    keywords: Iterable[str] = (),
) -> list[dict[str, Any]]:
    ranked = [
        score_candidate(
            candidate,
            name=name,
            handle=handle,
            profession=profession,
            organization=organization,
            keywords=keywords,
        )
        for candidate in candidates
    ]
    ranked.sort(
        key=lambda item: (
            -int(item.get("identity_score") or 0),
            int(item.get("rank") or 999999),
            str(item.get("canonical_url") or item.get("url") or ""),
        )
    )
    for position, item in enumerate(ranked, start=1):
        item["profile_rank"] = position
    return ranked


def _merge_candidates(
    destination: dict[str, dict[str, Any]],
    items: Iterable[dict[str, Any]],
) -> int:
    added = 0
    for raw in items:
        canonical = canonicalize_url(str(raw.get("canonical_url") or raw.get("url") or ""))
        if not canonical:
            continue
        if canonical in destination:
            current = destination[canonical]
            discoveries = list(current.get("discovered_by") or [])
            for discovery in raw.get("discovered_by") or []:
                if discovery not in discoveries:
                    discoveries.append(discovery)
            current["discovered_by"] = discoveries
            continue
        item = dict(raw)
        item["canonical_url"] = canonical
        item["domain"] = _host(canonical)
        destination[canonical] = item
        added += 1
    return added


def _seed_candidate(url: str, *, label: str) -> dict[str, Any] | None:
    canonical = canonicalize_url(url)
    if not canonical:
        return None
    return {
        "kind": "search_candidate",
        "provider": "seed",
        "url": url,
        "canonical_url": canonical,
        "domain": _host(canonical),
        "title": label,
        "snippet": "",
        "published_at": None,
        "language": None,
        "engine": "seed",
        "provider_meta": {},
        "discovered_by": [{"query_id": "SEED", "provider_rank": 0, "page": 0}],
    }


def _slim_capture(item: dict[str, Any], *, score: int) -> dict[str, Any]:
    text = str(item.get("text") or item.get("text_main") or "")
    return {
        "kind": "profile_page_capture",
        "url": item.get("url"),
        "final_url": item.get("final_url"),
        "status": item.get("status"),
        "title": item.get("title"),
        "author": item.get("author"),
        "date": item.get("date"),
        "text_excerpt": text[:4000],
        "text_len": len(text),
        "links": list(item.get("links") or [])[:200],
        "links_count": item.get("links_count"),
        "extract_method": item.get("extract_method"),
        "identity_score": score,
        "errors": list(item.get("errors") or []),
    }


def _capture_candidates(
    ranked: list[dict[str, Any]],
    *,
    already_captured: set[str],
    max_new: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    captures: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in ranked:
        if len(captures) >= max_new:
            break
        url = str(candidate.get("canonical_url") or candidate.get("url") or "")
        if not url or url in already_captured:
            continue
        already_captured.add(url)
        try:
            result = capture_page(
                url,
                mode="auto",
                storage_state=None,
                timeout=timeout,
                include_html=False,
            )
        except Exception as exc:
            errors.append(f"{url}: captura falhou ({type(exc).__name__}: {exc})")
            continue
        item = (result.get("items") or [{}])[0]
        captures.append(_slim_capture(item, score=int(candidate.get("identity_score") or 0)))
        for error in result.get("errors") or []:
            errors.append(f"{url}: {error}")
    return captures, errors


def _brand_tokens_from_captures(
    captures: Iterable[dict[str, Any]],
    *,
    name: str,
    handle: str | None,
) -> list[str]:
    """Extrai somente locais de e-mail coerentes com nome/handle; nunca guarda o e-mail."""
    surname = _compact((_name_parts(name) or [""])[-1])
    handle_compact = _compact(_handle_value(handle))
    tokens: list[str] = []
    for capture in captures:
        text = str(capture.get("text_excerpt") or "")
        for match in _EMAIL_RE.finditer(text):
            local = match.group(1).strip("._+-")
            compact = _compact(local)
            if len(compact) < 5:
                continue
            if (surname and surname in compact) or (handle_compact and handle_compact in compact):
                tokens.append(local)
    return _unique(tokens)


def _independent_domains(ranked: Iterable[dict[str, Any]], *, min_score: int = 20) -> list[str]:
    domains: list[str] = []
    for candidate in ranked:
        if int(candidate.get("identity_score") or 0) < min_score:
            continue
        if candidate.get("domain_class") != "independent":
            continue
        host = str(candidate.get("domain") or "")
        if host:
            domains.append(host)
    return _unique(domains)


def generate_followup_queries(
    *,
    name: str,
    ranked: Iterable[dict[str, Any]],
    captures: Iterable[dict[str, Any]],
    handle: str | None = None,
    profession: str | None = None,
    keywords: Iterable[str] = (),
) -> list[str]:
    short = _short_name(name)
    quoted_short = f'"{short}"'
    domains = _independent_domains(ranked)
    brand_tokens = _brand_tokens_from_captures(captures, name=name, handle=handle)
    queries: list[str] = []
    for domain in domains[:6]:
        queries.extend(
            [
                f'site:{domain} {quoted_short}',
                f"site:{domain} blog OR artigo OR autor",
            ]
        )
    for token in brand_tokens[:4]:
        queries.extend(
            [
                f'"{token}" {quoted_short}',
                f'"{token}" blog OR artigos',
            ]
        )
    if profession:
        queries.append(f'{quoted_short} "{profession}" publicação OR artigo')
    for keyword in _unique(keywords)[:3]:
        queries.append(f'{quoted_short} "{keyword}"')
    return _unique(queries)


def _discover_sitemap_urls(
    root_url: str,
    *,
    timeout: float,
    max_urls: int = 500,
) -> tuple[list[str], list[str]]:
    """Consulta robots e sitemaps comuns sem sair do host inicial."""
    root = _root_url(root_url)
    candidates = [
        f"{root.rstrip('/')}/robots.txt",
        f"{root.rstrip('/')}/sitemap.xml",
        f"{root.rstrip('/')}/sitemap_index.xml",
    ]
    sitemap_documents: list[str] = []
    urls: list[str] = []
    errors: list[str] = []

    robots = fetch_url(candidates[0], timeout=timeout)
    if not robots.get("error") and int(robots.get("status") or 0) < 400:
        sitemap_documents.extend(_ROBOTS_SITEMAP_RE.findall(str(robots.get("text") or "")))
    sitemap_documents.extend(candidates[1:])

    seen_docs: set[str] = set()
    for sitemap_url in _unique(sitemap_documents)[:10]:
        canonical = canonicalize_url(sitemap_url)
        if not canonical or canonical in seen_docs or not same_registrable_host(root, canonical):
            continue
        seen_docs.add(canonical)
        raw = fetch_url(canonical, timeout=timeout)
        status = int(raw.get("status") or 0)
        if raw.get("error"):
            errors.append(f"{canonical}: {raw['error']}")
            continue
        if status >= 400:
            continue
        for location in _SITEMAP_LOC_RE.findall(str(raw.get("text") or "")):
            found = canonicalize_url(location)
            if not found or not same_registrable_host(root, found):
                continue
            if found.lower().endswith(".xml") and len(seen_docs) < 10:
                sitemap_documents.append(found)
            elif found not in urls:
                urls.append(found)
                if len(urls) >= max_urls:
                    return urls, errors

    # Uma segunda passagem curta cobre índices encontrados durante a primeira.
    for sitemap_url in _unique(sitemap_documents):
        canonical = canonicalize_url(sitemap_url)
        if not canonical or canonical in seen_docs or not same_registrable_host(root, canonical):
            continue
        if len(seen_docs) >= 10:
            break
        seen_docs.add(canonical)
        raw = fetch_url(canonical, timeout=timeout)
        if raw.get("error") or int(raw.get("status") or 0) >= 400:
            continue
        for location in _SITEMAP_LOC_RE.findall(str(raw.get("text") or "")):
            found = canonicalize_url(location)
            if found and same_registrable_host(root, found) and not found.lower().endswith(".xml"):
                if found not in urls:
                    urls.append(found)
                    if len(urls) >= max_urls:
                        return urls, errors
    return urls, errors


def _page_matches_identity(
    page: dict[str, Any],
    *,
    name: str,
    handle: str | None,
    profession: str | None,
    keywords: Iterable[str],
) -> tuple[int, list[str]]:
    text = _fold(
        " ".join(
            str(page.get(key) or "")
            for key in ("url", "final_url", "title", "author", "text", "text_excerpt")
        )
    )
    compact = _compact(text)
    score = 0
    evidence: list[str] = []
    if _compact(name) in compact or _compact(_short_name(name)) in compact:
        score += 2
        evidence.append("nome")
    handle_compact = _compact(_handle_value(handle))
    if handle_compact and handle_compact in compact:
        score += 2
        evidence.append("handle")
    if profession and _fold(profession) in text:
        score += 1
        evidence.append("profissao")
    for keyword in _unique(keywords):
        if _fold(keyword) in text:
            score += 1
            evidence.append(f"palavra_chave:{keyword}")
            break
    return score, evidence


def inventory_articles(
    pages: Iterable[dict[str, Any]],
    sitemap_urls: Iterable[str],
    *,
    name: str,
) -> list[dict[str, Any]]:
    """Enumera páginas com sinais objetivos de conteúdo editorial/autoral."""
    articles: dict[str, dict[str, Any]] = {}
    short_folded = _fold(_short_name(name))
    for page in pages:
        url = canonicalize_url(str(page.get("final_url") or page.get("url") or ""))
        if not url:
            continue
        path = urlsplit(url).path
        author = str(page.get("author") or "")
        title = str(page.get("title") or "")
        is_article = bool(_ARTICLE_PATH_RE.search(path))
        if author and short_folded in _fold(author):
            is_article = True
        if path not in ("", "/") and _ARTICLE_TITLE_RE.search(title):
            is_article = True
        if not is_article or path.rstrip("/") in ("/blog", "/artigo", "/artigos"):
            continue
        articles[url] = {
            "kind": "authored_content_candidate",
            "url": url,
            "title": title,
            "author": author or None,
            "date": page.get("date"),
            "text_len": page.get("text_len") or len(str(page.get("text") or "")),
            "discovered_via": "crawl",
        }
    for raw_url in sitemap_urls:
        url = canonicalize_url(raw_url)
        if not url or url in articles or not _ARTICLE_PATH_RE.search(urlsplit(url).path):
            continue
        path = urlsplit(url).path.rstrip("/")
        if path in ("/blog", "/artigo", "/artigos"):
            continue
        articles[url] = {
            "kind": "authored_content_candidate",
            "url": url,
            "title": "",
            "author": None,
            "date": None,
            "text_len": 0,
            "discovered_via": "sitemap",
        }
    return sorted(articles.values(), key=lambda item: item["url"])


def inventory_external_articles(
    ranked: Iterable[dict[str, Any]],
    captures: Iterable[dict[str, Any]],
    *,
    name: str,
    excluded_domains: Iterable[str] = (),
) -> list[dict[str, Any]]:
    """Inclui produção autoral candidata fora do domínio próprio."""
    excluded = {_fold(domain) for domain in excluded_domains if domain}
    short_name = _fold(_short_name(name))
    captures_by_url: dict[str, dict[str, Any]] = {}
    for capture in captures:
        url = canonicalize_url(str(capture.get("final_url") or capture.get("url") or ""))
        if url:
            captures_by_url[url] = capture

    articles: dict[str, dict[str, Any]] = {}
    for candidate in ranked:
        url = canonicalize_url(
            str(candidate.get("canonical_url") or candidate.get("url") or "")
        )
        if not url or _fold(_host(url)) in excluded:
            continue
        if int(candidate.get("identity_score") or 0) < 20:
            continue
        capture = captures_by_url.get(url)
        status = int((capture or {}).get("status") or 0)
        if (
            not capture
            or status < 200
            or status >= 400
            or int(capture.get("text_len") or 0) <= 0
        ):
            continue
        path = urlsplit(url).path.rstrip("/")
        author = _fold(str(capture.get("author") or ""))
        has_editorial_path = bool(
            re.search(r"/(?:article|articles|artigo|artigos)(?:/|$)", path, re.IGNORECASE)
        )
        if not has_editorial_path and (not author or short_name not in author):
            continue
        articles[url] = {
            "kind": "authored_content_candidate",
            "url": url,
            "title": str(capture.get("title") or candidate.get("title") or ""),
            "author": capture.get("author"),
            "date": capture.get("date") or candidate.get("published_at"),
            "text_len": int(capture.get("text_len") or 0),
            "discovered_via": "search_capture",
            "relationship": "candidate",
            "domain": _host(url),
        }
    return sorted(articles.values(), key=lambda item: item["url"])


def _site_slug(host: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", host.lower()).strip("_") or "site"


def _crawl_sites(
    ranked: list[dict[str, Any]],
    *,
    explicit_sites: Iterable[str],
    name: str,
    handle: str | None,
    profession: str | None,
    keywords: Iterable[str],
    out_dir: Path,
    max_domains: int,
    max_pages: int,
    max_depth: int,
    timeout: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    roots: list[str] = []
    for url in explicit_sites:
        canonical = canonicalize_url(url)
        if canonical:
            roots.append(_root_url(canonical))
    for candidate in ranked:
        if candidate.get("domain_class") != "independent":
            continue
        if int(candidate.get("identity_score") or 0) < 25:
            continue
        url = str(candidate.get("canonical_url") or candidate.get("url") or "")
        if url:
            roots.append(_root_url(url))

    sites: list[dict[str, Any]] = []
    all_articles: list[dict[str, Any]] = []
    errors: list[str] = []
    seen_hosts: set[str] = set()
    for root in _unique(roots):
        host = _host(root)
        if not host or host in seen_hosts or len(seen_hosts) >= max_domains:
            continue
        seen_hosts.add(host)
        try:
            result = crawl(
                root,
                max_pages=max_pages,
                max_depth=max_depth,
                same_domain=True,
                timeout=timeout,
            )
        except Exception as exc:
            errors.append(f"{root}: crawl falhou ({type(exc).__name__}: {exc})")
            continue
        sitemap_urls, sitemap_errors = _discover_sitemap_urls(root, timeout=timeout)
        errors.extend(sitemap_errors)
        pages = list(result.get("pages") or [])
        identity_score = 0
        identity_evidence: list[str] = []
        for page in pages[:10]:
            score, evidence = _page_matches_identity(
                page,
                name=name,
                handle=handle,
                profession=profession,
                keywords=keywords,
            )
            if score > identity_score:
                identity_score = score
                identity_evidence = evidence
        articles = inventory_articles(pages, sitemap_urls, name=name)
        all_articles.extend(articles)
        site_record = {
            "kind": "profile_site_expansion",
            "root_url": root,
            "domain": host,
            "relationship": (
                "strong_candidate"
                if identity_score >= 3
                else "candidate"
                if identity_score >= 2
                else "unconfirmed"
            ),
            "identity_evidence": identity_evidence,
            "pages": len(pages),
            "sitemap_urls": len(sitemap_urls),
            "articles": len(articles),
            "errors": len(result.get("errors") or []) + len(sitemap_errors),
        }
        sites.append(site_record)
        site_envelope = build_envelope(
            "profile-site",
            source={"url": root, "profile_relationship": site_record["relationship"]},
            items=pages,
            meta={
                **dict(result.get("meta") or {}),
                "identity_evidence": identity_evidence,
                "sitemap_urls": sitemap_urls,
                "articles": articles,
            },
            errors=list(result.get("errors") or []) + sitemap_errors,
            notes=[
                "Crawl same-host iniciado por um candidato; não prova propriedade do domínio.",
                "Artigos são inventariados por caminho, autoria e metadados públicos.",
            ],
        )
        write_json(out_dir / f"site_{_site_slug(host)}.json", site_envelope)
    deduped_articles = {article["url"]: article for article in all_articles}
    return sites, sorted(deduped_articles.values(), key=lambda item: item["url"]), errors


def _read_json_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _instagram_profile_candidate(
    handle: str | None,
    ranked: Iterable[dict[str, Any]],
) -> str | None:
    if handle:
        return instagram_profile_url(handle)
    for item in ranked:
        candidate = instagram_profile_url(
            str(item.get("canonical_url") or item.get("url") or "")
        )
        if candidate:
            return candidate
    return None


def collect_instagram(
    *,
    handle: str | None,
    ranked: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    explicit_media_urls: list[str],
    out_dir: Path,
    enabled: bool,
    storage_state: str | None,
    headed: bool,
    max_posts: int,
    max_comments: int,
    expand_replies: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Executa a etapa IG do perfil e retorna inventário + erros materiais."""
    profile_url = _instagram_profile_candidate(handle, ranked)
    required = bool(handle)
    record: dict[str, Any] = {
        "enabled": enabled,
        "required": required,
        "profile_url": profile_url,
        "profile": None,
        "media_urls": [],
        "posts": [],
        "state": "disabled" if not enabled else "missing",
        "posts_state": "not_run",
    }
    if not enabled:
        return record, []
    if not profile_url:
        record["posts_state"] = "no_profile"
        return record, []

    instagram_dir = out_dir / "instagram"
    instagram_dir.mkdir(parents=True, exist_ok=True)
    profile_out = instagram_dir / "profile.json"
    profile_shot = instagram_dir / "profile.png"
    inventory_args = [
        "--url",
        profile_url,
        "--out",
        str(profile_out),
        "--profile-shot",
        str(profile_shot),
        "--max-posts",
        str(max_posts),
    ]
    if storage_state:
        inventory_args.extend(["--storage-state", storage_state])
    if headed:
        inventory_args.append("--headed")

    profile_code = ig_main(inventory_args)
    profile_payload = _read_json_object(profile_out)
    profile_item = (
        profile_payload["items"][0]
        if profile_payload
        and isinstance(profile_payload.get("items"), list)
        and profile_payload["items"]
        and isinstance(profile_payload["items"][0], dict)
        else None
    )
    login_wall = bool(
        (profile_payload or {}).get("meta", {}).get("login_wall")
        or (profile_item or {}).get("login_wall")
    )
    record["profile"] = {
        "exit_code": profile_code,
        "path": str(profile_out),
        "screenshot": (
            str(profile_shot)
            if profile_shot.is_file() and not login_wall
            else None
        ),
        "login_wall": login_wall,
        "media_discovered": int((profile_item or {}).get("media_count") or 0),
    }
    errors: list[str] = []
    if profile_code == 0 and profile_item and not login_wall:
        record["state"] = "found"
    elif login_wall or profile_code == 5:
        record["state"] = "blocked"
        errors.append("instagram_profile: login wall detectado")
    else:
        record["state"] = "error"
        errors.append(f"instagram_profile: coleta falhou com exit code {profile_code}")

    media_inputs = list(explicit_media_urls)
    media_inputs.extend(list((profile_item or {}).get("media_urls") or []))
    for candidate in ranked:
        media_inputs.append(str(candidate.get("canonical_url") or candidate.get("url") or ""))
    for capture in captures:
        media_inputs.append(str(capture.get("final_url") or capture.get("url") or ""))
        media_inputs.extend(str(url) for url in (capture.get("links") or []))
    media_urls = instagram_media_urls(media_inputs, limit=max_posts)
    record["media_urls"] = media_urls
    if not media_urls:
        record["posts_state"] = "no_urls"
        return record, errors

    posts_ok = 0
    for media_url in media_urls:
        shortcode = shortcode_from_url(media_url) or f"item_{len(record['posts']) + 1:02d}"
        post_out = instagram_dir / f"post_{shortcode}.json"
        stats_out = instagram_dir / f"post_{shortcode}_stats.json"
        post_args = [
            "--url",
            media_url,
            "--out",
            str(post_out),
            "--stats",
            str(stats_out),
            "--max-comments",
            str(max_comments),
        ]
        if storage_state:
            post_args.extend(["--storage-state", storage_state])
        if headed:
            post_args.append("--headed")
        if expand_replies:
            post_args.append("--expand-replies")
        exit_code = ig_main(post_args)
        payload = _read_json_object(post_out)
        count = int((payload or {}).get("count") or 0)
        artifact_written = post_out.is_file()
        if exit_code in {0, 6} and artifact_written:
            posts_ok += 1
        else:
            errors.append(f"instagram_post {shortcode}: exit code {exit_code}")
        record["posts"].append(
            {
                "url": media_url,
                "shortcode": shortcode,
                "exit_code": exit_code,
                "path": str(post_out) if artifact_written else None,
                "comments": count,
            }
        )
    record["posts_state"] = "complete" if posts_ok == len(media_urls) else "partial"
    return record, errors


def build_coverage(
    *,
    ranked: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    instagram: dict[str, Any],
    rounds_executed: int,
    followup_queries_pending: int,
) -> list[dict[str, Any]]:
    def row(category: str, count: int, *, note: str = "") -> dict[str, Any]:
        return {
            "category": category,
            "state": "found" if count else "missing",
            "evidence_count": count,
            "note": note,
        }

    social = sum(1 for item in ranked if item.get("domain_class") == "social_or_platform")
    professional = sum(
        1 for item in ranked if item.get("domain_class") == "professional_directory"
    )
    verified_sites = sum(
        1 for site in sites if site.get("relationship") in ("strong_candidate", "candidate")
    )
    coverage = [
        row("identity_candidates", len(ranked)),
        row("captured_pages", len(captures)),
        row("social_profiles", social),
        row("professional_presence", professional),
        row(
            "official_site_candidates",
            verified_sites,
            note="Candidato por nexo de conteúdo; exige conferência humana antes de afirmar propriedade.",
        ),
        row("authored_content", len(articles)),
        {
            "category": "instagram_profile",
            "state": instagram.get("state") or "missing",
            "evidence_count": 1 if instagram.get("state") == "found" else 0,
            "note": {
                "found": "Perfil do Instagram coletado como etapa independente.",
                "blocked": "Perfil conhecido, mas a coleta encontrou login wall.",
                "error": "Perfil conhecido, mas a coleta falhou.",
                "disabled": "Etapa do Instagram desabilitada explicitamente.",
                "missing": "Nenhum handle ou perfil candidato foi encontrado.",
            }.get(str(instagram.get("state")), ""),
        },
        {
            "category": "instagram_posts",
            "state": {
                "complete": "found",
                "partial": "pending",
                "no_urls": "missing",
                "no_profile": "missing",
                "not_run": "disabled",
            }.get(str(instagram.get("posts_state")), "missing"),
            "evidence_count": len(instagram.get("posts") or []),
            "note": {
                "complete": "Posts/reels descobertos foram passados ao tarrafa ig.",
                "partial": "Uma ou mais coletas de posts/reels falharam.",
                "no_urls": "Nenhuma URL de post/reel ficou disponível para comentários.",
                "no_profile": "Nenhum perfil candidato disponível para inventariar mídias.",
                "not_run": "Etapa de posts/reels não executada.",
            }.get(str(instagram.get("posts_state")), ""),
        },
        {
            "category": "iterative_search",
            "state": "complete" if followup_queries_pending == 0 else "pending",
            "evidence_count": rounds_executed,
            "note": (
                "Sem consultas pendentes."
                if followup_queries_pending == 0
                else f"{followup_queries_pending} consultas de pivô aguardam busca externa."
            ),
        },
    ]
    return coverage


def _write_lines(path: Path, lines: Iterable[str]) -> None:
    from tarrafa.core.runtime import get_runtime

    path.parent.mkdir(parents=True, exist_ok=True)
    runtime = get_runtime()
    if path.exists() and runtime.no_clobber and not runtime.force:
        raise FileExistsError(
            f"refusing to overwrite {path} (no_clobber; pass --force or set defaults.force)"
        )
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    try:
        from tarrafa.core.run import register_artifact

        register_artifact(path, kind="text")
    except Exception:
        pass


def _profile_html_payload(
    *,
    identity: dict[str, Any],
    ranked: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    articles: list[dict[str, Any]],
    instagram: dict[str, Any],
    coverage: list[dict[str, Any]],
    queries_executed: int,
) -> dict[str, Any]:
    """Converte a descoberta material-only em dados para o renderer."""
    meta: list[str] = []
    for label, key in (
        ("Handle informado", "handle"),
        ("Profissão/função", "profession"),
        ("Local", "location"),
        ("Organização", "organization"),
    ):
        value = identity.get(key)
        if value:
            meta.append(f"{label}: {value}")

    strong_sites = [site for site in sites if site.get("relationship") == "strong_candidate"]
    site_articles = [
        article for article in articles if article.get("discovered_via") in {"crawl", "sitemap"}
    ]
    external_articles = [
        article for article in articles if article.get("discovered_via") == "search_capture"
    ]
    facts: list[str] = []
    if strong_sites:
        facts.append(
            f"{len(strong_sites)} domínio(s) profissional(is) classificado(s) como "
            "candidato forte por nexo de identidade e conteúdo."
        )
    if sites:
        facts.append(
            f"O crawl percorreu {sum(int(site.get('pages') or 0) for site in sites)} "
            f"página(s) e encontrou {len(site_articles)} conteúdo(s) editorial(is) "
            "no(s) domínio(s) avaliado(s)."
        )
    if external_articles:
        facts.append(
            f"A busca também capturou {len(external_articles)} publicação(ões) autoral(is) "
            "candidata(s) em domínio(s) externo(s)."
        )
    facts.append(
        f"A descoberta registrou {len(ranked)} candidato(s) e {len(captures)} "
        "captura(s) web pública(s), sem sessão autenticada nessa etapa."
    )
    if instagram.get("state") == "found":
        facts.append(
            "O perfil do Instagram foi coletado como cobertura independente; "
            f"{len(instagram.get('media_urls') or [])} post(s)/reel(s) foram descobertos "
            f"e {len(instagram.get('posts') or [])} coleta(s) de comentários foram executadas."
        )

    sources: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    successful_capture_urls = {
        canonicalize_url(str(capture.get("final_url") or capture.get("url") or ""))
        for capture in captures
        if 200 <= int(capture.get("status") or 0) < 400
    }

    def add_source(label: str, url: str, note: str) -> None:
        canonical = canonicalize_url(url)
        if not canonical or canonical in seen_urls:
            return
        seen_urls.add(canonical)
        sources.append({"label": label or "Fonte", "url": canonical, "note": note})

    for site in sites:
        add_source(
            f"Domínio candidato · {site.get('domain') or _host(str(site.get('root_url') or ''))}",
            str(site.get("root_url") or ""),
            f"Relação: {site.get('relationship') or 'unconfirmed'}",
        )
    for article in articles:
        add_source(
            str(article.get("title") or "Conteúdo autoral candidato"),
            str(article.get("url") or ""),
            (
                "Publicação externa candidata"
                if article.get("discovered_via") == "search_capture"
                else "Conteúdo inventariado no domínio avaliado"
            ),
        )
    for candidate in ranked:
        candidate_url = str(candidate.get("canonical_url") or candidate.get("url") or "")
        if canonicalize_url(candidate_url) not in successful_capture_urls:
            continue
        add_source(
            str(candidate.get("title") or candidate.get("domain") or "Fonte candidata"),
            candidate_url,
            f"Candidato de identidade · score {int(candidate.get('identity_score') or 0)}",
        )
    if instagram.get("profile_url"):
        add_source(
            "Perfil do Instagram",
            str(instagram["profile_url"]),
            f"Cobertura específica · estado {instagram.get('state') or 'missing'}",
        )

    gaps = [
        str(row.get("note") or f"Cobertura ausente: {row.get('category')}")
        for row in coverage
        if row.get("state") in {"missing", "pending"}
    ]
    if not gaps:
        gaps.append(
            "Domínios, identidade e autoria permanecem candidatos até conferência humana."
        )
    return {
        "meta": meta,
        "facts": facts,
        "stats": [
            {"label": "Consultas", "value": str(queries_executed)},
            {"label": "Candidatos", "value": str(len(ranked))},
            {"label": "Capturas", "value": str(len(captures))},
            {"label": "Conteúdos", "value": str(len(articles))},
            {
                "label": "Posts IG",
                "value": str(len(instagram.get("posts") or [])),
            },
        ],
        "sources": sources,
        "gaps": gaps,
        "notes": [
            "CPF, e-mail e telefone não foram usados como consultas.",
            (
                "A etapa Instagram pode usar storage_state local quando disponível; "
                "o arquivo de sessão nunca é embutido no HTML."
            ),
        ],
        "chips": [
            f"{len(ranked)} candidatos",
            f"{len(articles)} conteúdos",
            f"{len(sites)} sites avaliados",
            f"Instagram: {instagram.get('state') or 'missing'}",
        ],
        "shots": (
            [
                {
                    "id": "instagram_profile",
                    "path": instagram["profile"]["screenshot"],
                    "caption": "Perfil público no Instagram",
                    "url": instagram.get("profile_url") or "",
                    "kind": "instagram_profile",
                }
            ]
            if (instagram.get("profile") or {}).get("screenshot")
            else []
        ),
        "method": (
            f"{queries_executed} consultas · {len(captures)} capturas · "
            f"{sum(int(site.get('pages') or 0) for site in sites)} páginas em crawl · "
            f"Instagram {instagram.get('state') or 'missing'}"
        ),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa profile",
        description=(
            "Descoberta iterativa material-only de presença pública: consultas, pivôs, "
            "domínios próprios candidatos, crawl e cobertura. Não gera biografia."
        ),
    )
    ap.add_argument("--name", required=True, help="Nome público/civil usado como âncora")
    ap.add_argument("--handle", default=None, help="Handle público, com ou sem @")
    ap.add_argument("--profession", default=None, help="Profissão ou função pública")
    ap.add_argument("--location", default=None, help="Cidade/UF ou outra âncora geográfica")
    ap.add_argument("--organization", default=None, help="Organização pública associada")
    ap.add_argument("--keyword", action="append", default=[], help="Tema público; repetível")
    ap.add_argument("--seed-url", action="append", default=[], help="URL candidata; repetível")
    ap.add_argument(
        "--site",
        action="append",
        default=[],
        help="Domínio próprio já conhecido para expansão same-host; repetível",
    )
    ap.add_argument(
        "--from-agent",
        default=None,
        metavar="ARQUIVO",
        help=(
            "Repasse externo da primeira rodada. Sem provedor, as consultas de pivô "
            "ficam em queries_followup.txt para nova orquestração."
        ),
    )
    ap.add_argument("--provider", choices=["auto", "brave", "searxng"], default="auto")
    ap.add_argument("--api-key", default=None, help="Chave Brave; prefira variável de ambiente")
    ap.add_argument("--searxng-url", default=None, help="Endpoint SearXNG")
    ap.add_argument("--country", default="BR")
    ap.add_argument("--language", default="pt-br")
    ap.add_argument("--safesearch", choices=["off", "moderate", "strict"], default="moderate")
    ap.add_argument("--max-rounds", type=int, choices=[1, 2, 3], default=2)
    ap.add_argument("--max-results", type=int, default=20, help="Máximo por consulta")
    ap.add_argument("--max-captures", type=int, default=12)
    ap.add_argument("--max-domains", type=int, default=3)
    ap.add_argument("--max-site-pages", type=int, default=30)
    ap.add_argument("--max-depth", type=int, default=2)
    instagram = ap.add_mutually_exclusive_group()
    instagram.add_argument(
        "--instagram",
        dest="instagram",
        action="store_true",
        default=True,
        help="Executa cobertura específica do Instagram via tarrafa ig (padrão)",
    )
    instagram.add_argument(
        "--no-instagram",
        dest="instagram",
        action="store_false",
        help="Desabilita explicitamente a etapa do Instagram",
    )
    ap.add_argument(
        "--ig-url",
        action="append",
        default=[],
        help="URL conhecida de post/reel a coletar; repetível",
    )
    ap.add_argument(
        "--ig-storage-state",
        default=None,
        help=(
            "Sessão Playwright do Instagram; padrão: ./storage_state.json quando existir"
        ),
    )
    ap.add_argument("--ig-headed", action="store_true", help="Mostra navegador na etapa IG")
    ap.add_argument(
        "--ig-max-posts",
        type=int,
        default=12,
        help="Máximo de posts/reels inventariados e coletados (padrão: 12)",
    )
    ap.add_argument(
        "--ig-max-comments",
        type=int,
        default=500,
        help="Máximo de comentários por post/reel (padrão: 500)",
    )
    ap.add_argument(
        "--ig-expand-replies",
        action="store_true",
        help="Expande respostas nas coletas acopladas de posts/reels",
    )
    ap.add_argument("--out-dir", required=True)
    html = ap.add_mutually_exclusive_group()
    html.add_argument(
        "--html",
        dest="html",
        action="store_true",
        default=True,
        help="Gera profile.html (padrão)",
    )
    html.add_argument(
        "--no-html",
        dest="html",
        action="store_false",
        help="Não gera a ficha HTML",
    )
    ap.add_argument(
        "--html-out",
        default=None,
        help="Caminho do HTML; padrão: OUT_DIR/profile.html",
    )
    ap.add_argument("--timeout", type=float, default=30.0)
    return ap


def _validate_args(args: argparse.Namespace) -> str | None:
    if args.max_results < 1 or args.max_results > 200:
        return "--max-results deve estar entre 1 e 200"
    if args.max_captures < 0 or args.max_captures > 100:
        return "--max-captures deve estar entre 0 e 100"
    if args.max_domains < 0 or args.max_domains > 20:
        return "--max-domains deve estar entre 0 e 20"
    if args.max_site_pages < 1 or args.max_site_pages > 500:
        return "--max-site-pages deve estar entre 1 e 500"
    if args.max_depth < 0 or args.max_depth > 10:
        return "--max-depth deve estar entre 0 e 10"
    if args.ig_max_posts < 0 or args.ig_max_posts > 100:
        return "--ig-max-posts deve estar entre 0 e 100"
    if args.ig_max_comments < 0 or args.ig_max_comments > 50_000:
        return "--ig-max-comments deve estar entre 0 e 50000"
    invalid_ig_urls = [
        value for value in args.ig_url if not shortcode_from_url(value)
    ]
    if invalid_ig_urls:
        return "--ig-url aceita somente URLs de post/reel/TV do Instagram"
    sensitive = _query_input_has_sensitive_data(
        [
            args.name,
            args.handle or "",
            args.profession or "",
            args.location or "",
            args.organization or "",
            *args.keyword,
        ]
    )
    if sensitive:
        return (
            "âncora sensível bloqueada "
            f"({', '.join(sensitive)}). profile nunca envia CPF, e-mail ou telefone; "
            "use esses dados somente em tools específicas de conferência local"
        )
    return None


def _round_envelope(
    *,
    round_number: int,
    provider_name: str,
    queries: list[str],
    result: dict[str, Any],
) -> dict[str, Any]:
    return build_envelope(
        "profile-search",
        source={
            "provider": provider_name,
            "round": round_number,
            "queries": [
                {
                    "id": record["id"],
                    "display": record["display"],
                    "sha256": record["sha256"],
                    "sensitive_kinds": record["sensitive_kinds"],
                }
                for record in _query_records(queries)
            ],
        },
        items=list(result.get("items") or []),
        meta={**dict(result.get("meta") or {}), "round": round_number},
        errors=list(result.get("errors") or []),
        notes=[
            "Resultados são candidatos; a rodada não confirma identidade nem propriedade.",
            "profile não envia CPF, e-mail completo ou telefone ao provedor.",
        ],
    )


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    validation_error = _validate_args(args)
    if validation_error:
        print(f"profile: {validation_error}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    planned_queries = generate_initial_queries(
        name=args.name,
        handle=args.handle,
        profession=args.profession,
        location=args.location,
        organization=args.organization,
        keywords=args.keyword,
    )
    initial_queries = planned_queries

    provider: BaseSearchProvider | None = None
    handoff: dict[str, Any] | None = None
    if args.from_agent:
        try:
            handoff = read_agent_handoff(Path(args.from_agent))
        except Exception as exc:
            print(f"profile: repasse inválido ({exc})", file=sys.stderr)
            return 2
        # O repasse é autoritativo quanto às consultas efetivamente executadas.
        initial_queries = [block["query"] for block in handoff["blocks"]]
        _write_lines(out_dir / "queries_planned.txt", planned_queries)
    else:
        try:
            provider = resolve_provider(
                args.provider,
                api_key=args.api_key,
                searxng_url=args.searxng_url,
                timeout=args.timeout,
            )
        except SearchProviderConfigurationError as exc:
            print(
                f"profile: {exc}\n"
                "Gere a primeira rodada com as ferramentas do seu ambiente e use "
                "--from-agent repasse.json.",
                file=sys.stderr,
            )
            return 2

    _write_lines(out_dir / "queries_round_01.txt", initial_queries)

    all_candidates: dict[str, dict[str, Any]] = {}
    all_captures: list[dict[str, Any]] = []
    captured_urls: set[str] = set()
    errors: list[str] = []
    used_queries: set[str] = set()
    round_summaries: list[dict[str, Any]] = []
    current_queries = initial_queries
    pending_followups: list[str] = []

    for round_number in range(1, args.max_rounds + 1):
        if not current_queries:
            break
        query_records = _query_records(current_queries)
        used_queries.update(current_queries)
        if round_number == 1 and handoff is not None:
            result = collect_from_agent(handoff, query_records, max_results=args.max_results)
            provider_name = f"agent:{handoff['agent']}"
        elif provider is not None:
            result = collect_search(
                provider,
                query_records,
                max_results=args.max_results,
                country=args.country,
                language=args.language,
                freshness=None,
                safesearch=args.safesearch,
            )
            provider_name = provider.name
        else:
            pending_followups = current_queries
            break

        new_candidates = _merge_candidates(all_candidates, result.get("items") or [])
        round_envelope = _round_envelope(
            round_number=round_number,
            provider_name=provider_name,
            queries=current_queries,
            result=result,
        )
        write_json(out_dir / f"search_round_{round_number:02d}.json", round_envelope)
        errors.extend(result.get("errors") or [])

        ranked = rank_candidates(
            all_candidates.values(),
            name=args.name,
            handle=args.handle,
            profession=args.profession,
            organization=args.organization,
            keywords=args.keyword,
        )
        remaining_capture_budget = max(0, args.max_captures - len(all_captures))
        captures, capture_errors = _capture_candidates(
            ranked,
            already_captured=captured_urls,
            max_new=remaining_capture_budget,
            timeout=args.timeout,
        )
        all_captures.extend(captures)
        errors.extend(capture_errors)

        followups = generate_followup_queries(
            name=args.name,
            ranked=ranked,
            captures=all_captures,
            handle=args.handle,
            profession=args.profession,
            keywords=args.keyword,
        )
        followups = [query for query in followups if query not in used_queries]
        round_summaries.append(
            {
                "round": round_number,
                "queries": len(current_queries),
                "new_candidates": new_candidates,
                "total_candidates": len(all_candidates),
                "new_captures": len(captures),
                "followup_queries": len(followups),
            }
        )
        if not followups or new_candidates == 0:
            pending_followups = []
            break
        if provider is None:
            pending_followups = followups
            break
        current_queries = followups

    for url in [*args.seed_url, *args.site]:
        candidate = _seed_candidate(url, label="URL fornecida")
        if candidate:
            _merge_candidates(all_candidates, [candidate])

    ranked = rank_candidates(
        all_candidates.values(),
        name=args.name,
        handle=args.handle,
        profession=args.profession,
        organization=args.organization,
        keywords=args.keyword,
    )
    remaining_capture_budget = max(0, args.max_captures - len(all_captures))
    seed_captures, seed_capture_errors = _capture_candidates(
        ranked,
        already_captured=captured_urls,
        max_new=remaining_capture_budget,
        timeout=args.timeout,
    )
    all_captures.extend(seed_captures)
    errors.extend(seed_capture_errors)

    sites, site_articles, site_errors = _crawl_sites(
        ranked,
        explicit_sites=args.site,
        name=args.name,
        handle=args.handle,
        profession=args.profession,
        keywords=args.keyword,
        out_dir=out_dir,
        max_domains=args.max_domains,
        max_pages=args.max_site_pages,
        max_depth=args.max_depth,
        timeout=args.timeout,
    )
    errors.extend(site_errors)
    external_articles = inventory_external_articles(
        ranked,
        all_captures,
        name=args.name,
        excluded_domains=[str(site.get("domain") or "") for site in sites],
    )
    article_map = {article["url"]: article for article in site_articles}
    for article in external_articles:
        article_map.setdefault(article["url"], article)
    articles = sorted(article_map.values(), key=lambda article: article["url"])
    ig_storage_state = args.ig_storage_state
    if not ig_storage_state and Path("storage_state.json").is_file():
        ig_storage_state = str(Path("storage_state.json").resolve())
    instagram_record, instagram_errors = collect_instagram(
        handle=args.handle,
        ranked=ranked,
        captures=all_captures,
        explicit_media_urls=args.ig_url,
        out_dir=out_dir,
        enabled=args.instagram,
        storage_state=ig_storage_state,
        headed=args.ig_headed,
        max_posts=args.ig_max_posts,
        max_comments=args.ig_max_comments,
        expand_replies=args.ig_expand_replies,
    )
    errors.extend(instagram_errors)
    coverage = build_coverage(
        ranked=ranked,
        captures=all_captures,
        sites=sites,
        articles=articles,
        instagram=instagram_record,
        rounds_executed=len(round_summaries),
        followup_queries_pending=len(pending_followups),
    )

    _write_lines(
        out_dir / "candidate_urls.txt",
        [str(item.get("canonical_url") or item.get("url")) for item in ranked],
    )
    _write_lines(out_dir / "queries_followup.txt", pending_followups)

    item = {
        "kind": "profile_discovery",
        "identity": {
            "name": args.name,
            "handle": f"@{_handle_value(args.handle)}" if args.handle else None,
            "profession": args.profession,
            "location": args.location,
            "organization": args.organization,
            "keywords": list(args.keyword),
        },
        "rounds": round_summaries,
        "candidates": ranked,
        "captures": all_captures,
        "sites": sites,
        "authored_content": articles,
        "instagram": instagram_record,
        "coverage": coverage,
        "followup_queries": pending_followups,
    }
    envelope = build_envelope(
        "profile",
        source={
            "mode": "agent_handoff" if handoff is not None else "provider",
            "provider": (
                f"agent:{handoff['agent']}"
                if handoff is not None
                else provider.name
                if provider is not None
                else None
            ),
        },
        items=[item] if ranked or sites or instagram_record.get("profile_url") else [],
        meta={
            "rounds_executed": len(round_summaries),
            "queries_executed": len(used_queries),
            "candidates": len(ranked),
            "captures": len(all_captures),
            "sites_expanded": len(sites),
            "authored_content": len(articles),
            "instagram": {
                "state": instagram_record.get("state"),
                "posts_state": instagram_record.get("posts_state"),
                "posts": len(instagram_record.get("posts") or []),
            },
            "followup_queries_pending": len(pending_followups),
            "privacy": {
                "accepts_cpf": False,
                "accepts_email": False,
                "accepts_phone": False,
                "authenticated_session_used": bool(
                    ig_storage_state
                    and Path(ig_storage_state).is_file()
                    and args.instagram
                    and instagram_record.get("profile_url")
                ),
            },
        },
        errors=errors,
        notes=[
            "Material-only: candidatos e relações de domínio exigem conferência humana.",
            "O comando não gera biografia, não classifica condutas e não consulta CPF.",
            (
                "Busca e crawl usam páginas públicas; a etapa Instagram pode usar apenas "
                "o storage_state local informado ou já existente."
            ),
        ],
    )
    html_path: Path | None = None
    if args.html:
        html_path = Path(args.html_out) if args.html_out else out_dir / "profile.html"
        try:
            html_payload = _profile_html_payload(
                identity=item["identity"],
                ranked=ranked,
                captures=all_captures,
                sites=sites,
                articles=articles,
                instagram=instagram_record,
                coverage=coverage,
                queries_executed=len(used_queries),
            )
            dossier_envelope = build_dossier(
                title=args.name,
                subtitle="Perfil público · descoberta e produção autoral",
                kicker="Tarrafa · perfil público",
                out_html=html_path,
                meta=html_payload["meta"],
                facts=html_payload["facts"],
                stats=html_payload["stats"],
                sources=html_payload["sources"],
                shots=html_payload["shots"],
                gaps=html_payload["gaps"],
                notes=html_payload["notes"],
                chips=html_payload["chips"],
                intro=(
                    "Ficha material-only produzida a partir de páginas públicas. "
                    "Candidatos de identidade, domínio e autoria exigem conferência humana."
                ),
                method=html_payload["method"],
            )
            dossier_item = dossier_envelope["items"][0]
            item["html"] = {
                "path": str(html_path),
                "bytes": dossier_item["bytes_html"],
                "sources": dossier_item["sources"],
            }
            envelope["meta"]["html"] = {
                "generated": True,
                "path": str(html_path),
                "bytes": dossier_item["bytes_html"],
            }
        except Exception as exc:
            errors.append(f"html: {type(exc).__name__}: {exc}")
            envelope["errors"] = errors
            envelope["meta"]["html"] = {"generated": False, "path": str(html_path)}
    else:
        envelope["meta"]["html"] = {"generated": False, "disabled": True}
    out = write_json(out_dir / "profile.json", envelope)
    print(
        f"profile: wrote {out}  rounds={len(round_summaries)}  candidates={len(ranked)}  "
        f"captures={len(all_captures)}  sites={len(sites)}  articles={len(articles)}  "
        f"instagram={instagram_record.get('state')}  ig_posts={len(instagram_record.get('posts') or [])}  "
        f"pending_queries={len(pending_followups)}  errors={len(errors)}  "
        f"html={html_path if html_path and html_path.is_file() else 'off'}"
    )
    if not envelope["items"]:
        return 1 if errors else 6
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
