import logging
import re
from typing import Any, List, Optional, Set

from bs4 import BeautifulSoup

from .alert_helpers import (
    GOLD_NUM,
    PALLADIUM_NUM,
    assemble_commodity_links,
    mask_commodity_links,
)
from .http_client import http_get
from .market_database import MarketDatabase

logger = logging.getLogger("gold.powerplay")


def _parse_powerplay_fields(block) -> dict[str, Any]:
    power_link = block.find("a", href=re.compile(r"/elite/power/\d+/?"))
    power_name = power_link.get_text(strip=True) if power_link else None

    role_tag = block.find("small")
    role_text = role_tag.get_text(" ", strip=True).strip("()") if role_tag else None

    status_tag = block.find("span", class_=lambda c: c and "bigger" in c.split())
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

    return {
        "power": power_name,
        "role": role_text,
        "status": status_text,
        "progress": percent_text,
        "parts": parts,
    }


def _build_commodity_ids(system: List[str]) -> List[int]:
    ids: List[int] = []
    for item in system:
        if item == "Gold":
            ids.append(GOLD_NUM)
        elif item == "Palladium":
            ids.append(PALLADIUM_NUM)
    return ids


def get_powerplay_status(
    systems, market_db: Optional[MarketDatabase] = None
) -> Set[str]:
    """Check each system in the list for Powerplay status."""
    processed_systems: Set[str] = set()
    for system in systems:
        system_url = system[0]
        try:
            resp = http_get(system_url)
            soup = BeautifulSoup(resp.text, "html.parser")

            system_name = None
            h2 = soup.find("h2")
            if h2:
                raw_name = h2.get_text(" ", strip=True)
                system_name = re.sub(r"[\uE000-\uF8FF]", "", raw_name)
                system_name = re.sub(r"\\u[0-9a-fA-F]{4}", "", system_name).strip()
                # Strip unicode variation selectors (VS1-VS16) to prevent name mismatch with station pages
                system_name = re.sub(r"[\uFE00-\uFE0F]", "", system_name).strip()

            label = soup.find("span", string=re.compile(r"Powerplay", re.IGNORECASE))
            if not label:
                logger.info(
                    "No Powerplay section found for %s", system_name or system_url
                )
                continue

            block = label.find_parent("div")
            if block is None:
                logger.info(
                    "Powerplay section malformed for %s", system_name or system_url
                )
                continue

            fields = _parse_powerplay_fields(block)
            status_text = fields["status"]

            if not fields["parts"]:
                logger.info(
                    "Powerplay section present but empty for %s",
                    system_name or system_url,
                )
                continue

            msg = f"Powerplay info for {system_name or system_url}: " + "; ".join(
                fields["parts"]
            )
            logger.info(msg)

            ids = _build_commodity_ids(system)

            if status_text == "Unoccupied":
                logger.debug(
                    "Powerplay status is Unoccupied for %s", system_name or system_url
                )
                continue

            if status_text == "Fortified":
                commodity_url = assemble_commodity_links(
                    ids, system_name or "", 20, fetch=http_get
                )
                if not commodity_url:
                    logger.debug(
                        "No commodity links found for Fortified system %s",
                        system_name or system_url,
                    )
                    continue

                masked_links = mask_commodity_links(commodity_url)
                if market_db:
                    market_db.write_powerplay_entry(
                        system_name=system_name or "",
                        system_address=system_url,
                        power=fields["power"],
                        status=status_text,
                        progress=fields["progress"],
                        commodity_urls=masked_links,
                    )
                    processed_systems.add(system_name or "")

                logger.info(
                    "Powerplay opportunity: %s is a %s %s system with acquisition systems nearby",
                    system_name,
                    fields["power"],
                    status_text,
                )

            elif status_text == "Stronghold":
                commodity_url = assemble_commodity_links(
                    ids, system_name or "", 30, fetch=http_get
                )
                if not commodity_url:
                    logger.debug(
                        "No commodity links found for Stronghold system %s",
                        system_name or system_url,
                    )
                    continue

                masked_links = mask_commodity_links(commodity_url)
                if market_db:
                    market_db.write_powerplay_entry(
                        system_name=system_name or "",
                        system_address=system_url,
                        power=fields["power"],
                        status=status_text,
                        progress=fields["progress"],
                        commodity_urls=masked_links,
                    )
                    processed_systems.add(system_name or "")

                logger.info(
                    "Powerplay opportunity: %s is a %s %s system",
                    system_name,
                    fields["power"],
                    status_text,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Failed to fetch Powerplay status from %s: %s",
                system_url,
                exc,
                exc_info=True,
            )
            continue

    return processed_systems
