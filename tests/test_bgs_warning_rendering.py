from typing import Any

from gold_detector.messaging import DiscordMessenger


def _render_warning(states: tuple[str, ...]) -> str:
    messenger = object.__new__(DiscordMessenger)
    market_line: dict[str, Any] = {
        "system_name": "Albarib",
        "system_address": "https://example.com/system",
        "station_name": "Hale Orbital",
        "station_type": "Outpost",
        "url": "https://example.com/station",
        "metal": "Gold",
        "stock": 20_000,
        "bgs_states": states,
    }
    return messenger._build_message([market_line], [], {}).splitlines()[-1]


def test_bgs_warning_uses_singular_state_for_one_detected_state() -> None:
    assert _render_warning(("Boom",)) == (
        "Boom state is present, supply will be reduced."
    )


def test_bgs_warning_uses_plural_states_for_multiple_detected_states() -> None:
    assert _render_warning(("Boom", "Famine")) == (
        "Boom, Famine states are present, supply will be reduced."
    )
