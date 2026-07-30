#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Instagram comment tool for Tarrafa (Playwright + authenticated API).

Entry: ``tarrafa ig …`` or ``python -m tarrafa ig …``.

Strategy:
  1. Authenticated REST ``/api/v1/media/{id}/comments/`` with forced ``min_id`` pagination
     (``has_more_comments`` is often false; use ``next_min_id`` + growth).
  2. Optional network intercept of GraphQL JSON.
  3. DOM enrichment via permanent anchors ``a[href*='/c/']``.

Never automate Facebook OIDC / password / password-reset flows — native IG login only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHECKPOINT_EVERY = 25  # save partial dump every N successful load iterations
STAGNANT_ROUNDS_STOP = 8  # stop when count does not grow for this many rounds
SCROLL_PAUSE_MS = 900
CLICK_PAUSE_MS = 700
DEFAULT_MAX = 50_000
PAGE_TIMEOUT_MS = 60_000

# PT-BR / EN UI labels seen on Instagram
LOAD_MORE_PATTERNS = [
    re.compile(r"carregar\s+mais\s+coment[aá]rios?", re.I),
    re.compile(r"ver\s+mais\s+coment[aá]rios?", re.I),
    re.compile(r"load\s+more\s+comments?", re.I),
    re.compile(r"view\s+more\s+comments?", re.I),
]
VIEW_REPLIES_PATTERNS = [
    re.compile(r"ver\s+resposta", re.I),
    re.compile(r"ver\s+\d+\s+resposta", re.I),
    re.compile(r"view\s+repl", re.I),
    re.compile(r"\d+\s+repl", re.I),
]
LOGIN_WALL_PATTERNS = [
    re.compile(r"\bentrar\b", re.I),
    re.compile(r"entre\s+para\s+ver", re.I),
    re.compile(r"log\s*in", re.I),
    re.compile(r"sign\s*up", re.I),
    re.compile(r"cadastre-se", re.I),
]

LIKES_TRAILING_RE = re.compile(
    r"\s("
    r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|"  # 4.537 / 1.062
    r"\d+[.,]\d+|"
    r"\d+"
    r")\s*(mil\s*)?curtidas?\s*$",
    re.I,
)
LIKES_ONLY_RE = re.compile(
    r"^("
    r"\d{1,3}(?:\.\d{3})+|"
    r"\d+[.,]\d+|"
    r"\d+"
    r")\s*(mil\s*)?curtidas?$",
    re.I,
)
COMMENT_ID_FROM_URL_RE = re.compile(r"/c/(\d+)/?")
SHORTCODE_RE = re.compile(
    r"instagram\.com/(?:[A-Za-z0-9._]+/)?(?:p|reel|tv)/([^/?#]+)",
    re.I,
)
PROFILE_PATH_RE = re.compile(r"^/([A-Za-z0-9._]{1,30})/?$")
PROFILE_RESERVED_PATHS = {
    "accounts",
    "about",
    "api",
    "developer",
    "directory",
    "direct",
    "emails",
    "explore",
    "legal",
    "p",
    "privacy",
    "reel",
    "reels",
    "stories",
    "terms",
    "tv",
    "web",
}

