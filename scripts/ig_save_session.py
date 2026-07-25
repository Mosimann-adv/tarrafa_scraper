#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Open headed Chromium for native Instagram login and auto-save storage_state.

  python scripts/ig_save_session.py
  python scripts/ig_save_session.py --out D:\\...\\storage_state.json --timeout 600

Does NOT type passwords. Wait until URL leaves /accounts/login and sessionid cookie exists.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "storage_state.json"),
    )
    ap.add_argument("--timeout", type=int, default=600, help="Seconds to wait for login")
    args = ap.parse_args()
    out = Path(args.out)

    from playwright.sync_api import sync_playwright

    print("Abrindo Chromium headed em Instagram…")
    print("1) Faça login NATIVO (não use Continuar com Facebook).")
    print("2) Quando o feed carregar, o script grava sozinho.")
    print(f"3) Timeout: {args.timeout}s → {out}")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded")
        deadline = time.time() + args.timeout
        saved = False
        while time.time() < deadline:
            url = page.url or ""
            cookies = context.cookies()
            has_sess = any(c.get("name") == "sessionid" and c.get("value") for c in cookies)
            left_login = "accounts/login" not in url and "challenge" not in url
            if has_sess and left_login:
                # small settle
                time.sleep(1.5)
                context.storage_state(path=str(out))
                saved = True
                print(f"OK storage salvo: {out}")
                break
            time.sleep(1.5)
        if not saved:
            # still save whatever we have if sessionid present (2FA mid-flow etc.)
            cookies = context.cookies()
            if any(c.get("name") == "sessionid" and c.get("value") for c in cookies):
                context.storage_state(path=str(out))
                print(f"Salvo com sessionid (URL ainda: {page.url}): {out}")
                saved = True
            else:
                print("Timeout sem sessão. Nada gravado.", file=sys.stderr)
        browser.close()
    return 0 if saved else 5


if __name__ == "__main__":
    raise SystemExit(main())
