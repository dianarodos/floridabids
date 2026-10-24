"""Headless Chromium for JavaScript-built pages. One browser per run, opened on demand."""
from __future__ import annotations

from contextlib import contextmanager

from .net import USER_AGENT, check, wait_turn

_pw = None
_browser = None


def _ensure():
    global _pw, _browser
    if _browser is None:
        from playwright.sync_api import sync_playwright
        _pw = sync_playwright().start()
        _browser = _pw.chromium.launch(headless=True)
    return _browser


@contextmanager
def page(url: str, wait_for: str | None = None, timeout_ms: int = 45000):
    """Open url in a fresh page (robots.txt checked first). Yields the Playwright page."""
    delay = check(url)
    wait_turn(url, delay)
    ctx = _ensure().new_context(user_agent=USER_AGENT, locale="en-US", timezone_id="America/New_York")
    pg = ctx.new_page()
    pg.set_default_timeout(timeout_ms)
    try:
        pg.goto(url, wait_until="domcontentloaded")
        if wait_for:
            pg.wait_for_selector(wait_for)
        else:
            pg.wait_for_load_state("networkidle")
        yield pg
    finally:
        ctx.close()


def close():
    global _pw, _browser
    if _browser:
        _browser.close()
        _pw.stop()
    _browser = _pw = None
