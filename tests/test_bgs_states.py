from pathlib import Path

import pytest

from gold_detector.bgs_states import (
    BgsStateError,
    EFFECT_FILES,
    load_reduced_supply_states,
    match_station_owner_reduced_supply_states,
)
from gold_detector.edsm_client import (
    EdsmFaction,
    EdsmStation,
    EdsmSystemFactions,
    EdsmSystemStations,
)


def test_warning_states_for_stations_returns_qualifying_owner_states() -> None:
    stations = EdsmSystemStations(
        id64=123,
        stations=(
            EdsmStation(
                name="Hale Orbital",
                station_type="Outpost",
                controlling_faction="Imperial Enforcement Division",
            ),
        ),
    )
    factions = EdsmSystemFactions(
        factions=(
            EdsmFaction(
                name="Imperial Enforcement Division",
                active_states=("Boom", "Infrastructure Failure"),
            ),
        )
    )
    reduced_states = load_reduced_supply_states(EFFECT_FILES)

    states = match_station_owner_reduced_supply_states(
        stations,
        factions,
        frozenset({"Hale Orbital"}),
        reduced_states,
    )

    assert states == ("Boom",)


def test_reduced_supply_states_excludes_exact_threshold() -> None:
    # Given / When
    states = load_reduced_supply_states(EFFECT_FILES)

    # Then
    assert "Public Holiday" in states
    assert "Civil Unrest" not in states
    assert "Pirate Attack" not in states


def test_reduced_supply_states_excludes_infrastructure_failure() -> None:
    states = load_reduced_supply_states(EFFECT_FILES)

    assert "Infrastructure Failure" not in states


def test_warning_states_for_stations_ignores_unmatched_station() -> None:
    stations = EdsmSystemStations(
        id64=123,
        stations=(
            EdsmStation(
                name="Hale Orbital",
                station_type="Outpost",
                controlling_faction="Imperial Enforcement Division",
            ),
        ),
    )
    factions = EdsmSystemFactions(
        factions=(
            EdsmFaction(
                name="Imperial Enforcement Division",
                active_states=("Infrastructure Failure",),
            ),
        )
    )
    reduced_states = load_reduced_supply_states(EFFECT_FILES)

    states = match_station_owner_reduced_supply_states(
        stations,
        factions,
        frozenset({"Missing Station"}),
        reduced_states,
    )

    assert states == ()


def test_warning_states_rejects_owner_without_infrastructure_failure() -> None:
    stations = EdsmSystemStations(
        id64=123,
        stations=(
            EdsmStation(
                name="Hale Orbital",
                station_type="Outpost",
                controlling_faction="Imperial Enforcement Division",
            ),
        ),
    )
    factions = EdsmSystemFactions(
        factions=(
            EdsmFaction(
                name="Imperial Enforcement Division",
                active_states=("Boom",),
            ),
        )
    )

    states = match_station_owner_reduced_supply_states(
        stations,
        factions,
        frozenset({"Hale Orbital"}),
        load_reduced_supply_states(EFFECT_FILES),
    )

    assert states == ()


def test_load_reduced_supply_states_rejects_missing_quantity(tmp_path: Path) -> None:
    # Given
    malformed_csv = tmp_path / "effects.csv"
    _ = malformed_csv.write_text(
        "State,Supply Quantity,Supply Price,Demand Quantity,Demand Price\nBoom\n",
        encoding="utf-8",
    )

    # When / Then
    with pytest.raises(BgsStateError, match="invalid BGS effect row"):
        _ = load_reduced_supply_states((malformed_csv,))
