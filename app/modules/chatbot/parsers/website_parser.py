import asyncio
import re
from typing import Union, List, Dict, Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from app.config.settings import get_settings

settings = get_settings()

# Max pages fetched in parallel per site (tune to stay polite to the target server)
_CRAWL_CONCURRENCY = 10

# =========================================================
# Public Function (This is the ONLY function you call)
# =========================================================


async def scrape_websites(
    input_data: Union[str, List[str], Dict[str, Any]],
    max_pages: int = settings.SCRAPPER_WEB_MAX_PAGES,
    headless: bool = settings.SCRAPPER_WEB_HEADLESS,
    timeout: int = settings.SCRAPPER_WEB_TIMEOUT,
    exclude_urls: set[str] | None = None,
) -> Dict[str, Dict[str, str]]:
    """
    Accepts:
        - str → single URL
        - List[str] → multiple URLs
        - Dict → {"url": "..."} or {"urls": ["...", "..."]}

    exclude_urls: set of page URLs already in the knowledge base — skipped
                  entirely so re-crawls only fetch genuinely new pages.

    Returns:
        {
            "https://site.com": {
                "https://site.com/page1": "clean text",
                ...
            }
        }
    """
    urls = _normalize_input(input_data)
    results: Dict[str, Dict[str, str]] = {}

    timeout_seconds = timeout / 1000  # convert ms to seconds
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; VeloceBot/1.0; +https://getveloce.com)"
        )
    }

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=timeout_seconds,
        headers=headers,
    ) as client:
        for start_url in urls:
            start_url = start_url.rstrip("/")
            results[start_url] = await _crawl_site(client, start_url, max_pages, exclude_urls)

    return results


# =========================================================
# Internal Helpers (Private)
# =========================================================


async def _crawl_site(
    client: httpx.AsyncClient,
    start_url: str,
    max_pages: int,
    exclude_urls: set[str] | None = None,
) -> Dict[str, str]:
    """
    Crawl a single site concurrently using a batch-wave BFS.

    Each wave fetches up to _CRAWL_CONCURRENCY pages in parallel via
    asyncio.gather, then discovers new links before starting the next wave.
    Uses two sets (fetched + queued) for O(1) duplicate detection instead
    of the original O(n) `link not in queue` list scan.

    exclude_urls: pages already in the knowledge base — never fetched or
                  enqueued, and do NOT count toward max_pages.
    """
    fetched: set[str] = set()        # already fetched or attempted this run
    already_seen: set[str] = set(exclude_urls) if exclude_urls else set()
    queued: set[str] = {start_url}   # in queue — prevents duplicate enqueue
    queue: list[str] = [start_url]
    site_data: Dict[str, str] = {}

    async def _fetch(url: str) -> tuple[str, str | None, list[str]]:
        """Fetch one page; return (url, cleaned_text_or_None, discovered_links)."""
        if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|css|js|zip|mp4|mp3)$", url, re.I):
            return url, None, []
        try:
            response = await client.get(url)
            response.raise_for_status()
            html = response.text
        except Exception:
            return url, None, []
        return url, _clean_text(html) or None, _extract_links(html, start_url)

    while queue and len(fetched) < max_pages:
        # Build next batch: up to _CRAWL_CONCURRENCY unvisited URLs
        batch: list[str] = []
        while queue and len(fetched) + len(batch) < max_pages and len(batch) < _CRAWL_CONCURRENCY:
            url = queue.pop(0)
            if url not in fetched and url not in already_seen:
                batch.append(url)

        if not batch:
            break

        # Fetch all pages in the batch concurrently
        page_results = await asyncio.gather(*(_fetch(url) for url in batch))

        for url, text, links in page_results:
            fetched.add(url)
            if text:
                site_data[url] = text
            for link in links:
                if link not in fetched and link not in queued and link not in already_seen:
                    queued.add(link)
                    queue.append(link)

    return site_data


def _normalize_input(input_data: Union[str, List[str], Dict[str, Any]]) -> List[str]:
    if isinstance(input_data, str):
        return [input_data]

    if isinstance(input_data, list):
        if not all(isinstance(u, str) for u in input_data):
            raise ValueError("All items in list must be strings.")
        return input_data

    if isinstance(input_data, dict):
        if "url" in input_data:
            return [input_data["url"]]
        if "urls" in input_data:
            if not isinstance(input_data["urls"], list):
                raise ValueError("'urls' must be a list.")
            return input_data["urls"]

    raise TypeError("Invalid input type.")


def _same_domain(base: str, url: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "noscript", "header", "footer", "nav", "aside"]):
        tag.decompose()

    text = soup.get_text(separator="\n")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def _extract_links(html: str, base_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        absolute = urljoin(base_url, href)
        absolute = absolute.split("#")[0].rstrip("/")

        if _same_domain(base_url, absolute) and absolute.startswith("http"):
            links.add(absolute)

    return list(links)
