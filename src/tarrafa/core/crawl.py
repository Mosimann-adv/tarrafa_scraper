# -*- coding: utf-8 -*-
"""Controlled concurrent BFS crawl (same-host, max depth/pages)."""
from __future__ import annotations

import asyncio
from collections import deque
from typing import Any, Callable
from urllib.parse import urldefrag, urlparse

from tarrafa.core.extract import extract_article
from tarrafa.core.http import DEFAULT_CONCURRENCY, AsyncHTTPClient, same_registrable_host


def _canon(url: str) -> str:
    url, _ = urldefrag(url)
    # strip trailing slash for de-dupe except root
    p = urlparse(url)
    path = p.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    return p._replace(path=path, fragment="").geturl()


async def crawl_async(
    start_url: str,
    *,
    max_pages: int = 20,
    max_depth: int = 2,
    same_domain: bool = True,
    timeout: float = 30.0,
    concurrency: int = DEFAULT_CONCURRENCY,
    allowed_content_substrings: tuple[str, ...] = ("text/html", "application/xhtml"),
    on_page: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """
    Concurrent BFS crawl with deterministic processing order.

    A single AsyncHTTPClient (and therefore one connection pool) is shared for
    the complete crawl. Small queue batches are fetched concurrently, while
    responses and discovered links are processed in queue order.
    """
    start = _canon(start_url)
    q: deque[tuple[str, int]] = deque([(start, 0)])
    seen: set[str] = {start}
    pages: list[dict[str, Any]] = []
    errors: list[str] = []

    async with AsyncHTTPClient(timeout=timeout, concurrency=concurrency) as client:
        while q and len(pages) < max_pages:
            batch_size = min(concurrency, len(q), max_pages - len(pages))
            batch = [q.popleft() for _ in range(batch_size)]
            raw_results = await client.fetch_many(url for url, _depth in batch)

            for (url, depth), raw in zip(batch, raw_results):
                if raw.get("error"):
                    errors.append(f"{url}: {raw['error']}")
                    continue
                status = raw.get("status")
                if status and int(status) >= 400:
                    errors.append(f"{url}: HTTP {status}")
                    item = {
                        "url": url,
                        "final_url": raw.get("final_url"),
                        "status": status,
                        "depth": depth,
                        "title": None,
                        "text": "",
                        "text_len": 0,
                        "links": [],
                        "links_count": 0,
                        "extract_method": None,
                        "error": f"HTTP {status}",
                    }
                    pages.append(item)
                    if on_page:
                        on_page(item)
                    continue

                ctype = (raw.get("content_type") or "").lower()
                if allowed_content_substrings and not any(
                    substring in ctype for substring in allowed_content_substrings
                ):
                    errors.append(f"{url}: skip content-type {ctype or 'unknown'}")
                    continue

                final = raw.get("final_url") or url
                extracted = extract_article(raw.get("text") or "", final)
                item = {
                    **extracted,
                    "url": url,
                    "final_url": final,
                    "status": status,
                    "depth": depth,
                    "content_type": ctype,
                    "bytes_len": raw.get("bytes_len"),
                }
                pages.append(item)
                if on_page:
                    on_page(item)

                if depth >= max_depth:
                    continue
                for href in extracted.get("links") or []:
                    try:
                        link = _canon(href)
                    except Exception:
                        continue
                    if not link.startswith("http"):
                        continue
                    if same_domain and not same_registrable_host(start, link):
                        continue
                    if link in seen:
                        continue
                    seen.add(link)
                    q.append((link, depth + 1))
                    if len(seen) > max_pages * 20:
                        # safety: stop queue growth
                        break

    return {
        "pages": pages,
        "meta": {
            "start_url": start_url,
            "max_pages": max_pages,
            "max_depth": max_depth,
            "same_domain": same_domain,
            "visited": len(pages),
            "queued_seen": len(seen),
            "concurrency": concurrency,
        },
        "errors": errors,
    }


def crawl(
    start_url: str,
    *,
    max_pages: int = 20,
    max_depth: int = 2,
    same_domain: bool = True,
    timeout: float = 30.0,
    concurrency: int = DEFAULT_CONCURRENCY,
    allowed_content_substrings: tuple[str, ...] = ("text/html", "application/xhtml"),
    on_page: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Synchronous compatibility wrapper around :func:`crawl_async`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            crawl_async(
                start_url,
                max_pages=max_pages,
                max_depth=max_depth,
                same_domain=same_domain,
                timeout=timeout,
                concurrency=concurrency,
                allowed_content_substrings=allowed_content_substrings,
                on_page=on_page,
            )
        )
    raise RuntimeError("crawl cannot run inside an event loop; use crawl_async")
