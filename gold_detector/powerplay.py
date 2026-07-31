import logging
from typing import List, Optional, Set

from .alert_helpers import assemble_commodity_links, mask_commodity_links
from .commodities import name_to_id_map
from .edsm_client import fetch_system_stations
from .http_client import http_get
from .market_database import MarketDatabase
from .spansh_client import fetch_powerplay

logger = logging.getLogger("gold.powerplay")


def _build_commodity_ids(system: List[str]) -> List[int]:
    _name_to_id = name_to_id_map()
    return [_name_to_id[item] for item in system if item in _name_to_id]


def _clear_stale_powerplay(
    market_db: Optional[MarketDatabase], system_name: Optional[str]
) -> None:
    """Clear stale powerplay data when a system is no longer a Fortified/Stronghold opportunity.

    Guards against missing market_db (standalone caller) and empty system names.
    """
    if market_db and system_name:
        market_db.clear_powerplay_entry(system_name)


def get_powerplay_status(
    systems,
    market_db: Optional[MarketDatabase] = None,
    failed_systems: Optional[Set[str]] = None,
) -> Set[str]:
    """Check each system in the list for Powerplay status."""
    processed_systems: Set[str] = set()
    for system in systems:
        if len(system) < 2:
            continue
        system_name = system[0]
        system_url = system[1]
        try:
            edsm_system = fetch_system_stations(system_name)
            powerplay = fetch_powerplay(edsm_system.id64)
            if powerplay is None:
                logger.info("No Powerplay control data found for %s", system_name)
                _clear_stale_powerplay(market_db, system_name)
                continue

            if powerplay.status not in {"Fortified", "Stronghold"}:
                logger.info(
                    "Powerplay status %s is not Fortified/Stronghold for %s",
                    powerplay.status,
                    system_name,
                )
                _clear_stale_powerplay(market_db, system_name)
                continue

            ids = _build_commodity_ids(system[2:])
            distance = 20 if powerplay.status == "Fortified" else 30
            commodity_url = assemble_commodity_links(
                ids, system_name, distance, fetch=http_get
            )
            if not commodity_url:
                logger.debug(
                    "No commodity links found for %s system %s",
                    powerplay.status,
                    system_name,
                )
                _clear_stale_powerplay(market_db, system_name)
                continue

            masked_links = mask_commodity_links(commodity_url)
            if market_db:
                market_db.write_powerplay_entry(
                    system_name=system_name,
                    system_address=system_url,
                    power=powerplay.power,
                    status=powerplay.status,
                    progress=powerplay.progress,
                    commodity_urls=masked_links,
                )
                processed_systems.add(system_name)

            logger.info(
                "Powerplay opportunity: %s is a %s %s system",
                system_name,
                powerplay.power,
                powerplay.status,
            )

        except Exception as exc:  # noqa: BLE001
            if failed_systems is not None:
                failed_systems.add(system_name)
            logger.error(
                "Failed to fetch Powerplay status from %s: %s",
                system_url,
                exc,
                exc_info=True,
            )
            continue

    return processed_systems
