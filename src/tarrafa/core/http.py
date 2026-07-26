# -*- coding: utf-8 -*-
"""HTTP fetch helpers backed by a reusable async httpx client."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 Tarrafa/0.2"
)
DEFAULT_TIMEOUT = 30.0
DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_CONNECTIONS = 8
DEFAULT_MAX_KEEPALIVE_CONNECTIONS = 4
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF = 0.25
MAX_RETRY_DELAY = 5.0


def ensure_httpx():
    try:
        import httpx  # noqa: F401
    except ImportError as e:
        raise SystemExit(
            "Missing dependency: httpx. Install with: pip install 'tarrafa-scraper[web]' "
            "or: pip install httpx trafilatura feedparser"
        ) from e
    import httpx

    return httpx


def _headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    result = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    if headers:
        result.update(headers)
    return result


def _result_from_response(url: str, response: Any, *, attempts: int) -> dict[str, Any]:
    ctype = response.headers.get("content-type", "")
    # Avoid decoding common binary formats into a potentially huge string.
    text = (
        response.text
        if "image/" not in ctype.lower() and "application/pdf" not in ctype.lower()
        else ""
    )
    return {
        "url": url,
        "final_url": str(response.url),
        "status": response.status_code,
        "content_type": ctype,
        "encoding": response.encoding,
        "text": text,
        "bytes_len": len(response.content),
        "error": None,
        "attempts": attempts,
    }


def _error_result(url: str, error: Exception, *, attempts: int) -> dict[str, Any]:
    return {
        "url": url,
        "final_url": url,
        "status": None,
        "content_type": None,
        "encoding": None,
        "text": "",
        "bytes_len": 0,
        "error": f"{type(error).__name__}: {error}",
        "attempts": attempts,
    }


def _retry_after_seconds(value: str | None, *, now: datetime | None = None) -> float | None:
    """Parse Retry-After seconds or HTTP date, capped to a short operational delay."""
    if not value:
        return None
    value = value.strip()
    try:
        seconds = max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            current = now or datetime.now(timezone.utc)
            seconds = max(0.0, (retry_at - current).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    return min(seconds, MAX_RETRY_DELAY)


class AsyncHTTPClient:
    """Reusable HTTP operation with pooling, concurrency control and short retries."""

    def __init__(
        self,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        headers: dict[str, str] | None = None,
        follow_redirects: bool = True,
        concurrency: int = DEFAULT_CONCURRENCY,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections: int = DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        transport: Any | None = None,
    ) -> None:
        if concurrency < 1:
            raise ValueError("concurrency must be >= 1")
        if retries < 0:
            raise ValueError("retries must be >= 0")

        httpx = ensure_httpx()
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
            keepalive_expiry=15.0,
        )
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=follow_redirects,
            headers=_headers(headers),
            limits=limits,
            transport=transport,
        )
        self._semaphore = asyncio.Semaphore(concurrency)
        self.retries = retries
        self.backoff = max(0.0, backoff)
        self._closed = False

    async def __aenter__(self) -> AsyncHTTPClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            await self._client.aclose()

    async def fetch(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Fetch one URL while sharing this operation's pool and concurrency budget."""
        if self._closed:
            raise RuntimeError("AsyncHTTPClient is closed")

        httpx = ensure_httpx()
        transient_errors = (
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
        )
        max_attempts = self.retries + 1

        async with self._semaphore:
            for attempt in range(1, max_attempts + 1):
                try:
                    response = await self._client.get(url, headers=headers)
                except transient_errors as error:
                    if attempt >= max_attempts:
                        return _error_result(url, error, attempts=attempt)
                    await asyncio.sleep(self.backoff * (2 ** (attempt - 1)))
                    continue
                except Exception as error:
                    # Configuration, URL and programming errors are not transient.
                    return _error_result(url, error, attempts=attempt)

                retryable_status = response.status_code == 429 or 500 <= response.status_code < 600
                if not retryable_status or attempt >= max_attempts:
                    return _result_from_response(url, response, attempts=attempt)

                retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(self.backoff * (2 ** (attempt - 1)), MAX_RETRY_DELAY)
                )
                await asyncio.sleep(delay)

        raise RuntimeError("unreachable")

    async def fetch_many(self, urls: Iterable[str]) -> list[dict[str, Any]]:
        """Fetch URLs concurrently and return results in input order."""
        return list(await asyncio.gather(*(self.fetch(url) for url in urls)))


async def fetch_url_async(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    retries: int = DEFAULT_RETRIES,
) -> dict[str, Any]:
    """One-shot async fetch; use :class:`AsyncHTTPClient` to share an operation pool."""
    async with AsyncHTTPClient(
        timeout=timeout,
        headers=headers,
        follow_redirects=follow_redirects,
        concurrency=1,
        retries=retries,
    ) as client:
        return await client.fetch(url)


def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    """Synchronous compatibility API for a single HTTP fetch."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_url_async(
                url,
                timeout=timeout,
                headers=headers,
                follow_redirects=follow_redirects,
            )
        )
    raise RuntimeError("fetch_url cannot run inside an event loop; use fetch_url_async")


def same_registrable_host(a: str, b: str) -> bool:
    """Loose same-host check (netloc, ignore www.)."""
    ha = (urlparse(a).netloc or "").lower().removeprefix("www.")
    hb = (urlparse(b).netloc or "").lower().removeprefix("www.")
    return bool(ha) and ha == hb


def normalize_link(base: str, href: str | None) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return None
    try:
        return urljoin(base, href)
    except Exception:
        return None
