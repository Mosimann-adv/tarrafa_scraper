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
import re
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


_SPA_MARKERS = (
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    "__next",
    "__nuxt",
    "data-reactroot",
    "ng-version",
    "webpackjsonp",
)
_LOGIN_WALL_RE = re.compile(
    r"(?:"
    r"(?:log\s*in|sign\s*in|entrar|iniciar\s+sess[aã]o).{0,80}"
    r"(?:continue|continuar|account|conta|password|senha)|"
    r"(?:you\s+must\s+be\s+logged|fa[cç]a\s+login|cadastre-se).{0,80}"
    r"(?:continue|continuar|para\s+ver|to\s+view)"
    r")",
    re.IGNORECASE | re.DOTALL,
)
_HIGH_VALUE_FACT_KINDS = {"signature_count", "person", "display_name"}


def _main_text(extracted: dict[str, Any]) -> str:
    return str(extracted.get("text_main") or extracted.get("text") or "")


def _has_spa_shell(extracted: dict[str, Any], html: str) -> bool:
    """Recognise an otherwise empty client-rendered shell, not every React page."""
    if len(_main_text(extracted)) >= 200:
        return False
    low = (html or "").lower()
    return any(marker in low for marker in _SPA_MARKERS)


def _looks_thin(extracted: dict[str, Any], html: str) -> bool:
    """Only call a short HTTP extract thin when the response is substantial."""
    return len(_main_text(extracted)) < 80 and len(html or "") >= 1000


def _looks_like_login_wall(extracted: dict[str, Any], html: str) -> bool:
    # Keep this deliberately narrow: a mention of "login" in an article is not a wall.
    return bool(_LOGIN_WALL_RE.search(f"{_main_text(extracted)}\n{html or ''}"))


def _needs_browser_for_missing_facts(extracted: dict[str, Any]) -> bool:
    """Whether HTTP misses enough high-value facts to justify one render."""
    facts = extracted.get("structured_facts") or []
    text = extracted.get("text") or ""
    missing = facts_missing_from_text(facts, extracted.get("text_main") or text)
    kinds = {f.get("kind") for f in missing}
    high_value = kinds & _HIGH_VALUE_FACT_KINDS
    # A single person name is commonplace metadata.  A counter, or two distinct
    # high-value kinds, is a stronger signal that rendered UI may add evidence.
    return "signature_count" in high_value or len(high_value) >= 2


def _browser_reasons(
    extracted: dict[str, Any],
    html: str,
    *,
    browser_if_missing_facts: bool,
) -> list[str]:
    """Return conservative, user-visible reasons to render a page once."""
    reasons: list[str] = []
    spa_shell = _has_spa_shell(extracted, html)
    thin = _looks_thin(extracted, html)
    if spa_shell:
        reasons.append("spa_shell")
    elif thin:
        reasons.append("thin_http_extract")
    if _looks_like_login_wall(extracted, html):
        reasons.append("http_login_wall")
    if browser_if_missing_facts and _needs_browser_for_missing_facts(extracted):
        reasons.append("missing_high_value_facts")
    return reasons


def _fact_keys(extracted: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        (str(f.get("kind")), str(f.get("value")))
        for f in (extracted.get("structured_facts") or [])
        if f.get("kind") in _HIGH_VALUE_FACT_KINDS and f.get("value") is not None
    }


