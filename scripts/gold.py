import re
import time
import datetime
from datetime import timezone
import requests
from bs4 import BeautifulSoup

# Mark-and-print helper so the bot forwards only what you choose
DISCORD_PREFIX = "__DISCORD__"
PING_TOKEN = os.getenv("PING_TOKEN", "[PING]")


def send_to_bot(message: str, *, ping: bool = False):
    """Prints a marked line that the bot forwards. Set ping=True to request a role mention."""
    if ping:
        print(f"{DISCORD_PREFIX} {PING_TOKEN} {message}", flush=True)
    else:
        print(f"{DISCORD_PREFIX} {message}", flush=True)



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

def monitor_metals(near_urls, metals, cooldown_hours=48):
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

            # 2) Station type is the text right below the H2, e.g. "Refinery (Alliance Democracy)"
            st_type_text = soup.find(string=re.compile(r'^[A-Za-z ]+\s*\(.+\)$'))
            st_type = st_type_text.split("(",1)[0].strip() if st_type_text else "Unknown"

            # 3) For each metal
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
                    key = f"{station_id}-{metal}"
                    last_time = last_ping.get(key)
                    if not last_time or (now - last_time) > datetime.timedelta(hours=cooldown_hours):
                        # build and send the message
                        msg = (
                            f"Hidden market detected at {st_name}, {url}\n"
                            f"System: {system_name}, {system_address}\n"
                            f"Stock: {stock}"
                        )
                        send_to_bot(msg, ping=True)
                        last_ping[key] = now
                        print(f"  • {metal} @ {st_name}: price={buy_price}, stock={stock}")
                        print(f"    ↪ alert sent, cooldown until {now + cooldown}")

        # wait before checking again
        time.sleep(5 * 60)  # 5 minutes

if __name__ == "__main__":
    url1 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=3&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26"
    )
    url2 = (
        "https://inara.cz/elite/nearest-stations/"
        "?formbrief=1&ps1=Sol&pi15=6&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26"
    )

    # monitor both Gold and Silver
    monitor_metals([url1, url2], metals=["Gold", "Silver"])
