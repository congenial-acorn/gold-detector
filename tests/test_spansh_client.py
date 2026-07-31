import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.spansh_client import (
    SpanshDataError,
    fetch_powerplay,
    parse_powerplay,
)


def test_parse_powerplay_returns_current_control_data() -> None:
    payload = {
        "record": {
            "controlling_power": "Jerome Archer",
            "power_state": "Stronghold",
            "power_state_control_progress": 0.632343,
        }
    }

    result = parse_powerplay(payload)

    assert result is not None
    assert result.power == "Jerome Archer"
    assert result.status == "Stronghold"
    assert result.progress == "63.2%"


def test_parse_powerplay_returns_none_for_unoccupied_system() -> None:
    payload = {
        "record": {
            "controlling_power": None,
            "power_state": "Unoccupied",
        }
    }

    assert parse_powerplay(payload) is None


def test_parse_powerplay_rejects_missing_control_fields() -> None:
    with pytest.raises(SpanshDataError):
        parse_powerplay({"record": {"name": "Malformed System"}})


def test_parse_powerplay_accepts_unoccupied_without_controlling_power() -> None:
    assert parse_powerplay({"record": {"power_state": "Unoccupied"}}) is None


def test_parse_powerplay_rejects_missing_record() -> None:
    with pytest.raises(SpanshDataError, match="record"):
        parse_powerplay({})


def test_fetch_powerplay_refreshes_each_call(monkeypatch) -> None:
    calls: list[str] = []

    class FakeResponse:
        @staticmethod
        def json() -> object:
            return {
                "record": {
                    "controlling_power": None,
                    "power_state": "Unoccupied",
                }
            }

    def fake_get(url: str) -> FakeResponse:
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr("gold_detector.spansh_client.http_get", fake_get)

    fetch_powerplay(10477373803)
    fetch_powerplay(10477373803)

    assert len(calls) == 2