# Known IG comment GraphQL doc_ids / path fragments (best-effort; IG rotates them)
GRAPHQL_HINTS = (
    "comments",
    "comment",
    "xdt_api__v1__media",
    "media/comments",
    "child_comments",
    "comment_list",
    "PolarisPostComments",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    try:
        from tarrafa.core.writers import utc_now_iso as _core_utc

        return _core_utc()
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def shortcode_from_url(url: str) -> str | None:
    m = SHORTCODE_RE.search(url or "")
    return m.group(1) if m else None


def instagram_profile_url(value: str) -> str | None:
    """Normaliza handle/URL de perfil; rejeita posts e rotas reservadas."""
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.startswith("@"):
        raw = raw[1:]
    if "://" not in raw and "/" not in raw:
        handle = raw.strip()
        if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", handle):
            return None
        if handle.casefold() in PROFILE_RESERVED_PATHS:
            return None
        return f"https://www.instagram.com/{handle}/"

    if "://" not in raw:
        raw = f"https://{raw.lstrip('/')}"
    try:
        parts = urlsplit(raw)
    except ValueError:
        return None
    host = (parts.hostname or "").casefold()
    if host not in {"instagram.com", "www.instagram.com"}:
        return None
    match = PROFILE_PATH_RE.fullmatch(parts.path or "/")
    if not match:
        return None
    handle = match.group(1)
    if handle.casefold() in PROFILE_RESERVED_PATHS:
        return None
    return urlunsplit(("https", "www.instagram.com", f"/{handle}/", "", ""))


def instagram_media_urls(values: list[str], *, limit: int = 12) -> list[str]:
    """Canonicaliza e deduplica URLs de posts/reels/TV na ordem recebida."""
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        match = re.search(
            r"https?://(?:www\.)?instagram\.com/"
            r"(?:[A-Za-z0-9._]+/)?(p|reel|tv)/([A-Za-z0-9_-]+)",
            value or "",
            re.IGNORECASE,
        )
        if not match:
            continue
        canonical = f"https://www.instagram.com/{match.group(1).lower()}/{match.group(2)}/"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
        if len(out) >= max(0, limit):
            break
    return out


def instagram_reported_posts(*values: str | None) -> int | None:
    """Extrai a contagem declarada no perfil sem confundi-la com seguidores."""
    public_text = " ".join(str(value or "") for value in values)
    match = re.search(
        r"\b([\d.,]+)\s+(?:posts?|publica(?:ç|c)[õo]es)\b",
        public_text,
        re.IGNORECASE,
    )
    digits = re.sub(r"\D", "", match.group(1)) if match else ""
    return int(digits) if digits else None


def abs_comment_url(source_post: str, comment_id: str | None) -> str | None:
    if not comment_id:
        return None
    sc = shortcode_from_url(source_post)
    if not sc:
        return None
    # Normalize reel → p for stable /c/ permalinks (IG accepts both; inventory uses /p/)
    return f"https://www.instagram.com/p/{sc}/c/{comment_id}/"


def parse_likes_n(raw: Any) -> int | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return int(raw)
    s = str(raw).lower().strip()
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*mil", s)
    if m:
        num = m.group(1).replace(".", "").replace(",", ".")
        try:
            return int(float(num) * 1000)
        except ValueError:
            pass
    m = re.search(r"([\d.]+)\s*curtidas?", s)
    if m:
        digits = m.group(1).replace(".", "")
        if digits.isdigit():
            return int(digits)
    m = re.search(r"(\d+)", s)
    return int(m.group(1)) if m else None


def peel_likes_from_text(text: str | None, likes_field: Any) -> tuple[str, Any]:
    """Separate trailing 'N curtidas' glued into comment text."""
    text = text or ""
    likes = likes_field
    m = LIKES_TRAILING_RE.search(text)
    if m:
        likes = m.group(0).strip()
        text = text[: m.start()].strip()
    return text, likes


def is_likes_only_text(text: str | None) -> bool:
    if not text:
        return False
    return bool(LIKES_ONLY_RE.match(text.strip()))


def dedupe_key(row: dict[str, Any]) -> str:
    cid = row.get("comment_id")
    if cid:
        return f"id:{cid}"
    user = (row.get("user") or "").strip().lower()
    text = (row.get("text") or "").strip()
    return f"ut:{user}|{text}"


def normalize_row(row: dict[str, Any], source_post: str, collected_at: str) -> dict[str, Any] | None:
    """Build canonical comment record; drop garbage likes-only rows."""
    text = row.get("text")
    likes_raw = row.get("likes")
    text, likes_raw = peel_likes_from_text(text, likes_raw)

    if is_likes_only_text(text):
        return None
    if text is not None and not str(text).strip() and not row.get("comment_id"):
        return None

    comment_id = row.get("comment_id")
    if comment_id is not None:
        comment_id = str(comment_id)

    url = row.get("url") or row.get("permalink")
    if not url and comment_id:
        url = abs_comment_url(source_post, comment_id)
    if url and comment_id is None:
        m = COMMENT_ID_FROM_URL_RE.search(url)
        if m:
            comment_id = m.group(1)

    parent_id = row.get("parent_id") or row.get("parent_comment_id")
    if parent_id is not None:
        parent_id = str(parent_id)

    is_reply = row.get("is_reply")
    if is_reply is None:
        is_reply = bool(parent_id)

    likes_n = row.get("likes_n")
    if likes_n is None:
        likes_n = parse_likes_n(likes_raw)

    user = row.get("user")
    if user:
        user = str(user).lstrip("@").strip()

    profile_url = row.get("profile_url")
    if not profile_url and user:
        profile_url = f"https://www.instagram.com/{user}/"

    out = {
        "comment_id": comment_id,
        "url": url,
        "user": user,
        "profile_url": profile_url,
        "text": text.strip() if isinstance(text, str) else text,
        "likes": likes_raw,
        "likes_n": likes_n,
        "parent_id": parent_id,
        "is_reply": bool(is_reply),
        "timestamp_iso": row.get("timestamp_iso") or row.get("timestamp") or None,
        "collected_at": row.get("collected_at") or collected_at,
        "source_post": row.get("source_post") or source_post,
    }
    return out


# ---------------------------------------------------------------------------
# GraphQL / API payload walkers
# ---------------------------------------------------------------------------

def _walk_comment_nodes(obj: Any, out: list[dict[str, Any]], parent_hint: str | None = None) -> None:
    """Recursively find dicts that look like IG comment nodes."""
    if isinstance(obj, dict):
        # Heuristic: node with pk/id + text + user
        has_text = "text" in obj and isinstance(obj.get("text"), str)
        has_user = any(k in obj for k in ("user", "owner", "username"))
        has_id = any(k in obj for k in ("pk", "id", "strong_id__", "comment_id"))
        if has_text and (has_user or has_id):
            cid = obj.get("pk") or obj.get("id") or obj.get("comment_id") or obj.get("strong_id__")
            if isinstance(cid, dict):
                cid = cid.get("id") or cid.get("pk")
            user = None
            profile_url = None
            u = obj.get("user") or obj.get("owner")
            if isinstance(u, dict):
                user = u.get("username") or u.get("user_name")
                if u.get("pk") or u.get("id"):
                    profile_url = f"https://www.instagram.com/{user}/" if user else None
            elif isinstance(obj.get("username"), str):
                user = obj.get("username")

            parent = obj.get("parent_comment_id") or obj.get("parent_id")
            if parent is None:
                pobj = obj.get("parent")
                if isinstance(pobj, dict):
                    parent = pobj.get("pk") or pobj.get("id")
                elif pobj is not None:
                    parent = pobj
            if parent is None:
                parent = parent_hint
            if isinstance(parent, dict):
                parent = parent.get("pk") or parent.get("id")

            likes_raw = obj.get("comment_like_count")
            if likes_raw is None:
                likes_raw = obj.get("like_count")
            if likes_raw is None and isinstance(obj.get("edge_liked_by"), dict):
                likes_raw = obj["edge_liked_by"].get("count")

            ts = obj.get("created_at") or obj.get("created_at_utc") or obj.get("timestamp")
            ts_iso = None
            if isinstance(ts, (int, float)):
                try:
                    ts_iso = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    )
                except (OSError, ValueError, OverflowError):
                    ts_iso = None
            elif isinstance(ts, str) and "T" in ts:
                ts_iso = ts

            out.append(
                {
                    "comment_id": str(cid) if cid is not None else None,
                    "user": user,
                    "profile_url": profile_url,
                    "text": obj.get("text"),
                    "likes": likes_raw,
                    "likes_n": parse_likes_n(likes_raw),
                    "parent_id": str(parent) if parent is not None else None,
                    "is_reply": bool(parent),
                    "timestamp_iso": ts_iso,
                    "_from": "graphql",
                }
            )

        for k, v in obj.items():
            # child comment lists
            if k in (
                "child_comments",
                "preview_child_comments",
                "edge_threaded_comments",
                "replies",
                "comment_replies",
            ):
                cid_here = obj.get("pk") or obj.get("id") or obj.get("comment_id")
                if isinstance(cid_here, dict):
                    cid_here = cid_here.get("id") or cid_here.get("pk")
                _walk_comment_nodes(v, out, parent_hint=str(cid_here) if cid_here else parent_hint)
            else:
                _walk_comment_nodes(v, out, parent_hint=parent_hint)
    elif isinstance(obj, list):
        for item in obj:
            _walk_comment_nodes(item, out, parent_hint=parent_hint)


def response_looks_like_comments(url: str, content_type: str | None) -> bool:
    u = (url or "").lower()
    if any(h in u for h in GRAPHQL_HINTS):
        return True
    if "graphql" in u or "/api/v1/" in u:
        return True
    if content_type and "json" in content_type.lower():
        # still capture generic JSON from IG origin — filter later
        if "instagram.com" in u or "cdninstagram" in u:
            return True
    return False


