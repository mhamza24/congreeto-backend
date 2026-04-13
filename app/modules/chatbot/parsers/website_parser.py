import re
from typing import Union, List, Dict, Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from app.config.settings import get_settings
settings = get_settings()

# =========================================================
# Public Function (This is the ONLY function you call)
# =========================================================


async def scrape_websites(
    input_data: Union[str, List[str], Dict[str, Any]],
    max_pages: int = settings.SCRAPPER_WEB_MAX_PAGES,
    headless: bool = settings.SCRAPPER_WEB_HEADLESS,
    timeout: int = settings.SCRAPPER_WEB_TIMEOUT,
) -> Dict[str, Dict[str, str]]:
    """
    Accepts:
        - str → single URL
        - List[str] → multiple URLs
        - Dict → {"url": "..."} or {"urls": ["...", "..."]}

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
            visited = set()
            queue = [start_url]
            site_data: Dict[str, str] = {}

            while queue and len(visited) < max_pages:
                url = queue.pop(0)

                if url in visited:
                    continue

                if re.search(r"\.(pdf|jpg|jpeg|png|gif|svg|css|js|zip|mp4|mp3)$", url, re.I):
                    visited.add(url)
                    continue

                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    html = response.text
                except Exception:
                    visited.add(url)
                    continue

                visited.add(url)

                text = _clean_text(html)
                if text:
                    site_data[url] = text

                for link in _extract_links(html, start_url):
                    if link not in visited and link not in queue:
                        queue.append(link)

            results[start_url] = site_data

    return results


# =========================================================
# Internal Helpers (Private)
# =========================================================

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
