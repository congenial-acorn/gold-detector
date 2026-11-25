import logging
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup, Tag

from .http_client import http_get

logger = logging.getLogger("gold.inara")


class InaraDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class InaraFactionLink:
    name: str
    href: str


# Keyed by minor faction href (e.g. "/elite/minorfaction/76647/").
InaraSystemFactions = dict[str, tuple[str, ...]]


def parse_station_owner(soup: BeautifulSoup) -> InaraFactionLink | None:
    """Read the controlling minor faction from a station or station-market page.

    Returns None for stations without a minor faction (shown as "-").
    """
    for label in soup.find_all("div", class_="itempairlabel"):
        if not isinstance(label, Tag) or label.get_text(strip=True) != "Minor faction":
            continue
        value = label.find_next_sibling("div")
        if not isinstance(value, Tag):
            break
        link = value.find("a", href=True)
        if not isinstance(link, Tag):
            return None
        href = link.get("href")
        if not isinstance(href, str):
            break
        return InaraFactionLink(name=link.get_text(strip=True), href=href)
    raise InaraDataError("Inara page has no minor faction field")


def parse_system_factions(soup: BeautifulSoup) -> InaraSystemFactions:
    """Read each minor faction's active states from an Inara star system page."""
    heading = next(
        (
            h2
            for h2 in soup.find_all("h2")
            if isinstance(h2, Tag) and "System minor factions" in h2.get_text()
        ),
        None,
    )
    table = heading.find_next("table") if heading is not None else None
    if not isinstance(table, Tag):
        raise InaraDataError("Inara system page has no minor factions table")

    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    if "Active" not in headers:
        raise InaraDataError("Inara minor factions table has no Active column")
    active_index = headers.index("Active")

    factions: InaraSystemFactions = {}
    for row in table.find_all("tr"):
        if not isinstance(row, Tag):
            continue
        cells = [cell for cell in row.find_all("td") if isinstance(cell, Tag)]
        if len(cells) <= active_index:
            continue
        link = cells[0].find("a", href=True)
        if not isinstance(link, Tag):
            continue
        href = link.get("href")
        if not isinstance(href, str):
            continue
        factions[href] = tuple(
            tag.get_text(strip=True)
            for tag in cells[active_index].find_all("span", class_="statetag")
        )
    return factions


def fetch_system_factions(system_address: str) -> InaraSystemFactions:
    response = http_get(system_address)
    return parse_system_factions(BeautifulSoup(response.text, "html.parser"))


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
