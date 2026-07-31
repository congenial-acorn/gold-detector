from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

from gold_detector.http_client import http_get

EDSM_STATIONS_URL = "https://www.edsm.net/api-system-v1/stations"
EDSM_FACTIONS_URL = "https://www.edsm.net/api-system-v1/factions"


class EdsmDataError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class EdsmStation:
    name: str
    station_type: str
    controlling_faction: str | None


@dataclass(frozen=True, slots=True)
class EdsmSystemStations:
    id64: int
    stations: tuple[EdsmStation, ...]


@dataclass(frozen=True, slots=True)
class EdsmFaction:
    name: str
    active_states: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EdsmSystemFactions:
    factions: tuple[EdsmFaction, ...]


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise EdsmDataError(f"EDSM {label} must be an object")
    return value


def _display_station_type(raw_type: str) -> str:
    normalized = raw_type.casefold()
    if "starport" in normalized:
        return f"Starport ({raw_type})"
    if normalized == "outpost":
        return "Outpost"
    if any(
        marker in normalized
        for marker in ("planetary", "surface", "settlement", "planet station")
    ):
        return f"Surface Port ({raw_type})"
    return raw_type


def parse_system_stations(payload: object) -> EdsmSystemStations:
    root = _mapping(payload, "stations response")
    id64 = root.get("id64")
    if not isinstance(id64, int) or isinstance(id64, bool):
        raise EdsmDataError("EDSM stations response is missing system id64")

    raw_stations = root.get("stations")
    if not isinstance(raw_stations, list):
        raise EdsmDataError("EDSM stations response is missing stations")

    stations: list[EdsmStation] = []
    for raw_station in raw_stations:
        station = _mapping(raw_station, "station")
        name = station.get("name")
        station_type = station.get("type")
        if not isinstance(name, str) or not isinstance(station_type, str):
            continue

        controlling_faction: str | None = None
        raw_faction = station.get("controllingFaction")
        if isinstance(raw_faction, Mapping):
            faction_name = raw_faction.get("name")
            if isinstance(faction_name, str):
                controlling_faction = faction_name

        stations.append(
            EdsmStation(
                name=name,
                station_type=_display_station_type(station_type),
                controlling_faction=controlling_faction,
            )
        )

    return EdsmSystemStations(id64=id64, stations=tuple(stations))


def parse_system_factions(payload: object) -> EdsmSystemFactions:
    root = _mapping(payload, "factions response")
    raw_factions = root.get("factions")
    if not isinstance(raw_factions, list):
        raise EdsmDataError("EDSM factions response is missing factions")

    factions: list[EdsmFaction] = []
    for raw_faction in raw_factions:
        faction = _mapping(raw_faction, "faction")
        name = faction.get("name")
        if not isinstance(name, str):
            continue

        active_states: list[str] = []
        raw_states = faction.get("activeStates", [])
        if isinstance(raw_states, list):
            for raw_state in raw_states:
                if not isinstance(raw_state, Mapping):
                    continue
                state = raw_state.get("state")
                if isinstance(state, str):
                    active_states.append(state)

        factions.append(EdsmFaction(name=name, active_states=tuple(active_states)))

    return EdsmSystemFactions(factions=tuple(factions))


@lru_cache(maxsize=512)
def fetch_system_stations(system_name: str) -> EdsmSystemStations:
    query = urlencode({"systemName": system_name})
    response = http_get(f"{EDSM_STATIONS_URL}?{query}")
    payload: object = response.json()
    return parse_system_stations(payload)


def fetch_system_factions(system_name: str) -> EdsmSystemFactions:
    query = urlencode({"systemName": system_name})
    response = http_get(f"{EDSM_FACTIONS_URL}?{query}")
    payload: object = response.json()
    return parse_system_factions(payload)


def clear_station_cache() -> None:
    fetch_system_stations.cache_clear()


def find_station(system: EdsmSystemStations, station_name: str) -> EdsmStation | None:
    target = station_name.casefold()
    return next(
        (station for station in system.stations if station.name.casefold() == target),
        None,
    )


def get_station_type(system_name: str, station_name: str) -> str:
    station = find_station(fetch_system_stations(system_name), station_name)
    return station.station_type if station is not None else "Unknown"
