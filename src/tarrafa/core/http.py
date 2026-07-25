# -*- coding: utf-8 -*-
"""HTTP fetch helpers (httpx)."""
from __future__ import annotations

from typing import Any
from urllib.parse import urljoin, urlparse

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36 Tarrafa/0.2"
)
DEFAULT_TIMEOUT = 30.0


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


def fetch_url(
    url: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
) -> dict[str, Any]:
    """GET url → {url, final_url, status, content_type, text, encoding, error?}."""
    httpx = ensure_httpx()
    hdrs = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"}
    if headers:
        hdrs.update(headers)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=follow_redirects, headers=hdrs) as client:
            r = client.get(url)
            ctype = r.headers.get("content-type", "")
            # Prefer text; for binary keep empty text
            text = r.text if "image/" not in ctype and "application/pdf" not in ctype else ""
            return {
                "url": url,
                "final_url": str(r.url),
                "status": r.status_code,
                "content_type": ctype,
                "encoding": r.encoding,
                "text": text,
                "bytes_len": len(r.content),
                "error": None,
            }
    except Exception as e:
        return {
            "url": url,
            "final_url": url,
            "status": None,
            "content_type": None,
            "encoding": None,
            "text": "",
            "bytes_len": 0,
            "error": f"{type(e).__name__}: {e}",
        }


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
