import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.edsm_client import (
    EdsmDataError,
    fetch_system_factions,
    parse_system_factions,
    parse_system_stations,
)


def test_parse_system_stations_returns_id64_and_station_metadata() -> None:
    payload = {
        "id64": 10477373803,
        "stations": [
            {
                "name": "Abraham Lincoln",
                "type": "Orbis Starport",
                "controllingFaction": {"name": "Mother Gaia"},
            }
        ],
    }

    result = parse_system_stations(payload)

    assert result.id64 == 10477373803
    assert result.stations[0].name == "Abraham Lincoln"
    assert result.stations[0].station_type == "Starport (Orbis Starport)"
    assert result.stations[0].controlling_faction == "Mother Gaia"


def test_parse_system_stations_maps_surface_port_types() -> None:
    payload = {
        "id64": 123,
        "stations": [
            {
                "name": "Surface Site",
                "type": "Planetary Port",
                "controllingFaction": {"name": "Surface Owners"},
            }
        ],
    }

    result = parse_system_stations(payload)

    assert result.stations[0].station_type == "Surface Port (Planetary Port)"


def test_parse_system_factions_reads_active_states() -> None:
    payload = {
        "factions": [
            {
                "name": "Imperial Enforcement Division",
                "activeStates": [
                    {"state": "Boom"},
                    {"state": "Infrastructure Failure"},
                ],
            }
        ]
    }

    result = parse_system_factions(payload)

    assert result.factions[0].active_states == (
        "Boom",
        "Infrastructure Failure",
    )


def test_parse_system_stations_rejects_missing_id64() -> None:
    with pytest.raises(EdsmDataError, match="system id64"):
        parse_system_stations({"stations": []})


def test_fetch_system_factions_refreshes_each_call(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResponse:
        @staticmethod
        def json() -> object:
            return {"factions": []}

    def fake_get(url: str) -> FakeResponse:
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr("gold_detector.edsm_client.http_get", fake_get)

    fetch_system_factions("Sol")
    fetch_system_factions("Sol")

    assert len(calls) == 2
