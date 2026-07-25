# -*- coding: utf-8 -*-
"""Media helpers: paths, hashing, slugs, ffmpeg/yt-dlp probes."""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def slugify(text: str, *, max_len: int = 48) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"https?://", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:max_len] or "item").rstrip("_")


def id_from_url(url: str, *, prefix: str = "") -> str:
    path = urlparse(url or "").path or ""
    base = path.rstrip("/").split("/")[-1] or "page"
    base = slugify(base, max_len=40)
    return f"{prefix}{base}" if prefix else base


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def mime_for_path(path: Path | str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "application/octet-stream")


def file_to_data_uri(path: Path | str) -> str:
    """Read image file → data: URI (base64)."""
    import base64

    p = Path(path)
    raw = p.read_bytes()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:{mime_for_path(p)};base64,{b64}"


def file_sha256(path: Path | str, *, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def has_ffmpeg() -> bool:
    return bool(which("ffmpeg"))


def has_yt_dlp() -> bool:
    if which("yt-dlp"):
        return True
    try:
        import yt_dlp  # noqa: F401

        return True
    except ImportError:
        return False


def run_cmd(argv: list[str], *, timeout: float = 300) -> dict[str, Any]:
    try:
        r = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": r.returncode == 0,
            "code": r.returncode,
            "stdout": (r.stdout or "")[-4000:],
            "stderr": (r.stderr or "")[-4000:],
            "argv": argv,
        }
    except FileNotFoundError as e:
        return {"ok": False, "code": 127, "stdout": "", "stderr": str(e), "argv": argv}
    except subprocess.TimeoutExpired:
        return {"ok": False, "code": 124, "stdout": "", "stderr": "timeout", "argv": argv}


def ffmpeg_extract_frames(
    video_path: Path,
    out_dir: Path,
    *,
    count: int = 5,
    prefix: str = "frame",
) -> list[Path]:
    """Extract evenly spaced frames with ffmpeg. Returns list of PNG paths."""
    if count < 1:
        return []
    if not has_ffmpeg():
        return []
    ensure_dir(out_dir)
    # duration via ffprobe if available
    duration = None
    if which("ffprobe"):
        pr = run_cmd(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            timeout=60,
        )
        if pr["ok"]:
            try:
                duration = float((pr["stdout"] or "").strip().splitlines()[0])
            except (ValueError, IndexError):
                duration = None

    paths: list[Path] = []
    if duration and duration > 0 and count > 1:
        for i in range(count):
            t = (duration * i) / max(count - 1, 1)
            # avoid last-frame edge issues
            if i == count - 1:
                t = max(0.0, duration - 0.15)
            out = out_dir / f"{prefix}_{i:02d}.png"
            r = run_cmd(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{t:.3f}",
                    "-i",
                    str(video_path),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(out),
                ],
                timeout=120,
            )
            if r["ok"] and out.is_file():
                paths.append(out)
    else:
        # fps filter: ~count frames from whole file
        out_pattern = out_dir / f"{prefix}_%02d.png"
        # select every Nth — approximate with fps=count/duration unknown → fps=1 and take first N
        r = run_cmd(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vf",
                f"fps={max(1, min(count, 5))}",
                "-vframes",
                str(count),
                str(out_pattern),
            ],
            timeout=180,
        )
        if r["ok"]:
            paths = sorted(out_dir.glob(f"{prefix}_*.png"))[:count]
    return paths