# ---------------------------------------------------------------------------
# Collector state
# ---------------------------------------------------------------------------

class CommentStore:
    def __init__(self, source_post: str):
        self.source_post = source_post
        self.collected_at = utc_now_iso()
        self.by_key: dict[str, dict[str, Any]] = {}
        self.public_comment_count: int | None = None
        self.methods: set[str] = set()
        self.graphql_hits = 0
        self.dom_hits = 0
        self.clinks: set[str] = set()

    def upsert_many(self, rows: list[dict[str, Any]], method: str) -> int:
        added = 0
        for raw in rows:
            row = normalize_row(raw, self.source_post, self.collected_at)
            if not row:
                continue
            if row.get("url"):
                self.clinks.add(row["url"])
            key = dedupe_key(row)
            if key in self.by_key:
                # merge: fill missing fields
                prev = self.by_key[key]
                for k, v in row.items():
                    if prev.get(k) in (None, "", False) and v not in (None, ""):
                        prev[k] = v
                continue
            self.by_key[key] = row
            self.methods.add(method)
            added += 1
            if method == "graphql":
                self.graphql_hits += 1
            elif method == "dom":
                self.dom_hits += 1
        return added

    @property
    def count(self) -> int:
        return len(self.by_key)

    def comments_list(self) -> list[dict[str, Any]]:
        rows = list(self.by_key.values())
        # Stable-ish order: top-level first, then by likes desc, then user
        rows.sort(
            key=lambda r: (
                1 if r.get("is_reply") else 0,
                -(r.get("likes_n") or 0),
                r.get("user") or "",
                r.get("comment_id") or "",
            )
        )
        return rows

    def to_payload(self, notes: list[str] | None = None) -> dict[str, Any]:
        comments = self.comments_list()
        with_id = sum(1 for c in comments if c.get("comment_id"))
        with_url = sum(1 for c in comments if c.get("url"))
        with_parent = sum(1 for c in comments if c.get("parent_id"))
        return {
            "source": self.source_post,
            "collected_at": self.collected_at,
            "count": len(comments),
            "public_comment_count": self.public_comment_count,
            "cLinks": with_url,
            "cLinks_set_size": len(self.clinks),
            "with_comment_id": with_id,
            "with_parent_id": with_parent,
            "methods": sorted(self.methods),
            "graphql_nodes_seen": self.graphql_hits,
            "dom_nodes_seen": self.dom_hits,
            "note": (
                "Coleta Playwright: GraphQL/API intercept (primário) + DOM a[href*='/c/'] "
                "(enriquecimento). Checkpoint incremental. Não automatiza OIDC Facebook."
            ),
            "limitations": notes
            or [
                "Universo canônico = public_comment_count no momento da coleta (snapshot UI/meta).",
                "Sem login válido a UI limita o que carrega; use --storage-state de sessão nativa IG.",
                "doc_id GraphQL do IG muda; se intercept falhar, fallback DOM ainda grava permalinks.",
                "Threading depende de expandir 'Ver respostas' e/ou payloads child_comments.",
            ],
            "comments": comments,
        }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    try:
        from tarrafa.core.writers import write_json as _core_write

        _core_write(path, payload)
        return
    except Exception:
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    # Always real JSON object (never double-encoded string)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_checkpoint(store: CommentStore, out_path: Path, stats_path: Path, round_i: int) -> None:
    payload = store.to_payload()
    write_json(out_path, payload)
    # NDJSON checkpoint log (cursor/count)
    ndjson_path = out_path.with_suffix(out_path.suffix + ".checkpoint.ndjson")
    line = {
        "ts": utc_now_iso(),
        "round": round_i,
        "count": store.count,
        "cLinks": payload["cLinks"],
        "public_comment_count": store.public_comment_count,
        "methods": payload["methods"],
    }
    with ndjson_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
    write_json(
        stats_path,
        {
            "count": store.count,
            "cLinks": payload["cLinks"],
            "cLinks_set_size": payload["cLinks_set_size"],
            "with_comment_id": payload["with_comment_id"],
            "with_parent_id": payload["with_parent_id"],
            "public_comment_count": store.public_comment_count,
            "round": round_i,
            "collected_at": store.collected_at,
            "source": store.source_post,
        },
    )


# ---------------------------------------------------------------------------
# Browser-side extractors (evaluate)
# ---------------------------------------------------------------------------

