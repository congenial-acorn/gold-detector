import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.message_filters import filter_message_for_preferences  # noqa: E402


ALERT_MESSAGE = """Hidden markets detected in Example System (<addr>):
- Alpha (Starport), <https://example.com/a> - Gold stock: 20000; Palladium stock: 18000
- Bravo (Outpost), <https://example.com/b> - Palladium stock: 22000
"""


def test_station_type_filters_out_mismatched_lines():
    filtered = filter_message_for_preferences(
        ALERT_MESSAGE, {"station_type": ["Starport"], "commodity": []}
    )
    assert filtered is not None
    assert "Starport" in filtered
    assert "Outpost" not in filtered


def test_commodity_filter_removes_unpreferred_entries_and_lines():
    filtered = filter_message_for_preferences(
        ALERT_MESSAGE, {"commodity": ["Gold"], "station_type": []}
    )
    assert filtered is not None
    assert "Gold stock: 20000" in filtered
    assert "Palladium stock: 18000" not in filtered
    assert "Bravo" not in filtered  # entire line removed (no preferred commodities)


def test_no_preferences_leave_message_unchanged():
    filtered = filter_message_for_preferences(ALERT_MESSAGE, {})
    assert filtered == ALERT_MESSAGE


def test_powerplay_preferences_control_delivery():
    pp_message = "Powerplay info for Sol: power=Jerome Archer; status=Fortified"

    allowed = filter_message_for_preferences(
        pp_message, {"powerplay": ["Jerome Archer"]}
    )
    blocked = filter_message_for_preferences(
        pp_message, {"powerplay": ["Aisling Duval"]}
    )

    assert allowed == pp_message
    assert blocked is None
