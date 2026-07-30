# -*- coding: utf-8 -*-
"""tarrafa profile — descoberta iterativa e expansão de presença pública.

O comando não produz biografia nem classifica pessoas. Ele:

1. gera consultas diversificadas a partir de âncoras não sensíveis;
2. registra resultados de Brave/SearXNG ou de um repasse externo;
3. captura candidatos públicos sem sessão autenticada;
4. extrai pivôs seguros e executa novas rodadas quando há provedor;
5. identifica domínios próprios prováveis e faz crawl same-host;
6. inventaria conteúdo autoral e emite uma matriz de cobertura.

CPF, e-mail completo e telefone não são aceitos como âncoras de busca.
"""
from __future__ import annotations

import argparse
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
    r"/(?:blog|artigos?|noticias?|publicacoes?|insights?|conteudos?|author|autor)(?:/|$)",
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


def build_coverage(
    *,
    ranked: list[dict[str, Any]],
    captures: list[dict[str, Any]],
    sites: list[dict[str, Any]],
    articles: list[dict[str, Any]],
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
    ap.add_argument("--out-dir", required=True)
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

    sites, articles, site_errors = _crawl_sites(
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
    coverage = build_coverage(
        ranked=ranked,
        captures=all_captures,
        sites=sites,
        articles=articles,
        rounds_executed=len(round_summaries),
        followup_queries_pending=len(pending_followups),
    )

    _write_lines(
        out_dir / "candidate_urls.txt",
        [str(item.get("canonical_url") or item.get("url")) for item in ranked],
    )
    if pending_followups:
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
        items=[item] if ranked or sites else [],
        meta={
            "rounds_executed": len(round_summaries),
            "queries_executed": len(used_queries),
            "candidates": len(ranked),
            "captures": len(all_captures),
            "sites_expanded": len(sites),
            "authored_content": len(articles),
            "followup_queries_pending": len(pending_followups),
            "privacy": {
                "accepts_cpf": False,
                "accepts_email": False,
                "accepts_phone": False,
                "authenticated_session_used": False,
            },
        },
        errors=errors,
        notes=[
            "Material-only: candidatos e relações de domínio exigem conferência humana.",
            "O comando não gera biografia, não classifica condutas e não consulta CPF.",
            "Capturas são públicas e não usam storage_state nem outra sessão autenticada.",
        ],
    )
    out = write_json(out_dir / "profile.json", envelope)
    print(
        f"profile: wrote {out}  rounds={len(round_summaries)}  candidates={len(ranked)}  "
        f"captures={len(all_captures)}  sites={len(sites)}  articles={len(articles)}  "
        f"pending_queries={len(pending_followups)}  errors={len(errors)}"
    )
    if not envelope["items"]:
        return 1 if errors else 6
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