DOM_EXTRACT_JS = r"""
() => {
  const results = [];
  const seen = new Set();
  const abs = (href) => {
    try { return new URL(href, location.origin).href; } catch { return href; }
  };
  const idFrom = (href) => {
    const m = (href || '').match(/\/c\/(\d+)/);
    return m ? m[1] : null;
  };

  // 1) Permanent comment anchors
  for (const a of document.querySelectorAll("a[href*='/c/']")) {
    const href = abs(a.getAttribute('href') || '');
    const cid = idFrom(href);
    if (!cid || seen.has('c:' + cid)) continue;
    seen.add('c:' + cid);

    // climb to a reasonable comment container
    let root = a.closest('ul > div, ul > li, div[role="article"], li') || a.parentElement;
    for (let i = 0; i < 6 && root && root.parentElement; i++) {
      if (root.innerText && root.innerText.length > 20) break;
      root = root.parentElement;
    }
    const block = root || a;

    // username: first profile link that is not /c/ or /p/
    let user = null;
    let profile_url = null;
    for (const p of block.querySelectorAll('a[href^="/"]')) {
      const h = p.getAttribute('href') || '';
      if (h.includes('/c/') || h.includes('/p/') || h.includes('/reel/') || h.includes('/tv/')) continue;
      if (h.startsWith('/explore') || h.startsWith('/stories') || h.startsWith('/direct')) continue;
      const m = h.match(/^\/([A-Za-z0-9._]+)\/?$/);
      if (m) {
        user = m[1];
        profile_url = abs('/' + user + '/');
        break;
      }
    }

    // time
    let timestamp_iso = null;
    const t = block.querySelector('time');
    if (t) {
      timestamp_iso = t.getAttribute('datetime') || t.getAttribute('title') || null;
    }

    // likes: prefer spans/buttons with 'curtida'
    let likes = null;
    const allText = (block.innerText || '').split('\n').map(s => s.trim()).filter(Boolean);
    for (const line of allText) {
      if (/^\d[\d.\s]*\s*(mil\s*)?curtidas?$/i.test(line) || /^\d+\s*likes?$/i.test(line)) {
        likes = line;
        break;
      }
    }
    // button aria
    if (!likes) {
      for (const el of block.querySelectorAll('button, span, div')) {
        const tx = (el.innerText || el.textContent || '').trim();
        if (/^\d[\d.\s]*\s*(mil\s*)?curtidas?$/i.test(tx)) {
          likes = tx;
          break;
        }
      }
    }

    // text: prefer span that is not username and not likes
    let text = null;
    const spans = [...block.querySelectorAll('span')].map(s => (s.innerText || '').trim()).filter(Boolean);
    // longest plausible comment span
    let best = '';
    for (const s of spans) {
      if (user && s === user) continue;
      if (/curtidas?$/i.test(s) || /^likes?$/i.test(s)) continue;
      if (/^Responder$/i.test(s) || /^Reply$/i.test(s)) continue;
      if (/^Ver\s/i.test(s) || /^View\s/i.test(s)) continue;
      if (s.length > best.length && s.length >= 1) best = s;
    }
    text = best || null;

    results.push({
      comment_id: cid,
      url: href.split('?')[0],
      user,
      profile_url,
      text,
      likes,
      parent_id: null,
      is_reply: false,
      timestamp_iso,
      _from: 'dom_anchor'
    });
  }

  // 2) public comment count (meta / aria / header text)
  let public_count = null;
  const bodyText = document.body ? document.body.innerText : '';
  let m = bodyText.match(/([\d.]+)\s*mil\s*coment[aá]rios?/i);
  if (m) {
    const n = parseFloat(m[1].replace('.', '').replace(',', '.'));
    if (!isNaN(n)) public_count = Math.round(n * 1000);
  }
  if (public_count == null) {
    m = bodyText.match(/([\d.]+)\s*coment[aá]rios?/i);
    if (m) {
      const digits = m[1].replace(/\./g, '');
      if (/^\d+$/.test(digits)) public_count = parseInt(digits, 10);
    }
  }
  // meta description sometimes has counts
  const md = document.querySelector('meta[name="description"]');
  if (md && public_count == null) {
    const c = md.getAttribute('content') || '';
    m = c.match(/([\d,.]+)\s*Comments/i) || c.match(/([\d.]+)\s*coment/i);
    if (m) {
      const digits = m[1].replace(/[.,]/g, '');
      if (/^\d+$/.test(digits) && digits.length < 8) public_count = parseInt(digits, 10);
    }
  }

  // login wall signals
  const login_wall = !!(
    document.querySelector('input[name="username"]') ||
    document.querySelector('a[href*="/accounts/login"]') ||
    /entre para ver|log in to see|entrar/i.test(
      (document.querySelector('header') || document.body || {}).innerText || ''
    )
  );

  // load-more / view-replies presence
  const buttons = [...document.querySelectorAll('button, div[role="button"], span[role="button"]')]
    .map(el => ({ text: (el.innerText || el.textContent || '').trim().slice(0, 120) }))
    .filter(x => x.text);

  return {
    comments: results,
    public_count,
    login_wall,
    buttons: buttons.slice(0, 80),
    href: location.href
  };
}
"""


CLICK_BY_TEXT_JS = r"""
(patterns) => {
  const reList = patterns.map(p => new RegExp(p, 'i'));
  const candidates = [
    ...document.querySelectorAll('button, div[role="button"], span[role="button"], a')
  ];
  let clicked = 0;
  for (const el of candidates) {
    const tx = (el.innerText || el.textContent || '').trim().replace(/\s+/g, ' ');
    if (!tx || tx.length > 80) continue;
    if (!reList.some(re => re.test(tx))) continue;
    // skip disabled
    if (el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled')) continue;
    try {
      el.scrollIntoView({ block: 'center', inline: 'nearest' });
      el.click();
      clicked += 1;
      if (clicked >= 6) break; // batch of reply expands
    } catch (e) { /* ignore */ }
  }
  return clicked;
}
"""


