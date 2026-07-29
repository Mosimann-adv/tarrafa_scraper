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


def test_resolve_provider_auto_without_config_points_to_handoff(monkeypatch):
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
        message = str(exc)
        assert "normal, não um defeito" in message
        assert "--from-agent" in message
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


# --- descoberta repassada de fora do CLI (--from-agent) -----------------------


def _handoff(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "repasse.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_from_agent_records_provenance_without_provider(tmp_path):
    """Sem provedor configurado, o registro ainda tem que existir."""
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "nenhum resultado descartado",
            "queries": [
                {
                    "query": "\"Nome Completo\" cidade",
                    "results": [
                        {"url": "https://exemplo.test/a", "title": "A"},
                        "https://exemplo.test/b",
                    ],
                }
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["source"]["provider"] == "agent:assistente X"
    assert envelope["meta"]["requests"] == 0
    assert envelope["meta"]["agent_note"] == "nenhum resultado descartado"
    assert envelope["count"] == 2
    assert "não executou a busca" in envelope["notes"][0]


def test_from_agent_canonicalizes_and_deduplicates(tmp_path):
    """A mesma URL com parâmetro de rastreio não pode virar dois candidatos."""
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "nenhum resultado descartado",
            "queries": [
                {
                    "query": "consulta",
                    "results": [
                        "https://exemplo.test/pagina",
                        "https://exemplo.test/pagina?utm_source=x&fbclid=y",
                    ],
                }
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["count"] == 1
    assert envelope["meta"]["duplicates_removed"] == 1
    assert len(envelope["items"][0]["discovered_by"]) == 2


def test_from_agent_discards_invalid_url_as_partial(tmp_path):
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "URL inválida registrada no envelope",
            "queries": [
                {"query": "c", "results": ["https://exemplo.test/ok", "nao-e-url"]}
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 1

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["count"] == 1
    assert envelope["meta"]["discarded_invalid_urls"] == 1
    assert envelope["errors"]


def test_from_agent_merges_repeated_query(tmp_path):
    """Consulta repetida vira um bloco; o pareamento posicional não pode desalinhar."""
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "nenhum resultado descartado",
            "queries": [
                {"query": "mesma", "results": ["https://exemplo.test/1"]},
                {"query": "mesma", "results": ["https://exemplo.test/2"]},
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["meta"]["queries"] == 1
    assert envelope["count"] == 2
    for item in envelope["items"]:
        assert item["discovered_by"][0]["query_id"] == "Q001"


def test_from_agent_requires_agent_field(tmp_path):
    handoff = _handoff(
        tmp_path,
        {
            "note": "nenhum resultado descartado",
            "queries": [{"query": "c", "results": []}],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 2
    assert not out.exists()


def test_from_agent_requires_discard_note(tmp_path, capsys):
    handoff = _handoff(
        tmp_path,
        {"agent": "assistente X", "queries": [{"query": "c", "results": []}]},
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 2
    assert not out.exists()
    assert "campo 'note' obrigatório" in capsys.readouterr().err


def test_from_agent_rejects_malformed_json(tmp_path):
    path = tmp_path / "repasse.json"
    path.write_text("{isto nao e json", encoding="utf-8")
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(path), "--out", str(out)]) == 2


def test_from_agent_conflicts_with_query(tmp_path):
    handoff = _handoff(
        tmp_path,
        {
            "agent": "x",
            "note": "nenhum resultado descartado",
            "queries": [{"query": "c", "results": []}],
        },
    )
    out = tmp_path / "search.json"
    code = main(["--from-agent", str(handoff), "--query", "outra", "--out", str(out)])
    assert code == 2


def test_from_agent_masks_sensitive_query_without_blocking(tmp_path):
    """A busca externa já ocorreu: bloquear não desfaz o envio, só apaga o rastro."""
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "nenhum resultado descartado",
            "queries": [
                {
                    "query": "fulano 123.456.789-09",
                    "results": ["https://exemplo.test/x"],
                }
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(["--from-agent", str(handoff), "--out", str(out)]) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    consulta = envelope["source"]["queries"][0]
    assert "123.456.789-09" not in json.dumps(envelope, ensure_ascii=False)
    assert consulta["display"] == "fulano <CPF>"
    assert consulta["sha256"] is None
    assert any("provedor externo antes deste registro" in n for n in envelope["notes"])


def test_from_agent_urls_out_feeds_page(tmp_path):
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "nenhum resultado descartado",
            "queries": [
                {"query": "c", "results": ["https://exemplo.test/a", "https://exemplo.test/b"]}
            ],
        },
    )
    out = tmp_path / "search.json"
    urls = tmp_path / "urls.txt"
    assert main(["--from-agent", str(handoff), "--urls-out", str(urls), "--out", str(out)]) == 0
    assert urls.read_text(encoding="utf-8").splitlines() == [
        "https://exemplo.test/a",
        "https://exemplo.test/b",
    ]


def test_from_agent_reports_received_processed_and_truncated_results(tmp_path):
    handoff = _handoff(
        tmp_path,
        {
            "agent": "assistente X",
            "note": "terceiro resultado não processado pelo limite",
            "queries": [
                {
                    "query": "c",
                    "results": [
                        "https://exemplo.test/a",
                        "https://exemplo.test/b",
                        "https://exemplo.test/c",
                    ],
                }
            ],
        },
    )
    out = tmp_path / "search.json"
    assert main(
        ["--from-agent", str(handoff), "--max-results", "1", "--out", str(out)]
    ) == 0

    envelope = json.loads(out.read_text(encoding="utf-8"))
    assert envelope["count"] == 1
    assert envelope["meta"]["raw_results"] == 3
    assert envelope["meta"]["received_results"] == 3
    assert envelope["meta"]["processed_results"] == 1
    assert envelope["meta"]["truncated_results"] == 2
    assert envelope["meta"]["duplicates_removed"] == 0
