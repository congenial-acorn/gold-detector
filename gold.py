import re
import time
import datetime
from datetime import timezone
import requests
import functools
from bs4 import BeautifulSoup

# ← set your webhook here

_emit = None  # set by the bot at runtime

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



def get_station_market_urls(near_urls):
    """From nearest‐stations pages, pull every /station-market/<id>/ link once."""
    market_urls = []
    pattern = re.compile(r'^/elite/station/(\d+)/$')
    for url in near_urls:
        resp = requests.get(url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            m = pattern.match(a["href"])
            if m:
                sid = m.group(1)
                market_urls.append(f"https://inara.cz/elite/station-market/{sid}/")
    # preserve order, drop dupes
    return list(dict.fromkeys(market_urls))

_TYPE_ANCHOR = re.compile(r"\b(Starport|Outpost|Surface\s+Port)\b", re.IGNORECASE)

# Full pattern: Base type with optional parentheses immediately after
_TYPE_WITH_PARENS = re.compile(
    r"\b(Starport|Outpost|Surface\s+Port)\b(?:\s*\(([^)]+)\))?",
    re.IGNORECASE
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
    resp = requests.get(
        url,
        timeout=10,
        headers={"User-Agent": "Mozilla/5.0 (inaragold/1.0)"}
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    # Anchor on the DOM text node that contains the base type word.
    node = soup.find(string=_TYPE_ANCHOR)
    if not node:
        # Broader fallback: scan all matching nodes (using 'string=' to avoid deprecation)
        for el in soup.find_all(string=_TYPE_ANCHOR):
            node = el
            break
    if not node:
        return "Unknown"

    parent = node.parent
    # --- Normal place: same element's text ---
    context = parent.get_text(" ", strip=True)
    m = _TYPE_WITH_PARENS.search(context)
    if m:
        base = _canon_base(m.group(1))
        suffix = m.group(2)
        return f"{base} ({suffix})" if suffix else base

    # --- Surface-station case: try one more <div> after ---
    div_anchor = parent if parent.name == "div" else parent.find_parent("div")
    next_div = div_anchor.find_next_sibling("div") if div_anchor else None
    if next_div:
        ctx2 = next_div.get_text(" ", strip=True)
        # Best case: the next div repeats the base type with parentheses
        m2 = _TYPE_WITH_PARENS.search(ctx2)
        if m2:
            base = _canon_base(m2.group(1))
            suffix = m2.group(2)
            return f"{base} ({suffix})" if suffix else base

        # Otherwise, we already know the base type from the anchor; just harvest parentheses
        paren = re.search(r"\(([^)]+)\)", ctx2)
        base = _canon_base(_TYPE_ANCHOR.search(node).group(1))
        if paren:
            return f"{base} ({paren.group(1)})"
        return base

    # Fallback: return just the base type we anchored on
    base = _canon_base(_TYPE_ANCHOR.search(node).group(1))
    return base


def monitor_metals(near_urls, metals, cooldown_hours=0):
    # key = f"{station_id}-{metal_name}"
    last_ping = {}  # key -> datetime of last ping
    cooldown = datetime.timedelta(hours=cooldown_hours)

    while True:
        now = datetime.datetime.now(timezone.utc)
        market_urls = get_station_market_urls(near_urls)

        alive_ids = {re.search(r'/(\d+)/$', u).group(1) for u in market_urls}
        for key in list(last_ping):
            station_id, metal = key.split("-", 1)
            if station_id not in alive_ids:
                del last_ping[key]
        for url in market_urls:
            resp = requests.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # 1) Station & System info from the <h2>
            header = soup.find("h2")
            a_tags = header.find_all("a", href=True)
            st_name       = a_tags[0].get_text(strip=True)
            system_name   = a_tags[1].get_text(strip=True)
            system_address= f"https://inara.cz{a_tags[1]['href']}"
            

            # 2) For each metal
            for metal in metals:
                link = soup.find("a", string=metal)
                if not link:
                    continue
                row   = link.find_parent("tr")
                cells = row.find_all("td")
                # buy price = 4th <td>, stock = 5th <td>
                buy_price = int(cells[3]["data-order"])
                stock     = int(cells[4]["data-order"])
                print(f"  • {metal} @ {st_name}: price={buy_price}, stock={stock}")
                if buy_price > 28_000 and stock > 19_000:
                    station_id = re.search(r'/(\d+)/$', url).group(1)
                    st_type = get_station_type(station_id)
                    key = f"{station_id}-{metal}"
                    last_time = last_ping.get(key)
                    if not last_time or (now - last_time) > datetime.timedelta(hours=cooldown_hours):
                        # build and send the message
                        msg = (
                            f"Hidden market detected at {st_name} ({st_type}), {url}\n"
                            f"System: {system_name}, {system_address}\n"
                            f"{metal} stock: {stock}"
                        )
                        send_to_discord(msg)
                        last_ping[key] = now
                        print(f"  • {metal} @ {st_name}: price={buy_price}, stock={stock}")
                        print(f"    ↪ alert sent, cooldown until {now + cooldown}")

        # wait before checking again
        time.sleep(30 * 60)  # 30 minutes


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
    url6= (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=6&pi16=14&ps2=&pa2%5B%5D=26"
    )
    # monitor both Gold and Silver
    monitor_metals([url1, url2, url3, url4, url5, url6], metals=["Gold"])
    
if __name__ == "__main__":
    main()
