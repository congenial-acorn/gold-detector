import logging
import os
import sys

from gold_detector.alert_helpers import (
    GOLD_NUM,
    PALLADIUM_NUM,
    assemble_commodity_links,
    assemble_hidden_market_messages,
    mask_commodity_links,
)
from gold_detector.emitter import (
    emit_loop_done,
    send_to_discord,
    set_emitter,
    set_loop_done_emitter,
)
from gold_detector.http_client import http_get
from gold_detector.inara_client import get_station_market_urls, get_station_type
from gold_detector.monitor import monitor_metals
from gold_detector.powerplay import get_powerplay_status

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


def main():
    monitor_metals(nearest_station_urls(), metals=["Gold", "Palladium"])


if __name__ == "__main__":
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    main()
