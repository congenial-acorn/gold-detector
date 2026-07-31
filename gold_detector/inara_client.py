import logging
import re

from bs4 import BeautifulSoup, Tag

from .http_client import http_get

logger = logging.getLogger("gold.inara")


def get_station_market_urls(near_urls):
    """From nearest-stations pages, pull every /station-market/<id>/ link once.

    Returns ``(market_urls, failed_near_urls)`` where ``failed_near_urls`` is
    the set of near_urls whose fetch errored. Callers must skip pruning when it
    is non-empty — a partial discovery must not delete entries (their sent_to
    state would be wiped, causing duplicate alerts once the page recovers).
    """
    market_urls = []
    failed_near_urls: set[str] = set()
    pattern = re.compile(r"^/elite/station/(\d+)/$")
    for url in near_urls:
        try:
            resp = http_get(url)
            soup: BeautifulSoup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if not isinstance(a, Tag):
                    continue
                href = a.get("href")
                if not isinstance(href, str):
                    continue
                match = pattern.match(href)
                if match:
                    station_id = match.group(1)
                    market_urls.append(
                        f"https://inara.cz/elite/station-market/{station_id}/"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to fetch station list from %s: %s", url, exc, exc_info=True
            )
            failed_near_urls.add(url)
            continue
    logger.info("Found %s station market URLs", len(market_urls))
    return list(dict.fromkeys(market_urls)), failed_near_urls
