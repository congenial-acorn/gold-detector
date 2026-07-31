from __future__ import annotations

import asyncio
import csv
import logging
from collections.abc import Awaitable, Callable, Collection, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Final

from requests import RequestException
from typing_extensions import override

from gold_detector.edsm_client import (
    EdsmDataError,
    EdsmSystemFactions,
    EdsmSystemStations,
    fetch_system_factions,
    fetch_system_stations,
)


SUPPLY_REDUCTION_THRESHOLD: Final = Decimal("0.8")
REFERENCE_DIR: Final = Path(__file__).resolve().parent / "data" / "bgs_effects"
EFFECT_FILES: Final = tuple(
    REFERENCE_DIR / filename
    for filename in ("gold_effects.csv", "palladium_effects.csv", "silver_effects.csv")
)
INFRASTRUCTURE_FAILURE: Final = "Infrastructure Failure"

SystemStationWarnings = dict[str, dict[str, tuple[str, ...]]]

logger = logging.getLogger("bot.bgs_states")


@dataclass(frozen=True, slots=True)
class SystemBgsQuery:
    system_name: str
    system_address: str
    station_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class BgsStateError(Exception):
    reason: str

    @override
    def __str__(self) -> str:
        return self.reason


BgsFetcher = Callable[[Sequence[SystemBgsQuery]], Awaitable[SystemStationWarnings]]


def load_reduced_supply_states(effect_files: Sequence[Path]) -> tuple[str, ...]:
    """Load states whose supply quantity is below the reduction threshold."""
    states: dict[str, str] = {}
    for effect_file in effect_files:
        with effect_file.open(encoding="utf-8", newline="") as file:
            for row in csv.DictReader(file):
                state_value = row.get("State")
                supply_quantity_value = row.get("Supply Quantity")
                if not state_value or supply_quantity_value is None:
                    raise BgsStateError("invalid BGS effect row")
                state = state_value.strip()
                try:
                    supply_quantity = Decimal(supply_quantity_value)
                except InvalidOperation as exc:
                    raise BgsStateError("invalid BGS effect row") from exc
                if (
                    supply_quantity < SUPPLY_REDUCTION_THRESHOLD
                    and state.casefold() != INFRASTRUCTURE_FAILURE.casefold()
                ):
                    states[state.casefold()] = state

    return tuple(sorted(states.values(), key=str.casefold))


def match_station_owner_reduced_supply_states(
    stations: EdsmSystemStations,
    factions: EdsmSystemFactions,
    station_names: Collection[str],
    reduced_supply_states: Collection[str],
) -> tuple[str, ...]:
    requested_stations = {station.casefold() for station in station_names}
    reduced_by_key = {state.casefold(): state for state in reduced_supply_states}
    owner_factions = {
        station.controlling_faction.casefold()
        for station in stations.stations
        if station.name.casefold() in requested_stations
        and station.controlling_faction is not None
    }

    matched_states: set[str] = set()
    for faction in factions.factions:
        if faction.name.casefold() not in owner_factions:
            continue
        active_state_keys = {state.casefold() for state in faction.active_states}
        if INFRASTRUCTURE_FAILURE.casefold() not in active_state_keys:
            continue
        for state_key in active_state_keys:
            state = reduced_by_key.get(state_key)
            if state is not None:
                matched_states.add(state)

    return tuple(sorted(matched_states, key=str.casefold))


async def fetch_system_reduced_supply_states(
    queries: Sequence[SystemBgsQuery],
) -> SystemStationWarnings:
    try:
        reduced_supply_states = load_reduced_supply_states(EFFECT_FILES)
    except (OSError, KeyError, InvalidOperation) as exc:
        raise BgsStateError("BGS effect data is unavailable") from exc
    warnings: SystemStationWarnings = {}

    for query in queries:
        try:
            stations = await asyncio.to_thread(fetch_system_stations, query.system_name)
            factions = await asyncio.to_thread(fetch_system_factions, query.system_name)
        except (EdsmDataError, RequestException) as exc:
            logger.warning("EDSM BGS lookup failed for %s: %s", query.system_name, exc)
            continue

        station_warnings: dict[str, tuple[str, ...]] = {}
        for station_name in sorted(query.station_names, key=str.casefold):
            states = match_station_owner_reduced_supply_states(
                stations,
                factions,
                frozenset({station_name}),
                reduced_supply_states,
            )
            if states:
                station_warnings[station_name] = states
        if station_warnings:
            warnings[query.system_name] = station_warnings

    return warnings
