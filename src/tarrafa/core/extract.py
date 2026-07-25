# -*- coding: utf-8 -*-
"""HTML extraction (trafilatura + meta/JSON-LD/structured facts + optional visible text).

Trafilatura keeps the "main article" and drops UI chrome (signature counters, creator
chips, og:title with metrics). For forensic inventory we also harvest structured
side-channels that are already in the HTML, and can merge browser ``innerText``.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

from tarrafa.core.http import normalize_link

_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")
_META_RE = re.compile(r"(?is)<meta\s+([^>]+)>")
_ATTR_RE = re.compile(r"""(?is)([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(["'])(.*?)\2""")
_JSONLD_RE = re.compile(
    r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
)
# Common petition / campaign counters embedded as JSON (Change.org and kin)
_SIG_COUNT_RE = re.compile(
    r'"signatureCount"\s*:\s*\{[^}]{0,200}?"(?:displayed|total)"\s*:\s*(\d+)',
    re.I,
)
_SIG_COUNT_FLAT_RE = re.compile(
    r'"(?:signatureCount|totalSignatures|numSignatures|signature_count|total_signatures)"\s*:\s*(\d+)',
    re.I,
)
_DISPLAY_NAME_RE = re.compile(r'"displayName"\s*:\s*"([^"\\]{1,120})"')
_PERSON_NAME_LD_RE = re.compile(
    r'"@type"\s*:\s*"Person"[^}]{0,400}?"name"\s*:\s*"([^"\\]{1,120})"',
    re.I | re.S,
)


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links: list[str] = []
        self.title: str | None = None
        self._in_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): v for k, v in attrs}
        if tag.lower() == "a":
            href = normalize_link(self.base_url, ad.get("href"))
            if href:
                self.links.append(href)
        if tag.lower() == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title" and self._in_title:
            self._in_title = False
            t = " ".join(self._title_parts).strip()
            if t:
                self.title = re.sub(r"\s+", " ", t)

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)


def _extract_links_and_title(html: str, base_url: str) -> tuple[str | None, list[str]]:
    p = _LinkParser(base_url)
    try:
        p.feed(html or "")
    except Exception:
        pass
    seen: set[str] = set()
    out: list[str] = []
    for u in p.links:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return p.title, out


def extract_meta_tags(html: str) -> dict[str, str]:
    """Parse <meta name/property/content> into a flat dict (last wins)."""
    out: dict[str, str] = {}
    for m in _META_RE.finditer(html or ""):
        attrs = {a.group(1).lower(): a.group(3) for a in _ATTR_RE.finditer(m.group(1))}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        content = attrs.get("content")
        if key and content is not None:
            out[key.strip()] = content.strip()
    return out


def extract_json_ld(html: str) -> list[Any]:
    blocks: list[Any] = []
    for m in _JSONLD_RE.finditer(html or ""):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            blocks.append(json.loads(raw))
        except json.JSONDecodeError:
            # some pages concatenate objects; try soft fix
            try:
                blocks.append(json.loads(f"[{raw}]"))
            except json.JSONDecodeError:
                continue
    return blocks


