import datetime
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from gold_detector.emitter import emit_loop_done
from gold_detector.http_client import http_get
from gold_detector.inara_client import get_station_market_urls, get_station_type
from gold_detector.market_database import MarketDatabase
from gold_detector.powerplay import get_powerplay_status

logger = logging.getLogger("gold.monitor")

MONITOR_INTERVAL_SECONDS = float(os.getenv("GOLD_MONITOR_INTERVAL_SECONDS", str(1800)))
PRICE_THRESHOLD = 28_000
STOCK_THRESHOLD = 15_000


def _parse_header(soup: BeautifulSoup, url: str):
    header = soup.find("h2")
    if header is None:
        logger.warning("Missing <h2> header on %s; skipping", url)
        return None

    a_tags = header.find_all("a", href=True)
    if len(a_tags) < 2:
        logger.warning("Incomplete header links on %s; skipping", url)
        return None

    st_name = a_tags[0].get_text(strip=True)
    system_name = a_tags[1].get_text(strip=True)
    system_address = f"https://inara.cz{a_tags[1]['href']}"
    return st_name, system_name, system_address


def _extract_price_and_stock(row):
    cells = row.find_all("td")
    if len(cells) < 5:
        return None, None
    try:
        buy_price = int(cells[3].get("data-order") or "0")
        stock = int(cells[4].get("data-order") or "0")
    except (TypeError, ValueError):
        return None, None
    return buy_price, stock


def _update_systems(
    systems: Dict[str, List[str]], system_address: str, metal: str
) -> None:
    metals = systems.setdefault(system_address, [])
    if metal not in metals:
        metals.append(metal)


def monitor_metals(near_urls, metals, cooldown_hours=0, market_db: Optional[MarketDatabase] = None):
    logger.info(
        "Starting monitor loop: checking %s metals with %sh cooldown",
        len(metals),
        cooldown_hours,
    )

    while True:
        try:
            systems: Dict[str, List[str]] = {}
            logger.info("=== Beginning new scan cycle ===")

            # Begin scan if using database
            if market_db:
                market_db.begin_scan()

            scanned_systems = set()
            market_urls = get_station_market_urls(near_urls)

            stations_checked = 0

            for url in market_urls:
                try:
                    resp = http_get(url)
                    soup = BeautifulSoup(resp.text, "html.parser")

                    header = _parse_header(soup, url)
                    if not header:
                        continue
                    st_name, system_name, system_address = header
                    stations_checked += 1
                    
                    scanned_systems.add(system_address)

                    for metal in metals:
                        link = soup.find("a", string=metal)
                        if not link:
                            continue

                        row = link.find_parent("tr")
                        if row is None:
                            logger.warning(
                                "No table row for %s at %s; skipping entry", metal, url
                            )
                            continue

                        buy_price, stock = _extract_price_and_stock(row)
                        if buy_price is None or stock is None:
                            logger.warning(
                                "Non-numeric price/stock for %s at %s; skipping entry",
                                metal,
                                url,
                            )
                            continue

                        logger.debug(
                            "%s @ %s: price=%s, stock=%s",
                            metal,
                            st_name,
                            buy_price,
                            stock,
                        )

                        if buy_price > PRICE_THRESHOLD and stock > STOCK_THRESHOLD:
                            match = re.search(r"/(\d+)/$", url)
                            if not match:
                                logger.warning("Could not extract station ID from URL: %s", url)
                                continue
                            station_id = match.group(1)
                            st_type = get_station_type(station_id)

                            _update_systems(systems, system_address, metal)

                            if market_db:
                                market_db.write_market_entry(
                                    system_name=system_name,
                                    system_address=system_address,
                                    station_name=st_name,
                                    station_type=st_type,
                                    url=url,
                                    metal=metal,
                                    stock=stock,
                                )
                                logger.info(
                                    "Found: %s @ %s - price=%s, stock=%s",
                                    metal,
                                    st_name,
                                    buy_price,
                                    stock,
                                )
                            else:
                                logger.info(
                                    "Found: %s @ %s - price=%s, stock=%s",
                                    metal,
                                    st_name,
                                    buy_price,
                                    stock,
                                )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Error processing station %s: %s", url, exc, exc_info=True
                    )
                    continue

            logger.info(
                "Scan complete: checked %s stations",
                stations_checked,
            )
            logger.info("Starting Powerplay check.")

            system_list = [[url] + found for url, found in systems.items()]
            if market_db:
                get_powerplay_status(system_list, market_db=market_db)
            else:
                get_powerplay_status(system_list)

            if market_db:
                market_db.end_scan(scanned_systems)

            try:
                emit_loop_done()
            except Exception as exc:  # noqa: BLE001
                logger.error("Loop-done emitter failed: %s", exc, exc_info=True)

            interval_seconds = max(0.0, MONITOR_INTERVAL_SECONDS)
            minutes = interval_seconds / 60.0
            logger.info(
                "Sleeping for %.0f seconds (%.1f minutes) until next scan at %s",
                interval_seconds,
                minutes,
                datetime.datetime.now() + datetime.timedelta(seconds=interval_seconds),
            )
            time.sleep(interval_seconds)

        except Exception as exc:  # noqa: BLE001
            logger.error("Fatal error in monitor loop: %s", exc, exc_info=True)
            raise
