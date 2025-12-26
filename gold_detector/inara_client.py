import functools
import logging
import re
from typing import Optional, cast

from bs4 import BeautifulSoup, NavigableString, PageElement, Tag

from .http_client import http_get

logger = logging.getLogger("gold.inara")


def get_station_market_urls(near_urls):
    """From nearest-stations pages, pull every /station-market/<id>/ link once."""
    market_urls = []
    pattern = re.compile(r"^/elite/station/(\d+)/$")
    for url in near_urls:
        try:
            resp = http_get(url)
            soup: BeautifulSoup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                match = pattern.match(a["href"])
                if match:
                    station_id = match.group(1)
                    market_urls.append(
                        f"https://inara.cz/elite/station-market/{station_id}/"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to fetch station list from %s: %s", url, exc, exc_info=True
            )
            continue
    logger.info("Found %s station market URLs", len(market_urls))
    return list(dict.fromkeys(market_urls))


_TYPE_ANCHOR = re.compile(r"\b(Starport|Outpost|Surface\s+Port)\b", re.IGNORECASE)
_TYPE_WITH_PARENS = re.compile(
    r"\b(Starport|Outpost|Surface\s+Port)\b(?:\s*\(([^)]+)\))?", re.IGNORECASE
)
_CANON = {
    "starport": "Starport",
    "outpost": "Outpost",
    "surface port": "Surface Port",
}


def _canon_base(raw: str) -> str:
    return _CANON[raw.lower().replace("  ", " ")]


def _scan_with_anchor(node: PageElement) -> Optional[str]:
    if not getattr(node, "parent", None):
        return None
    parent = getattr(node, "parent", None)
    if parent is None or not isinstance(parent, Tag):
        return None
    context = parent.get_text(" ", strip=True)
    match = _TYPE_WITH_PARENS.search(context)
    if match:
        base = _canon_base(match.group(1))
        suffix = match.group(2)
        return f"{base} ({suffix})" if suffix else base
    return None


@functools.lru_cache(maxsize=512)
def get_station_type(station_id: str) -> str:
    url = f"https://inara.cz/elite/station/{station_id}/"
    resp = http_get(
        url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (inaragold/1.0)"}
    )
    soup = BeautifulSoup(resp.text, "html.parser")

    node: Optional[PageElement] = soup.find(string=_TYPE_ANCHOR)
    if not node:
        for el in soup.find_all(string=_TYPE_ANCHOR):
            node = cast(NavigableString, el)
            break
    if not node:
        return "Unknown"

    parsed = _scan_with_anchor(node)
    if parsed:
        return parsed

    parent = getattr(node, "parent", None)
    div_anchor: Optional[Tag] = (
        parent if isinstance(parent, Tag) and parent.name == "div" else None
    )
    if not div_anchor and isinstance(parent, Tag):
        div_anchor = parent.find_parent("div")
    next_div: Optional[Tag] = (
        div_anchor.find_next_sibling("div") if div_anchor else None
    )
    ctx2 = next_div.get_text(" ", strip=True) if next_div is not None else ""

    match = _TYPE_WITH_PARENS.search(ctx2)
    if match:
        base = _canon_base(match.group(1))
        suffix = match.group(2)
        return f"{base} ({suffix})" if suffix else base

    paren = re.search(r"\(([^)]+)\)", ctx2)
    m_base = _TYPE_ANCHOR.search(str(node))
    if not m_base:
        return "Unknown"
    base = _canon_base(m_base.group(1))
    return f"{base} ({paren.group(1)})" if paren else base
