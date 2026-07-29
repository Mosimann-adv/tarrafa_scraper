# -*- coding: utf-8 -*-
"""Provedores intercambiáveis para ``tarrafa search``."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from tarrafa.core.http import DEFAULT_TIMEOUT, DEFAULT_UA, ensure_httpx

BRAVE_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class SearchProviderError(RuntimeError):
    """Falha operacional de um provedor de busca."""


class SearchProviderConfigurationError(SearchProviderError):
    """Configuração ausente ou inválida para o provedor."""


@dataclass
class SearchPage:
    items: list[dict[str, Any]] = field(default_factory=list)
    has_more: bool = False
    total_hint: int | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class BaseSearchProvider:
    name = "base"
    page_size = 10
    max_pages = 20

    def search_page(
        self,
        query: str,
        *,
        page: int,
        country: str,
        language: str,
        freshness: str | None,
        safesearch: str,
    ) -> SearchPage:
        raise NotImplementedError


class BraveSearchProvider(BaseSearchProvider):
    name = "brave"
    page_size = 20
    max_pages = 10

    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Any | None = None,
    ) -> None:
        if not api_key.strip():
            raise SearchProviderConfigurationError(
                "Brave Search sem chave. Configure BRAVE_SEARCH_API_KEY "
                "ou TARRAFA_BRAVE_SEARCH_API_KEY."
            )
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.transport = transport

    def search_page(
        self,
        query: str,
        *,
        page: int,
        country: str,
        language: str,
        freshness: str | None,
        safesearch: str,
    ) -> SearchPage:
        httpx = ensure_httpx()
        params: dict[str, Any] = {
            "q": query,
            "count": self.page_size,
            "offset": max(0, page - 1),
            "country": country.upper(),
            "search_lang": language.lower(),
            "safesearch": safesearch,
            "result_filter": "web",
            "text_decorations": "false",
        }
        if freshness:
            params["freshness"] = freshness
        headers = {
            "Accept": "application/json",
            "User-Agent": DEFAULT_UA,
            "X-Subscription-Token": self.api_key,
        }
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers=headers,
                transport=self.transport,
            ) as client:
                response = client.get(BRAVE_ENDPOINT, params=params)
        except Exception as exc:
            raise SearchProviderError(
                f"Brave Search: falha de rede ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            hint = {
                401: "chave ausente ou inválida",
                403: "acesso negado pelo plano ou pela chave",
                422: "consulta ou parâmetro inválido",
                429: "limite de requisições excedido",
            }.get(response.status_code, "falha HTTP")
            raise SearchProviderError(f"Brave Search: HTTP {response.status_code} ({hint})")
        try:
            data = response.json()
        except Exception as exc:
            raise SearchProviderError("Brave Search: resposta não-JSON") from exc
        if not isinstance(data, dict):
            raise SearchProviderError("Brave Search: resposta JSON inesperada")

        web = data.get("web") if isinstance(data.get("web"), dict) else {}
        raw_results = web.get("results") if isinstance(web, dict) else []
        items: list[dict[str, Any]] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict) or not raw.get("url"):
                continue
            items.append(
                {
                    "url": str(raw["url"]),
                    "title": str(raw.get("title") or ""),
                    "snippet": str(raw.get("description") or ""),
                    "published_at": raw.get("page_age") or raw.get("age"),
                    "language": raw.get("language"),
                    "engine": "brave",
                    "provider_meta": {
                        "profile": raw.get("profile"),
                        "family_friendly": raw.get("family_friendly"),
                    },
                }
            )
        has_more = bool(web.get("more_results_available")) if isinstance(web, dict) else False
        return SearchPage(
            items=items,
            has_more=has_more,
            meta={
                "altered_query": (data.get("query") or {}).get("altered")
                if isinstance(data.get("query"), dict)
                else None,
            },
        )


class SearXNGSearchProvider(BaseSearchProvider):
    name = "searxng"
    page_size = 10

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Any | None = None,
    ) -> None:
        candidate = base_url.strip().rstrip("/")
        parsed = urlparse(candidate)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise SearchProviderConfigurationError(
                "SearXNG URL inválida. Configure SEARXNG_URL ou TARRAFA_SEARXNG_URL."
            )
        if parsed.username or parsed.password:
            raise SearchProviderConfigurationError(
                "SearXNG URL não deve conter credenciais; configure autenticação no servidor."
            )
        self.endpoint = candidate if candidate.endswith("/search") else f"{candidate}/search"
        self.timeout = timeout
        self.transport = transport

    def search_page(
        self,
        query: str,
        *,
        page: int,
        country: str,
        language: str,
        freshness: str | None,
        safesearch: str,
    ) -> SearchPage:
        httpx = ensure_httpx()
        time_range = {
            "pd": "day",
            "pw": "week",
            "pm": "month",
            "py": "year",
        }.get(freshness or "")
        safe_value = {"off": 0, "moderate": 1, "strict": 2}[safesearch]
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "categories": "general",
            "language": language,
            "pageno": max(1, page),
            "safesearch": safe_value,
        }
        if time_range:
            params["time_range"] = time_range
        headers = {"Accept": "application/json", "User-Agent": DEFAULT_UA}
        try:
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=True,
                headers=headers,
                transport=self.transport,
            ) as client:
                response = client.get(self.endpoint, params=params)
        except Exception as exc:
            raise SearchProviderError(
                f"SearXNG: falha de rede ({type(exc).__name__})"
            ) from exc
        if response.status_code != 200:
            hint = (
                "formato JSON pode estar desabilitado na instância"
                if response.status_code == 403
                else "falha HTTP"
            )
            raise SearchProviderError(f"SearXNG: HTTP {response.status_code} ({hint})")
        try:
            data = response.json()
        except Exception as exc:
            raise SearchProviderError("SearXNG: resposta não-JSON") from exc
        if not isinstance(data, dict):
            raise SearchProviderError("SearXNG: resposta JSON inesperada")

        raw_results = data.get("results") or []
        items: list[dict[str, Any]] = []
        for raw in raw_results:
            if not isinstance(raw, dict) or not raw.get("url"):
                continue
            engines = raw.get("engines") or raw.get("engine")
            items.append(
                {
                    "url": str(raw["url"]),
                    "title": str(raw.get("title") or ""),
                    "snippet": str(raw.get("content") or ""),
                    "published_at": raw.get("publishedDate") or raw.get("published_date"),
                    "language": raw.get("language"),
                    "engine": engines,
                    "provider_meta": {
                        "score": raw.get("score"),
                        "category": raw.get("category"),
                    },
                }
            )
        return SearchPage(
            items=items,
            has_more=bool(items),
            total_hint=data.get("number_of_results")
            if isinstance(data.get("number_of_results"), int)
            else None,
            meta={
                "suggestions_count": len(data.get("suggestions") or []),
                "answers_count": len(data.get("answers") or []),
            },
        )


def resolve_provider(
    name: str,
    *,
    api_key: str | None = None,
    searxng_url: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> BaseSearchProvider:
    selected = name.strip().lower()
    brave_key = (
        api_key
        or os.environ.get("TARRAFA_BRAVE_SEARCH_API_KEY")
        or os.environ.get("BRAVE_SEARCH_API_KEY")
        or ""
    )
    sx_url = (
        searxng_url
        or os.environ.get("TARRAFA_SEARXNG_URL")
        or os.environ.get("SEARXNG_URL")
        or ""
    )
    if selected == "auto":
        if brave_key:
            selected = "brave"
        elif sx_url:
            selected = "searxng"
        else:
            # Provedor é o caminho opcional, não o pré-requisito: a maioria das
            # instalações não tem chave nem instância, e a descoberta continua
            # possível por fora, desde que registrada com --from-agent.
            raise SearchProviderConfigurationError(
                "Nenhum provedor configurado — isto é o normal, não um defeito. "
                "Faça a descoberta com as ferramentas que você já tem e registre o "
                "resultado com `tarrafa search --from-agent ARQUIVO.json`, que grava "
                "consulta, origem e proveniência. Provedor próprio (BRAVE_SEARCH_API_KEY "
                "ou SEARXNG_URL) é opcional, para quem quiser buscar dentro do CLI."
            )
    if selected == "brave":
        return BraveSearchProvider(brave_key, timeout=timeout)
    if selected == "searxng":
        return SearXNGSearchProvider(sx_url, timeout=timeout)
    raise SearchProviderConfigurationError(f"Provedor desconhecido: {name}")
