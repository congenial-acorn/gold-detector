import re
import time
import datetime
from datetime import timezone
import os
import threading
import requests
import functools
import logging
import sys
from urllib.parse import quote_plus
from typing import Optional, cast
from bs4 import BeautifulSoup, Tag, NavigableString, PageElement

# Get logger (logging is configured by bot.py before this module is imported)
logger = logging.getLogger("gold")

# ---- EMITTER WIRING ---------------------------------------------------------

_emit = None  # set by the bot at runtime
_emit_loop_done = None


def set_emitter(func):
    """Bot calls this to register a simple, thread-safe 'emit(message: str)' function."""
    global _emit
    _emit = func


def send_to_discord(message: str):
    """gold.py will keep calling this. The bot provides the real emitter."""
    if _emit is not None:
        _emit(message)
        # Log first line only to avoid multi-line log confusion
        first_line = message.split("\n")[0]
        logger.info(f"Alert sent to Discord: {first_line[:150]}")
    else:
        first_line = message.split("\n")[0]
        logger.warning(
            f"Discord emitter not wired, message not sent: {first_line[:150]}"
        )


def set_loop_done_emitter(func):  # <-- ADD THIS
    """Bot registers a callback we call once per cycle if any alerts were sent."""
    global _emit_loop_done
    _emit_loop_done = func


# ---- GLOBAL HTTP THROTTLE + BACKOFF -----------------------------------------

# Seconds to wait between ANY two outbound HTTP calls (min spacing)
# You can override via env: GOLD_HTTP_COOLDOWN=1.5
_RATE_LIMIT_SECONDS = float(os.getenv("GOLD_HTTP_COOLDOWN", "1.0"))

# Optional absolute timeout per request (seconds)
_HTTP_TIMEOUT = float(os.getenv("GOLD_HTTP_TIMEOUT", "15"))

# Max extra backoff after 429 (seconds)
_MAX_BACKOFF = float(os.getenv("GOLD_HTTP_MAX_BACKOFF", "60"))

# Shared session & throttle state
_SESSION = requests.Session()
_DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0 (inaragold/1.0)"}
_last_http_call = 0.0
_rl_lock = threading.Lock()

# Monitor loop delay (seconds)
_MONITOR_INTERVAL_SECONDS = float(
    os.getenv("GOLD_MONITOR_INTERVAL_SECONDS", str(1800))  # default: 30 minutes
)


