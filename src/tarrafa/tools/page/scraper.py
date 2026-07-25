# -*- coding: utf-8 -*-
"""
tarrafa page — capture one public URL (HTTP and/or browser).

  tarrafa page --url https://example.com --out page.json
  tarrafa page --url … --mode browser --storage-state …

Extraction: trafilatura main text + structured facts (meta/JSON-LD/embedded
counters) + optional browser visible text — so UI chrome (e.g. signature count,
creator name) is not lost when the article body is long enough.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.extract import extract_article, facts_missing_from_text
from tarrafa.core.http import fetch_url
from tarrafa.core.writers import utc_now_iso, write_json


def _fetch_browser(
    url: str,
    storage_state: str | None,
    timeout_ms: int = 60_000,
    wait_ms: int = 1500,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        return {
            "error": f"playwright not installed: {e}",
            "text": "",
            "visible_text": "",
            "final_url": url,
            "status": None,
        }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx_kwargs: dict[str, Any] = {}
            if storage_state and Path(storage_state).is_file():
                ctx_kwargs["storage_state"] = storage_state
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            resp = page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(max(0, wait_ms))
            # networkidle is flaky on analytics-heavy sites; best-effort
            try:
                page.wait_for_load_state("networkidle", timeout=min(8000, timeout_ms))
            except Exception:
                pass
            html = page.content()
            try:
                visible = page.inner_text("body")
            except Exception:
                visible = ""
            final = page.url
            status = resp.status if resp else None
            context.close()
            browser.close()
            return {
                "error": None,
                "text": html,
                "visible_text": visible,
                "final_url": final,
                "status": status,
                "content_type": "text/html",
                "bytes_len": len(html.encode("utf-8", errors="replace")),
            }
    except Exception as e:
        return {
            "error": f"{type(e).__name__}: {e}",
            "text": "",
            "visible_text": "",
            "final_url": url,
            "status": None,
        }


def _looks_thin(extracted: dict[str, Any], html: str) -> bool:
    text = extracted.get("text_main") or extracted.get("text") or ""
    if len(text) >= 200:
        # Long article can still miss structured chrome — do NOT force browser
        # solely for that (HTTP already has JSON-LD). Browser is for empty SPA shells.
        return False
    low = (html or "").lower()
    if 'id="root"' in low or "id='root'" in low or "__next" in low:
        return True
    if len(text) < 80:
        return True
    return False


def _needs_browser_for_missing_facts(extracted: dict[str, Any]) -> bool:
    """Optional: if HTTP extract still misses high-value fact kinds, try browser visible text."""
    facts = extracted.get("structured_facts") or []
    text = extracted.get("text") or ""
    missing = facts_missing_from_text(facts, extracted.get("text_main") or text)
    kinds = {f.get("kind") for f in missing}
    return bool(kinds & {"signature_count", "person", "display_name"})


def capture_page(
    url: str,
    *,
    mode: str = "auto",
    storage_state: str | None = None,
    timeout: float = 30.0,
    include_html: bool = False,
    enrich: bool = True,
    browser_if_missing_facts: bool = True,
) -> dict[str, Any]:
    collected_at = utc_now_iso()
    errors: list[str] = []
    methods: list[str] = []
    raw_html = ""
    visible_text: str | None = None
    final_url = url
    status = None
    used = None

    mode = (mode or "auto").lower()
    if mode not in ("auto", "http", "browser"):
        errors.append(f"unknown mode {mode!r}; using auto")
        mode = "auto"

    extracted_http: dict[str, Any] | None = None

    if mode in ("auto", "http"):
        raw = fetch_url(url, timeout=timeout)
        if raw.get("error"):
            errors.append(f"http: {raw['error']}")
        else:
            methods.append("http")
            raw_html = raw.get("text") or ""
            final_url = raw.get("final_url") or url
            status = raw.get("status")
            used = "http"
            extracted_http = extract_article(raw_html, final_url, enrich=enrich)

    need_browser = mode == "browser" or (
        mode == "auto"
        and (
            used is None
            or _looks_thin(extracted_http or {}, raw_html)
            or (browser_if_missing_facts and extracted_http is not None and _needs_browser_for_missing_facts(extracted_http))
        )
    )

    if need_browser and mode != "http":
        b = _fetch_browser(url, storage_state, timeout_ms=int(timeout * 1000))
        if b.get("error"):
            errors.append(f"browser: {b['error']}")
            # keep HTTP extract if we had one
        else:
            methods.append("browser")
            raw_html = b.get("text") or raw_html
            visible_text = b.get("visible_text") or ""
            final_url = b.get("final_url") or final_url
            status = b.get("status") if b.get("status") is not None else status
            used = "browser" if mode == "browser" or not extracted_http else "http+browser"

    if not raw_html and used is None:
        env = build_envelope(
            "page",
            source={"url": url},
            items=[],
            meta={"mode": mode, "methods": methods, "used": used},
            errors=errors or ["empty response"],
            notes=["Single-page capture failed."],
            collected_at=collected_at,
        )
        return env

    # Prefer re-extract with visible text when browser ran; else use HTTP extract
    if visible_text is not None and "browser" in methods:
        extracted = extract_article(
            raw_html, final_url, visible_text=visible_text, enrich=enrich
        )
    elif extracted_http is not None and used == "http":
        extracted = extracted_http
    else:
        extracted = extract_article(raw_html, final_url, enrich=enrich)

    item: dict[str, Any] = {
        **extracted,
        "final_url": final_url,
        "status": status,
        "fetch_method": used,
    }
    if include_html:
        item["html"] = raw_html
    if visible_text is not None and include_html:
        item["visible_text"] = visible_text

    facts = item.get("structured_facts") or []
    notes = [
        "Material-only capture (title/text/links + structured facts). No classification.",
        "Main article via trafilatura; meta/JSON-LD/embedded counters merged into text when missing.",
        "mode=auto: HTTP first; browser if SPA shell or high-value facts still missing from main text.",
    ]
    return build_envelope(
        "page",
        source={"url": url, "final_url": final_url},
        items=[item],
        meta={
            "mode": mode,
            "methods": methods,
            "used": used,
            "status": status,
            "text_len": item.get("text_len"),
            "text_main_len": item.get("text_main_len"),
            "links_count": item.get("links_count"),
            "facts_count": len(facts),
            "enrich_notes": item.get("enrich_notes") or [],
            "author": item.get("author"),
        },
        errors=errors,
        notes=notes,
        collected_at=collected_at,
    )


def _read_urls_file(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # allow "url | note" lines
        url = line.split("|", 1)[0].strip()
        if url:
            urls.append(url)
    return urls


def _page_out_path(out: Path, url: str, index: int, *, batch: bool) -> Path:
    if not batch:
        return out
    # batch: --out is a directory (or *.json treated as dir stem)
    dest_dir = out if out.suffix.lower() != ".json" else out.parent / out.stem
    dest_dir.mkdir(parents=True, exist_ok=True)
    from tarrafa.core.media import id_from_url

    stem = id_from_url(url, prefix=f"{index:03d}_")
    return dest_dir / f"{stem}.json"


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa page",
        description="Capture public page(s) -> forensic JSON envelope (text + structured facts).",
    )
    ap.add_argument("--url", default=None, help="Target URL (single)")
    ap.add_argument(
        "--urls-file",
        default=None,
        help="Text file with one URL per line (# comments ok) for batch capture",
    )
    ap.add_argument(
        "--out",
        required=True,
        help="Output JSON path (single) or directory / stem (batch with --urls-file)",
    )
    ap.add_argument(
        "--mode",
        choices=("auto", "http", "browser"),
        default="auto",
        help="Fetch mode (default: auto)",
    )
    ap.add_argument("--storage-state", default=None, help="Playwright storage_state.json (browser mode)")
    ap.add_argument("--timeout", type=float, default=30.0, help="Timeout seconds (default 30)")
    ap.add_argument("--include-html", action="store_true", help="Embed raw HTML in item (large)")
    ap.add_argument(
        "--no-enrich",
        action="store_true",
        help="Disable structured-fact / visible-text merge into text",
    )
    ap.add_argument(
        "--no-browser-facts",
        action="store_true",
        help="In auto mode, do not open browser just to recover missing facts",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)

    urls: list[str] = []
    if args.urls_file:
        uf = Path(args.urls_file)
        if not uf.is_file():
            print(f"page: urls-file not found: {uf}", file=sys.stderr)
            return 2
        urls.extend(_read_urls_file(uf))
    if args.url:
        urls.append(args.url)
    # de-dupe preserve order
    seen: set[str] = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]
    if not urls:
        print("page: provide --url and/or --urls-file", file=sys.stderr)
        return 2

    batch = len(urls) > 1 or bool(args.urls_file)
    out_base = Path(args.out)
    ok_n = 0
    fail_n = 0
    last_path: Path | None = None
    all_errors: list[str] = []

    for i, url in enumerate(urls, start=1):
        payload = capture_page(
            url,
            mode=args.mode,
            storage_state=args.storage_state,
            timeout=args.timeout,
            include_html=args.include_html,
            enrich=not args.no_enrich,
            browser_if_missing_facts=not args.no_browser_facts,
        )
        out = _page_out_path(out_base, url, i, batch=batch)
        write_json(out, payload)
        last_path = out
        count = payload.get("count", 0)
        meta = payload.get("meta") or {}
        errs = list(payload.get("errors") or [])
        if count == 0:
            fail_n += 1
            all_errors.append(f"{url}: empty or failed")
        else:
            ok_n += 1
        if errs:
            all_errors.extend(f"{url}: {e}" for e in errs)
        if not batch:
            from tarrafa.core.summary import print_summary

            print_summary(
                "page",
                ok=count > 0,
                count=count,
                path=out,
                extra=(
                    f"text_len={meta.get('text_len')} main={meta.get('text_main_len')} "
                    f"facts={meta.get('facts_count')} used={meta.get('used')}"
                ),
                errors=errs,
            )
        elif count > 0:
            print(f"  [{i}/{len(urls)}] ok {out.name}  text_len={meta.get('text_len')}")
        else:
            print(f"  [{i}/{len(urls)}] fail {url}", file=sys.stderr)

    if batch:
        from tarrafa.core.summary import print_summary

        print_summary(
            "page",
            ok=ok_n > 0,
            count=ok_n,
            path=last_path.parent if last_path else out_base,
            extra=f"batch ok={ok_n} fail={fail_n} total={len(urls)}",
            errors=all_errors[:12],
        )

    if ok_n == 0:
        return 6
    if fail_n > 0:
        return 0  # partial success still 0; errors listed
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
