# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

import httpx

from tarrafa.core import crawl as crawl_module
from tarrafa.core.http import AsyncHTTPClient


def test_fetch_many_is_concurrent_but_bounded_and_ordered():
    active = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        return httpx.Response(200, text=request.url.path, headers={"content-type": "text/plain"})

    async def run():
        transport = httpx.MockTransport(handler)
        async with AsyncHTTPClient(
            concurrency=2, retries=0, transport=transport
        ) as client:
            return await client.fetch_many(
                [f"https://example.test/{number}" for number in range(5)]
            )

    results = asyncio.run(run())
    assert peak == 2
    assert [result["text"] for result in results] == [f"/{number}" for number in range(5)]


def test_retries_429_using_retry_after():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, text="ok", headers={"content-type": "text/plain"})

    async def run():
        async with AsyncHTTPClient(
            retries=2, backoff=0, transport=httpx.MockTransport(handler)
        ) as client:
            return await client.fetch("https://example.test/")

    result = asyncio.run(run())
    assert result["status"] == 200
    assert result["attempts"] == 2
    assert calls == 2


def test_does_not_retry_non_transient_http_status():
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="missing")

    async def run():
        async with AsyncHTTPClient(
            retries=2, backoff=0, transport=httpx.MockTransport(handler)
        ) as client:
            return await client.fetch("https://example.test/missing")

    result = asyncio.run(run())
    assert result["status"] == 404
    assert result["attempts"] == 1
    assert calls == 1


def test_crawl_concurrency_preserves_bfs_order(monkeypatch):
    responses = {
        "https://example.test/": {
            "url": "https://example.test/",
            "final_url": "https://example.test/",
            "status": 200,
            "content_type": "text/html",
            "text": "root",
            "bytes_len": 4,
            "error": None,
        },
        "https://example.test/a": {
            "url": "https://example.test/a",
            "final_url": "https://example.test/a",
            "status": 200,
            "content_type": "text/html",
            "text": "a",
            "bytes_len": 1,
            "error": None,
        },
        "https://example.test/b": {
            "url": "https://example.test/b",
            "final_url": "https://example.test/b",
            "status": 404,
            "content_type": "text/html",
            "text": "",
            "bytes_len": 0,
            "error": None,
        },
    }

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def fetch_many(self, urls):
            return [responses[url] for url in urls]

    def fake_extract(_html, url):
        links = (
            ["https://example.test/a", "https://example.test/b"]
            if url == "https://example.test/"
            else []
        )
        return {
            "url": url,
            "title": url,
            "text": url,
            "text_len": len(url),
            "links": links,
            "links_count": len(links),
            "extract_method": "fake",
        }

    monkeypatch.setattr(crawl_module, "AsyncHTTPClient", FakeClient)
    monkeypatch.setattr(crawl_module, "extract_article", fake_extract)

    result = asyncio.run(
        crawl_module.crawl_async(
            "https://example.test/",
            max_pages=3,
            max_depth=1,
            concurrency=2,
        )
    )

    assert [page["url"] for page in result["pages"]] == [
        "https://example.test/",
        "https://example.test/a",
        "https://example.test/b",
    ]
    assert result["pages"][2]["error"] == "HTTP 404"