def http_get(url: str, *, headers=None, timeout=None):
    """
    Throttled GET:
      • Enforces at least _RATE_LIMIT_SECONDS spacing between ALL HTTP calls.
      • If 429 is received, honors Retry-After (if present) or uses exponential backoff.
    """
    global _last_http_call

    # Enforce global cooldown between calls
    with _rl_lock:
        now = time.monotonic()
        wait = max(0.0, (_last_http_call + _RATE_LIMIT_SECONDS) - now)
    if wait > 0:
        logger.debug(f"Throttling HTTP request for {wait:.2f}s")
        time.sleep(wait)

    # Merge headers
    merged_headers = dict(_DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    # Backoff settings for 429
    backoff = 2.0
    timeout = _HTTP_TIMEOUT if timeout is None else timeout

    while True:
        try:
            logger.debug(f"HTTP GET: {url}")
            resp = _SESSION.get(url, headers=merged_headers, timeout=timeout)
            # mark call time on ANY attempt (even if not 200)
            with _rl_lock:
                _last_http_call = time.monotonic()

            logger.debug(f"HTTP {resp.status_code} from {url}")

            # Check for IP block before checking status code
            if resp.status_code == 200 and "Access Temporarily Restricted" in resp.text:
                logger.error(f"IP BLOCKED by {url.split('/')[2]}")
                logger.error(f"Response preview: {resp.text[:500]}")
                raise requests.exceptions.HTTPError(
                    f"IP address blocked by {url.split('/')[2]}. "
                    "Check logs for contact information.",
                    response=resp,
                )

            if resp.status_code == 429:
                # Respect Retry-After if provided; otherwise exponential backoff
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after) if retry_after is not None else backoff
                except ValueError:
                    delay = backoff
                delay = min(delay, _MAX_BACKOFF)
                logger.warning(
                    f"HTTP 429 (rate limited) from {url}, retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                backoff = min(backoff * 2.0, _MAX_BACKOFF)
                continue

            resp.raise_for_status()
            return resp

        except requests.exceptions.Timeout as e:
            logger.error(f"HTTP timeout for {url}: {e}")
            raise
        except requests.exceptions.ConnectionError as e:
            logger.error(f"HTTP connection error for {url}: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error for {url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during HTTP GET {url}: {e}", exc_info=True)
            raise


# ---- PARSERS & HELPERS ------------------------------------------------------


def get_station_market_urls(near_urls):
    """From nearest‐stations pages, pull every /station-market/<id>/ link once."""
    market_urls = []
    pattern = re.compile(r"^/elite/station/(\d+)/$")
    for url in near_urls:
        try:
            resp = http_get(url)
            soup: BeautifulSoup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a", href=True):
                m = pattern.match(a["href"])
                if m:
                    sid = m.group(1)
                    market_urls.append(f"https://inara.cz/elite/station-market/{sid}/")
        except Exception as e:
            logger.error(f"Failed to fetch station list from {url}: {e}", exc_info=True)
            continue
    logger.info(f"Found {len(market_urls)} station market URLs")
    # preserve order, drop dupes
    return list(dict.fromkeys(market_urls))


_TYPE_ANCHOR = re.compile(r"\b(Starport|Outpost|Surface\s+Port)\b", re.IGNORECASE)

# Full pattern: Base type with optional parentheses immediately after
_TYPE_WITH_PARENS = re.compile(
    r"\b(Starport|Outpost|Surface\s+Port)\b(?:\s*\(([^)]+)\))?", re.IGNORECASE
)

# Canonical capitalization
_CANON = {
    "starport": "Starport",
    "outpost": "Outpost",
    "surface port": "Surface Port",
}


def _canon_base(s: str) -> str:
    return _CANON[s.lower().replace("  ", " ")]


@functools.lru_cache(maxsize=512)
def get_station_type(station_id: str) -> str:
    url = f"https://inara.cz/elite/station/{station_id}/"
    resp = http_get(
        url, timeout=10, headers={"User-Agent": "Mozilla/5.0 (inaragold/1.0)"}
    )
    soup = BeautifulSoup(resp.text, "html.parser")

    # Anchor on the DOM text node that contains the base type word.
    node: Optional[PageElement] = soup.find(string=_TYPE_ANCHOR)
    if not node:
        # Broader fallback: scan all matching nodes (using 'string=' to avoid deprecation)
        for el in soup.find_all(string=_TYPE_ANCHOR):
            node = cast(NavigableString, el)
            break
    if not node:
        return "Unknown"

    if not getattr(node, "parent", None):
        return "Unknown"
    if node.parent is None or not isinstance(node.parent, Tag):
        return "Unknown"
    parent = getattr(node, "parent", None)
    if not isinstance(parent, Tag):
        return "Unknown"
    # --- Normal place: same element's text ---
    context = parent.get_text(" ", strip=True)
    m = _TYPE_WITH_PARENS.search(context)
    if m:
        base = _canon_base(m.group(1))
        suffix = m.group(2)
        return f"{base} ({suffix})" if suffix else base

    # --- Surface-station case: try one more <div> after ---
    div_anchor: Optional[Tag] = (
        parent if parent.name == "div" else parent.find_parent("div")
    )
    next_div: Optional[Tag] = (
        div_anchor.find_next_sibling("div") if div_anchor else None
    )
    ctx2 = next_div.get_text(" ", strip=True) if next_div is not None else ""

    # Best case: the next div repeats the base type with parentheses
    m2 = _TYPE_WITH_PARENS.search(ctx2)
    if m2:
        base = _canon_base(m2.group(1))
        suffix = m2.group(2)
        return f"{base} ({suffix})" if suffix else base

    # Otherwise, we already know the base type from the anchor; just harvest parentheses
    paren = re.search(r"\(([^)]+)\)", ctx2)
    m_base = _TYPE_ANCHOR.search(str(node))
    if not m_base:
        return "Unknown"
    base = _canon_base(m_base.group(1))
    return f"{base} ({paren.group(1)})" if paren else base


PALLADIUM_NUM = 45
GOLD_NUM = 42


def assemble_commodity_links(ids, system_name, distance):
    """Build an Inara commodities URL inserting each ID as pa1%5B%5D=ID after pi1=2&."""
    encoded_system = quote_plus(system_name or "")
    base = "https://inara.cz/elite/commodities/?formbrief=1&pi1=2"
    commodity_bits = "&".join(f"pa1%5B%5D={int(cid)}" for cid in ids)
    tail = (
        f"&ps1={encoded_system}"
        f"&pi10=3&pi11={distance}"
        "&pi3=1&pi9=0&pi4=0&pi8=0&pi13=0&pi5=720&pi12=0&pi7=0&pi14=0&ps3="
    )
    return f"{base}&{commodity_bits}{tail}" if commodity_bits else f"{base}{tail}"

def get_powerplay_status(systems):
    """Check each system in the list for Powerplay status."""
    for system in systems:
        system_url = system[0]
        try:
            resp = http_get(system_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            system_name = None
            h2 = soup.find("h2")
            if h2:
                raw_name = h2.get_text(" ", strip=True)
                # Drop any decorative glyphs (e.g., private-use icons) trailing the name.
                system_name = re.sub(r"[\uE000-\uF8FF]", "", raw_name).strip()

            # Anchor on the "Powerplay" label, then walk its parent div to pull fields
            label = soup.find("span", string=re.compile(r"Powerplay", re.IGNORECASE))
            if not label:
                logger.info(f"No Powerplay section found for {system_name or system_url}")
                continue

            block = label.find_parent("div")
            if block is None:
                logger.info(f"Powerplay section malformed for {system_name or system_url}")
                continue

            power_link = block.find("a", href=re.compile(r"/elite/power/\d+/?"))
            power_name = power_link.get_text(strip=True) if power_link else None

            role_tag = block.find("small")
            role_text = (
                role_tag.get_text(" ", strip=True).strip("()") if role_tag else None
            )

            status_tag = block.find(
                "span",
                class_=lambda c: c and "bigger" in c.split(),
            )
            status_text = status_tag.get_text(" ", strip=True) if status_tag else None

            percent_text = None
            neg_tag = block.find("span", class_="negative")
            if neg_tag:
                raw = neg_tag.get_text(" ", strip=True)
                m_pct = re.search(r"(\d+(?:[.,]\d+)?)%", raw)
                percent_text = f"{m_pct.group(1)}%" if m_pct else (raw or None)

            parts = []
            if power_name:
                parts.append(f"power={power_name}")
            if role_text:
                parts.append(f"role={role_text}")
            if status_text:
                parts.append(f"status={status_text}")
            if percent_text:
                parts.append(f"progress={percent_text}")

            if not parts:
                logger.info(
                    f"Powerplay section present but empty for {system_name or system_url}"
                )
                continue

            msg = f"Powerplay info for {system_name or system_url}: " + "; ".join(parts)
            logger.info(msg)
            
            id_list = []
            for i in range(len(system)):
                if system[i] == "Gold":
                    id_list.append(GOLD_NUM)
                elif system[i] == "Palladium":
                    id_list.append(PALLADIUM_NUM)
                else:
                    continue
            
            if status_text == "Unoccupied":
                logger.debug(
                    f"Powerplay status is Unoccupied for {system_name or system_url}"
                )
                continue
            if status_text == "Fortified":
                commodity_url = assemble_commodity_links(id_list, system_name or "", 20)
                send_to_discord(
                    f"{system_name} is a {power_name} {status_text} system.\n"
                    f"You can earn merits by selling for large profit in (these systems)[{commodity_url}]."
                )
            elif status_text == "Stronghold":
                commodity_url = assemble_commodity_links(id_list, system_name or "", 30)
                send_to_discord(
                    f"{system_name} is a {power_name} {status_text} system.\n"
                    f"You can earn merits by selling for large profit in (these systems)[{commodity_url}]."
                )
            send_to_discord(msg)
        except Exception as e:
            logger.error(f"Failed to fetch Powerplay status from {system_url}: {e}", exc_info=True)
            continue


# ---- MAIN LOOP --------------------------------------------------------------


def monitor_metals(near_urls, metals, cooldown_hours=0):
    # key = f"{station_id}-{metal_name}"
    last_ping = {}  # key -> datetime of last ping
    cooldown = datetime.timedelta(hours=cooldown_hours)
    systems = []
    messages = []

    logger.info(
        f"Starting monitor loop: checking {len(metals)} metals with {cooldown_hours}h cooldown"
    )

    while True:
        try:
            now = datetime.datetime.now(timezone.utc)
            logger.info("=== Beginning new scan cycle ===")
            market_urls = get_station_market_urls(near_urls)

            alive_ids = {re.search(r"/(\d+)/$", u).group(1) for u in market_urls}
            pruned = [k for k in list(last_ping) if k.split("-", 1)[0] not in alive_ids]
            for key in pruned:
                del last_ping[key]
            if pruned:
                logger.info(f"Pruned {len(pruned)} stale cooldown entries")

            stations_checked = 0
            alerts_sent = 0

            for url in market_urls:
                try:
                    resp = http_get(url)
                    soup = BeautifulSoup(resp.text, "html.parser")

                    # 1) Station & System info from the <h2>
                    header = soup.find("h2")
                    if header is None:
                        logger.warning(f"Missing <h2> header on {url}; skipping")
                        continue

                    a_tags = header.find_all("a", href=True)
                    if len(a_tags) < 2:
                        logger.warning(f"Incomplete header links on {url}; skipping")
                        continue

                    st_name = a_tags[0].get_text(strip=True)
                    system_name = a_tags[1].get_text(strip=True)
                    system_address = f"https://inara.cz{a_tags[1]['href']}"

                    stations_checked += 1

                    # 2) For each metal
                    for metal in metals:
                        link = soup.find("a", string=metal)
                        if not link:
                            continue

                        row = link.find_parent("tr")
                        if row is None:
                            logger.warning(
                                f"No table row for {metal} at {url}; skipping entry"
                            )
                            continue

                        cells = row.find_all("td")
                        if len(cells) < 5:
                            logger.warning(
                                f"Expected >=5 <td> cells for {metal} at {url}, got {len(cells)}"
                            )
                            continue

                        # buy price = 4th <td>, stock = 5th <td>
                        try:
                            buy_price = int(cells[3].get("data-order") or "0")
                            stock = int(cells[4].get("data-order") or "0")
                        except (TypeError, ValueError):
                            logger.warning(
                                f"Non-numeric price/stock for {metal} at {url}; skipping entry"
                            )
                            continue

                        logger.debug(
                            f"{metal} @ {st_name}: price={buy_price}, stock={stock}"
                        )

                        if buy_price > 28_000 and stock > 15_000:
                            station_id = re.search(r"/(\d+)/$", url).group(1)
                            st_type = get_station_type(station_id)
                            key = f"{station_id}-{metal}"
                            last_time = last_ping.get(key)
                            existing = None
                            for entry in systems:
                                if entry and entry[0] == system_address:
                                    existing = entry
                                    break
                            if existing is None:
                                systems.append([system_address, metal])
                            elif metal not in existing[1:]:
                                existing.append(metal)
                            if not last_time or (now - last_time) > cooldown:
                                # build and send the message
                                msg = (
                                    f"Hidden market detected at {st_name} ({st_type}), <{url}>\n"
                                    f"System: {system_name}, <{system_address}>\n"
                                    f"{metal} stock: {stock}"
                                )
                                for message in messages:
                                    if st_name in message:
                                        message += f", {metal} stock: {stock}"
                                        break
                                else:
                                    messages.append(msg)
                                #send_to_discord(msg)
                                last_ping[key] = now
                                alerts_sent += 1
                                logger.info(
                                    f"ALERT: {metal} @ {st_name} - price={buy_price}, stock={stock}, "
                                    f"cooldown until {now + cooldown}"
                                )
                            
                            else:
                                remaining = cooldown - (now - last_time)
                                logger.debug(
                                    f"Skipping {metal} @ {st_name} - still on cooldown "
                                    f"({remaining.total_seconds()/3600:.1f}h remaining)"
                                )
                except Exception as e:
                    logger.error(f"Error processing station {url}: {e}", exc_info=True)
                    continue
            
            logger.info(
                f"Scan complete: checked {stations_checked} stations, sent {alerts_sent} alerts"
            )
            logger.info("Starting Powerplay check.")
            for message in messages:
                send_to_discord(message)
            
            get_powerplay_status(systems)

            if _emit_loop_done:
                try:
                    _emit_loop_done()
                except Exception as e:
                    logger.error(f"Loop-done emitter failed: {e}", exc_info=True)

            # wait before checking again
            interval_seconds = max(0.0, _MONITOR_INTERVAL_SECONDS)
            minutes = interval_seconds / 60.0
            logger.info(
                f"Sleeping for {interval_seconds:.0f} seconds ({minutes:.1f} minutes) "
                f"until next scan at {datetime.datetime.now() + datetime.timedelta(seconds=interval_seconds)}"
            )
            time.sleep(interval_seconds)

        except Exception as e:
            logger.error(f"Fatal error in monitor loop: {e}", exc_info=True)
            raise


def main():
    url1 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=3&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26"
    )
    url2 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=6&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26"
    )
    
    url3 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=3&pi16=2&pa2%5B%5D=26"
    )
    url4 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=6&pi16=2&pi1=0&pi17=0&pa2%5B%5D=26"
    )
    url5 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=3&pi16=14&ps2=&pa2%5B%5D=26"
    )
    url6 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=6&pi16=14&ps2=&pa2%5B%5D=26"
    )
    
    monitor_metals([url1, url2, url3, url4, url5, url6], metals=["Gold", "Palladium"])


if __name__ == "__main__":
    # Configure logging if running standalone (not imported by bot.py)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
