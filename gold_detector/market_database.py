"""Thread-safe JSON database for market opportunities and powerplay data."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Literal, NotRequired, TypedDict, cast


class SentToMap(TypedDict):
    guild: dict[str, bool]
    user: dict[str, bool]


class MetalEntry(TypedDict):
    stock: int
    sent_to: SentToMap


class PowerplayEntry(TypedDict):
    power: str
    status: str
    progress: int
    commodity_urls: str


class StationEntry(TypedDict):
    station_type: str
    url: str
    metals: dict[str, MetalEntry]


class SystemEntry(TypedDict):
    system_address: str
    stations: dict[str, StationEntry]
    powerplay: NotRequired[PowerplayEntry]


RecipientType = Literal["guild", "user"]
DatabaseData = dict[str, SystemEntry]
JsonDict = dict[str, object]

logger = logging.getLogger("gold.database")


class MarketDatabase:
    """Thread-safe database for Elite Dangerous market opportunities."""

    def __init__(self, path: Path):
        """
        Initialize MarketDatabase.

        Args:
            path: Path to the JSON database file
        """
        self.path: Path = path
        logger.debug("MarketDatabase initialized with path: %s", self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock: threading.Lock = threading.Lock()
        self._data: DatabaseData = self._load()
        if self._strip_legacy_cooldowns(self._data):
            self._save(self._data)
        self._scan_in_progress: bool = False

    def _load(self) -> DatabaseData:
        """
        Load data from disk.

        Returns:
            Dictionary containing all market data, or empty dict if file doesn't exist
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                loaded: object = json.load(f)
                if isinstance(loaded, dict):
                    return cast(DatabaseData, loaded)
        except Exception:
            pass
        return {}

    def _save(self, data: DatabaseData) -> None:
        """
        Save data to disk using atomic write pattern.

        Args:
            data: Dictionary to save
        """
        logger.debug(
            "_save() called: path=%s, writing %d systems", self.path, len(data)
        )
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            _ = tmp.replace(self.path)
            logger.debug(
                "Successfully wrote data to %s (atomic replace complete)", self.path
            )
        except Exception as e:
            if tmp.exists():
                tmp.unlink()
            logger.error(
                "Failed to save database to %s: %s", self.path, e, exc_info=True
            )
            raise

    @staticmethod
    def _empty_sent_to() -> SentToMap:
        return {"guild": {}, "user": {}}

    def _normalize_metal_entry(self, metal_data: object) -> MetalEntry:
        if not isinstance(metal_data, dict):
            return {"stock": 0, "sent_to": self._empty_sent_to()}

        metal_dict = cast(JsonDict, metal_data)
        sent_to = metal_dict.get("sent_to")
        normalized_sent_to = self._empty_sent_to()
        if isinstance(sent_to, dict):
            sent_to_dict = cast(JsonDict, sent_to)
            for recipient_type in ("guild", "user"):
                recipients = sent_to_dict.get(recipient_type)
                if isinstance(recipients, dict):
                    recipient_dict = cast(JsonDict, recipients)
                    normalized_sent_to[recipient_type] = {
                        str(recipient_id): bool(sent)
                        for recipient_id, sent in recipient_dict.items()
                        if sent
                    }

        return {
            "stock": self._coerce_int(metal_dict.get("stock", 0)),
            "sent_to": normalized_sent_to,
        }

    @staticmethod
    def _coerce_int(value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        return 0

    def _strip_legacy_cooldowns(self, data: DatabaseData) -> bool:
        changed = False

        for system_data in data.values():
            powerplay = system_data.get("powerplay")
            if isinstance(powerplay, dict) and "cooldowns" in powerplay:
                legacy_powerplay = cast(JsonDict, powerplay)
                del legacy_powerplay["cooldowns"]
                changed = True

            for station_data in system_data["stations"].values():
                metals = station_data.get("metals")
                for metal_name, metal_data in list(metals.items()):
                    normalized = self._normalize_metal_entry(metal_data)
                    if not isinstance(metal_data, dict):
                        metals[metal_name] = normalized
                        changed = True
                        continue

                    legacy_metal = cast(JsonDict, cast(object, metal_data))

                    if "cooldowns" in legacy_metal:
                        del legacy_metal["cooldowns"]
                        changed = True

                    if legacy_metal.get("sent_to") != normalized["sent_to"]:
                        legacy_metal["sent_to"] = normalized["sent_to"]
                        changed = True

                    stock_value = legacy_metal.get("stock", 0)
                    normalized_stock = self._coerce_int(stock_value)
                    if stock_value != normalized_stock:
                        legacy_metal["stock"] = normalized_stock
                        changed = True

        return changed

    def _save_locked(self) -> None:
        try:
            self._save(self._data)
        except Exception:
            self._data = self._load()
            raise

    def write_market_entry(
        self,
        system_name: str,
        system_address: str,
        station_name: str,
        station_type: str,
        url: str,
        metal: str,
        stock: int,
    ) -> None:
        """
        Write or update a market entry for a station's metal stock.

        Creates system/station/metal hierarchy as needed. Preserves existing
        cooldown data when updating stock.

        Args:
            system_name: Name of the system
            system_address: Unique system address
            station_name: Name of the station
            station_type: Type of station (e.g., "Coriolis Starport")
            url: URL to station info (e.g., Inara link)
            metal: Metal commodity name (e.g., "Gold")
            stock: Current stock amount
        """
        with self._lock:
            data = self._data

            # Ensure system exists
            if system_name not in data:
                data[system_name] = {
                    "system_address": system_address,
                    "stations": {},
                }

            # Update system address
            data[system_name]["system_address"] = system_address

            # Ensure stations dict exists
            if "stations" not in data[system_name]:
                data[system_name]["stations"] = {}

            # Ensure station exists
            if station_name not in data[system_name]["stations"]:
                data[system_name]["stations"][station_name] = {
                    "station_type": station_type,
                    "url": url,
                    "metals": {},
                }

            # Update station info
            data[system_name]["stations"][station_name]["station_type"] = station_type
            data[system_name]["stations"][station_name]["url"] = url

            # Ensure metals dict exists
            if "metals" not in data[system_name]["stations"][station_name]:
                data[system_name]["stations"][station_name]["metals"] = {}

            existing_sent_to = self._empty_sent_to()
            existing_metal = data[system_name]["stations"][station_name]["metals"].get(
                metal
            )
            if existing_metal is not None:
                existing_sent_to = self._normalize_metal_entry(existing_metal)[
                    "sent_to"
                ]

            data[system_name]["stations"][station_name]["metals"][metal] = {
                "stock": stock,
                "sent_to": existing_sent_to,
            }
            self._save_locked()

    def write_powerplay_entry(
        self,
        system_name: str,
        system_address: str,
        power: str,
        status: str,
        progress: int,
        commodity_urls: str = "",
    ) -> None:
        """Write or update powerplay data for a system."""
        logger.info(
            "write_powerplay_entry called: system_name=%s, system_address=%s, power=%s, status=%s, progress=%s, commodity_urls=%s",
            system_name,
            system_address,
            power,
            status,
            progress,
            commodity_urls,
        )
        with self._lock:
            data = self._data

            # Ensure system exists
            if system_name not in data:
                data[system_name] = {
                    "system_address": system_address,
                    "stations": {},
                }

            # Update system address
            data[system_name]["system_address"] = system_address

            data[system_name]["powerplay"] = {
                "power": power,
                "status": status,
                "progress": progress,
                "commodity_urls": commodity_urls,
            }

            # Ensure stations dict exists
            if "stations" not in data[system_name]:
                data[system_name]["stations"] = {}

            logger.debug(
                "About to save powerplay data for system %s: powerplay=%s",
                system_name,
                data[system_name].get("powerplay"),
            )

            self._save_locked()

            logger.info("Successfully saved powerplay entry for system %s", system_name)

    def clear_powerplay_entry(self, system_name: str) -> None:
        """Remove powerplay data for a system, preserving stations and metals.

        No-op if the system is unknown or has no powerplay block.
        Used when a system refreshes as non-Fortified/Stronghold so stale
        powerplay data does not keep appearing in future market messages.
        """
        logger.info("clear_powerplay_entry called: system_name=%s", system_name)
        with self._lock:
            system = self._data.get(system_name)
            if system is None:
                return
            if "powerplay" not in system:
                return
            del system["powerplay"]
            self._save_locked()
            logger.info("Cleared stale powerplay entry for system %s", system_name)

    def read_all_entries(self) -> DatabaseData:
        """
        Read all market entries from the database.

        Returns:
            Dictionary containing all systems with their stations, metals, and powerplay data
        """
        with self._lock:
            return self._data

    def has_market_alert_been_sent(
        self,
        system_name: str,
        station_name: str,
        metal: str,
        recipient_type: RecipientType | str,
        recipient_id: str,
    ) -> bool:
        with self._lock:
            if recipient_type not in {"guild", "user"}:
                return False

            data = self._data

            if system_name not in data:
                return False
            if "stations" not in data[system_name]:
                return False
            if station_name not in data[system_name]["stations"]:
                return False
            if "metals" not in data[system_name]["stations"][station_name]:
                return False
            if metal not in data[system_name]["stations"][station_name]["metals"]:
                return False

            metal_data = data[system_name]["stations"][station_name]["metals"][metal]
            sent_to = metal_data["sent_to"]
            recipients = sent_to[cast(RecipientType, recipient_type)]
            return recipients.get(recipient_id, False) is True

    def mark_market_alerts_sent_batch(
        self, entries: list[tuple[str, str, str, str, str]]
    ) -> None:
        if not entries:
            return

        with self._lock:
            data = self._data

            for (
                system_name,
                station_name,
                metal,
                recipient_type,
                recipient_id,
            ) in entries:
                if recipient_type not in {"guild", "user"}:
                    continue
                if system_name not in data:
                    continue
                if "stations" not in data[system_name]:
                    continue
                if station_name not in data[system_name]["stations"]:
                    continue
                if "metals" not in data[system_name]["stations"][station_name]:
                    continue
                metals = data[system_name]["stations"][station_name]["metals"]
                if metal not in metals:
                    continue

                metal_data = self._normalize_metal_entry(metals[metal])
                recipients = metal_data["sent_to"][cast(RecipientType, recipient_type)]
                recipients[recipient_id] = True
                metals[metal] = metal_data

            self._save_locked()

    def prune_stale(
        self,
        current_opportunities: set[tuple[str, str, str]],
        current_powerplay_systems: set[str] | None = None,
    ) -> None:
        """Prune inactive opportunities and optionally stale powerplay blocks."""
        with self._lock:
            data = self._data
            for system_name in list(data.keys()):
                system_data = data[system_name]
                stations = system_data["stations"]

                for station_name in list(stations.keys()):
                    station_data = stations[station_name]
                    metals = station_data["metals"]

                    for metal in list(metals.keys()):
                        if (
                            system_name,
                            station_name,
                            metal,
                        ) not in current_opportunities:
                            del metals[metal]

                    if not metals:
                        del stations[station_name]

                if current_powerplay_systems is not None and (
                    system_name not in current_powerplay_systems
                ):
                    _ = system_data.pop("powerplay", None)

                has_stations = bool(system_data.get("stations"))
                has_powerplay = bool(system_data.get("powerplay"))
                if not has_stations and not has_powerplay:
                    del data[system_name]

            self._save_locked()

    def begin_scan(self) -> None:
        """
        Mark the beginning of a scan operation.

        This tracks that a scan is in progress to help with pruning logic.
        """
        with self._lock:
            self._scan_in_progress = True

    def end_scan(
        self,
        current_opportunities: set[tuple[str, str, str]],
        powerplay_systems: set[str] | None = None,
    ) -> None:
        """
        Mark the end of a scan operation and prune stale opportunities.
        """
        with self._lock:
            self._scan_in_progress = False

        self.prune_stale(current_opportunities, powerplay_systems)