# Deep path proven 2026-07-24 on JR reel (media_id + min_id force).
# has_more_comments is often FALSE; keep going while next_min_id advances
# and has_more_headload_comments / unique growth continues.
API_V1_PAGINATE_JS = r"""
async ({ source, maxComments, expandReplies }) => {
  const sleep = (ms) => new Promise(r => setTimeout(r, ms));
  const APP_ID = '936619743392459';
  const map = new Map();
  const pagesMeta = [];
  let stagnant = 0;

  function mediaIdFromPage() {
    const html = document.documentElement.innerHTML;
    let m = html.match(/"media_id"\s*:\s*"?(\d{6,})"?/);
    if (m) return m[1];
    m = html.match(/mediaid=(\d+)/i);
    if (m) return m[1];
    // shortcode → sometimes in props as id "NNN_USER"
    m = html.match(/"id"\s*:\s*"(\d{10,})_\d+"/);
    if (m) return m[1];
    return null;
  }

  function shortcodeFrom(sourceUrl) {
    const m = (sourceUrl || location.href).match(/instagram\.com\/(?:p|reel|tv)\/([^/?#]+)/i);
    return m ? m[1] : null;
  }

  function absUrl(sc, cid) {
    if (!cid) return null;
    return 'https://www.instagram.com/p/' + (sc || 'unknown') + '/c/' + cid + '/';
  }

  function tsIso(ts) {
    if (ts == null) return null;
    try {
      const n = typeof ts === 'number' ? ts : parseInt(ts, 10);
      return n ? new Date(n * 1000).toISOString() : null;
    } catch (e) { return null; }
  }

  function upsert(c, parentId, sc) {
    if (!c) return;
    const cid = c.pk != null ? String(c.pk) : (c.strong_id__ != null ? String(c.strong_id__) : null);
    const user = c.user && c.user.username ? c.user.username : null;
    const text = (c.text || '').trim();
    if (!text) return;
    const likes_n = typeof c.comment_like_count === 'number' ? c.comment_like_count
      : (typeof c.like_count === 'number' ? c.like_count : null);
    const key = cid ? ('id:' + cid) : ('ut:' + (user || '') + '|' + text);
    const prev = map.get(key) || {};
    const pid = parentId != null ? String(parentId)
      : (c.parent_comment_id != null ? String(c.parent_comment_id) : (prev.parent_id || null));
    map.set(key, {
      comment_id: cid || prev.comment_id || null,
      url: absUrl(sc, cid || prev.comment_id),
      user: user || prev.user || null,
      profile_url: (user || prev.user) ? ('https://www.instagram.com/' + (user || prev.user) + '/') : null,
      text,
      likes: likes_n != null ? (likes_n + ' curtidas') : (prev.likes || null),
      likes_n: likes_n != null ? likes_n : prev.likes_n,
      parent_id: pid,
      is_reply: !!pid,
      timestamp_iso: tsIso(c.created_at_utc || c.created_at) || prev.timestamp_iso || null,
      _from: 'api_v1'
    });
    const kids = c.preview_child_comments || [];
    if (Array.isArray(kids)) for (const k of kids) upsert(k, cid, sc);
  }

  async function get(url) {
    const r = await fetch(url, {
      credentials: 'include',
      headers: {
        'X-IG-App-ID': APP_ID,
        'X-Requested-With': 'XMLHttpRequest',
        'Accept': '*/*'
      }
    });
    const text = await r.text();
    let json = null;
    try { json = JSON.parse(text); } catch (e) {}
    return { status: r.status, json };
  }

  const sc = shortcodeFrom(source);
  const mediaId = mediaIdFromPage();
  if (!mediaId) {
    return { error: 'media_id_not_found', count: 0, comments: [] };
  }

  let minId = null;
  let publicCount = null;
  let page = 0;
  const maxPages = 2500;
  const parents = new Set();
  let prevSize = 0;

  while (page < maxPages && map.size < (maxComments || 50000)) {
    page++;
    let url = 'https://www.instagram.com/api/v1/media/' + mediaId
      + '/comments/?can_support_threading=true&permalink_enabled=false';
    if (minId) url += '&min_id=' + encodeURIComponent(minId);
    const { status, json } = await get(url);
    if (status !== 200 || !json) {
      pagesMeta.push({ page, status, error: true });
      break;
    }
    if (publicCount == null && json.comment_count != null) publicCount = json.comment_count;
    const list = json.comments || [];
    for (const c of list) {
      upsert(c, null, sc);
      if ((c.child_comment_count || 0) > 0 || c.has_more_head_child_comments || c.has_more_tail_child_comments) {
        parents.add(String(c.pk));
      }
    }
    const size = map.size;
    const next = json.next_min_id || null;
    pagesMeta.push({
      page, n: list.length, total: size,
      has_more: !!json.has_more_comments,
      head_more: !!json.has_more_headload_comments,
      grew: size > prevSize
    });
    if (size <= prevSize) stagnant++; else stagnant = 0;
    prevSize = size;
    // CRITICAL: do NOT stop on has_more_comments===false alone
    if (!next) break;
    if (stagnant >= 6) break;
    minId = next;
    await sleep(page % 20 === 0 ? 900 : 260);
  }

  let childFetches = 0;
  let childOk = 0;
  if (expandReplies) {
    const parentList = Array.from(parents);
    const parentLimit = Math.min(parentList.length, 4000);
    for (let i = 0; i < parentLimit && map.size < (maxComments || 50000); i++) {
      childFetches++;
      let cMin = '';
      let guard = 0;
      let got = false;
      while (guard < 40) {
        guard++;
        const u = 'https://www.instagram.com/api/v1/media/' + mediaId
          + '/comments/' + parentList[i] + '/child_comments/?min_id='
          + encodeURIComponent(cMin || '');
        const { status, json } = await get(u);
        if (status !== 200 || !json) break;
        got = true;
        const list = json.child_comments || json.comments || [];
        for (const c of list) upsert(c, parentList[i], sc);
        const more = json.has_more_head_child_comments || json.has_more_tail_child_comments || json.has_more_comments;
        const next = json.next_min_id || json.next_max_child_cursor || null;
        if (!more || !next || !list.length) break;
        cMin = next;
        await sleep(160);
      }
      if (got) childOk++;
      if (i % 20 === 0) await sleep(350);
      else await sleep(150);
    }
  }

  return {
    media_id: mediaId,
    public_comment_count: publicCount,
    count: map.size,
    pages: pagesMeta.length,
    stagnant,
    parents_queued: parents.size,
    parents_fetched: expandReplies ? Math.min(parents.size, 4000) : 0,
    childFetches,
    childOk,
    pages_tail: pagesMeta.slice(-5),
    top_level: Array.from(map.values()).filter(c => !c.parent_id).length,
    comments: Array.from(map.values())
  };
}
"""


# ---------------------------------------------------------------------------
# Login / safety
# ---------------------------------------------------------------------------

def url_is_dangerous_auth_flow(url: str) -> bool:
    u = (url or "").lower()
    fatal = (
        "password/reset",
        "accounts/password",
        "recover/initiate",
        "signupviafb",
        "facebook.com/login",
        "facebook.com/dialog",
        "facebook.com/v",
    )
    return any(x in u for x in fatal)


def detect_login_wall_from_dom(dom_info: dict[str, Any]) -> bool:
    if dom_info.get("login_wall"):
        return True
    href = (dom_info.get("href") or "").lower()
    if "/accounts/login" in href or "/accounts/emailsignup" in href:
        return True
    return False


# ---------------------------------------------------------------------------
# Inventário de perfil
# ---------------------------------------------------------------------------

PROFILE_EXTRACT_JS = r"""
() => {
  const abs = (href) => {
    try { return new URL(href, location.origin).href; } catch { return href || ""; }
  };
  const media = [];
  const seen = new Set();
  for (const a of document.querySelectorAll("a[href]")) {
    const url = abs(a.getAttribute("href"));
    if (!/instagram\.com\/(?:[A-Za-z0-9._]+\/)?(?:p|reel|tv)\//i.test(url) || seen.has(url)) continue;
    seen.add(url);
    media.push(url);
  }
  const meta = (selector) => document.querySelector(selector)?.getAttribute("content") || null;
  const profileText = (
    document.querySelector("main")?.innerText ||
    document.body?.innerText ||
    ""
  ).replace(/\s+/g, " ").trim();
  const loginText = Array.from(document.querySelectorAll("a,button"))
    .map((el) => (el.innerText || "").trim())
    .filter(Boolean)
    .slice(0, 100)
    .join(" | ");
  return {
    href: location.href,
    title: document.title || null,
    description: meta('meta[name="description"]') || meta('meta[property="og:description"]'),
    og_title: meta('meta[property="og:title"]'),
    image: meta('meta[property="og:image"]'),
    media_urls: media,
    text_excerpt: profileText.slice(0, 2000),
    login_wall:
      /\/accounts\/(?:login|emailsignup)/i.test(location.href) ||
      /\b(?:entrar|entre para ver|log in|sign up|cadastre-se)\b/i.test(loginText),
  };
}
"""