def _walk_jsonld_persons(obj: Any, out: list[str]) -> None:
    if isinstance(obj, dict):
        t = obj.get("@type")
        types = t if isinstance(t, list) else ([t] if t else [])
        types_l = [str(x).lower() for x in types]
        if "person" in types_l and isinstance(obj.get("name"), str):
            name = obj["name"].strip()
            if name and name not in out:
                out.append(name)
        for v in obj.values():
            _walk_jsonld_persons(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_jsonld_persons(v, out)


def extract_structured_facts(html: str, meta: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """
    Side-channel facts that trafilatura often drops (counters, creator names, og metrics).
    Generic patterns — not site-specific scrapers.
    """
    meta = meta if meta is not None else extract_meta_tags(html)
    facts: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(kind: str, value: Any, source: str, **extra: Any) -> None:
        key = (kind, str(value))
        if key in seen:
            return
        seen.add(key)
        row = {"kind": kind, "value": value, "source": source}
        row.update(extra)
        facts.append(row)

    # Open Graph / Twitter
    for k in ("og:title", "og:description", "twitter:title", "twitter:description", "description", "author"):
        if k in meta and meta[k]:
            add("meta", meta[k], f"meta:{k}", key=k)

    # JSON-LD persons
    for block in extract_json_ld(html):
        persons: list[str] = []
        _walk_jsonld_persons(block, persons)
        for name in persons:
            add("person", name, "json_ld")

    # Embedded signature / supporter counts
    m = _SIG_COUNT_RE.search(html or "")
    if m:
        add("signature_count", int(m.group(1)), "embedded_json:signatureCount")
    else:
        m2 = _SIG_COUNT_FLAT_RE.search(html or "")
        if m2:
            add("signature_count", int(m2.group(1)), "embedded_json:flat")

    # First displayName often = petition creator on Change.org-like payloads
    names = _DISPLAY_NAME_RE.findall(html or "")
    # Prefer names that look like people (space, not pure locale labels)
    for n in names:
        if n.lower() in {"brasil", "brazil", "united states", "portugal", "españa", "spain"}:
            continue
        if " " in n or re.search(r"[A-Za-zÀ-ÿ]{2,}", n):
            add("display_name", n, "embedded_json:displayName")
            break

    # LD Person via regex fallback
    for n in _PERSON_NAME_LD_RE.findall(html or ""):
        add("person", n, "json_ld_regex")

    return facts


def facts_missing_from_text(facts: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """Facts whose value string does not appear in main text (case-insensitive)."""
    blob = (text or "").lower()
    missing = []
    for f in facts:
        val = str(f.get("value") or "").strip()
        if not val:
            continue
        # for long meta titles, check distinctive tokens (numbers / proper-ish chunks)
        if len(val) > 80:
            # keep if any number in fact is missing from text
            nums = re.findall(r"\b\d{2,}\b", val)
            if nums and any(n not in (text or "") for n in nums):
                missing.append(f)
                continue
            # or if less than half of words appear
            words = [w for w in re.findall(r"\w{4,}", val.lower()) if w not in {"https", "http", "www"}]
            if words and sum(1 for w in words if w in blob) < max(1, len(words) // 2):
                missing.append(f)
            continue
        if val.lower() not in blob:
            missing.append(f)
    return missing


def format_facts_block(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return ""
    lines = ["--- structured facts (not always in main article text) ---"]
    for f in facts:
        kind = f.get("kind")
        val = f.get("value")
        src = f.get("source")
        key = f.get("key")
        if key:
            lines.append(f"[{kind}/{key} @ {src}] {val}")
        else:
            lines.append(f"[{kind} @ {src}] {val}")
    return "\n".join(lines)


def enrich_text_with_facts(text: str, facts: list[dict[str, Any]]) -> str:
    missing = facts_missing_from_text(facts, text)
    if not missing:
        return text or ""
    block = format_facts_block(missing)
    if not (text or "").strip():
        return block
    return (text or "").rstrip() + "\n\n" + block


def merge_visible_text(article_text: str, visible_text: str | None) -> tuple[str, str | None]:
    """
    If browser visible text contains substantial content missing from article extract,
    append a visible-text appendix (deduped lightly).
    Returns (merged_text, note).
    """
    if not visible_text or not visible_text.strip():
        return article_text or "", None
    vis = re.sub(r"\s+", " ", visible_text).strip()
    art = (article_text or "").strip()
    if not art:
        return vis, "visible_text_only"
    # If visible is barely longer, skip
    if len(vis) <= len(art) + 80:
        # still check for short missing tokens (names/numbers)
        return art, None
    # Find sentences/chunks in visible not in art (simple window)
    art_l = art.lower()
    # Prefer appending only if visible has unique digits or capitalized names
    unique_bits = []
    for m in re.finditer(r"\b\d{2,6}\b", vis):
        if m.group(0) not in art:
            unique_bits.append(m.group(0))
    for m in re.finditer(r"\b[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+){1,3}\b", vis):
        if m.group(0).lower() not in art_l:
            unique_bits.append(m.group(0))
    if not unique_bits and len(vis) < len(art) * 1.15:
        return art, None
    note = "appended_visible_text_delta"
    # Keep appendix bounded
    appendix = vis if len(vis) <= 12000 else vis[:12000] + "…"
    merged = art + "\n\n--- visible page text (browser) ---\n" + appendix
    return merged, note


def extract_article(
    html: str,
    url: str,
    *,
    visible_text: str | None = None,
    enrich: bool = True,
) -> dict[str, Any]:
    """
    Extract main text + metadata from HTML.

    Always attaches:
      - meta_tags
      - json_ld (raw blocks)
      - structured_facts
    When ``enrich=True`` (default), appends structured facts / visible text missing
    from the main article into ``text`` (original remains in ``text_main``).
    """
    title, links = _extract_links_and_title(html, url)
    text = ""
    author = None
    date = None
    method = "fallback"

    meta = extract_meta_tags(html)
    json_ld = extract_json_ld(html)
    facts = extract_structured_facts(html, meta)

    # Prefer og:title for display title when richer
    if meta.get("og:title"):
        title = title or meta["og:title"]

    try:
        from trafilatura import extract as traf_extract
        from trafilatura import bare_extraction

        bare = bare_extraction(html, url=url, include_comments=False, include_tables=True)
        if bare:
            if isinstance(bare, dict):
                text = (bare.get("text") or "").strip()
                title = bare.get("title") or title
                author = bare.get("author")
                date = bare.get("date")
            else:
                text = (getattr(bare, "text", None) or "").strip()
                title = getattr(bare, "title", None) or title
                author = getattr(bare, "author", None)
                date = getattr(bare, "date", None)
            method = "trafilatura.bare"
        if not text:
            text = (traf_extract(html, url=url, include_comments=False, include_tables=True) or "").strip()
            if text:
                method = "trafilatura.extract"
    except ImportError:
        method = "fallback_no_trafilatura"
        text = _SCRIPT_RE.sub(" ", html or "")
        text = _STYLE_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
    except Exception as e:
        method = f"trafilatura_error:{type(e).__name__}"

    # Author from JSON-LD / facts if trafilatura missed
    if not author:
        for f in facts:
            if f.get("kind") in ("person", "display_name"):
                author = str(f.get("value"))
                break

    # Date from meta
    if not date:
        date = meta.get("article:published_time") or meta.get("og:updated_time") or meta.get("date")

    text_main = text
    enrich_notes: list[str] = []
    if enrich:
        text = enrich_text_with_facts(text, facts)
        if text != text_main:
            enrich_notes.append("structured_facts")
        text2, vnote = merge_visible_text(text, visible_text)
        if vnote:
            text = text2
            enrich_notes.append(vnote)
            method = f"{method}+visible"

    # If og:title has signature metric and still not in text after enrich, force-add og:title line
    # (enrich_text_with_facts should already handle via facts)

    return {
        "url": url,
        "title": title or meta.get("og:title"),
        "author": author,
        "date": date,
        "text": text,
        "text_main": text_main,
        "text_len": len(text or ""),
        "text_main_len": len(text_main or ""),
        "links": links,
        "links_count": len(links),
        "extract_method": method,
        "host": urlparse(url).netloc,
        "meta_tags": {
            k: meta[k]
            for k in (
                "og:title",
                "og:description",
                "og:url",
                "og:type",
                "description",
                "author",
                "twitter:title",
                "article:published_time",
            )
            if k in meta
        },
        "json_ld": json_ld,
        "structured_facts": facts,
        "enrich_notes": enrich_notes,
    }
