# -*- coding: utf-8 -*-
"""Shared Playwright launch helpers."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def chromium_page(
    *,
    storage_state: str | None = None,
    headless: bool = True,
    width: int = 1280,
    height: int = 900,
    device_scale_factor: float = 2.0,
    user_agent: str | None = None,
    accept_downloads: bool = False,
    cdp_url: str | None = None,
    channel: str | None = None,
    user_data_dir: str | Path | None = None,
) -> Iterator[tuple[Any, Any, Any, Any]]:
    """
    Yields (playwright, browser, context, page).

    - ``cdp_url``: connect to an existing Chrome (e.g. http://127.0.0.1:9222).
    - ``channel``: Playwright browser channel (``chrome``, ``msedge``, …).
      Prefer ``chrome`` for Cloudflare-protected sites (bundled Chromium is often blocked).
    - ``user_data_dir``: persistent profile (launch_persistent_context). Survives CF cookies
      better than ephemeral context + storage_state alone.
    - ``accept_downloads``: enable Playwright download capture.
    - Caller must not close; context manager cleans up (does not kill CDP browser).
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        if cdp_url:
            browser = p.chromium.connect_over_cdp(cdp_url)
            if browser.contexts:
                context = browser.contexts[0]
                page = context.new_page()
                created_page = True
            else:
                ctx_kwargs: dict[str, Any] = {
                    "viewport": {"width": width, "height": height},
                    "device_scale_factor": device_scale_factor,
                    "accept_downloads": accept_downloads,
                }
                if user_agent:
                    ctx_kwargs["user_agent"] = user_agent
                if storage_state and Path(storage_state).is_file():
                    ctx_kwargs["storage_state"] = storage_state
                context = browser.new_context(**ctx_kwargs)
                page = context.new_page()
                created_page = True
            try:
                yield p, browser, context, page
            finally:
                if created_page:
                    try:
                        page.close()
                    except Exception:
                        pass
            return

        if user_data_dir:
            udd = Path(user_data_dir)
            udd.mkdir(parents=True, exist_ok=True)
            launch_kwargs: dict[str, Any] = {
                "user_data_dir": str(udd),
                "headless": headless,
                "viewport": {"width": width, "height": height},
                "device_scale_factor": device_scale_factor,
                "accept_downloads": accept_downloads,
            }
            if channel:
                launch_kwargs["channel"] = channel
            if user_agent:
                launch_kwargs["user_agent"] = user_agent
            # storage_state is ignored by persistent context on create; profile holds cookies
            context = p.chromium.launch_persistent_context(**launch_kwargs)
            browser = context.browser
            page = context.pages[0] if context.pages else context.new_page()
            try:
                yield p, browser, context, page
            finally:
                try:
                    context.close()
                except Exception:
                    pass
            return

        launch_kwargs = {"headless": headless}
        if channel:
            launch_kwargs["channel"] = channel
        browser = p.chromium.launch(**launch_kwargs)
        ctx_kwargs = {
            "viewport": {"width": width, "height": height},
            "device_scale_factor": device_scale_factor,
            "accept_downloads": accept_downloads,
        }
        if user_agent:
            ctx_kwargs["user_agent"] = user_agent
        if storage_state and Path(storage_state).is_file():
            ctx_kwargs["storage_state"] = storage_state
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        try:
            yield p, browser, context, page
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass


def goto_settled(page: Any, url: str, *, timeout_ms: int = 60_000, wait_ms: int = 1200) -> Any:
    """Navigate and best-effort wait for late content."""
    resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=min(10_000, timeout_ms))
    except Exception:
        pass
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    return resp


def default_stj_profile_dir() -> Path:
    """Dedicated Chrome profile for STJ (not the user's daily profile)."""
    home = Path.home() / ".tarrafa" / "chrome-stj-profile"
    home.mkdir(parents=True, exist_ok=True)
    return home
