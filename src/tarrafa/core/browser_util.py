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
) -> Iterator[tuple[Any, Any, Any]]:
    """
    Yields (playwright, browser, page). Caller must not close; context manager cleans up.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx_kwargs: dict[str, Any] = {
            "viewport": {"width": width, "height": height},
            "device_scale_factor": device_scale_factor,
        }
        if user_agent:
            ctx_kwargs["user_agent"] = user_agent
        if storage_state and Path(storage_state).is_file():
            ctx_kwargs["storage_state"] = storage_state
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()
        try:
            yield p, browser, page
        finally:
            context.close()
            browser.close()


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
