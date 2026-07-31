# -*- coding: utf-8 -*-
"""
tarrafa album — compile shots/frames into print-ready HTML (estilo inventário).

By default images are **embedded** (base64 data URIs) so the HTML is a single
shareable file — no local folder / backend required.

  tarrafa album --dir ./shots --out album.html
  tarrafa album --dir ./shots --out album.html --no-embed   # relative paths only
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.media import file_to_data_uri
from tarrafa.core.run import register_artifact
from tarrafa.core.writers import utc_now_iso, write_json
from tarrafa.templates.album_html import render_album


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def collect_items_from_dir(directory: Path) -> list[dict[str, Any]]:
    """Discover shot/video envelopes and image files."""
    items: list[dict[str, Any]] = []
    seen_images: set[str] = set()

    for jp in sorted(directory.glob("*.json")):
        if jp.name.endswith(".frames.json") or jp.name in ("manifest.json", "album_meta.json"):
            continue
        if jp.name.startswith("album_") or jp.stem.endswith("_album"):
            continue
        data = _load_json(jp)
        if not data:
            continue
        tool = data.get("tool")
        if tool in ("album", "site", "feed"):
            continue
        for raw in data.get("items") or []:
            if tool == "shot" or raw.get("kind") == "shot":
                img = raw.get("image")
                if img and (directory / img).is_file():
                    items.append(
                        {
                            "id": raw.get("id") or jp.stem,
                            "caption": raw.get("caption") or raw.get("title") or img,
                            "url": raw.get("final_url") or raw.get("url") or (data.get("source") or {}).get("url"),
                            "collected_at": raw.get("collected_at") or data.get("collected_at"),
                            "image": img,
                            "kind": "shot",
                            "notes": [],
                        }
                    )
                    seen_images.add(img)
            elif tool == "video" or raw.get("kind") == "video":
                frames = raw.get("frames") or []
                if frames:
                    for fi, fr in enumerate(frames, 1):
                        img = fr.get("image")
                        if img and (directory / img).is_file():
                            items.append(
                                {
                                    "id": f"{raw.get('id') or jp.stem}_F{fi:02d}",
                                    "caption": raw.get("caption") or raw.get("title") or f"Frame {fi}",
                                    "url": raw.get("final_url") or raw.get("url"),
                                    "collected_at": raw.get("collected_at") or data.get("collected_at"),
                                    "image": img,
                                    "kind": "frame",
                                    "notes": [
                                        f"Vídeo-pai: {raw.get('id')}",
                                        f"Título: {raw.get('title')}",
                                    ],
                                }
                            )
                            seen_images.add(img)
                elif raw.get("image") and (directory / raw["image"]).is_file():
                    img = raw["image"]
                    items.append(
                        {
                            "id": raw.get("id") or jp.stem,
                            "caption": raw.get("caption") or raw.get("title"),
                            "url": raw.get("url"),
                            "collected_at": data.get("collected_at"),
                            "image": img,
                            "kind": "video",
                            "notes": [],
                        }
                    )
                    seen_images.add(img)

    for png in sorted(directory.glob("*.png")):
        if png.name in seen_images:
            continue
        if png.name.startswith("_"):
            continue
        items.append(
            {
                "id": png.stem,
                "caption": png.name,
                "url": "",
                "collected_at": "",
                "image": png.name,
                "kind": "image",
                "notes": ["Arquivo de imagem sem envelope JSON associado."],
            }
        )
    return items


def collect_items_from_manifest(manifest: dict[str, Any], base_dir: Path) -> list[dict[str, Any]]:
    items = []
    for raw in manifest.get("items") or []:
        img = raw.get("image") or raw.get("file")
        items.append(
            {
                "id": raw.get("id") or Path(str(img or "item")).stem,
                "caption": raw.get("caption") or raw.get("title") or "",
                "url": raw.get("url") or "",
                "collected_at": raw.get("collected_at") or "",
                "image": img,
                "kind": raw.get("kind") or "shot",
                "notes": raw.get("notes") or [],
            }
        )
    return items


def _resolve_image_path(item: dict[str, Any], base: Path | None) -> Path | None:
    img = item.get("image") or item.get("file")
    if not img:
        return None
    p = Path(img)
    if p.is_file():
        return p
    if base and (base / img).is_file():
        return base / img
    return None


def embed_items(items: list[dict[str, Any]], base: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach image_src data URIs. Returns (items, stats)."""
    stats = {"embedded": 0, "missing": 0, "bytes_raw": 0, "errors": []}
    out: list[dict[str, Any]] = []
    for it in items:
        row = dict(it)
        path = _resolve_image_path(it, base)
        if path is None:
            stats["missing"] += 1
            row["image_src"] = it.get("image") or ""
            out.append(row)
            continue
        try:
            raw_len = path.stat().st_size
            stats["bytes_raw"] += raw_len
            row["image_src"] = file_to_data_uri(path)
            row["image_file"] = path.name
            stats["embedded"] += 1
        except Exception as e:
            stats["errors"].append(f"{path.name}: {e}")
            row["image_src"] = path.name
        out.append(row)
    return out, stats


