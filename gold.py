import logging
import os
import sys
from pathlib import Path

from gold_detector.commodities import commodity_names
from gold_detector.emitter import set_loop_done_emitter  # noqa: F401
from gold_detector.market_database import MarketDatabase
from gold_detector.monitor import monitor_metals

logger = logging.getLogger("gold")

_NEAREST_STATION_URLS = [
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=3&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26",
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=6&pi16=99&pi1=0&pi17=0&pa2%5B%5D=26",
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=3&pi16=2&pa2%5B%5D=26",
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=6&pi16=2&pi1=0&pi17=0&pa2%5B%5D=26",
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=3&pi16=14&ps2=&pa2%5B%5D=26",
    "https://inara.cz/elite/nearest-stations/?formbrief=1&ps1=Sol&pi15=6&pi16=14&ps2=&pa2%5B%5D=26",
]


def nearest_station_urls():
    return list(_NEAREST_STATION_URLS)


def main(market_db: MarketDatabase | None = None):
    """
    Run the monitor loop.

    Args:
        market_db: Optional shared MarketDatabase instance. When provided
            (e.g. by bot.py via GoldRunner), the monitor and the messenger
            share the same in-memory state so dispatch sees fresh writes.
            When None (standalone ``python gold.py``), a new instance is
            constructed against ``market_database.json`` in the CWD.
    """
    if market_db is None:
        db_path = Path("market_database.json")
        market_db = MarketDatabase(db_path)
    monitor_metals(
        nearest_station_urls(), metals=commodity_names(), market_db=market_db
    )


if __name__ == "__main__":
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
