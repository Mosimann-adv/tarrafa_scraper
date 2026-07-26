# -*- coding: utf-8 -*-
"""
tarrafa video — audiovisual material capture (meta + frames + optional download).

  tarrafa video --url URL --out-dir ./vid --id INF01
  tarrafa video --url URL --out-dir ./vid --download --frames 5
  tarrafa video --url URL --out-dir ./vid --meta-only

No speech-to-text in v1 (Whisper optional later).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tarrafa.core.browser_util import chromium_page, goto_settled
from tarrafa.core.envelope import build_envelope
from tarrafa.core.media import (
    ensure_dir,
    ffmpeg_extract_frames,
    file_sha256,
    has_ffmpeg,
    has_yt_dlp,
    id_from_url,
    run_cmd,
    which,
)
from tarrafa.core.writers import utc_now_iso, write_json


def _page_video_meta(page: Any) -> dict[str, Any]:
    """Best-effort metadata from DOM / OG tags / video element."""
    return page.evaluate(
        """() => {
      const og = (p) => {
        const el = document.querySelector(`meta[property="${p}"]`) || document.querySelector(`meta[name="${p}"]`);
        return el ? el.getAttribute('content') : null;
      };
      const videos = [...document.querySelectorAll('video')].map(v => ({
        src: v.currentSrc || v.src || null,
        duration: Number.isFinite(v.duration) ? v.duration : null,
        width: v.videoWidth || null,
        height: v.videoHeight || null,
      }));
      const sources = [...document.querySelectorAll('video source')].map(s => s.src).filter(Boolean);
      return {
        title: document.title || null,
        og_title: og('og:title'),
        og_description: og('og:description'),
        og_video: og('og:video') || og('og:video:secure_url') || og('og:video:url'),
        og_image: og('og:image'),
        description: og('description'),
        videos,
        sources,
        href: location.href,
      };
    }"""
    )


def _download_yt_dlp(url: str, out_dir: Path, stem: str) -> dict[str, Any]:
    out_tmpl = str(out_dir / f"{stem}.%(ext)s")
    if which("yt-dlp"):
        argv = [
            "yt-dlp",
            "-o",
            out_tmpl,
            "--no-playlist",
            "--write-info-json",
            "--write-thumbnail",
            "--restrict-filenames",
            url,
        ]
        r = run_cmd(argv, timeout=600)
    else:
        try:
            import yt_dlp
        except ImportError as e:
            return {"ok": False, "error": f"yt-dlp not installed: {e}", "path": None}
        ydl_opts = {
            "outtmpl": out_tmpl,
            "noplaylist": True,
            "writethumbnail": True,
            "writeinfojson": True,
            "restrictfilenames": True,
            "quiet": True,
            "no_warnings": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            r = {"ok": True, "stderr": "", "stdout": ""}
        except Exception as e:
            return {"ok": False, "error": str(e), "path": None}

    if not r.get("ok") and r.get("error"):
        return r
    if not r.get("ok"):
        return {"ok": False, "error": r.get("stderr") or "yt-dlp failed", "path": None}

    # find downloaded media
    candidates = []
    for ext in ("mp4", "webm", "mkv", "mov", "m4a"):
        candidates.extend(out_dir.glob(f"{stem}.{ext}"))
        candidates.extend(out_dir.glob(f"{stem}.*.{ext}"))
    # also any new media-ish files
    if not candidates:
        candidates = [
            p
            for p in out_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"} and stem in p.stem
        ]
    path = sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
    media = path[0] if path else None
    return {"ok": bool(media), "path": media, "error": None if media else "no media file found after yt-dlp"}


def _playwright_frames(page: Any, out_dir: Path, stem: str, count: int) -> list[Path]:
    """Screenshot the first video element at progressive timestamps if possible."""
    ensure_dir(out_dir)
    paths: list[Path] = []
    try:
        has_v = page.evaluate("() => !!document.querySelector('video')")
        if not has_v:
            # page screenshot as single visual proxy
            p = out_dir / f"{stem}_page.png"
            page.screenshot(path=str(p), full_page=False, type="png")
            return [p] if p.is_file() else []
        page.evaluate(
            """async () => {
              const v = document.querySelector('video');
              if (!v) return;
              try { v.muted = true; await v.play(); } catch(e) {}
            }"""
        )
        page.wait_for_timeout(500)
        duration = page.evaluate(
            """() => {
              const v = document.querySelector('video');
              return v && Number.isFinite(v.duration) ? v.duration : 0;
            }"""
        ) or 0
        for i in range(max(1, count)):
            t = 0.0
            if duration and count > 1:
                t = (duration * i) / (count - 1)
                if i == count - 1:
                    t = max(0.0, duration - 0.2)
            page.evaluate(
                """(t) => {
                  const v = document.querySelector('video');
                  if (!v) return;
                  v.pause();
                  v.currentTime = t;
                }""",
                t,
            )
            page.wait_for_timeout(350)
            out = out_dir / f"{stem}_frame_{i:02d}.png"
            # element screenshot if possible
            try:
                el = page.query_selector("video")
                if el:
                    el.screenshot(path=str(out), type="png")
                else:
                    page.screenshot(path=str(out), type="png")
            except Exception:
                page.screenshot(path=str(out), type="png")
            if out.is_file():
                paths.append(out)
    except Exception:
        pass
    return paths


def capture_video(
    url: str,
    out_dir: Path,
    *,
    item_id: str | None = None,
    download: bool = False,
    frames: int = 5,
    meta_only: bool = False,
    timeout: float = 90.0,
    wait_ms: int = 2000,
    storage_state: str | None = None,
    headed: bool = False,
    caption: str | None = None,
) -> dict[str, Any]:
    collected_at = utc_now_iso()
    out_dir = ensure_dir(out_dir)
    iid = item_id or id_from_url(url, prefix="vid_")
    json_path = out_dir / f"{iid}.json"
    errors: list[str] = []
    methods: list[str] = []
    meta_dom: dict[str, Any] = {}
    final_url = url
    frame_paths: list[Path] = []
    media_path: Path | None = None

    # Browser pass for meta (+ optional frames if no download)
    try:
        with chromium_page(
            storage_state=storage_state,
            headless=not headed,
            width=1280,
            height=900,
            device_scale_factor=2.0,
        ) as (_p, _b, _ctx, page):
            page.set_default_timeout(int(timeout * 1000))
            resp = goto_settled(page, url, timeout_ms=int(timeout * 1000), wait_ms=wait_ms)
            final_url = page.url
            status = resp.status if resp else None
            meta_dom = _page_video_meta(page) or {}
            methods.append("browser_meta")
            if not meta_only and not download and frames > 0:
                frame_paths = _playwright_frames(page, out_dir, iid, frames)
                if frame_paths:
                    methods.append("browser_frames")
    except Exception as e:
        errors.append(f"browser: {type(e).__name__}: {e}")
        status = None

    if download and not meta_only:
        if not has_yt_dlp():
            errors.append("yt-dlp not available (pip install yt-dlp or install yt-dlp CLI)")
        else:
            dl = _download_yt_dlp(url, out_dir, iid)
            if dl.get("ok") and dl.get("path"):
                media_path = Path(dl["path"])
                methods.append("yt_dlp")
            else:
                errors.append(f"download: {dl.get('error') or 'failed'}")

    if media_path and media_path.is_file() and frames > 0 and not meta_only:
        if has_ffmpeg():
            ff_frames = ffmpeg_extract_frames(media_path, out_dir, count=frames, prefix=f"{iid}_frame")
            if ff_frames:
                frame_paths = ff_frames
                methods.append("ffmpeg_frames")
        elif not frame_paths:
            errors.append("ffmpeg not found; could not extract frames from downloaded file")

    frame_items = []
    for fp in frame_paths:
        frame_items.append(
            {
                "id": f"{iid}_{fp.stem}",
                "kind": "frame",
                "image": fp.name,
                "path": str(fp.resolve()),
                "sha256": file_sha256(fp),
                "bytes": fp.stat().st_size,
                "parent_id": iid,
            }
        )

    media_item = None
    if media_path and media_path.is_file():
        media_item = {
            "id": iid,
            "kind": "video_file",
            "file": media_path.name,
            "path": str(media_path.resolve()),
            "sha256": file_sha256(media_path),
            "bytes": media_path.stat().st_size,
            "ext": media_path.suffix.lower(),
        }

    title = (
        caption
        or meta_dom.get("og_title")
        or meta_dom.get("title")
        or url
    )
    item = {
        "id": iid,
        "kind": "video",
        "url": url,
        "final_url": final_url,
        "title": title,
        "caption": caption or meta_dom.get("og_description") or meta_dom.get("description") or title,
        "og": {
            "title": meta_dom.get("og_title"),
            "description": meta_dom.get("og_description"),
            "video": meta_dom.get("og_video"),
            "image": meta_dom.get("og_image"),
        },
        "dom_videos": meta_dom.get("videos") or [],
        "media": media_item,
        "frames": frame_items,
        "collected_at": collected_at,
        "status": status,
    }
    # primary image for album = first frame or og screenshot not available
    if frame_items:
        item["image"] = frame_items[0]["image"]

    env = build_envelope(
        "video",
        source={"url": url, "final_url": final_url},
        items=[item],
        meta={
            "id": iid,
            "methods": methods,
            "frames": len(frame_items),
            "downloaded": bool(media_item),
            "has_ffmpeg": has_ffmpeg(),
            "has_yt_dlp": has_yt_dlp(),
        },
        errors=errors,
        notes=[
            "Audiovisual material capture: page meta + optional download (yt-dlp) + frames.",
            "No speech-to-text in this version.",
            "Use tarrafa album --dir to build print HTML from frames.",
        ],
        collected_at=collected_at,
    )
    write_json(json_path, env)
    # also write a small album-friendly sidecar listing frames
    if frame_items:
        write_json(
            out_dir / f"{iid}.frames.json",
            {"id": iid, "frames": [f["image"] for f in frame_items]},
        )
    return env


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="tarrafa video",
        description="Capture video page meta, optional download (yt-dlp), and still frames.",
    )
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--id", dest="item_id", default=None)
    ap.add_argument("--caption", default=None)
    ap.add_argument("--download", action="store_true", help="Try yt-dlp download")
    ap.add_argument("--frames", type=int, default=5, help="Number of still frames (default 5)")
    ap.add_argument("--meta-only", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0)
    ap.add_argument("--wait-ms", type=int, default=2000)
    ap.add_argument("--storage-state", default=None)
    ap.add_argument("--headed", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_arg_parser().parse_args(argv)
    env = capture_video(
        args.url,
        Path(args.out_dir),
        item_id=args.item_id,
        download=args.download,
        frames=args.frames,
        meta_only=args.meta_only,
        timeout=args.timeout,
        wait_ms=args.wait_ms,
        storage_state=args.storage_state,
        headed=args.headed,
        caption=args.caption,
    )
    meta = env.get("meta") or {}
    items = env.get("items") or []
    print(
        f"video: id={meta.get('id')}  frames={meta.get('frames')}  "
        f"downloaded={meta.get('downloaded')}  methods={meta.get('methods')}  "
        f"json={Path(args.out_dir) / ((meta.get('id') or 'vid') + '.json')}"
    )
    if env.get("errors"):
        for e in env["errors"]:
            print(f"  warn: {e}", file=sys.stderr)
    if not items:
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
