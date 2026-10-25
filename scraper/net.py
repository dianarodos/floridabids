"""Polite network access: identify ourselves, honor robots.txt and crawl-delay."""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from functools import lru_cache
from urllib.parse import urlsplit

import requests

USER_AGENT = "FloridaBidsBot/1.0 (+https://floridabids.org/about; daily list of public solicitations)"
DEFAULT_DELAY = 2.0          # seconds between requests to the same host
_last_hit: dict[str, float] = {}
_host_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()
_local = threading.local()


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    return s


class _SessionProxy:
    """Sources run in parallel threads; each thread gets its own session (own cookies)."""
    def __getattr__(self, name):
        if not hasattr(_local, "s"):
            _local.s = _new_session()
        return getattr(_local.s, name)


session = _SessionProxy()


class Blocked(Exception):
    """robots.txt disallows this URL."""


@lru_cache(maxsize=128)
def _robots(origin: str) -> urllib.robotparser.RobotFileParser | None:
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = session.get(origin + "/robots.txt", timeout=20)
    except requests.RequestException:
        return None          # unreachable robots.txt: treat as no rules
    if r.status_code >= 400 or "text/html" in r.headers.get("content-type", ""):
        return None          # missing robots.txt means no restrictions
    rp.parse(r.text.splitlines())
    return rp


def check(url: str) -> float:
    """Raise Blocked if disallowed; return the crawl delay to use for this host."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    rp = _robots(origin)
    if rp is None:
        return DEFAULT_DELAY
    if not rp.can_fetch(USER_AGENT, url):
        raise Blocked(f"robots.txt disallows {url}")
    delay = rp.crawl_delay(USER_AGENT)
    return max(float(delay or 0), DEFAULT_DELAY)


def wait_turn(url: str, delay: float) -> None:
    """Space out requests to one host, even when several sources share it (e.g. DemandStar)."""
    host = urlsplit(url).netloc
    with _locks_guard:
        lock = _host_locks.setdefault(host, threading.Lock())
    with lock:
        elapsed = time.monotonic() - _last_hit.get(host, 0)
        if elapsed < delay:
            time.sleep(delay - elapsed)
        _last_hit[host] = time.monotonic()


def get(url: str, **kw) -> requests.Response:
    delay = check(url)
    wait_turn(url, delay)
    r = session.get(url, timeout=kw.pop("timeout", 45), **kw)
    r.raise_for_status()
    return r


def post(url: str, **kw) -> requests.Response:
    delay = check(url)
    wait_turn(url, delay)
    r = session.post(url, timeout=kw.pop("timeout", 45), **kw)
    r.raise_for_status()
    return r
