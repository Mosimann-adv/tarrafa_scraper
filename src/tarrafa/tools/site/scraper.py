# -*- coding: utf-8 -*-
"""
tarrafa site — controlled same-host BFS crawl.

  tarrafa site --url https://example.com --out site.json --max-pages 10 --max-depth 2

Optional Scrapy is NOT required; crawl uses pooled async httpx + trafilatura.
Install scrapy later for advanced spiders if needed (optional extra).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tarrafa.core.crawl import crawl
from tarrafa.core.envelope import build_envelope
from tarrafa.core.writers import utc_now_iso, write_json


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa site",
        description="Crawl a site (concurrent BFS, same-domain) -> forensic JSON envelope.",
    )
    ap.add_argument("--url", required=True, help="Start URL")
    ap.add_argument("--out", required=True, help="Output JSON path")
    ap.add_argument("--max-pages", type=int, default=20, help="Max pages to fetch (default 20)")
    ap.add_argument("--max-depth", type=int, default=2, help="Max link depth from start (default 2)")
    ap.add_argument(
        "--all-domains",
        action="store_true",
        help="Allow leaving the start host (dangerous; default stays same domain)",
    )
    ap.add_argument("--timeout", type=float, default=30.0, help="Per-request timeout seconds")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)

    if args.max_pages < 1:
        print("--max-pages must be >= 1", file=sys.stderr)
        return 2
    if args.max_depth < 0:
        print("--max-depth must be >= 0", file=sys.stderr)
        return 2

    collected_at = utc_now_iso()
    result = crawl(
        args.url,
        max_pages=args.max_pages,
        max_depth=args.max_depth,
        same_domain=not args.all_domains,
        timeout=args.timeout,
    )

    items = result["pages"]
    # Slim items for dump (drop huge link lists? keep them — forensic)
    envelope = build_envelope(
        "site",
        source={"url": args.url},
        items=items,
        meta={
            **result["meta"],
            "engine": "bfs_httpx_async",
            "scrapy": "optional_not_used",
        },
        errors=result.get("errors") or [],
        notes=[
            "Controlled concurrent BFS crawl (pooled async httpx + trafilatura). Material-only.",
            "Same-domain by default. Use --all-domains with care.",
            "Scrapy is optional (pip install scrapy); this engine does not require it.",
        ],
        collected_at=collected_at,
    )

    out = Path(args.out)
    write_json(out, envelope)
    print(
        f"site: wrote {out}  pages={envelope['count']}  "
        f"depth<={args.max_depth}  errors={len(envelope.get('errors') or [])}"
    )
    if envelope.get("errors"):
        for e in envelope["errors"][:10]:
            print(f"  warn: {e}", file=sys.stderr)
        if len(envelope["errors"]) > 10:
            print(f"  … +{len(envelope['errors']) - 10} more", file=sys.stderr)
    if envelope["count"] == 0:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