def build_album(
    *,
    directory: Path | None = None,
    manifest_path: Path | None = None,
    out_html: Path,
    title: str | None = None,
    kicker: str | None = None,
    meta_lines: list[str] | None = None,
    footer: str | None = None,
    embed: bool = True,
) -> dict[str, Any]:
    manifest = None
    base = directory
    if manifest_path:
        manifest = _load_json(manifest_path) or {}
        base = base or manifest_path.parent
        items = collect_items_from_manifest(manifest, base)
        title = title or manifest.get("title")
        kicker = kicker or manifest.get("kicker")
        if not meta_lines and manifest.get("meta"):
            meta_lines = list(manifest["meta"])
    else:
        if not directory:
            raise ValueError("directory or manifest required")
        items = collect_items_from_dir(directory)
        base = directory

    embed_stats: dict[str, Any] = {"embedded": 0, "bytes_raw": 0}
    if embed:
        items, embed_stats = embed_items(items, base)
    else:
        for it in items:
            it["image_src"] = it.get("image") or ""

    title = title or "Álbum de capturas visuais"
    kicker = kicker or "Inventário visual · Fontes abertas"
    meta_lines = list(meta_lines or [])
    if not meta_lines:
        meta_lines = [
            f"Itens: {len(items)}",
            f"Gerado em: {utc_now_iso()}",
        ]
    # annotate embed mode for the reader
    if embed:
        mb = (embed_stats.get("bytes_raw") or 0) / (1024 * 1024)
        meta_lines = meta_lines + [
            f"Formato: HTML autocontido (imagens embutidas; ~{mb:.1f} MB de mídia na origem)",
        ]
    else:
        meta_lines = meta_lines + ["Formato: HTML com imagens relativas (pasta local)"]

    html = render_album(
        title=title,
        kicker=kicker,
        meta_lines=meta_lines,
        items=items,
        footer=footer,
    )
    out_html = Path(out_html)
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")
    register_artifact(out_html, kind="html")
    html_bytes = out_html.stat().st_size

    # index without huge data URIs
    index_items = []
    for it in items:
        slim = {k: v for k, v in it.items() if k != "image_src"}
        if embed and it.get("image_file"):
            slim["embedded"] = True
            slim["image_file"] = it.get("image_file")
        index_items.append(slim)

    index = {
        "tool": "album",
        "collected_at": utc_now_iso(),
        "title": title,
        "html": str(out_html.resolve()),
        "count": len(items),
        "embed": embed,
        "html_bytes": html_bytes,
        "media_bytes_raw": embed_stats.get("bytes_raw"),
        "items": index_items,
    }
    write_json(out_html.with_suffix(".json"), index)
    return index


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa album",
        description="Compile shot/video captures into print-ready HTML album (embedded by default).",
    )
    ap.add_argument("--dir", dest="directory", default=None, help="Directory with PNG+JSON captures")
    ap.add_argument("--manifest", default=None, help="Optional manifest.json")
    ap.add_argument("--out", required=True, help="Output HTML path")
    ap.add_argument("--title", default=None)
    ap.add_argument("--kicker", default=None)
    ap.add_argument(
        "--meta",
        action="append",
        default=[],
        help="Meta line (repeatable). Use 'Label: value' format.",
    )
    ap.add_argument("--footer", default=None)
    ap.add_argument(
        "--embed",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Embed images as base64 data URIs (default: true). Use --no-embed for relative paths.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    if not args.directory and not args.manifest:
        print("album: provide --dir and/or --manifest", file=sys.stderr)
        return 2
    try:
        index = build_album(
            directory=Path(args.directory) if args.directory else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
            out_html=Path(args.out),
            title=args.title,
            kicker=args.kicker,
            meta_lines=args.meta or None,
            footer=args.footer,
            embed=args.embed,
        )
    except Exception as e:
        print(f"album: error: {e}", file=sys.stderr)
        return 2
    mb = (index.get("html_bytes") or 0) / (1024 * 1024)
    print(
        f"album: wrote {args.out}  items={index.get('count')}  "
        f"embed={index.get('embed')}  size={mb:.1f} MB"
    )
    if index.get("count", 0) == 0:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