def _browser_is_better(
    http_extracted: dict[str, Any],
    browser_extracted: dict[str, Any],
    *,
    http_html: str,
    browser_html: str,
) -> bool:
    """Require a material improvement before replacing an HTTP capture.

    Rendering can surface cookie banners or a login prompt.  The browser result
    therefore needs to recover substantially more content, a new high-value fact,
    or escape an HTTP login wall; merely being different is not enough.
    """
    http_text = _main_text(http_extracted)
    browser_text = _main_text(browser_extracted)
    http_login = _looks_like_login_wall(http_extracted, http_html)
    browser_login = _looks_like_login_wall(browser_extracted, browser_html)
    if browser_login and not http_login:
        return False
    if http_login and not browser_login and len(browser_text) >= 80:
        return True
    if len(browser_text) >= 120 and len(browser_text) >= len(http_text) + max(100, len(http_text) // 4):
        return True
    if len(browser_extracted.get("text") or "") >= len(http_extracted.get("text") or "") + max(
        200, len(http_extracted.get("text") or "") // 3
    ) and not browser_login:
        return True
    new_facts = _fact_keys(browser_extracted) - _fact_keys(http_extracted)
    return bool(new_facts) and len(browser_text) >= 80 and not browser_login


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
    final_choice: str | None = None
    browser_reasons: list[str] = []
    browser_decision = "not_needed"

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
            final_choice = "http"
            extracted_http = extract_article(raw_html, final_url, enrich=enrich)

    if mode == "browser":
        browser_reasons = ["forced_mode"]
    elif mode == "http":
        browser_decision = "disabled_http_mode"
    elif extracted_http is None:
        browser_reasons = ["http_failed"]
    else:
        browser_reasons = _browser_reasons(
            extracted_http,
            raw_html,
            browser_if_missing_facts=browser_if_missing_facts,
        )

    # A single call here is the per-URL browser budget.  Keep it explicit so a
    # future retry path cannot accidentally make auto mode launch twice.
    need_browser = mode == "browser" or (mode == "auto" and bool(browser_reasons))
    extracted_browser: dict[str, Any] | None = None
    browser_html = ""
    browser_visible_text: str | None = None
    browser_final_url = final_url
    browser_status = None

    if need_browser and mode != "http":
        browser_decision = "attempted"
        b = _fetch_browser(url, storage_state, timeout_ms=int(timeout * 1000))
        if b.get("error"):
            errors.append(f"browser: {b['error']}")
            browser_decision = "failed_kept_http" if extracted_http is not None else "failed"
            # keep HTTP extract if we had one
        else:
            methods.append("browser")
            browser_html = b.get("text") or ""
            browser_visible_text = b.get("visible_text") or ""
            browser_final_url = b.get("final_url") or final_url
            browser_status = b.get("status")
            extracted_browser = extract_article(
                browser_html,
                browser_final_url,
                visible_text=browser_visible_text,
                enrich=enrich,
            )
            if mode == "browser" or extracted_http is None:
                raw_html = browser_html
                visible_text = browser_visible_text
                final_url = browser_final_url
                status = browser_status
                used = "browser"
                final_choice = "browser"
                browser_decision = "selected_browser"
            elif _browser_is_better(
                extracted_http,
                extracted_browser,
                http_html=raw_html,
                browser_html=browser_html,
            ):
                raw_html = browser_html
                visible_text = browser_visible_text
                final_url = browser_final_url
                status = browser_status if browser_status is not None else status
                used = "http+browser"
                final_choice = "browser"
                browser_decision = "selected_browser"
            else:
                # Preserve the original HTTP response and extraction when browser
                # rendering only exposed less useful chrome/login content.
                used = "http+browser"
                final_choice = "http"
                browser_decision = "kept_http_better"

    if not raw_html and used is None:
        env = build_envelope(
            "page",
            source={"url": url},
            items=[],
            meta={
                "mode": mode,
                "methods": methods,
                "used": used,
                "final_choice": final_choice,
                "browser_reason": browser_reasons,
                "browser_decision": browser_decision,
            },
            errors=errors or ["empty response"],
            notes=["Single-page capture failed."],
            collected_at=collected_at,
        )
        return env

    if final_choice == "browser" and extracted_browser is not None:
        extracted = extracted_browser
    elif extracted_http is not None:
        extracted = extracted_http
    else:
        extracted = extract_article(raw_html, final_url, enrich=enrich)

    item: dict[str, Any] = {
        **extracted,
        "final_url": final_url,
        "status": status,
        "fetch_method": used,
        "capture_choice": final_choice,
    }
    if include_html:
        item["html"] = raw_html
    if visible_text is not None and include_html:
        item["visible_text"] = visible_text

    facts = item.get("structured_facts") or []
    notes = [
        "Material-only capture (title/text/links + structured facts). No classification.",
        "Main article via trafilatura; meta/JSON-LD/embedded counters merged into text when missing.",
        "mode=auto: HTTP first; one browser attempt only for a likely SPA shell, thin response, or login wall.",
    ]
    return build_envelope(
        "page",
        source={"url": url, "final_url": final_url},
        items=[item],
        meta={
            "mode": mode,
            "methods": methods,
            "used": used,
            "final_choice": final_choice,
            "browser_reason": browser_reasons,
            "browser_decision": browser_decision,
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
    ap.add_argument(
        "--storage-state",
        default=None,
        help="Playwright storage_state.json (auto/browser modes)",
    )
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
