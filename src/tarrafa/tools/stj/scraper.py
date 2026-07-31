# -*- coding: utf-8 -*-
"""
tarrafa stj — download de inteiro teor do STJ (SCON) via browser.

O SCON costuma estar atrás de Cloudflare/CSID. Headless limpo recebe 403.
Fluxos suportados:

  # 1) Aquecer sessão (você resolve o desafio no Chrome headed)
  tarrafa stj --warmup --headed --save-storage ./stj_storage.json

  # 2) Baixar com a sessão salva
  tarrafa stj --num-registro 201600461292 --dt-publicacao 23/08/2019 \\
    --storage-state ./stj_storage.json --out-dir ./pdfs --out stj.json

  # 3) Chrome real já aberto com debug remoto
  #    chrome.exe --remote-debugging-port=9222
  tarrafa stj --cdp http://127.0.0.1:9222 --url "https://scon.stj.jus.br/..." \\
    --out-dir ./pdfs --out stj.json

  # 4) Lote
  tarrafa stj --urls-file seeds.txt --out-dir ./pdfs --out stj.json --storage-state ./stj_storage.json

Exit codes:
  0 ok · 2 args/deps · 3 nav · 5 challenge/WAF · 6 zero PDFs
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from tarrafa.core.browser_util import chromium_page
from tarrafa.core.challenge import challenge_meta, is_challenge_page, is_pdf_bytes
from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import ensure_dir, file_sha256, slugify
from tarrafa.core.run import register_artifact
from tarrafa.core.writers import write_json

SCON_HOME = "https://scon.stj.jus.br/SCON/"
INTEIRO_TEOR_PATH = "/SCON/GetInteiroTeorDoAcordao"
INTEIRO_TEOR_HOST = "scon.stj.jus.br"

# Exit codes (align with ig / page conventions)
EX_OK = 0
EX_ARGS = 2
EX_NAV = 3
EX_CHALLENGE = 5
EX_ZERO = 6


def digits_only(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def normalize_dt_publicacao(s: str) -> str:
    """Accept DD/MM/YYYY or YYYY-MM-DD → DD/MM/YYYY (SCON format)."""
    s = (s or "").strip()
    if not s:
        return s
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(3)}/{m.group(2)}/{m.group(1)}"
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), m.group(3)
        return f"{d:02d}/{mo:02d}/{y}"
    return s


def build_inteiro_teor_url(num_registro: str, dt_publicacao: str) -> str:
    num = digits_only(num_registro)
    dt = normalize_dt_publicacao(dt_publicacao)
    if not num or not dt:
        raise ValueError("num_registro e dt_publicacao são obrigatórios")
    q = urlencode({"num_registro": num, "dt_publicacao": dt})
    return f"https://{INTEIRO_TEOR_HOST}{INTEIRO_TEOR_PATH}?{q}"


def parse_inteiro_teor_url(url: str) -> dict[str, str | None]:
    u = urlparse(url.strip())
    qs = parse_qs(u.query)
    num = (qs.get("num_registro") or [None])[0]
    dt = (qs.get("dt_publicacao") or [None])[0]
    return {
        "num_registro": digits_only(num) if num else None,
        "dt_publicacao": normalize_dt_publicacao(dt) if dt else None,
        "url": url.strip(),
    }


def parse_seed_line(line: str) -> dict[str, str] | None:
    """
    One of:
      - full GetInteiroTeor URL
      - num_registro|dt_publicacao
      - num_registro  dt_publicacao  (whitespace)
    """
    raw = (line or "").strip()
    if not raw or raw.startswith("#"):
        return None
    if "GetInteiroTeor" in raw or "scon.stj.jus.br" in raw:
        if not raw.startswith("http"):
            raw = "https://" + raw.lstrip("/")
        meta = parse_inteiro_teor_url(raw)
        if not meta.get("num_registro") and "GetInteiroTeor" not in raw:
            # plain URL without params — still try as-is
            return {"url": raw, "num_registro": "", "dt_publicacao": ""}
        url = meta["url"] or raw
        if meta.get("num_registro") and meta.get("dt_publicacao"):
            url = build_inteiro_teor_url(str(meta["num_registro"]), str(meta["dt_publicacao"]))
        return {
            "url": url,
            "num_registro": str(meta.get("num_registro") or ""),
            "dt_publicacao": str(meta.get("dt_publicacao") or ""),
        }
    if "|" in raw:
        left, _, right = raw.partition("|")
        return {
            "url": build_inteiro_teor_url(left.strip(), right.strip()),
            "num_registro": digits_only(left),
            "dt_publicacao": normalize_dt_publicacao(right),
        }
    parts = raw.split()
    if len(parts) >= 2:
        return {
            "url": build_inteiro_teor_url(parts[0], parts[1]),
            "num_registro": digits_only(parts[0]),
            "dt_publicacao": normalize_dt_publicacao(parts[1]),
        }
    return None


def load_seeds(
    *,
    url: str | None = None,
    num_registro: str | None = None,
    dt_publicacao: str | None = None,
    urls_file: Path | None = None,
) -> list[dict[str, str]]:
    seeds: list[dict[str, str]] = []
    if url:
        s = parse_seed_line(url)
        if s:
            seeds.append(s)
    if num_registro and dt_publicacao:
        seeds.append(
            {
                "url": build_inteiro_teor_url(num_registro, dt_publicacao),
                "num_registro": digits_only(num_registro),
                "dt_publicacao": normalize_dt_publicacao(dt_publicacao),
            }
        )
    if urls_file:
        text = Path(urls_file).read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            s = parse_seed_line(line)
            if s:
                seeds.append(s)
    # de-dupe by url
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for s in seeds:
        u = s["url"]
        if u in seen:
            continue
        seen.add(u)
        out.append(s)
    return out


def pdf_stem(seed: dict[str, str]) -> str:
    num = seed.get("num_registro") or ""
    dt = (seed.get("dt_publicacao") or "").replace("/", "-")
    if num and dt:
        return f"stj-{num}-{dt}"
    if num:
        return f"stj-{num}"
    return slugify(seed.get("url") or "stj", max_len=60)


def _page_snapshot(page: Any) -> dict[str, Any]:
    title = ""
    html = ""
    text = ""
    try:
        title = page.title() or ""
    except Exception:
        pass
    try:
        html = page.content() or ""
    except Exception:
        pass
    try:
        text = page.inner_text("body") or ""
    except Exception:
        pass
    return {"title": title, "html": html, "text": text, "url": getattr(page, "url", "")}


def wait_challenge_clear(
    page: Any,
    *,
    timeout_s: float = 120.0,
    poll_s: float = 2.0,
    headed: bool = False,
) -> bool:
    """Poll until challenge interstitial goes away. Headed: human can solve in window."""
    deadline = time.time() + max(1.0, timeout_s)
    first = True
    while time.time() < deadline:
        snap = _page_snapshot(page)
        if not is_challenge_page(
            title=snap["title"],
            html=snap["html"],
            text=snap["text"],
            status=None,
        ):
            # also reject empty error shells
            if snap["html"] and len(snap["html"]) > 200:
                return True
            if not is_challenge_page(title=snap["title"], html=snap["html"], text=snap["text"]):
                return True
        if first and headed:
            print(
                "stj: desafio Cloudflare/CSID detectado. "
                "Resolva na janela do navegador (checkbox/aguardar).",
                file=sys.stderr,
            )
            first = False
        try:
            page.wait_for_timeout(int(poll_s * 1000))
        except Exception:
            time.sleep(poll_s)
    return False


def _save_pdf_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    register_artifact(path, kind="pdf")
    return path


# SCON GetInteiroTeor often returns an HTML catalog; real PDF is on processo.stj.jus.br
_DOC_LINK_RE = re.compile(
    r"https?://processo\.stj\.jus\.br/processo/julgamento/eletronico/documento/\?[^\s\"'<>]+",
    re.I,
)
_DOC_HREF_RE = re.compile(
    r"""href=["'](https?://processo\.stj\.jus\.br/processo/julgamento/eletronico/documento/\?[^"']+)["']""",
    re.I,
)


def dt_to_publicacao_data(dt: str) -> str | None:
    """DD/MM/YYYY → YYYYMMDD (param publicacao_data no portal STJ)."""
    dt = normalize_dt_publicacao(dt or "")
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", dt)
    if not m:
        return None
    return f"{m.group(3)}{m.group(2)}{m.group(1)}"


def extract_documento_links(html: str) -> list[str]:
    """Collect unique julgamento/eletronico/documento URLs from SCON HTML."""
    if not html:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for rx in (_DOC_HREF_RE, _DOC_LINK_RE):
        for m in rx.finditer(html):
            u = m.group(1) if m.lastindex else m.group(0)
            u = u.replace("&amp;", "&").strip()
            if u not in seen:
                seen.add(u)
                found.append(u)
    return found


def pick_documento_link(
    links: list[str],
    *,
    num_registro: str | None = None,
    dt_publicacao: str | None = None,
) -> str | None:
    """Prefer link matching registro_numero and/or publicacao_data."""
    if not links:
        return None
    num = digits_only(num_registro or "")
    pub = dt_to_publicacao_data(dt_publicacao or "") if dt_publicacao else None

    def score(u: str) -> tuple[int, int]:
        s = 0
        if num and f"registro_numero={num}" in u:
            s += 10
        if pub and f"publicacao_data={pub}" in u:
            s += 5
        if "documento_tipo=integra" in u.lower():
            s += 1
        return (s, -len(u))

    ranked = sorted(links, key=score, reverse=True)
    best = ranked[0]
    # if we have num and nothing matches, still return first integra link
    return best


def fetch_pdf_url(
    page: Any,
    doc_url: str,
    dest: Path,
    *,
    timeout_ms: int = 90_000,
) -> dict[str, Any]:
    """Fetch document URL and save PDF (API request, body, or download event)."""
    result: dict[str, Any] = {
        "ok": False,
        "path": None,
        "bytes": None,
        "sha256": None,
        "status": None,
        "fetch_method": None,
        "error": None,
        "doc_url": doc_url,
    }

    # 1) HTTP GET with browser cookies (best for binary PDF)
    try:
        api = page.context.request
        r = api.get(doc_url, timeout=timeout_ms, max_redirects=10)
        result["status"] = r.status
        body = r.body()
        ct = (r.headers.get("content-type") or "").lower()
        if is_pdf_bytes(body) or "application/pdf" in ct:
            if is_pdf_bytes(body):
                _save_pdf_bytes(dest, body)
                result.update(
                    {
                        "ok": True,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "documento_request_get",
                    }
                )
                return result
    except Exception as e:
        result["error"] = f"request_get: {type(e).__name__}: {e}"

    # 2) Navigate + download / response body
    resp = None
    download = None
    try:
        with page.expect_download(timeout=min(15_000, timeout_ms)) as dl_info:
            resp = page.goto(doc_url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            download = dl_info.value
        except Exception:
            download = None
    except Exception:
        if resp is None:
            try:
                resp = page.goto(doc_url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e:
                result["error"] = f"doc_nav: {type(e).__name__}: {e}"
                return result

    if resp is not None:
        result["status"] = resp.status
        try:
            body = resp.body()
            if is_pdf_bytes(body):
                _save_pdf_bytes(dest, body)
                result.update(
                    {
                        "ok": True,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "documento_response_body",
                        "error": None,
                    }
                )
                return result
        except Exception:
            pass

    if download is not None:
        try:
            download.save_as(str(dest))
            if is_pdf_bytes(dest.read_bytes()):
                result.update(
                    {
                        "ok": True,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "documento_download",
                        "error": None,
                    }
                )
                return result
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as e:
            result["error"] = f"doc_download: {type(e).__name__}: {e}"

    snap = _page_snapshot(page)
    if is_challenge_page(title=snap["title"], html=snap["html"], text=snap["text"]):
        result["error"] = "waf_challenge on documento URL"
        result["challenge"] = True
        return result
    result["error"] = (
        f"documento não-PDF (status={result['status']}, title={snap['title']!r}, "
        f"html_len={len(snap['html'] or '')})"
    )
    return result


def try_follow_scon_html(
    page: Any,
    html: str,
    seed: dict[str, str],
    dest: Path,
    *,
    timeout_ms: int,
) -> dict[str, Any] | None:
    """
    If SCON returned the 'Íntegra de Acórdãos' catalog, follow documento link.
    Returns fetch result dict or None if no links found.
    """
    links = extract_documento_links(html)
    if not links:
        return None
    chosen = pick_documento_link(
        links,
        num_registro=seed.get("num_registro"),
        dt_publicacao=seed.get("dt_publicacao"),
    )
    if not chosen:
        return None
    result = fetch_pdf_url(page, chosen, dest, timeout_ms=timeout_ms)
    result["documento_links_found"] = len(links)
    result["documento_url"] = chosen
    return result


def download_one(
    page: Any,
    seed: dict[str, str],
    out_dir: Path,
    *,
    timeout_ms: int = 90_000,
    headed: bool = False,
    challenge_wait_s: float = 120.0,
) -> dict[str, Any]:
    """
    Navigate to GetInteiroTeor URL and save PDF if obtained.

    Returns item dict for envelope (ok / challenge / error).
    """
    url = seed["url"]
    stem = pdf_stem(seed)
    dest = out_dir / f"{stem}.pdf"
    item: dict[str, Any] = {
        "url": url,
        "num_registro": seed.get("num_registro") or None,
        "dt_publicacao": seed.get("dt_publicacao") or None,
        "ok": False,
        "challenge": False,
        "path": None,
        "sha256": None,
        "bytes": None,
        "status": None,
        "title": None,
        "error": None,
    }

    try:
        page.set_default_timeout(timeout_ms)
    except Exception:
        pass

    # Prefer API request: Chrome's built-in PDF viewer turns page.goto(PDF) into an
    # empty embedder shell (html_len≈174), so resp.body() is useless after navigation.
    try:
        r = page.context.request.get(url, timeout=timeout_ms, max_redirects=10)
        item["status"] = r.status
        body = r.body()
        ct = (r.headers.get("content-type") or "").lower()
        if is_pdf_bytes(body) or (
            "application/pdf" in ct and len(body) > 500 and body[:4] != b"<!" and body[:5] != b"<html"
        ):
            if is_pdf_bytes(body):
                _save_pdf_bytes(dest, body)
                item.update(
                    {
                        "ok": True,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "scon_request_get",
                    }
                )
                return item
        # HTML catalog via request (no PDF viewer interference)
        if body and not is_pdf_bytes(body):
            try:
                html_req = body.decode("utf-8", errors="replace")
            except Exception:
                html_req = body.decode("latin-1", errors="replace")
            low = html_req.lower()
            if "n\u00e3o encontrado" in low or "nao encontrado" in low:
                item["error"] = "Ac\u00f3rd\u00e3o n\u00e3o encontrado (SCON)"
                return item
            if is_challenge_page(html=html_req, status=r.status):
                item["challenge"] = True
                item["title"] = "challenge (request)"
            elif (
                "processo.stj.jus.br" in low
                or "getinteiroteor" in low
                or "integra" in low
                or "documento_sequencial" in low
            ):
                followed = try_follow_scon_html(
                    page, html_req, seed, dest, timeout_ms=timeout_ms
                )
                if followed and followed.get("ok"):
                    item.update(
                        {
                            "ok": True,
                            "path": followed.get("path"),
                            "bytes": followed.get("bytes"),
                            "sha256": followed.get("sha256"),
                            "fetch_method": followed.get("fetch_method"),
                            "documento_url": followed.get("documento_url"),
                            "documento_links_found": followed.get("documento_links_found"),
                            "error": None,
                        }
                    )
                    return item
                if followed and followed.get("error"):
                    item["error"] = followed["error"]
                    # still try navigation path below
    except Exception as e:
        item["error"] = f"scon_request: {type(e).__name__}: {e}"

    resp = None
    download = None
    try:
        with page.expect_download(timeout=min(12_000, timeout_ms)) as dl_info:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            download = dl_info.value
        except Exception:
            download = None
    except Exception as e:
        # Timeout sem download: a navegação em geral já ocorreu.
        # Só re-navega se goto nem chegou a responder.
        if resp is None:
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception as e2:
                if not item.get("error"):
                    item["error"] = f"nav: {type(e2).__name__}: {e2}"
                return item
        # senão segue: HTML challenge ou PDF inline
        _ = e

    status = resp.status if resp else item.get("status")
    item["status"] = status
    headers: dict[str, str] = {}
    if resp:
        try:
            headers = {k: v for k, v in resp.headers.items()}
        except Exception:
            headers = {}

    # Direct PDF response body (rare when PDF viewer hijacks navigation)
    if resp:
        try:
            body = resp.body()
            if is_pdf_bytes(body):
                _save_pdf_bytes(dest, body)
                item.update(
                    {
                        "ok": True,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "response_body",
                        "error": None,
                    }
                )
                return item
        except Exception:
            pass

    if download is not None:
        try:
            download.save_as(str(dest))
            data = dest.read_bytes()
            if not is_pdf_bytes(data):
                item["error"] = "download não é PDF"
                try:
                    dest.unlink(missing_ok=True)
                except OSError:
                    pass
                return item
            item.update(
                {
                    "ok": True,
                    "path": str(dest.resolve()),
                    "bytes": dest.stat().st_size,
                    "sha256": file_sha256(dest),
                    "fetch_method": "playwright_download",
                }
            )
            return item
        except Exception as e:
            item["error"] = f"download: {type(e).__name__}: {e}"

    snap = _page_snapshot(page)
    item["title"] = snap["title"]
    challenged = is_challenge_page(
        title=snap["title"],
        html=snap["html"],
        text=snap["text"],
        status=status,
        headers=headers,
    )

    if challenged:
        item["challenge"] = True
        item.update(challenge_meta(title=snap["title"], status=status, final_url=snap["url"]))
        if headed or challenge_wait_s > 0:
            cleared = wait_challenge_clear(
                page,
                timeout_s=challenge_wait_s if headed else min(8.0, challenge_wait_s),
                headed=headed,
            )
            if cleared:
                # re-try once after challenge
                return _retry_after_clear(page, seed, out_dir, timeout_ms=timeout_ms, item=item)
        item["error"] = "waf_challenge (Cloudflare/CSID) — use --headed --warmup ou --cdp"
        return item

    # HTML catalog "Íntegra de Acórdãos" → follow processo.stj.jus.br documento links
    html_for_links = snap["html"] or ""
    followed = try_follow_scon_html(
        page, html_for_links, seed, dest, timeout_ms=timeout_ms
    )
    if followed is not None:
        item["documento_url"] = followed.get("documento_url")
        item["documento_links_found"] = followed.get("documento_links_found")
        if followed.get("ok"):
            item.update(
                {
                    "ok": True,
                    "path": followed.get("path"),
                    "bytes": followed.get("bytes"),
                    "sha256": followed.get("sha256"),
                    "fetch_method": followed.get("fetch_method"),
                    "status": followed.get("status") or status,
                    "error": None,
                }
            )
            if followed.get("note"):
                item["note"] = followed["note"]
            return item
        item["error"] = followed.get("error") or "falha ao baixar documento STJ"
        if followed.get("challenge"):
            item["challenge"] = True
        return item

    # Non-PDF HTML (SCON error / empty)
    item["error"] = (
        f"resposta não-PDF (status={status}, title={snap['title']!r}, "
        f"html_len={len(snap['html'] or '')})"
    )
    return item


def _retry_after_clear(
    page: Any,
    seed: dict[str, str],
    out_dir: Path,
    *,
    timeout_ms: int,
    item: dict[str, Any],
) -> dict[str, Any]:
    """Second attempt after challenge cleared (same page)."""
    url = seed["url"]
    stem = pdf_stem(seed)
    dest = out_dir / f"{stem}.pdf"
    try:
        with page.expect_download(timeout=min(20_000, timeout_ms)) as dl_info:
            resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        download = None
        try:
            download = dl_info.value
        except Exception:
            download = None
        if resp:
            try:
                body = resp.body()
                if is_pdf_bytes(body):
                    _save_pdf_bytes(dest, body)
                    item.update(
                        {
                            "ok": True,
                            "challenge": False,
                            "error": None,
                            "path": str(dest.resolve()),
                            "bytes": dest.stat().st_size,
                            "sha256": file_sha256(dest),
                            "status": resp.status,
                            "fetch_method": "response_body_after_challenge",
                        }
                    )
                    return item
            except Exception:
                pass
        if download is not None:
            download.save_as(str(dest))
            if is_pdf_bytes(dest.read_bytes()):
                item.update(
                    {
                        "ok": True,
                        "challenge": False,
                        "error": None,
                        "path": str(dest.resolve()),
                        "bytes": dest.stat().st_size,
                        "sha256": file_sha256(dest),
                        "fetch_method": "download_after_challenge",
                    }
                )
                return item
        # HTML after clear — follow documento links
        snap = _page_snapshot(page)
        followed = try_follow_scon_html(
            page, snap.get("html") or "", seed, dest, timeout_ms=timeout_ms
        )
        if followed and followed.get("ok"):
            item.update(
                {
                    "ok": True,
                    "challenge": False,
                    "error": None,
                    "path": followed.get("path"),
                    "bytes": followed.get("bytes"),
                    "sha256": followed.get("sha256"),
                    "fetch_method": followed.get("fetch_method"),
                    "documento_url": followed.get("documento_url"),
                }
            )
            return item
        if followed and followed.get("error"):
            item["error"] = followed["error"]
            return item
    except Exception as e:
        item["error"] = f"retry_after_challenge: {type(e).__name__}: {e}"
        return item
    item["error"] = "challenge cleared but PDF still not obtained"
    return item


def _prompt_enter(msg: str) -> None:
    print(msg, file=sys.stderr)
    try:
        input()
    except EOFError:
        # non-interactive: fall back to short wait
        time.sleep(2.0)


def run_warmup(
    *,
    save_storage: Path,
    headed: bool = True,
    cdp_url: str | None = None,
    timeout_s: float = 300.0,
    home_url: str = SCON_HOME,
    channel: str | None = "chrome",
    user_data_dir: Path | None = None,
    wait_enter: bool = True,
) -> int:
    """Open SCON so the user can pass CF; save storage_state.

    Prefer system Chrome (``channel=chrome``) + persistent profile: Playwright's
    bundled Chromium is frequently stuck on Cloudflare forever.
    """
    if not headed and not cdp_url:
        print("stj --warmup: use --headed ou --cdp (sessão real)", file=sys.stderr)
        return EX_ARGS

    from tarrafa.core.browser_util import default_stj_profile_dir

    profile = user_data_dir or (None if cdp_url else default_stj_profile_dir())
    print(f"stj warmup: abrindo {home_url}", file=sys.stderr)
    if channel and not cdp_url:
        print(f"stj warmup: channel={channel} (Chrome real, não Chromium embutido)", file=sys.stderr)
    if profile:
        print(f"stj warmup: perfil persistente -> {profile}", file=sys.stderr)
    print(
        "stj warmup: se o captcha não passar no Chromium, feche e use:\n"
        "  chrome.exe --remote-debugging-port=9222 --user-data-dir=%USERPROFILE%\\.tarrafa\\chrome-stj-profile\n"
        "  tarrafa stj --warmup --cdp http://127.0.0.1:9222 --save-storage ...",
        file=sys.stderr,
    )
    if wait_enter:
        print(
            "stj warmup: resolva o desafio (ou abra o SCON no Chrome); "
            "quando a página do SCON carregar SEM 'Just a moment', volte aqui e pressione ENTER.",
            file=sys.stderr,
        )
    else:
        print("stj warmup: aguardando limpar desafio automaticamente…", file=sys.stderr)

    try:
        with chromium_page(
            headless=not headed,
            accept_downloads=True,
            cdp_url=cdp_url,
            channel=None if cdp_url else channel,
            user_data_dir=None if cdp_url else profile,
        ) as (_p, _browser, context, page):
            page.goto(home_url, wait_until="domcontentloaded", timeout=90_000)
            if wait_enter:
                _prompt_enter(">>> Pressione ENTER para salvar a sessão…")
                snap = _page_snapshot(page)
                ok = not is_challenge_page(
                    title=snap["title"], html=snap["html"], text=snap["text"]
                )
            else:
                ok = wait_challenge_clear(page, timeout_s=timeout_s, headed=True)
            if not ok:
                print(
                    "stj warmup: ainda parece challenge. Salvando cookies mesmo assim "
                    "(pode não bastar — prefira --cdp com Chrome real).",
                    file=sys.stderr,
                )
            save_storage = Path(save_storage)
            save_storage.parent.mkdir(parents=True, exist_ok=True)
            try:
                context.storage_state(path=str(save_storage))
                print(f"stj warmup: storage_state -> {save_storage.resolve()}", file=sys.stderr)
            except Exception as e:
                print(f"stj warmup: não salvou storage_state ({e}); perfil em disco ainda vale.", file=sys.stderr)
            if not ok:
                return EX_CHALLENGE
            return EX_OK
    except Exception as e:
        print(f"stj warmup: {type(e).__name__}: {e}", file=sys.stderr)
        print(
            "stj warmup: se channel=chrome falhou, instale o Google Chrome ou use --channel msedge / --cdp.",
            file=sys.stderr,
        )
        return EX_NAV


def maybe_extract(paths: list[Path], extract_out: Path | None) -> dict[str, Any] | None:
    if not extract_out or not paths:
        return None
    try:
        from tarrafa.tools.pdf_extract.scraper import collect, ensure_pypdf

        ensure_pypdf()
        result = collect(paths, max_pages=None)
        env = build_envelope(
            "pdf-extract",
            source={"files": [str(p) for p in paths], "via": "stj --extract"},
            items=[result["summary"], *result["items"]],
            meta={"files": len(paths), "from_tool": "stj"},
            errors=result["errors"],
            notes=["Encadeado por tarrafa stj --extract"],
        )
        write_json(extract_out, env)
        return result["summary"]
    except Exception as e:
        print(f"stj extract: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def run_downloads(
    seeds: list[dict[str, str]],
    *,
    out_dir: Path,
    out_json: Path,
    storage_state: str | None = None,
    save_storage: str | None = None,
    headed: bool = False,
    cdp_url: str | None = None,
    timeout: float = 90.0,
    challenge_wait: float = 120.0,
    extract_out: Path | None = None,
    pause_s: float = 1.5,
    channel: str | None = "chrome",
    user_data_dir: Path | None = None,
) -> int:
    from tarrafa.core.browser_util import default_stj_profile_dir

    ensure_dir(out_dir)
    timeout_ms = int(timeout * 1000)
    items: list[dict[str, Any]] = []
    errors: list[str] = []
    pdf_paths: list[Path] = []
    # Prefer persistent Chrome profile (survives CF) unless CDP
    profile = user_data_dir
    if profile is None and not cdp_url:
        # reuse warmup profile if it exists; only attach when headed or storage given
        default_p = default_stj_profile_dir()
        if headed or storage_state or default_p.exists():
            profile = default_p

    try:
        with chromium_page(
            storage_state=storage_state if not profile else None,
            headless=not headed,
            accept_downloads=True,
            cdp_url=cdp_url,
            channel=None if cdp_url else channel,
            user_data_dir=None if cdp_url else profile,
        ) as (_p, _browser, context, page):
            for i, seed in enumerate(seeds):
                if i and pause_s > 0:
                    try:
                        page.wait_for_timeout(int(pause_s * 1000))
                    except Exception:
                        time.sleep(pause_s)
                item = download_one(
                    page,
                    seed,
                    out_dir,
                    timeout_ms=timeout_ms,
                    headed=headed,
                    challenge_wait_s=challenge_wait if headed else min(5.0, challenge_wait),
                )
                items.append(item)
                if item.get("ok") and item.get("path"):
                    pdf_paths.append(Path(item["path"]))
                    print(
                        f"stj: ok  {item.get('num_registro') or stem_hint(seed)}  "
                        f"-> {item['path']}  bytes={item.get('bytes')}",
                        file=sys.stderr,
                    )
                elif item.get("challenge"):
                    errors.append(f"challenge: {seed['url']}")
                    print(f"stj: challenge  {seed['url']}", file=sys.stderr)
                else:
                    err = item.get("error") or "fail"
                    errors.append(f"{seed['url']}: {err}")
                    print(f"stj: fail  {err}", file=sys.stderr)

            if save_storage:
                sp = Path(save_storage)
                sp.parent.mkdir(parents=True, exist_ok=True)
                context.storage_state(path=str(sp))
                print(f"stj: storage_state salvo -> {sp.resolve()}", file=sys.stderr)
    except Exception as e:
        print(f"stj: browser {type(e).__name__}: {e}", file=sys.stderr)
        errors.append(f"browser: {type(e).__name__}: {e}")
        if not items:
            return EX_NAV

    extract_summary = maybe_extract(pdf_paths, extract_out)

    ok_n = sum(1 for it in items if it.get("ok"))
    ch_n = sum(1 for it in items if it.get("challenge"))
    envelope = build_envelope(
        "stj",
        source={
            "seeds": len(seeds),
            "out_dir": str(out_dir.resolve()),
            "storage_state": bool(storage_state),
            "cdp": bool(cdp_url),
            "headed": headed,
        },
        items=items,
        meta={
            "ok": ok_n,
            "challenge": ch_n,
            "failed": len(items) - ok_n,
            "extract": extract_summary,
            "extract_out": str(extract_out) if extract_out else None,
        },
        errors=errors,
        notes=[
            "Inteiro teor STJ/SCON. Material-only (PDF + metadados).",
            "Cloudflare/CSID: use --warmup --headed --save-storage, depois --storage-state; "
            "ou Chrome com --remote-debugging-port e --cdp.",
            "Não contorna captcha automaticamente.",
        ],
    )
    write_json(out_json, envelope)
    print(
        f"stj: wrote {out_json}  ok={ok_n}/{len(items)}  challenge={ch_n}  "
        f"pdf_dir={out_dir}",
        file=sys.stderr,
    )

    if ok_n == 0 and ch_n > 0:
        return EX_CHALLENGE
    if ok_n == 0:
        return EX_ZERO
    return EX_OK


def stem_hint(seed: dict[str, str]) -> str:
    return pdf_stem(seed)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa stj",
        description=(
            "Baixa inteiros teores do STJ (SCON GetInteiroTeorDoAcordao) via Playwright. "
            "Sensível a Cloudflare: preferir --warmup/--headed/--cdp."
        ),
    )
    ap.add_argument("--url", default=None, help="URL completa GetInteiroTeorDoAcordao")
    ap.add_argument("--num-registro", default=None, help="num_registro SCON (só dígitos ou formatado)")
    ap.add_argument(
        "--dt-publicacao",
        default=None,
        help="Data de publicação DD/MM/YYYY (ou YYYY-MM-DD)",
    )
    ap.add_argument(
        "--urls-file",
        default=None,
        help="Arquivo com uma seed por linha (URL ou num_registro|dt_publicacao)",
    )
    ap.add_argument(
        "--out-dir",
        default=None,
        help="Diretório para PDFs (default: ./stj_pdfs)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="JSON envelope de saída (default: <out-dir>/stj_envelope.json)",
    )
    ap.add_argument(
        "--storage-state",
        default=None,
        help="Playwright storage_state.json (cookies após warmup)",
    )
    ap.add_argument(
        "--save-storage",
        default=None,
        help="Salvar storage_state ao final (ou no --warmup)",
    )
    ap.add_argument(
        "--headed",
        action="store_true",
        help="Abrir browser visível (necessário para resolver desafio manualmente)",
    )
    ap.add_argument(
        "--channel",
        default="chrome",
        help="Canal Playwright: chrome (default), msedge, ou vazio=Chromium embutido",
    )
    ap.add_argument(
        "--user-data-dir",
        default=None,
        help="Perfil Chrome persistente (default: %%USERPROFILE%%\\.tarrafa\\chrome-stj-profile)",
    )
    ap.add_argument(
        "--no-wait-enter",
        action="store_true",
        help="No --warmup, não pedir ENTER (só poll automático do challenge)",
    )
    ap.add_argument(
        "--cdp",
        default=None,
        metavar="URL",
        help="Conectar a Chrome existente (ex.: http://127.0.0.1:9222)",
    )
    ap.add_argument(
        "--warmup",
        action="store_true",
        help="Só aquecer sessão no SCON e salvar --save-storage (não baixa PDF)",
    )
    ap.add_argument(
        "--timeout",
        type=float,
        default=90.0,
        help="Timeout por navegação em segundos (default 90)",
    )
    ap.add_argument(
        "--challenge-wait",
        type=float,
        default=120.0,
        help="Segundos aguardando limpar CF em modo headed (default 120)",
    )
    ap.add_argument(
        "--pause",
        type=float,
        default=1.5,
        help="Pausa entre downloads em lote (segundos)",
    )
    ap.add_argument(
        "--extract",
        action="store_true",
        help="Após baixar, rodar pdf-extract nos PDFs obtidos",
    )
    ap.add_argument(
        "--extract-out",
        default=None,
        help="JSON do pdf-extract (default: <out-dir>/pdf_extract_stj.json)",
    )
    args = ap.parse_args(argv)

    channel = (args.channel or "").strip() or None
    user_data = Path(args.user_data_dir) if args.user_data_dir else None

    if args.warmup:
        if not args.save_storage:
            print("stj --warmup: informe --save-storage PATH", file=sys.stderr)
            return EX_ARGS
        return run_warmup(
            save_storage=Path(args.save_storage),
            headed=bool(args.headed) or not args.cdp,
            cdp_url=args.cdp,
            timeout_s=max(args.challenge_wait, 60.0),
            channel=channel,
            user_data_dir=user_data,
            wait_enter=not bool(args.no_wait_enter),
        )

    seeds = load_seeds(
        url=args.url,
        num_registro=args.num_registro,
        dt_publicacao=args.dt_publicacao,
        urls_file=Path(args.urls_file) if args.urls_file else None,
    )
    if not seeds:
        print(
            "stj: informe --url e/ou --num-registro + --dt-publicacao e/ou --urls-file",
            file=sys.stderr,
        )
        return EX_ARGS

    out_dir = Path(args.out_dir or "./stj_pdfs")
    out_json = Path(args.out or (out_dir / "stj_envelope.json"))
    extract_out = None
    if args.extract or args.extract_out:
        extract_out = Path(args.extract_out or (out_dir / "pdf_extract_stj.json"))

    return run_downloads(
        seeds,
        out_dir=out_dir,
        out_json=out_json,
        storage_state=args.storage_state,
        save_storage=args.save_storage,
        headed=bool(args.headed),
        cdp_url=args.cdp,
        timeout=float(args.timeout),
        challenge_wait=float(args.challenge_wait),
        extract_out=extract_out,
        pause_s=float(args.pause),
        channel=channel,
        user_data_dir=user_data,
    )


if __name__ == "__main__":
    raise SystemExit(main())
