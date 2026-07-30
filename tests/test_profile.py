# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from tarrafa.tools.profile.scraper import (
    generate_initial_queries,
    inventory_articles,
    inventory_external_articles,
    main,
    score_candidate,
)


def test_generate_initial_queries_diversifies_name_handle_and_content():
    queries = generate_initial_queries(
        name="Marina de Luz",
        handle="@marinaluz",
        profession="arquiteta",
        location="Curitiba PR",
        keywords=["urbanismo"],
    )

    assert '"Marina de Luz"' in queries
    assert '"Marina Luz" blog OR artigo OR autor' in queries
    assert '"marinaluz"' in queries
    assert any("arquiteta" in query for query in queries)
    assert any("urbanismo" in query for query in queries)


def test_score_candidate_prioritizes_independent_domain_with_identity_anchors():
    scored = score_candidate(
        {
            "url": "https://marina-luz.example/",
            "canonical_url": "https://marina-luz.example/",
            "title": "Marina Luz | Arquitetura e Urbanismo",
            "snippet": "Portfólio e artigos de Marina Luz.",
        },
        name="Marina de Luz",
        handle="@marinaluz",
        profession="arquitetura",
        keywords=["urbanismo"],
    )

    assert scored["domain_class"] == "independent"
    assert scored["identity_score"] >= 50
    assert "nome_curto" in scored["score_reasons"]


def test_inventory_articles_combines_crawl_and_sitemap():
    pages = [
        {
            "url": "https://marina-luz.example/blog/cidades-caminhaveis",
            "final_url": "https://marina-luz.example/blog/cidades-caminhaveis",
            "title": "Cidades caminháveis",
            "author": "Marina Luz",
            "date": "2026-05-10",
            "text_len": 1200,
        }
    ]
    articles = inventory_articles(
        pages,
        [
            "https://marina-luz.example/blog/cidades-caminhaveis",
            "https://marina-luz.example/artigos/mobilidade",
        ],
        name="Marina de Luz",
    )

    assert len(articles) == 2
    assert {item["discovered_via"] for item in articles} == {"crawl", "sitemap"}


def test_inventory_external_articles_keeps_captured_editorial_candidate():
    articles = inventory_external_articles(
        [
            {
                "canonical_url": "https://revista.example/article/view/42",
                "title": "Cidades e cuidado",
                "identity_score": 28,
            },
            {
                "canonical_url": "https://entidade.example/noticias/nova-comissao",
                "title": "Nova comissão profissional",
                "identity_score": 45,
            },
            {
                "canonical_url": "https://revista.example/article/view/antigo",
                "title": "Página antiga",
                "identity_score": 28,
            }
        ],
        [
            {
                "url": "https://revista.example/article/view/42",
                "final_url": "https://revista.example/article/view/42",
                "status": 200,
                "title": "Cidades e cuidado",
                "text_len": 1800,
            },
            {
                "url": "https://entidade.example/noticias/nova-comissao",
                "final_url": "https://entidade.example/noticias/nova-comissao",
                "status": 200,
                "title": "Nova comissão profissional",
                "text_len": 900,
            },
            {
                "url": "https://revista.example/article/view/antigo",
                "final_url": "https://revista.example/article/view/antigo",
                "status": 404,
                "title": "404",
                "text_len": 30,
            }
        ],
        name="Marina de Luz",
    )

    assert len(articles) == 1
    assert articles[0]["discovered_via"] == "search_capture"
    assert articles[0]["relationship"] == "candidate"


def test_profile_rejects_sensitive_anchor(tmp_path: Path, capsys):
    code = main(
        [
            "--name",
            "Pessoa Exemplo 123.456.789-09",
            "--from-agent",
            str(tmp_path / "unused.json"),
            "--out-dir",
            str(tmp_path / "out"),
        ]
    )

    assert code == 2
    assert "âncora sensível bloqueada" in capsys.readouterr().err
    assert not (tmp_path / "out" / "profile.json").exists()


