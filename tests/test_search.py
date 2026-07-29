# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx

from tarrafa.tools.search.providers import (
    BRAVE_ENDPOINT,
    BaseSearchProvider,
    BraveSearchProvider,
    SearchPage,
    SearchProviderConfigurationError,
    SearXNGSearchProvider,
    resolve_provider,
)
from tarrafa.tools.search.scraper import (
    canonicalize_url,
    main,
    query_sha256,
    redact_sensitive_query,
    sensitive_query_kinds,
)


class FakeProvider(BaseSearchProvider):
    name = "fake"
    page_size = 2

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
        if page > 1:
            return SearchPage()
        return SearchPage(
            items=[
                {
                    "url": "https://Example.com/perfil/?utm_source=busca&b=2&a=1",
                    "title": "Perfil",
                    "snippet": "Resultado candidato",
                    "engine": "fake",
                },
                {
                    "url": "https://example.com/perfil?a=1&b=2#trecho",
                    "title": "Duplicado",
                    "snippet": "Mesmo endereço",
                    "engine": "fake",
                },
            ],
            has_more=False,
        )


def test_canonicalize_url_remove_tracking_e_fragmento():
    assert (
        canonicalize_url("HTTPS://Example.COM/a/?utm_source=x&b=2&a=1#frag")
        == "https://example.com/a?a=1&b=2"
    )
    assert canonicalize_url("javascript:alert(1)") is None


def test_sensitive_query_detection_and_redaction():
    email = "".join(("usuario", "@", "example.invalid"))
    query = f'"Pessoa Exemplo" {email}'
    assert sensitive_query_kinds(query) == ["email"]
    assert redact_sensitive_query(query) == '"Pessoa Exemplo" <EMAIL>'
    assert len(query_sha256(query)) == 64


def test_brave_provider_parses_web_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(BRAVE_ENDPOINT)
        assert request.headers["x-subscription-token"] == "segredo-sintetico"
        return httpx.Response(
            200,
            json={
                "query": {"original": "teste"},
                "web": {
                    "more_results_available": False,
                    "results": [
                        {
                            "url": "https://example.com/a",
                            "title": "A",
                            "description": "Trecho A",
                            "language": "pt",
                        }
                    ],
                },
            },
        )

    provider = BraveSearchProvider(
        "segredo-sintetico",
        transport=httpx.MockTransport(handler),
    )
    page = provider.search_page(
        "teste",
        page=1,
        country="BR",
        language="pt-br",
        freshness=None,
        safesearch="moderate",
    )
    assert provider.name == "brave"
    assert page.items[0]["url"] == "https://example.com/a"
    assert page.items[0]["snippet"] == "Trecho A"


def test_searxng_provider_parses_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search"
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.org/b",
                        "title": "B",
                        "content": "Trecho B",
                        "engines": ["brave", "duckduckgo"],
                        "score": 2.5,
                    }
                ],
                "suggestions": [],
            },
        )

    provider = SearXNGSearchProvider(
        "https://searx.example.org",
        transport=httpx.MockTransport(handler),
    )
    page = provider.search_page(
        "teste",
        page=1,
        country="BR",
        language="pt-BR",
        freshness="pw",
        safesearch="strict",
    )
    assert provider.name == "searxng"
    assert page.items[0]["url"] == "https://example.org/b"
    assert page.items[0]["engine"] == ["brave", "duckduckgo"]


def test_resolve_provider_auto_requires_configuration(monkeypatch):
    for name in (
        "BRAVE_SEARCH_API_KEY",
        "TARRAFA_BRAVE_SEARCH_API_KEY",
        "SEARXNG_URL",
        "TARRAFA_SEARXNG_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    try:
        resolve_provider("auto")
    except SearchProviderConfigurationError as exc:
        assert "Nenhum provedor" in str(exc)
    else:
        raise AssertionError("deveria exigir configuração")


def test_main_writes_envelope_and_urls(tmp_path: Path):
    out = tmp_path / "search.json"
    urls = tmp_path / "urls.txt"
    with patch(
        "tarrafa.tools.search.scraper.resolve_provider",
        return_value=FakeProvider(),
    ):
        code = main(
            [
                "--query",
                '"Pessoa Exemplo" cidade',
                "--out",
                str(out),
                "--urls-out",
                str(urls),
            ]
        )
    assert code == 0
    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["tool"] == "search"
    assert envelope["count"] == 1
    assert envelope["items"][0]["kind"] == "search_candidate"
    assert envelope["items"][0]["canonical_url"] == "https://example.com/perfil?a=1&b=2"
    assert envelope["items"][0]["discovered_by"][0]["query_id"] == "Q001"
    assert envelope["source"]["queries"][0]["display"] == '"Pessoa Exemplo" cidade'
    assert urls.read_text(encoding="utf-8") == "https://example.com/perfil?a=1&b=2\n"


def test_main_blocks_sensitive_query_before_provider(tmp_path: Path):
    out = tmp_path / "blocked.json"
    email = "".join(("usuario", "@", "example.invalid"))
    with patch("tarrafa.tools.search.scraper.resolve_provider") as resolver:
        code = main(["--query", email, "--out", str(out)])
    assert code == 2
    assert not resolver.called
    assert not out.exists()


def test_main_masks_allowed_sensitive_query_without_persistent_hash(tmp_path: Path):
    out = tmp_path / "allowed.json"
    synthetic_cpf = "".join(("000", ".", "000", ".", "000", "-", "00"))
    with patch(
        "tarrafa.tools.search.scraper.resolve_provider",
        return_value=FakeProvider(),
    ):
        code = main(
            [
                "--query",
                f'"Pessoa Exemplo" {synthetic_cpf}',
                "--allow-sensitive-query",
                "--out",
                str(out),
            ]
        )
    assert code == 0
    text = out.read_text(encoding="utf-8")
    envelope = json.loads(text)
    query_record = envelope["source"]["queries"][0]
    assert synthetic_cpf not in text
    assert query_record["display"] == '"Pessoa Exemplo" <CPF>'
    assert query_record["sha256"] is None


def test_main_rejects_same_json_and_urls_output(tmp_path: Path):
    out = tmp_path / "same.out"
    with patch("tarrafa.tools.search.scraper.resolve_provider") as resolver:
        code = main(
            [
                "--query",
                "consulta pública",
                "--out",
                str(out),
                "--urls-out",
                str(out),
            ]
        )
    assert code == 2
    assert not resolver.called
    assert not out.exists()
