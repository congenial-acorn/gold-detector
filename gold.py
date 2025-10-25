import re
import time
import datetime
from datetime import timezone
import os
import threading
import requests
import functools
from typing import Optional, cast
from bs4 import BeautifulSoup, Tag, NavigableString, PageElement

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
    else:
        print(f"[Discord] (noop) {message}")  # falls back to stdout if bot not wired


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
        time.sleep(wait)

    # Merge headers
    merged_headers = dict(_DEFAULT_HEADERS)
    if headers:
        merged_headers.update(headers)

    # Backoff settings for 429
    backoff = 2.0
    timeout = _HTTP_TIMEOUT if timeout is None else timeout

    while True:
        resp = _SESSION.get(url, headers=merged_headers, timeout=timeout)
        # mark call time on ANY attempt (even if not 200)
        with _rl_lock:
            _last_http_call = time.monotonic()

        if resp.status_code == 429:
            # Respect Retry-After if provided; otherwise exponential backoff
            retry_after = resp.headers.get("Retry-After")
            try:
                delay = float(retry_after) if retry_after is not None else backoff
            except ValueError:
                delay = backoff
            delay = min(delay, _MAX_BACKOFF)
            time.sleep(delay)
            backoff = min(backoff * 2.0, _MAX_BACKOFF)
            continue

        resp.raise_for_status()
        return resp


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
            print(f"[gold] failed {url}: {e}")
            continue
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


# ---- MAIN LOOP --------------------------------------------------------------


def monitor_metals(near_urls, metals, cooldown_hours=0):
    # key = f"{station_id}-{metal_name}"
    last_ping = {}  # key -> datetime of last ping
    cooldown = datetime.timedelta(hours=cooldown_hours)

    while True:
        now = datetime.datetime.now(timezone.utc)
        market_urls = get_station_market_urls(near_urls)

        alive_ids = {re.search(r"/(\d+)/$", u).group(1) for u in market_urls}
        for key in list(last_ping):
            station_id, metal = key.split("-", 1)
            if station_id not in alive_ids:
                del last_ping[key]

        for url in market_urls:
            resp = http_get(url)
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1) Station & System info from the <h2>
            header = soup.find("h2")
            if header is None:
                print(f"[gold] missing <h2> header on {url}; skipping")
                continue

            a_tags = header.find_all("a", href=True)
            if len(a_tags) < 2:
                print(f"[gold] incomplete header links on {url}; skipping")
                continue

            st_name = a_tags[0].get_text(strip=True)
            system_name = a_tags[1].get_text(strip=True)
            system_address = f"https://inara.cz{a_tags[1]['href']}"

            # 2) For each metal
            for metal in metals:
                link = soup.find("a", string=metal)
                if not link:
                    continue

                row = link.find_parent("tr")
                if row is None:
                    print(f"[gold] no table row for {metal} at {url}; skipping entry")
                    continue

                cells = row.find_all("td")
                if len(cells) < 5:
                    print(
                        f"[gold] expected >=5 <td> cells for {metal} at {url}, got {len(cells)}"
                    )
                    continue

                # buy price = 4th <td>, stock = 5th <td>
                try:
                    buy_price = int(cells[3].get("data-order") or "0")
                    stock = int(cells[4].get("data-order") or "0")
                except (TypeError, ValueError):
                    print(
                        f"[gold] non-numeric price/stock for {metal} at {url}; skipping entry"
                    )
                    continue
                print(f"  • {metal} @ {st_name}: price={buy_price}, stock={stock}")
                if buy_price > 28_000 and stock > 15_000:
                    station_id = re.search(r"/(\d+)/$", url).group(1)
                    st_type = get_station_type(station_id)
                    key = f"{station_id}-{metal}"
                    last_time = last_ping.get(key)
                    if not last_time or (now - last_time) > datetime.timedelta(
                        hours=cooldown_hours
                    ):
                        # build and send the message
                        msg = (
                            f"Hidden market detected at {st_name} ({st_type}), <{url}>\n"
                            f"System: {system_name}, <{system_address}>\n"
                            f"{metal} stock: {stock}"
                        )
                        send_to_discord(msg)
                        last_ping[key] = now
                        print(
                            f"  • {metal} @ {st_name}: price={buy_price}, stock={stock}"
                        )
                        print(f"    ↪ alert sent, cooldown until {now + cooldown}")

        if _emit_loop_done:
            try:
                _emit_loop_done()
            except Exception as e:
                print(f"[gold] loop_done emit failed: {e}")

        # wait before checking again
        print("Loop finished. Sleeping for 30 minutes.")
        #time.sleep(30 * 60)  # 30 minutes
        time.sleep(15)


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
    # monitor Gold (add "Silver" if needed)
    monitor_metals([url1, url2, url3, url4, url5, url6], metals=["Gold"])


if __name__ == "__main__":
    main()
