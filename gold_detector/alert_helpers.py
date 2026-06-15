import logging
from urllib.parse import quote_plus

from .commodities import id_to_mask_text_map
from .http_client import http_get

logger = logging.getLogger("gold.alert_helpers")


def _has_commodity_results(url, fetch):
    try:
        resp = fetch(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Commodity link check failed for %s: %s", url, exc)
        return True
    return "No commodities were found." not in resp.text


def assemble_commodity_links(ids, system_name, distance, fetch=http_get):
    """Build an Inara commodities URL inserting each ID as pa1%5B%5D=ID after pi1=2&."""
    encoded_system = quote_plus(system_name or "")
    base = "https://inara.cz/elite/commodities/?formbrief=1&pi1=2"
    commodity_bits = []
    for cid in ids:
        commodity_bits.append(f"&pa1%5B%5D={int(cid)}")
    tail = (
        f"&ps1={encoded_system}"
        f"&pi10=3&pi11={distance}"
        "&pi3=1&pi9=0&pi4=0&pi8=0&pi13=0&pi5=720&pi12=0&pi7=0&pi14=-1&ps3="
    )
    urls_list = []
    if commodity_bits:
        for bit in commodity_bits:
            url = f"{base}{bit}{tail}"
            if _has_commodity_results(url, fetch):
                urls_list.append(url)
        return urls_list

    url = f"{base}{tail}"
    return url if _has_commodity_results(url, fetch) else ""


def mask_commodity_links(urls):
    """Return space-separated masked links for commodities."""
    if not urls:
        return ""
    if isinstance(urls, str):
        urls = [urls]
    id_to_text = id_to_mask_text_map()
    masked = []
    for url in urls:
        text = "Sell here"
        for cid, mask_text in id_to_text.items():
            if f"pa1%5B%5D={cid}" in url:
                text = mask_text
                break
        masked.append(f"[{text}](<{url}>)")
    return " ".join(masked)
