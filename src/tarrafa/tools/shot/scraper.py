# -*- coding: utf-8 -*-
"""
tarrafa shot — high-quality page screenshots (Playwright).

  tarrafa shot --url https://example.com --out-dir ./shots --id EX01
  tarrafa shot --url … --out-dir ./shots --clip main --dpr 2
  tarrafa shot --url … --out-dir ./shots --clip page --full-page
  tarrafa shot --url … --out-dir ./shots --selector "article.post"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.browser_util import chromium_page, goto_settled
from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import ensure_dir, file_sha256, id_from_url
from tarrafa.core.writers import utc_now_iso, write_json

# Mark best main node + hide chrome noise for cleaner forensic crops.
_PREPARE_MAIN_JS = r"""
() => {
  // Outside main: broader chrome. Inside main: only clear noise (never blanket "header/menu").
  const HIDE_OUTSIDE = [
    'header', 'nav', 'footer', 'aside',
    '[role="banner"]', '[role="navigation"]', '[role="contentinfo"]', '[role="complementary"]',
    '.cookie', '.cookies', '#cookie', '#cookies', '.cookie-banner', '.gdpr',
    '[class*="cookie" i]', '[id*="cookie" i]',
    '[class*="newsletter" i]', '[class*="subscribe" i]',
    '[class*="sidebar" i]', '[class*="widget" i]',
    '[class*="footer" i]', '[id*="footer" i]',
    '[class*="related" i]', '[class*="recomend" i]', '[class*="recommend" i]',
    '[class*="mais-lidas" i]', '[class*="most-read" i]',
    '[class*="comment" i]', '#comments', '.comments',
    '[class*="advert" i]', '.adsbygoogle',
    '[class*="trending" i]', '[class*="leia-tambem" i]', '[class*="veja-tambem" i]',
    '[class*="more-stories" i]', '[class*="also-read" i]',
  ].join(',');
  const HIDE_INSIDE = [
    'footer', 'aside', 'nav',
    '[class*="related" i]', '[class*="recomend" i]', '[class*="recommend" i]',
    '[class*="newsletter" i]', '[class*="share-buttons" i]', '[class*="social-share" i]',
    '[class*="comment" i]', '#comments', '.comments',
    '[class*="leia-tambem" i]', '[class*="veja-tambem" i]', '[class*="more-stories" i]',
    '[class*="tags" i]', '.post-tags',
    '[class*="author-box" i]',
  ].join(',');

  const CANDIDATE_SEL = [
    'article',
    'main article',
    '[itemtype*="Article" i]',
    '[itemtype*="NewsArticle" i]',
    'main',
    '[role="main"]',
    '.entry-content',
    '.post-content',
    '.post__content',
    '.article-body',
    '.article__body',
    '.article-content',
    '.article__content',
    '.story-body',
    '.story__body',
    '.content-body',
    '.news-body',
    '.materia-conteudo',
    '.mc-article-body',
    '.content__body',
    '#article-body',
    '#content article',
    '.petition_body',
    '.petition-content',
    '[data-qa="petition-description"]',
    '[class*="PetitionPage" i]',
    '[class*="petition" i] [class*="content" i]',
  ];

  const isVisible = (el) => {
    if (!el || !(el instanceof Element)) return false;
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || st.opacity === '0') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 180 && r.height >= 80;
  };

  const textLen = (el) => ((el && el.innerText) || '').replace(/\s+/g, ' ').trim().length;

  const score = (el) => {
    if (!isVisible(el)) return 0;
    if (el === document.body || el === document.documentElement) return 0;
    const r = el.getBoundingClientRect();
    const t = textLen(el);
    if (t < 100) return 0;
    // Prefer column-like widths (article), mild penalty for full-bleed chrome
    const vw = window.innerWidth || 1200;
    const widthRatio = r.width / vw;
    let wPenalty = 1;
    if (widthRatio > 0.95) wPenalty = 0.55;
    else if (widthRatio > 0.85) wPenalty = 0.75;
    else if (widthRatio >= 0.35 && widthRatio <= 0.82) wPenalty = 1.25;
    // Cap height contribution so endless comment threads don't win
    const h = Math.min(r.height, 4000);
    return t * Math.sqrt(r.width * h) * wPenalty;
  };

  // Collect candidates
  const set = new Set();
  for (const sel of CANDIDATE_SEL) {
    try {
      document.querySelectorAll(sel).forEach((el) => set.add(el));
    } catch (e) {}
  }
  // Also large text blocks under main/body
  const roots = [document.querySelector('main'), document.body].filter(Boolean);
  for (const root of roots) {
    root.querySelectorAll('div, section').forEach((el) => {
      if (textLen(el) >= 400) set.add(el);
    });
  }

  let best = null;
  let bestScore = 0;
  for (const el of set) {
    // skip pure nav/footer-ish
    const tag = (el.tagName || '').toLowerCase();
    const cls = (el.className && String(el.className)) || '';
    const id = el.id || '';
    const blob = (tag + ' ' + cls + ' ' + id).toLowerCase();
    if (/(footer|sidebar|comment|cookie|menu|nav|related|share|newsletter|widget|banner)/.test(blob)) {
      continue;
    }
    const s = score(el);
    if (s > bestScore) {
      bestScore = s;
      best = el;
    }
  }
  if (!best) {
    best = document.querySelector('main') || document.querySelector('article') || document.body;
  }

  let hidden_noise = 0;
  const hideEl = (el) => {
    if (!el || el === best || el.contains(best)) return;
    try {
      el.style.setProperty('display', 'none', 'important');
      hidden_noise += 1;
    } catch (e) {}
  };
  try {
    document.querySelectorAll(HIDE_OUTSIDE).forEach((el) => {
      if (!best.contains(el)) hideEl(el);
    });
    best.querySelectorAll(HIDE_INSIDE).forEach((el) => hideEl(el));
  } catch (e) {}

  // Mark for Playwright locator
  document.querySelectorAll('[data-tarrafa-main]').forEach((el) => el.removeAttribute('data-tarrafa-main'));
  best.setAttribute('data-tarrafa-main', '1');

  // Soft background so crop isn't transparent-looking
  try {
    best.style.setProperty('background', '#fff', 'important');
  } catch (e) {}

  const r = best.getBoundingClientRect();
  return {
    tag: best.tagName,
    id: best.id || null,
    className: (typeof best.className === 'string' ? best.className : '').slice(0, 120),
    text_len: textLen(best),
    score: bestScore,
    width: Math.round(r.width),
    height: Math.round(r.height),
    hidden_noise: hidden_noise,
  };
}
"""


def _lazy_scroll(page: Any) -> None:
    try:
        page.evaluate(
            """async () => {
              await new Promise(r => {
                let total = 0;
                const step = () => {
                  const h = document.body.scrollHeight;
                  window.scrollBy(0, Math.min(700, h));
                  total += 700;
                  if (total < Math.min(h, 6000)) requestAnimationFrame(step);
                  else { window.scrollTo(0, 0); r(); }
                };
                step();
              });
            }"""
        )
        page.wait_for_timeout(350)
    except Exception:
        pass


def _screenshot_page(page: Any, png_path: Path, *, full_page: bool = True) -> dict[str, Any]:
    if full_page:
        _lazy_scroll(page)
    page.screenshot(path=str(png_path), full_page=full_page, type="png")
    return {"mode": "page", "full_page": full_page}


def _element_ok(box: dict[str, Any] | None, info: dict[str, Any] | None = None) -> bool:
    if not box:
        return False
    h = float(box.get("height") or 0)
    w = float(box.get("width") or 0)
    if h < 80 or w < 200:
        return False
    if info and int(info.get("text_len") or 0) < 80:
        return False
    return True


def _clean_fallback(page: Any, png_path: Path, url: str, info: dict[str, Any], reason: str) -> dict[str, Any]:
    """Reload page (undo hide mutations) then full-page shot."""
    try:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
    except Exception:
        pass
    meta = _screenshot_page(page, png_path, full_page=True)
    return {**info, **meta, "mode": "fallback_full_page", "reason": reason}


def _screenshot_main(page: Any, png_path: Path, *, pad: int = 12, url: str = "") -> dict[str, Any]:
    info = page.evaluate(_PREPARE_MAIN_JS) or {}
    page.wait_for_timeout(200)
    loc = page.locator("[data-tarrafa-main='1']").first
    if loc.count() == 0:
        return _clean_fallback(page, png_path, url or page.url, info, "no_main_mark")

    try:
        box = loc.bounding_box()
        if not _element_ok(box, info):
            return _clean_fallback(page, png_path, url or page.url, {**info, "box": box}, "main_box_too_small")

        loc.screenshot(path=str(png_path), type="png")
        if png_path.is_file() and png_path.stat().st_size < 12_000:
            return _clean_fallback(page, png_path, url or page.url, {**info, "box": box}, "png_too_small")

        vp = page.viewport_size or {"width": 1280, "height": 900}
        return {
            **info,
            "mode": "element",
            "box": box,
            "pad": pad,
            "viewport": vp,
            "width": int((box or {}).get("width") or info.get("width") or 0),
            "height": int((box or {}).get("height") or info.get("height") or 0),
        }
    except Exception as e:
        return _clean_fallback(page, png_path, url or page.url, {**info, "error": str(e)}, "exception")


def _screenshot_selector(page: Any, png_path: Path, selector: str) -> dict[str, Any]:
    loc = page.locator(selector).first
    if loc.count() == 0:
        raise RuntimeError(f"selector not found: {selector}")
    # hide common chrome outside
    page.evaluate(
        """(sel) => {
          const main = document.querySelector(sel);
          if (!main) return;
          main.setAttribute('data-tarrafa-main', '1');
          document.querySelectorAll('header, nav, footer, aside, [class*="cookie" i]').forEach(el => {
            if (!main.contains(el) && !el.contains(main)) el.style.setProperty('display','none','important');
          });
        }""",
        selector,
    )
    loc.screenshot(path=str(png_path), type="png")
    box = loc.bounding_box()
    return {"mode": "selector", "selector": selector, "box": box}


def capture_shot(
    url: str,
    out_dir: Path,
    *,
    item_id: str | None = None,
    clip: str = "main",
    selector: str | None = None,
    full_page: bool = True,
    dpr: float = 2.0,
    width: int = 1280,
    height: int = 900,
    wait_ms: int = 1500,
    timeout: float = 60.0,
    storage_state: str | None = None,
    headed: bool = False,
    caption: str | None = None,
    pad: int = 12,
) -> dict[str, Any]:
    """
    clip:
      - main: crop to detected article/main content (default)
      - page: full page or viewport (see full_page)
      - selector: use --selector CSS
    """
    collected_at = utc_now_iso()
    out_dir = ensure_dir(out_dir)
    iid = item_id or id_from_url(url, prefix="shot_")
    png_path = out_dir / f"{iid}.png"
    json_path = out_dir / f"{iid}.json"
    errors: list[str] = []
    clip_info: dict[str, Any] = {}
    final_url = url
    title = None
    status = None

    clip = (clip or "main").lower().strip()
    if selector:
        clip = "selector"

    try:
        with chromium_page(
            storage_state=storage_state,
            headless=not headed,
            width=width,
            height=height,
            device_scale_factor=dpr,
        ) as (_p, _b, page):
            page.set_default_timeout(int(timeout * 1000))
            resp = goto_settled(page, url, timeout_ms=int(timeout * 1000), wait_ms=wait_ms)
            status = resp.status if resp else None
            final_url = page.url
            try:
                title = page.title()
            except Exception:
                pass

            # Light scroll so lazy article images load (even for main crop)
            _lazy_scroll(page)
            page.wait_for_timeout(min(400, wait_ms))

            if clip == "main":
                clip_info = _screenshot_main(page, png_path, pad=pad, url=url)
            elif clip == "selector":
                if not selector:
                    raise RuntimeError("--selector required when clip=selector")
                clip_info = _screenshot_selector(page, png_path, selector)
            else:
                clip_info = _screenshot_page(page, png_path, full_page=full_page)
    except Exception as e:
        errors.append(f"{type(e).__name__}: {e}")
        env = build_envelope(
            "shot",
            source={"url": url},
            items=[],
            meta={"id": iid, "clip": clip},
            errors=errors,
            notes=["Screenshot failed."],
            collected_at=collected_at,
        )
        write_json(json_path, env)
        return env

    sha = file_sha256(png_path) if png_path.is_file() else None
    size = png_path.stat().st_size if png_path.is_file() else 0
    item = {
        "id": iid,
        "kind": "shot",
        "url": url,
        "final_url": final_url,
        "title": title,
        "caption": caption or title or url,
        "image": png_path.name,
        "path": str(png_path.resolve()),
        "sha256": sha,
        "bytes": size,
        "clip": clip,
        "clip_info": clip_info,
        "full_page": full_page if clip == "page" else False,
        "viewport": {"width": width, "height": height},
        "device_scale_factor": dpr,
        "status": status,
        "collected_at": collected_at,
    }
    env = build_envelope(
        "shot",
        source={"url": url, "final_url": final_url},
        items=[item],
        meta={
            "id": iid,
            "image": png_path.name,
            "sha256": sha,
            "clip": clip,
            "clip_mode": (clip_info or {}).get("mode"),
            "dpr": dpr,
            "text_len": (clip_info or {}).get("text_len"),
            "box": {
                "w": (clip_info or {}).get("width"),
                "h": (clip_info or {}).get("height"),
            },
        },
        errors=errors,
        notes=[
            "High-quality PNG via Playwright Chromium.",
            "clip=main crops to detected article/main and hides related/footer noise.",
            "Material-only. Pair with tarrafa album for print HTML.",
        ],
        collected_at=collected_at,
    )
    write_json(json_path, env)
    return env


def _read_urls_file(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url = line.split("|", 1)[0].strip()
        if url:
            urls.append(url)
    return urls


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa shot",
        description="Capture high-quality page screenshot(s) → PNG + JSON envelope.",
    )
    ap.add_argument("--url", default=None, help="Target URL (single)")
    ap.add_argument(
        "--urls-file",
        default=None,
        help="Text file with one URL per line for batch screenshots",
    )
    ap.add_argument("--out-dir", required=True, help="Directory for PNG + JSON")
    ap.add_argument("--id", dest="item_id", default=None, help="Item id / filename stem (single URL)")
    ap.add_argument("--caption", default=None)
    ap.add_argument(
        "--clip",
        choices=("main", "page", "selector"),
        default="main",
        help="main=content crop (default); page=full/viewport; selector=CSS",
    )
    ap.add_argument("--selector", default=None, help="CSS selector when --clip selector")
    ap.add_argument(
        "--full-page",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Only for --clip page (default true)",
    )
    ap.add_argument("--dpr", type=float, default=2.0, help="device_scale_factor (default 2)")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--pad", type=int, default=12, help="Padding hint around main (default 12)")
    ap.add_argument("--wait-ms", type=int, default=1500)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--storage-state", default=None)
    ap.add_argument("--headed", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)

    urls: list[str] = []
    if args.urls_file:
        uf = Path(args.urls_file)
        if not uf.is_file():
            print(f"shot: urls-file not found: {uf}", file=sys.stderr)
            return 2
        urls.extend(_read_urls_file(uf))
    if args.url:
        urls.append(args.url)
    seen: set[str] = set()
    urls = [u for u in urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]
    if not urls:
        print("shot: provide --url and/or --urls-file", file=sys.stderr)
        return 2

    from tarrafa.core.media import id_from_url
    from tarrafa.core.run import register_artifact
    from tarrafa.core.summary import print_summary

    out_dir = Path(args.out_dir)
    ok_n = 0
    fail_n = 0
    batch = len(urls) > 1 or bool(args.urls_file)
    last_img = None

    for i, url in enumerate(urls, start=1):
        if args.item_id and not batch:
            iid = args.item_id
        elif batch:
            iid = id_from_url(url, prefix=f"S{i:02d}_")
        else:
            iid = args.item_id
        env = capture_shot(
            url,
            out_dir,
            item_id=iid,
            clip=args.clip,
            selector=args.selector,
            full_page=args.full_page,
            dpr=args.dpr,
            width=args.width,
            height=args.height,
            wait_ms=args.wait_ms,
            timeout=args.timeout,
            storage_state=args.storage_state,
            headed=args.headed,
            caption=args.caption,
            pad=args.pad,
        )
        items = env.get("items") or []
        meta = env.get("meta") or {}
        if not items:
            fail_n += 1
            if not batch:
                print_summary(
                    "shot",
                    ok=False,
                    path=out_dir,
                    errors=list(env.get("errors") or ["screenshot failed"]),
                )
            else:
                print(f"  [{i}/{len(urls)}] fail {url}", file=sys.stderr)
            continue
        ok_n += 1
        it = items[0]
        last_img = it.get("path") or (out_dir / str(it.get("image") or ""))
        try:
            register_artifact(last_img, kind="png")
            register_artifact(out_dir / f"{meta.get('id')}.json", kind="json")
        except Exception:
            pass
        box = meta.get("box") or {}
        extra = (
            f"clip={meta.get('clip')}/{meta.get('clip_mode')} "
            f"{box.get('w')}x{box.get('h')} bytes={it.get('bytes')} "
            f"sha256={(it.get('sha256') or '')[:12]}…"
        )
        if batch:
            print(f"  [{i}/{len(urls)}] ok {it.get('image')}  {extra}")
        else:
            print_summary("shot", ok=True, count=1, path=it.get("image"), extra=extra)

    if batch:
        print_summary(
            "shot",
            ok=ok_n > 0,
            count=ok_n,
            path=out_dir,
            extra=f"batch ok={ok_n} fail={fail_n} total={len(urls)}",
        )
    if ok_n == 0:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
