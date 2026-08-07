"""Fetch layer (Phase 7.2): polite, rate-limited fetching with raw snapshotting.

Every page is checked against its domain's robots.txt before fetching, and
every successful fetch is written to data/raw/ before any extraction touches
it — extraction logic will change over time, but the source snapshot lets you
re-run extraction without re-fetching, and lets you audit what a chunk was
actually derived from.
"""

import re
import time
import urllib.robotparser
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import httpx

USER_AGENT = "stuttgart-mcp-rag-bot/0.1 (+educational project; contact via repo issues)"
RATE_LIMIT_SECONDS = 1.0
RAW_DIR = Path(__file__).parent / "data" / "raw"

_robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
_last_request_at: float = 0.0


class FetchError(Exception):
    pass


def _slugify(url: str) -> str:
    netloc = urlparse(url).netloc
    path = urlparse(url).path.strip("/")
    slug = f"{netloc}/{path}" if path else netloc
    return re.sub(r"[^a-zA-Z0-9]+", "-", slug).strip("-").lower()


def _allowed_by_robots(url: str) -> bool:
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in _robots_cache:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(f"{origin}/robots.txt")
        try:
            # Fetch with our own UA rather than rp.read()'s unbranded
            # default -- some sites 403 the stdlib default UA, which
            # RobotFileParser.read() silently treats as "disallow all".
            resp = httpx.get(
                f"{origin}/robots.txt",
                headers={"User-Agent": USER_AGENT},
                timeout=10.0,
                follow_redirects=True,
            )
            if resp.status_code == 404:
                rp.parse([])  # no robots.txt -> unrestricted
            else:
                resp.raise_for_status()
                rp.parse(resp.text.splitlines())
        except Exception:
            # Can't reach robots.txt at all -> treat as unrestricted rather
            # than blocking a legitimate fetch on a transient network error.
            rp.parse([])
        _robots_cache[origin] = rp
    return _robots_cache[origin].can_fetch(USER_AGENT, url)


def _rate_limit() -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_at = time.monotonic()


def fetch(url: str, retries: int = 3) -> str:
    """Fetch a URL and return raw HTML. Raises FetchError on failure or
    robots.txt disallow -- callers should fail loudly, not swallow this."""
    if not _allowed_by_robots(url):
        raise FetchError(f"robots.txt disallows fetching {url}")

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        _rate_limit()
        try:
            response = httpx.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=15.0,
                follow_redirects=True,
            )
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            if attempt < retries:
                time.sleep(2**attempt)  # exponential backoff
    raise FetchError(f"failed to fetch {url} after {retries} attempts: {last_exc}")


def save_raw_snapshot(url: str, html: str, as_of: date | None = None) -> Path:
    as_of = as_of or date.today()
    out_dir = RAW_DIR / _slugify(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{as_of.isoformat()}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


def fetch_and_snapshot(url: str) -> tuple[str, Path]:
    html = fetch(url)
    path = save_raw_snapshot(url, html)
    return html, path


if __name__ == "__main__":
    from scrape_sources import unique_sources

    for source in unique_sources():
        try:
            html, path = fetch_and_snapshot(source.url)
            print(f"OK   [{source.topic}] {source.url} -> {path} ({len(html)} bytes)")
        except FetchError as exc:
            print(f"FAIL [{source.topic}] {source.url}: {exc}")