PROFILE_MARK_CONTENT_JS = r"""
(handle) => {
  document.querySelectorAll("[data-tarrafa-ig-profile]").forEach(
    (el) => el.removeAttribute("data-tarrafa-ig-profile")
  );
  const mediaSelector = "a[href*='/p/'],a[href*='/reel/'],a[href*='/tv/']";
  const firstMedia = document.querySelector(mediaSelector);
  if (!firstMedia) return false;
  const wanted = String(handle || "").replace(/^@/, "").toLowerCase();
  let node = firstMedia;
  let chosen = null;
  while (node && node !== document.body) {
    const rect = node.getBoundingClientRect();
    const mediaCount = node.querySelectorAll?.(mediaSelector).length || 0;
    const text = (node.innerText || "").toLowerCase();
    if (rect.width >= 600 && mediaCount >= 3 && (!wanted || text.includes(wanted))) {
      chosen = node;
      break;
    }
    node = node.parentElement;
  }
  if (!chosen) return false;
  chosen.setAttribute("data-tarrafa-ig-profile", "1");
  for (const el of document.querySelectorAll("body *")) {
    const text = (el.innerText || "").trim();
    if (!/^Mensagens$/i.test(text)) continue;
    const style = getComputedStyle(el);
    if (style.position === "fixed") el.style.setProperty("visibility", "hidden", "important");
  }
  return true;
}
"""


