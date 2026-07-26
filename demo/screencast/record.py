# -*- coding: utf-8 -*-
"""Grava uma demonstração em tela cheia do uso do CLI Tarrafa."""
from __future__ import annotations

import http.server
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "out"
WIDTH = 1440
HEIGHT = 900
PORT = 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, format, *args):  # noqa: A003
        pass


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Handler)
    httpd.allow_reuse_address = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    video_path = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": WIDTH, "height": HEIGHT},
                device_scale_factor=2,
                record_video_dir=str(OUT_DIR),
                record_video_size={"width": WIDTH, "height": HEIGHT},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{PORT}/terminal.html", wait_until="networkidle")
            # Aguarda o roteiro terminar (digitação + rolagem do navegador).
            page.wait_for_function("() => window.__DEMO_DONE__ === true", timeout=180_000)
            # Mantém o último quadro por um instante.
            page.wait_for_timeout(900)
            video_path = page.video.path() if page.video else None
            context.close()
            browser.close()
    finally:
        httpd.shutdown()

    if not video_path:
        print("gravação: falha · nenhum vídeo produzido", file=sys.stderr)
        return 1

    src = Path(video_path)
    # O Playwright produz WebM; mantém um nome estável.
    webm = OUT_DIR / "tarrafa_screencast.webm"
    if src.resolve() != webm.resolve():
        if webm.exists():
            webm.unlink()
        src.replace(webm)

    # Gera MP4 opcionalmente via imageio-ffmpeg, quando disponível.
    mp4 = OUT_DIR / "tarrafa_screencast.mp4"
    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        subprocess.run(
            [
                ffmpeg,
                "-y",
                "-i",
                str(webm),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(mp4),
            ],
            check=True,
            capture_output=True,
        )
        print(f"gravação: ok · {mp4} · {mp4.stat().st_size} bytes")
    except Exception as exc:  # noqa: BLE001
        print(f"gravação: ok · {webm} · MP4 não gerado ({exc})")

    print(f"gravação: WebM -> {webm}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
