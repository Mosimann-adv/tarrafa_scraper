# -*- coding: utf-8 -*-
"""
tarrafa dossier — ficha HTML de pessoa (estilo perfil / overview).

Monta inventário a partir de arquivos e fatos já capturados.
Não pesquisa web, não inventa biografia, não classifica.

  tarrafa dossier --title "Nome" --out perfil.html \\
    --avatar foto.png \\
    --meta "Nome: Fulano" --meta "Cidade: X" \\
    --fact "Achado com fonte citada" \\
    --source "Lattes | http://lattes... | atualizado em …" \\
    --shot "lattes=shots/lattes.png::Currículo Lattes" \\
    --gap "O que não foi validado"

  tarrafa dossier --manifest dossier.json --out perfil.html
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import file_to_data_uri
from tarrafa.core.run import register_artifact
from tarrafa.core.writers import utc_now_iso, write_json
from tarrafa.templates.dossier_html import render_dossier


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def parse_meta(raw: str) -> tuple[str, str]:
    if ":" in raw:
        k, v = raw.split(":", 1)
        return k.strip(), v.strip()
    return raw.strip(), ""


def parse_shot_spec(raw: str) -> dict[str, str]:
    """
    Formats:
      path/to.png
      id=path/to.png
      id=path/to.png::caption text
      path/to.png::caption text
    """
    caption = ""
    body = raw
    if "::" in raw:
        body, caption = raw.split("::", 1)
        caption = caption.strip()
    body = body.strip()
    if "=" in body and not Path(body).is_file():
        left, right = body.split("=", 1)
        if left and right and ("/" in right or "\\" in right or Path(right).suffix):
            return {"id": left.strip(), "path": right.strip(), "caption": caption}
    return {
        "id": Path(body).stem,
        "path": body,
        "caption": caption,
    }


def parse_source_spec(raw: str) -> dict[str, str]:
    """
    Formats:
      Label | URL | note
      Label | URL
      Label: https://...
    """
    raw = (raw or "").strip()
    if "|" in raw:
        parts = [p.strip() for p in raw.split("|")]
        label = parts[0] if parts else "Fonte"
        url = parts[1] if len(parts) > 1 else ""
        note = parts[2] if len(parts) > 2 else ""
        return {"label": label, "url": url, "note": note}
    m = re.match(r"^(?P<label>.+?):\s*(?P<url>https?://\S+)(?:\s*[—\-–|]\s*(?P<note>.+))?$", raw)
    if m:
        return {
            "label": m.group("label").strip(),
            "url": m.group("url").strip(),
            "note": (m.group("note") or "").strip(),
        }
    return {"label": raw, "url": "", "note": ""}

def parse_timeline_spec(raw: str) -> dict[str, str]:
    """when | text   or   when: text"""
    raw = (raw or "").strip()
    if "|" in raw:
        when, text = raw.split("|", 1)
        return {"when": when.strip(), "text": text.strip()}
    if ":" in raw:
        when, text = raw.split(":", 1)
        return {"when": when.strip(), "text": text.strip()}
    return {"when": "", "text": raw}


def resolve_path(p: str | Path, base: Path | None) -> Path | None:
    path = Path(p)
    if path.is_file():
        return path
    if base and (base / p).is_file():
        return base / p
    return None


def embed_or_path(path: Path | None, *, embed: bool) -> str:
    if path is None:
        return ""
    if embed:
        return file_to_data_uri(path)
    return path.name


def _merge_manifest_list(
    cli_val: list[Any] | None,
    manifest: dict[str, Any] | None,
    key: str,
) -> list[Any]:
    if cli_val:
        return list(cli_val)
    if manifest and manifest.get(key):
        return list(manifest[key])
    return []


def build_dossier(
    *,
    title: str,
    out_html: Path,
    subtitle: str = "",
    kicker: str = "Dossiê · material público",
    avatar: str | Path | None = None,
    meta: list[str] | None = None,
    facts: list[str] | None = None,
    stats: list[Any] | None = None,
    sources: list[Any] | None = None,
    sections: list[dict[str, Any]] | None = None,
    shots: list[dict[str, Any]] | None = None,
    timeline: list[Any] | None = None,
    gaps: list[str] | None = None,
    notes: list[str] | None = None,
    chips: list[str] | None = None,
    quote: str = "",
    intro: str = "",
    method: str = "",
    footer: str | None = None,
    embed: bool = True,
    base_dir: Path | None = None,
    manifest: dict[str, Any] | None = None,
    screen_bar: str | None = None,
) -> dict[str, Any]:
    """
    Build HTML + envelope. Prefer manifest for rich sections.
    """
    if manifest:
        title = title or manifest.get("title") or "Dossiê"
        subtitle = subtitle or manifest.get("subtitle") or ""
        kicker = manifest.get("kicker") or kicker
        avatar = avatar or manifest.get("avatar")
        if not meta and manifest.get("meta"):
            meta = list(manifest["meta"])
        if not facts and manifest.get("facts"):
            facts = list(manifest["facts"])
        if not stats and manifest.get("stats"):
            stats = list(manifest["stats"])
        if not sources and manifest.get("sources"):
            sources = list(manifest["sources"])
        if not sections and manifest.get("sections"):
            sections = list(manifest["sections"])
        if not shots and manifest.get("shots"):
            shots = list(manifest["shots"])
        if not timeline and manifest.get("timeline"):
            timeline = list(manifest["timeline"])
        if not gaps and manifest.get("gaps"):
            gaps = list(manifest["gaps"])
        if not notes and manifest.get("notes"):
            notes = list(manifest["notes"])
        if not chips and manifest.get("chips"):
            chips = list(manifest["chips"])
        quote = quote or manifest.get("quote") or ""
        intro = intro or manifest.get("intro") or ""
        method = method or manifest.get("method") or ""
        footer = footer or manifest.get("footer")
        screen_bar = screen_bar or manifest.get("screen_bar")
        base_dir = base_dir or Path(manifest.get("base_dir") or out_html.parent)

    title = title or "Dossiê"
    meta = list(meta or [])
    facts = list(facts or [])
    stats_raw = list(stats or [])
    sources_raw = list(sources or [])
    sections = list(sections or [])
    shots = list(shots or [])
    timeline_raw = list(timeline or [])
    gaps = list(gaps or [])
    notes = list(notes or [])
    chips = list(chips or [])
    base = base_dir or out_html.parent

    meta_rows = [parse_meta(m) if isinstance(m, str) else (str(m[0]), str(m[1])) for m in meta]

    # normalize stats
    stats_rows: list[dict[str, str]] = []
    for st in stats_raw:
        if isinstance(st, dict):
            stats_rows.append(
                {
                    "label": str(st.get("label") or st.get("k") or ""),
                    "value": str(st.get("value") or st.get("v") or ""),
                }
            )
        elif isinstance(st, (list, tuple)) and len(st) >= 2:
            stats_rows.append({"label": str(st[0]), "value": str(st[1])})
        elif isinstance(st, str) and ":" in st:
            k, v = st.split(":", 1)
            stats_rows.append({"label": k.strip(), "value": v.strip()})

    # normalize sources
    source_rows: list[dict[str, str]] = []
    for s in sources_raw:
        if isinstance(s, str):
            source_rows.append(parse_source_spec(s))
        elif isinstance(s, dict):
            source_rows.append(
                {
                    "label": str(s.get("label") or s.get("name") or "Fonte"),
                    "url": str(s.get("url") or ""),
                    "note": str(s.get("note") or ""),
                }
            )

    # normalize timeline
    timeline_rows: list[dict[str, str]] = []
    for t in timeline_raw:
        if isinstance(t, str):
            timeline_rows.append(parse_timeline_spec(t))
        elif isinstance(t, dict):
            timeline_rows.append(
                {
                    "when": str(t.get("when") or t.get("year") or ""),
                    "text": str(t.get("text") or t.get("body") or ""),
                }
            )

    avatar_path = resolve_path(avatar, base) if avatar else None
    avatar_src = embed_or_path(avatar_path, embed=embed) if avatar_path else (
        str(avatar) if avatar and not embed else ""
    )

    # optional image paths inside sections
    for sec in sections:
        img_path = sec.get("image") or sec.get("image_path") or ""
        if img_path and not sec.get("image_src"):
            p = resolve_path(img_path, base)
            if p:
                try:
                    sec["image_src"] = file_to_data_uri(p) if embed else p.name
                except Exception:
                    sec["image_src"] = p.name

    shot_rows: list[dict[str, Any]] = []
    embed_stats = {"embedded": 0, "missing": 0, "bytes_raw": 0}
    for i, sh in enumerate(shots, 1):
        if isinstance(sh, str):
            sh = parse_shot_spec(sh)
        sid = sh.get("id") or f"shot_{i:02d}"
        path_raw = sh.get("path") or sh.get("image") or sh.get("file") or ""
        path = resolve_path(path_raw, base) if path_raw else None
        if path is None:
            embed_stats["missing"] += 1
            img_src = ""
        else:
            if embed:
                try:
                    embed_stats["bytes_raw"] += path.stat().st_size
                    img_src = file_to_data_uri(path)
                    embed_stats["embedded"] += 1
                except Exception:
                    embed_stats["missing"] += 1
                    img_src = path.name
            else:
                img_src = path.name
        shot_rows.append(
            {
                "id": sid,
                "caption": sh.get("caption") or sh.get("title") or sid,
                "url": sh.get("url") or "",
                "collected_at": sh.get("collected_at") or "",
                "kind": sh.get("kind") or "shot",
                "contain": bool(sh.get("contain")),
                "image_src": img_src,
                "image_file": path.name if path else path_raw,
            }
        )

    collected = utc_now_iso()
    # human-friendly date for meta bar (YYYY-MM-DD)
    collected_display = collected[:10] if collected else ""

    html = render_dossier(
        title=title,
        subtitle=subtitle,
        kicker=kicker,
        avatar_src=avatar_src or None,
        chips=chips,
        meta_rows=meta_rows,
        facts=facts,
        stats=stats_rows,
        sources=source_rows,        sections=sections,
        shots=shot_rows,
        timeline=timeline_rows,
        gaps=gaps,
        notes=notes,
        quote=quote,
        intro=intro,
        footer=footer,
        collected_at=collected_display,
        method=method,
        screen_bar_label=screen_bar,
    )

    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    register_artifact(out_html, kind="html")

    envelope = build_envelope(
        "dossier",
        source=str(out_html),
        items=[
            {
                "kind": "dossier_html",
                "path": str(out_html),
                "title": title,
                "shots": len(shot_rows),
                "meta_count": len(meta_rows),
                "facts": len(facts),
                "sources": len(source_rows),
                "sections": len(sections),
                "gaps": len(gaps),
                "embed": embed,
                "avatar": bool(avatar_path),
                "bytes_html": out_html.stat().st_size,
                "embed_stats": embed_stats,
            }
        ],
        meta={
            "title": title,
            "subtitle": subtitle,
            "kicker": kicker,
            "collected_at": collected,
            "embed": embed,
            "theme": "perfil",
        },
        notes=[
            "Material-only ficha HTML (estilo perfil). No web search, no biography invention.",
            "Images embedded as base64 when --embed (default).",
            "Prefer selective shots; inventory sources/facts even without prints.",
        ],
    )
    return envelope


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        prog="tarrafa dossier",
        description=(
            "Ficha HTML de pessoa (estilo perfil): avatar, metas, achados, fontes, "
            "seções e prints seletivos (embed base64)."
        ),
    )
    ap.add_argument("--title", default=None, help="Título da ficha")
    ap.add_argument("--subtitle", default="", help="Subtítulo")
    ap.add_argument(
        "--kicker",
        default="Dossiê · material público",
    )
    ap.add_argument(
        "--screen-bar",
        default=None,
        help="Texto da barra superior (tela); some na impressão",
    )
    ap.add_argument("--out", required=True, help="Caminho do HTML de saída")
    ap.add_argument("--avatar", default=None, help="Foto de identificação (png/jpg)")
    ap.add_argument(
        "--meta",
        action="append",
        default=[],
        help='Linha "Campo: valor" (repetível) — identificação',
    )
    ap.add_argument(
        "--fact",
        action="append",
        default=[],
        dest="facts",
        help="Achado factual com fonte citada no texto (repetível)",
    )
    ap.add_argument(
        "--source",
        action="append",
        default=[],
        dest="sources",
        help='Fonte: "Label | URL | nota" (repetível)',
    )
    ap.add_argument(
        "--timeline",
        action="append",
        default=[],
        dest="timeline",
        help='Marco: "quando | texto" (repetível)',
    )
    ap.add_argument(
        "--quote",
        default="",
        help="Citação / resumo em destaque na identificação",
    )
    ap.add_argument(
        "--intro",
        default="",
        help="Parágrafo introdutório (método / escopo)",
    )
    ap.add_argument(
        "--method",
        default="",
        help="Texto curto do método de coleta (barra meta)",
    )
    ap.add_argument(
        "--shot",
        action="append",
        default=[],
        dest="shots",
        help='Print seletivo: "id=path" ou "id=path::legenda" (repetível)',
    )
    ap.add_argument(
        "--gap",
        action="append",
        default=[],
        dest="gaps",
        help="Lacuna registrada (repetível)",
    )
    ap.add_argument(
        "--note",
        action="append",
        default=[],
        dest="notes",
        help="Nota de coleta (repetível)",
    )
    ap.add_argument(
        "--chip",
        action="append",
        default=[],
        dest="chips",
        help="Chip no header (repetível)",
    )
    ap.add_argument("--footer", default=None)
    ap.add_argument(
        "--manifest",
        default=None,
        help="JSON de entrada (seções ricas, facts, sources, shots…)",
    )
    ap.add_argument(
        "--base-dir",
        default=None,
        help="Base para paths relativos (default: pasta do --out)",
    )
    ap.add_argument(
        "--envelope-out",
        default=None,
        help="Opcional: gravar envelope JSON do job",
    )
    ap.add_argument("--embed", action="store_true", default=True)
    ap.add_argument("--no-embed", action="store_false", dest="embed")

    args = ap.parse_args(argv)
    out_html = Path(args.out)
    base = Path(args.base_dir) if args.base_dir else out_html.parent
    manifest = None
    if args.manifest:
        manifest = _load_json(Path(args.manifest))
        if not manifest:
            print(f"dossier: cannot read manifest {args.manifest}", file=sys.stderr)
            return 2

    title = args.title or (manifest or {}).get("title") or "Dossiê"
    shot_specs = [parse_shot_spec(s) for s in (args.shots or [])]
    source_specs = [parse_source_spec(s) for s in (args.sources or [])]
    timeline_specs = [parse_timeline_spec(s) for s in (args.timeline or [])]

    try:
        envelope = build_dossier(
            title=title,
            out_html=out_html,
            subtitle=args.subtitle or (manifest or {}).get("subtitle") or "",
            kicker=args.kicker,
            avatar=args.avatar,
            meta=args.meta or None,
            facts=args.facts or None,
            sources=source_specs or None,
            shots=shot_specs or None,
            timeline=timeline_specs or None,
            gaps=args.gaps or None,
            notes=args.notes or None,
            chips=args.chips or None,
            quote=args.quote or "",
            intro=args.intro or "",
            method=args.method or "",
            footer=args.footer,
            embed=args.embed,
            base_dir=base,
            manifest=manifest,
            screen_bar=args.screen_bar,
        )
    except Exception as e:
        print(f"dossier: error: {e}", file=sys.stderr)
        return 2

    item = (envelope.get("items") or [{}])[0]
    print(
        f"dossier: wrote {out_html}  "
        f"shots={item.get('shots')} meta={item.get('meta_count')} "
        f"facts={item.get('facts')} sources={item.get('sources')} "
        f"gaps={item.get('gaps')} bytes={item.get('bytes_html')} "
        f"embed={item.get('embed')}"
    )

    env_path = Path(args.envelope_out) if args.envelope_out else out_html.with_suffix(".dossier.json")
    write_json(env_path, envelope)
    print(f"dossier: envelope {env_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
