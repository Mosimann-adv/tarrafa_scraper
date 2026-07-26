# -*- coding: utf-8 -*-
"""Detect bot/WAF challenge pages (Cloudflare, STJ CSID, etc.)."""
from __future__ import annotations

import re
from typing import Any

# Titles / phrases seen on CF managed challenge and STJ CSID interstitials
_CHALLENGE_TITLE_RE = re.compile(
    r"(?:"
    r"just\s+a\s+moment"
    r"|um\s+momento"
    r"|attention\s+required"
    r"|verifica[cç][aã]o\s+autom[aá]tica"
    r"|checking\s+your\s+browser"
    r"|please\s+wait\s*\.\.\."
    r"|access\s+denied"
    r")",
    re.I,
)

_CHALLENGE_BODY_RE = re.compile(
    r"(?:"
    r"cdn-cgi/challenge-platform"
    r"|cf-browser-verification"
    r"|cf-challenge"
    r"|challenges\.cloudflare\.com"
    r"|__cf_chl"
    r"|verifica[cç][aã]o\s+autom[aá]tica\s+em\s+andamento"
    r"|aguarde\s+a\s+verifica[cç][aã]o"
    r"|enable\s+javascript\s+and\s+cookies\s+to\s+continue"
    r"|coordenadoria\s+de\s+seguran[cç]a\s+e\s+defesa\s+cibern[eé]tica"
    r"|csid/stj"
    r")",
    re.I,
)


def is_pdf_bytes(data: bytes | None) -> bool:
    if not data or len(data) < 5:
        return False
    return data[:4] == b"%PDF" or data[:5] == b"%PDF-"


def is_challenge_page(
    *,
    title: str | None = None,
    html: str | None = None,
    text: str | None = None,
    status: int | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    """
    Heuristic: Cloudflare / STJ WAF interstitial.

    True when the response is almost certainly a challenge wall, not the
    target document. Prefer false negatives over blocking real thin pages.
    """
    headers = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    server = headers.get("server", "")
    if "cloudflare" in server.lower() and status in (403, 503):
        # CF error/challenge with empty body still counts if title/body match
        pass

    blob = "\n".join(
        x for x in (title or "", (html or "")[:80_000], (text or "")[:20_000]) if x
    )
    if not blob.strip() and status not in (403, 503):
        return False

    if _CHALLENGE_TITLE_RE.search(title or ""):
        return True
    if _CHALLENGE_BODY_RE.search(blob):
        return True
    # Short 403 with Cloudflare server and almost no content → challenge-ish
    if status in (403, 503) and "cloudflare" in server.lower():
        if len(blob.strip()) < 2_000 or "just a moment" in blob.lower():
            return True
    return False


def challenge_meta(
    *,
    title: str | None = None,
    status: int | None = None,
    final_url: str | None = None,
    reason: str = "waf_challenge",
) -> dict[str, Any]:
    return {
        "challenge": True,
        "challenge_reason": reason,
        "title": title,
        "status": status,
        "final_url": final_url,
    }