def run_profile_inventory(args: argparse.Namespace, profile_url: str) -> int:
    """Coleta metadados públicos, print e links de mídia de um perfil IG."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERRO: playwright não instalado. Rode:\n"
            "  pip install -r requirements.txt\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 2

    from tarrafa.core.envelope import build_envelope

    out_path = Path(args.out).resolve()
    shot_path = (
        Path(args.profile_shot).resolve()
        if args.profile_shot
        else out_path.with_suffix(".png")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shot_path.parent.mkdir(parents=True, exist_ok=True)
    storage_state = args.storage_state

    print(f"[ig-profile] source={profile_url}")
    print(f"[ig-profile] out={out_path} shot={shot_path}")
    print(f"[ig-profile] storage_state={storage_state!r} headed={args.headed}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context_kwargs: dict[str, Any] = {
            "locale": "pt-BR",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 1000},
        }
        storage_loaded = bool(storage_state and Path(storage_state).is_file())
        if storage_loaded:
            context_kwargs["storage_state"] = storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT_MS)

        def _route_handler(route, request):
            if url_is_dangerous_auth_flow(request.url):
                print(
                    f"[ig-profile] BLOQUEADO fluxo OIDC/reset: {request.url[:120]}",
                    file=sys.stderr,
                )
                route.abort()
                return
            route.continue_()

        page.route("**/*", _route_handler)
        try:
            page.goto(profile_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2500)
            if args.max_posts > 0:
                try:
                    page.wait_for_selector(
                        "a[href*='/p/'],a[href*='/reel/'],a[href*='/tv/']",
                        state="attached",
                        timeout=10_000,
                    )
                except Exception:
                    # A ausência será registrada como lacuna abaixo; não inventar URL.
                    pass
        except Exception as exc:
            envelope = build_envelope(
                "ig-profile",
                source={"url": profile_url},
                errors=[f"navigation: {type(exc).__name__}: {exc}"],
                meta={"storage_state_used": storage_loaded},
            )
            write_json(out_path, envelope)
            browser.close()
            print(f"[ig-profile] goto falhou: {exc}", file=sys.stderr)
            return 3

        if url_is_dangerous_auth_flow(page.url):
            envelope = build_envelope(
                "ig-profile",
                source={"url": profile_url},
                errors=["Navegação caiu em fluxo proibido de password/reset ou Facebook OIDC."],
                meta={"storage_state_used": storage_loaded, "final_url": page.url},
            )
            write_json(out_path, envelope)
            browser.close()
            return 4

        handle = PROFILE_PATH_RE.fullmatch(urlsplit(profile_url).path).group(1)
        info = page.evaluate(PROFILE_EXTRACT_JS)
        login_wall = detect_login_wall_from_dom(info)
        screenshot_error: str | None = None
        try:
            marked = page.evaluate(PROFILE_MARK_CONTENT_JS, handle)
            profile_content = page.locator("[data-tarrafa-ig-profile]").first
            if marked and profile_content.count() and profile_content.is_visible():
                profile_content.screenshot(path=str(shot_path), type="png")
            else:
                page.screenshot(path=str(shot_path), full_page=False, type="png")
        except Exception as exc:
            screenshot_error = f"screenshot: {type(exc).__name__}: {exc}"

        media = instagram_media_urls(
            list(info.get("media_urls") or []),
            limit=args.max_posts,
        )
        reported_posts = instagram_reported_posts(
            info.get("description"),
            info.get("text_excerpt"),
        )
        item = {
            "kind": "instagram_profile",
            "handle": f"@{handle}",
            "profile_url": profile_url,
            "final_url": info.get("href") or page.url,
            "title": info.get("og_title") or info.get("title"),
            "description": info.get("description"),
            "image_url": info.get("image"),
            "text_excerpt": info.get("text_excerpt"),
            "media_urls": media,
            "media_count": len(media),
            "reported_posts": reported_posts,
            "login_wall": login_wall,
            "screenshot": str(shot_path) if screenshot_error is None else None,
        }
        errors = [screenshot_error] if screenshot_error else []
        if login_wall:
            errors.append("Login wall detectado; perfil e mídias não foram considerados coletados.")
        elif args.max_posts > 0 and reported_posts and not media:
            errors.append(
                "O perfil declara posts, mas a grade não expôs links após a espera; "
                "inventário de mídias incompleto."
            )
        envelope = build_envelope(
            "ig-profile",
            source={"url": profile_url},
            items=[item],
            meta={
                "storage_state_used": storage_loaded,
                "media_discovered": len(media),
                "login_wall": login_wall,
                "screenshot": str(shot_path) if screenshot_error is None else None,
            },
            errors=errors,
            notes=[
                "Inventário material-only do perfil e de links públicos de posts/reels.",
                "Não automatiza senha, Facebook OIDC nem contorna login wall.",
            ],
        )
        if args.save_storage and not login_wall:
            context.storage_state(path=args.save_storage)
        write_json(out_path, envelope)
        browser.close()

    print(
        f"[ig-profile] wrote {out_path} media={len(media)} "
        f"login_wall={login_wall} shot={shot_path if screenshot_error is None else 'erro'}"
    )
    if login_wall:
        return 5
    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Main scrape loop
# ---------------------------------------------------------------------------

def run_scrape(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "ERRO: playwright não instalado. Rode:\n"
            "  pip install -r requirements.txt\n"
            "  playwright install chromium",
            file=sys.stderr,
        )
        return 2

    source = args.url.strip()
    out_path = Path(args.out).resolve()
    stats_path = Path(args.stats).resolve() if args.stats else out_path.with_name("ig_scrape_stats.json")
    # Prefer case root stats if default relative
    if not args.stats:
        # write stats next to out, and also allow case-root copy via --stats
        stats_path = out_path.with_name("ig_scrape_stats.json")

    max_comments = args.max_comments
    expand_replies = args.expand_replies
    store = CommentStore(source_post=source)

    storage_state = args.storage_state
    save_storage = args.save_storage

    print(f"[scrape] source={source}")
    print(f"[scrape] out={out_path}")
    print(f"[scrape] storage_state={storage_state!r} save_storage={save_storage!r}")
    print(f"[scrape] max_comments={max_comments} expand_replies={expand_replies} headed={args.headed}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        context_kwargs: dict[str, Any] = {
            "locale": "pt-BR",
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "viewport": {"width": 1280, "height": 900},
        }
        if storage_state and Path(storage_state).is_file():
            context_kwargs["storage_state"] = storage_state

        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        page.set_default_timeout(PAGE_TIMEOUT_MS)

        # Block known FB OIDC navigation attempts (safety net)
        def _route_handler(route, request):
            url = request.url
            if url_is_dangerous_auth_flow(url):
                print(f"[scrape] BLOQUEADO fluxo OIDC/reset: {url[:120]}", file=sys.stderr)
                route.abort()
                return
            route.continue_()

        page.route("**/*", _route_handler)

        # Network intercept
        def on_response(response):
            try:
                url = response.url
                if url_is_dangerous_auth_flow(url):
                    print(f"[scrape] AVISO: URL de auth perigosa vista: {url[:140]}", file=sys.stderr)
                    return
                ct = response.headers.get("content-type", "")
                if response.status != 200:
                    return
                if not response_looks_like_comments(url, ct):
                    return
                # Only parse JSON bodies that might contain comments
                try:
                    data = response.json()
                except Exception:
                    return
                found: list[dict[str, Any]] = []
                _walk_comment_nodes(data, found)
                if found:
                    n = store.upsert_many(found, method="graphql")
                    if n:
                        print(f"[graphql] +{n} (total={store.count}) from {url[:90]}")
            except Exception as e:
                # never crash the page on intercept errors
                print(f"[graphql] intercept error: {e}", file=sys.stderr)

        page.on("response", on_response)

        # Navigate
        try:
            page.goto(source, wait_until="domcontentloaded")
        except Exception as e:
            print(f"[scrape] goto falhou: {e}", file=sys.stderr)
            browser.close()
            return 3

        page.wait_for_timeout(2000)

        # Abort if password-reset / FB OIDC landed
        if url_is_dangerous_auth_flow(page.url):
            print(
                "ERRO: navegação caiu em fluxo password/reset ou Facebook OIDC.\n"
                "NÃO automatize senha/FB. Feche e faça login NATIVO no Instagram:\n"
                f"  tarrafa ig --url https://www.instagram.com/accounts/login/ "
                f"--headed --save-storage {save_storage or 'storage_state.json'}\n"
                "Depois reexecute com --storage-state.",
                file=sys.stderr,
            )
            browser.close()
            return 4

        # Optional: only save storage after human login
        if save_storage and max_comments == 0:
            print(
                "[scrape] Modo login: faça login NATIVO no Instagram na janela aberta.\n"
                "  NÃO use 'Continuar com Facebook'. Quando o feed carregar, volte ao terminal e pressione Enter."
            )
            try:
                input("Pressione Enter após login bem-sucedido… ")
            except EOFError:
                page.wait_for_timeout(120_000)
            if url_is_dangerous_auth_flow(page.url):
                print("ERRO: ainda em fluxo de reset/OIDC. Abortando sem salvar storage.", file=sys.stderr)
                browser.close()
                return 4
            context.storage_state(path=save_storage)
            print(f"[scrape] storage salvo em {save_storage}")
            browser.close()
            return 0

        # Initial DOM harvest + login wall check
        dom_info = page.evaluate(DOM_EXTRACT_JS)
        if detect_login_wall_from_dom(dom_info) and not storage_state:
            print(
                "ERRO: login wall detectado (Entrar / Entre para ver).\n"
                "Reexecute em modo headed, faça login NATIVO IG e salve storage:\n"
                "  tarrafa ig --url https://www.instagram.com/accounts/login/ "
                f"--headed --save-storage {save_storage or 'storage_state.json'} --max-comments 0\n"
                "Depois:\n"
                f"  tarrafa ig --url {source} --out {out_path} "
                f"--storage-state {save_storage or 'storage_state.json'} --expand-replies",
                file=sys.stderr,
            )
            browser.close()
            return 5

        if dom_info.get("public_count") is not None:
            store.public_comment_count = dom_info["public_count"]
            print(f"[scrape] public_comment_count snapshot = {store.public_comment_count}")

        store.upsert_many(dom_info.get("comments") or [], method="dom")

        if max_comments == 0:
            # login-only already handled; nothing to load
            write_checkpoint(store, out_path, stats_path, 0)
            if save_storage:
                context.storage_state(path=save_storage)
            browser.close()
            return 0

        # --- Primary deep path: authenticated REST comments API -----------------
        # Live lesson (2026-07-24): has_more_comments is often false while
        # has_more_headload_comments + next_min_id still paginate. Force min_id.
        print("[scrape] tentando API v1 /media/{id}/comments/ (paginação min_id forçada)…")
        api_stats = page.evaluate(
            API_V1_PAGINATE_JS,
            {
                "source": source,
                "maxComments": max_comments,
                "expandReplies": bool(expand_replies),
            },
        )
        if api_stats and not api_stats.get("error"):
            if api_stats.get("public_comment_count") is not None:
                store.public_comment_count = api_stats["public_comment_count"]
            added = store.upsert_many(api_stats.get("comments") or [], method="api_v1")
            print(
                f"[api_v1] pages={api_stats.get('pages')} "
                f"top={api_stats.get('top_level')} children_parents={api_stats.get('parents_fetched')} "
                f"returned={api_stats.get('count')} upserted_new≈{added} "
                f"public={api_stats.get('public_comment_count')} "
                f"media_id={api_stats.get('media_id')}"
            )
            write_checkpoint(store, out_path, stats_path, api_stats.get("pages") or 0)
        else:
            print(f"[api_v1] indisponível: {api_stats} — seguindo DOM scroll")

        stagnant = 0
        round_i = 0
        last_count = store.count

        load_more_regexes = [p.pattern for p in LOAD_MORE_PATTERNS]
        replies_regexes = [p.pattern for p in VIEW_REPLIES_PATTERNS]

        # DOM loop as enrichment / fallback if API got little
        while store.count < max_comments and stagnant < STAGNANT_ROUNDS_STOP:
            round_i += 1
            if url_is_dangerous_auth_flow(page.url):
                print("ERRO: redirecionado para password/reset ou OIDC FB no meio da coleta.", file=sys.stderr)
                write_checkpoint(store, out_path, stats_path, round_i)
                browser.close()
                return 4

            # Click "Carregar mais comentários"
            clicked_more = page.evaluate(CLICK_BY_TEXT_JS, load_more_regexes)
            if clicked_more:
                page.wait_for_timeout(CLICK_PAUSE_MS + 400)

            # Expand replies (optional)
            if expand_replies:
                clicked_rep = page.evaluate(CLICK_BY_TEXT_JS, replies_regexes)
                if clicked_rep:
                    page.wait_for_timeout(CLICK_PAUSE_MS)

            # Scroll comments pane / page
            page.evaluate(
                """() => {
                  const dig = document.scrollingElement || document.documentElement;
                  window.scrollBy(0, Math.max(600, window.innerHeight * 0.8));
                  // also try nested scrollable comment lists
                  for (const el of document.querySelectorAll('div, ul, section')) {
                    const st = getComputedStyle(el);
                    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
                      el.scrollTop = Math.min(el.scrollTop + el.clientHeight * 0.9, el.scrollHeight);
                    }
                  }
                }"""
            )
            page.wait_for_timeout(SCROLL_PAUSE_MS)

            # DOM harvest
            dom_info = page.evaluate(DOM_EXTRACT_JS)
            if dom_info.get("public_count") is not None:
                store.public_comment_count = dom_info["public_count"]
            store.upsert_many(dom_info.get("comments") or [], method="dom")

            # stagnation
            if store.count <= last_count:
                stagnant += 1
            else:
                stagnant = 0
                last_count = store.count

            print(
                f"[round {round_i}] count={store.count} cLinks={len(store.clinks)} "
                f"stagnant={stagnant}/{STAGNANT_ROUNDS_STOP} "
                f"load_more_clicks={clicked_more} public={store.public_comment_count}"
            )

            if round_i % CHECKPOINT_EVERY == 0:
                write_checkpoint(store, out_path, stats_path, round_i)
                print(f"[checkpoint] saved {store.count} -> {out_path}")

            # Early stop if no load-more buttons and stagnant mid-way
            btn_texts = " | ".join(b.get("text", "") for b in (dom_info.get("buttons") or [])[:40])
            still_has_load_more = any(p.search(btn_texts) for p in LOAD_MORE_PATTERNS)
            if not still_has_load_more and stagnant >= max(3, STAGNANT_ROUNDS_STOP // 2):
                print("[scrape] sem 'Carregar mais' e contagem estável — plateau.")
                break

        # Final harvest
        dom_info = page.evaluate(DOM_EXTRACT_JS)
        if dom_info.get("public_count") is not None:
            store.public_comment_count = dom_info["public_count"]
        store.upsert_many(dom_info.get("comments") or [], method="dom")

        if save_storage:
            context.storage_state(path=save_storage)
            print(f"[scrape] storage atualizado em {save_storage}")

        write_checkpoint(store, out_path, stats_path, round_i)
        browser.close()

    payload = store.to_payload()
    print(
        f"[done] count={payload['count']} cLinks={payload['cLinks']} "
        f"with_id={payload['with_comment_id']} public={payload['public_comment_count']} "
        f"methods={payload['methods']}"
    )
    print(f"[done] wrote {out_path}")
    print(f"[done] stats {stats_path}")

    if payload["count"] == 0:
        print(
            "AVISO: 0 comentários capturados. Provável login wall ou seletor quebrado. "
            "Rode --headed com --storage-state válido.",
            file=sys.stderr,
        )
        return 6
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa ig",
        description=(
            "Coleta inventário de perfil ou comentários de post/reel do Instagram "
            "em JSON material-only."
        ),
    )
    ap.add_argument("--url", required=True, help="URL de perfil, post ou reel do Instagram")
    ap.add_argument(
        "--out",
        required=True,
        help="Output JSON path (object with comments[]; never a double-encoded string)",
    )
    ap.add_argument(
        "--max-comments",
        type=int,
        default=DEFAULT_MAX,
        help="Stop after N unique comments (0 = login-only / save storage)",
    )
    ap.add_argument(
        "--headed",
        action="store_true",
        help="Show browser window (required for first login)",
    )
    ap.add_argument(
        "--storage-state",
        default=None,
        help="Path to Playwright storage_state.json (logged-in session)",
    )
    ap.add_argument(
        "--save-storage",
        default=None,
        help="Write storage_state after successful native login",
    )
    ap.add_argument(
        "--expand-replies",
        action="store_true",
        help="Also fetch threaded replies (child_comments API + UI expand)",
    )
    ap.add_argument(
        "--stats",
        default=None,
        help="Path for stats JSON (default: next to --out as ig_scrape_stats.json)",
    )
    ap.add_argument(
        "--max-posts",
        type=int,
        default=12,
        help="Em URL de perfil, máximo de links recentes inventariados (padrão: 12)",
    )
    ap.add_argument(
        "--profile-shot",
        default=None,
        help="Em URL de perfil, caminho do PNG (padrão: mesmo nome de --out)",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.max_posts < 0 or args.max_posts > 100:
        print("ig: --max-posts deve estar entre 0 e 100", file=sys.stderr)
        return 2
    profile_url = instagram_profile_url(args.url)
    if profile_url:
        return run_profile_inventory(args, profile_url)
    if not shortcode_from_url(args.url) and args.max_comments != 0:
        print(
            "ig: --url deve apontar para perfil, post, reel ou TV do Instagram",
            file=sys.stderr,
        )
        return 2
    return run_scrape(args)


if __name__ == "__main__":
    sys.exit(main())