def test_profile_from_agent_emits_followups_and_expands_site(tmp_path: Path):
    handoff = tmp_path / "repasse.json"
    handoff.write_text(
        json.dumps(
            {
                "agent": "busca sintética",
                "note": "nenhum descarte",
                "queries": [
                    {
                        "query": '"Marina de Luz"',
                        "results": [
                            {
                                "url": "https://marina-luz.example/",
                                "title": "Marina Luz | Arquitetura",
                                "snippet": "Portfólio e artigos de urbanismo.",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "profile"

    fake_capture = {
        "items": [
            {
                "url": "https://marina-luz.example/",
                "final_url": "https://marina-luz.example/",
                "status": 200,
                "title": "Marina Luz | Arquitetura",
                "author": None,
                "date": None,
                "text": "Marina Luz, arquiteta. Leia artigos sobre urbanismo.",
                "links": ["https://marina-luz.example/blog/cidades-caminhaveis"],
                "links_count": 1,
                "extract_method": "fixture",
            }
        ],
        "errors": [],
    }
    fake_crawl = {
        "pages": [
            {
                "url": "https://marina-luz.example/",
                "final_url": "https://marina-luz.example/",
                "title": "Marina Luz | Arquitetura",
                "author": None,
                "date": None,
                "text": "Marina Luz, arquiteta e autora de artigos de urbanismo.",
                "text_len": 58,
                "links": ["https://marina-luz.example/blog/cidades-caminhaveis"],
            },
            {
                "url": "https://marina-luz.example/blog/cidades-caminhaveis",
                "final_url": "https://marina-luz.example/blog/cidades-caminhaveis",
                "title": "Cidades caminháveis",
                "author": "Marina Luz",
                "date": "2026-05-10",
                "text": "Conteúdo sintético para teste.",
                "text_len": 30,
                "links": [],
            },
        ],
        "meta": {"visited": 2},
        "errors": [],
    }

    with (
        patch("tarrafa.tools.profile.scraper.capture_page", return_value=fake_capture),
        patch("tarrafa.tools.profile.scraper.crawl", return_value=fake_crawl),
        patch(
            "tarrafa.tools.profile.scraper._discover_sitemap_urls",
            return_value=(
                ["https://marina-luz.example/blog/cidades-caminhaveis"],
                [],
            ),
        ),
    ):
        code = main(
            [
                "--name",
                "Marina de Luz",
                "--handle",
                "@marinaluz",
                "--profession",
                "arquiteta",
                "--keyword",
                "urbanismo",
                "--from-agent",
                str(handoff),
                "--out-dir",
                str(out),
            ]
        )

    assert code == 0
    payload = json.loads((out / "profile.json").read_text(encoding="utf-8"))
    item = payload["items"][0]
    assert payload["meta"]["authored_content"] == 1
    assert payload["meta"]["followup_queries_pending"] >= 1
    assert item["sites"][0]["relationship"] == "strong_candidate"
    assert item["authored_content"][0]["author"] == "Marina Luz"
    assert payload["meta"]["html"]["generated"] is True
    assert item["html"]["sources"] >= 2
    assert (out / "profile.html").is_file()
    html = (out / "profile.html").read_text(encoding="utf-8")
    assert "Marina de Luz" in html
    assert "Cidades caminháveis" in html
    assert (out / "queries_followup.txt").is_file()
    assert (out / "site_marina_luz_example.json").is_file()


def test_profile_clears_stale_followup_file_when_search_is_complete(tmp_path: Path):
    handoff = tmp_path / "repasse.json"
    handoff.write_text(
        json.dumps(
            {
                "agent": "busca sintética",
                "note": "nenhum resultado pertinente",
                "queries": [{"query": '"Pessoa Exemplo"', "results": []}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    out = tmp_path / "profile"
    out.mkdir()
    followup = out / "queries_followup.txt"
    followup.write_text("consulta antiga\n", encoding="utf-8")

    code = main(
        [
            "--name",
            "Pessoa Exemplo",
            "--from-agent",
            str(handoff),
            "--out-dir",
            str(out),
            "--no-html",
        ]
    )

    assert code == 6
    assert followup.read_text(encoding="utf-8") == ""
