# -*- coding: utf-8 -*-
"""
tarrafa feed — RSS/Atom inventory.

  tarrafa feed --url https://example.com/feed.xml --out feed.json
  tarrafa feed --url … --fetch-entries --max-entries 5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.http import fetch_url
from tarrafa.core.writers import utc_now_iso, write_json


def _parse_feed(body: str, url: str) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    try:
        import feedparser
    except ImportError as e:
        raise SystemExit(
            "Missing dependency: feedparser. Install: pip install feedparser"
        ) from e

    parsed = feedparser.parse(body)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        bozo_exc = getattr(parsed, "bozo_exception", None)
        errors.append(f"feed parse warning: {bozo_exc or 'bozo'}")

    feed_meta = {
        "title": getattr(parsed.feed, "title", None),
        "link": getattr(parsed.feed, "link", None) or url,
        "subtitle": getattr(parsed.feed, "subtitle", None),
        "language": getattr(parsed.feed, "language", None),
        "updated": getattr(parsed.feed, "updated", None),
        "version": getattr(parsed, "version", None),
    }

    items: list[dict[str, Any]] = []
    for e in parsed.entries:
        link = getattr(e, "link", None)
        # prefer id/guid
        entry_id = getattr(e, "id", None) or getattr(e, "guid", None) or link
        published = getattr(e, "published", None) or getattr(e, "updated", None)
        summary = getattr(e, "summary", None) or ""
        # content list
        content_text = summary
        if getattr(e, "content", None):
            try:
                content_text = e.content[0].value or summary
            except Exception:
                pass
        authors = []
        if getattr(e, "author", None):
            authors.append(e.author)
        items.append(
            {
                "id": entry_id,
                "title": getattr(e, "title", None),
                "link": link,
                "published": published,
                "authors": authors,
                "summary": summary,
                "content": content_text,
                "tags": [t.term for t in getattr(e, "tags", []) or [] if getattr(t, "term", None)],
            }
        )
    return feed_meta, items, errors


def capture_feed(
    url: str,
    *,
    max_entries: int | None = None,
    fetch_entries: bool = False,
    timeout: float = 30.0,
) -> dict[str, Any]:
    collected_at = utc_now_iso()
    raw = fetch_url(
        url,
        timeout=timeout,
        headers={"Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"},
    )
    errors: list[str] = []
    if raw.get("error"):
        return build_envelope(
            "feed",
            source={"url": url},
            items=[],
            meta={},
            errors=[raw["error"]],
            notes=["Feed download failed."],
            collected_at=collected_at,
        )
    if raw.get("status") and int(raw["status"]) >= 400:
        errors.append(f"HTTP {raw['status']}")

    feed_meta, items, parse_errs = _parse_feed(raw.get("text") or "", url)
    errors.extend(parse_errs)

    if max_entries is not None and max_entries >= 0:
        items = items[:max_entries]

    if fetch_entries:
        from tarrafa.tools.page.scraper import capture_page

        for it in items:
            link = it.get("link")
            if not link:
                it["fetched"] = None
                continue
            page_env = capture_page(link, mode="http", timeout=timeout)
            page_items = page_env.get("items") or []
            if page_items:
                it["fetched"] = {
                    "title": page_items[0].get("title"),
                    "text": page_items[0].get("text"),
                    "text_len": page_items[0].get("text_len"),
                    "final_url": page_items[0].get("final_url"),
                    "status": page_items[0].get("status"),
                }
            else:
                it["fetched"] = {"error": (page_env.get("errors") or ["empty"])[0]}

    return build_envelope(
        "feed",
        source={"url": url, "final_url": raw.get("final_url")},
        items=items,
        meta={
            "feed": feed_meta,
            "status": raw.get("status"),
            "fetch_entries": fetch_entries,
            "max_entries": max_entries,
        },
        errors=errors,
        notes=[
            "RSS/Atom inventory via feedparser. Material-only.",
            "Use --fetch-entries to HTTP-fetch full text of each entry link.",
        ],
        collected_at=collected_at,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa feed",
        description="Parse RSS/Atom feed → forensic JSON envelope.",
    )
    ap.add_argument("--url", required=True, help="Feed URL")
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--max-entries", type=int, default=None, help="Cap number of entries")
    ap.add_argument(
        "--fetch-entries",
        action="store_true",
        help="Also fetch each entry link body (HTTP extract)",
    )
    ap.add_argument("--timeout", type=float, default=30.0, help="Timeout seconds")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    payload = capture_feed(
        args.url,
        max_entries=args.max_entries,
        fetch_entries=args.fetch_entries,
        timeout=args.timeout,
    )
    out = Path(args.out)
    write_json(out, payload)
    print(f"feed: wrote {out}  entries={payload.get('count')}  title={(payload.get('meta') or {}).get('feed', {}).get('title')}")
    if payload.get("errors"):
        for e in payload["errors"]:
            print(f"  warn: {e}", file=sys.stderr)
    if payload.get("count", 0) == 0:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
