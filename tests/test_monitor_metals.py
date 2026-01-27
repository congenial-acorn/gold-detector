import datetime
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold_detector.monitor as monitor


class StopMonitoring(Exception):
    """Raised to break out of the monitor loop during tests."""


HTML_TEMPLATE = """
<html>
  <body>
    <h2>
      <a href="/elite/station/123/">Example Station</a>
      <a href="/elite/system/456/">Example System</a>
    </h2>
    <table>
      <tr>
        <td>col1</td>
        <td>col2</td>
        <td><a href="#">Gold</a></td>
        <td data-order="29000">29,000</td>
        <td data-order="20000">20,000</td>
      </tr>
    </table>
  </body>
</html>
"""


class _FixedDateTime(datetime.datetime):
    _fixed_now = datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc)

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return cls._fixed_now.astimezone(tz)
        return cls._fixed_now


def test_monitor_metals_respects_cooldown(monkeypatch):
    calls = []

    def fake_send(message: str) -> None:
        calls.append(message)

    class FakeResponse:
        text = HTML_TEMPLATE

    monkeypatch.setattr(monitor, "send_to_discord", fake_send)
    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/123/"],
    )
    monkeypatch.setattr(monitor, "get_station_type", lambda station_id: "Outpost")
    monkeypatch.setattr(monitor.datetime, "datetime", _FixedDateTime)

    def fake_sleep(seconds):
        raise StopMonitoring

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)

    with pytest.raises(StopMonitoring):
        monitor.monitor_metals(["dummy"], ["Gold", "Gold"], cooldown_hours=1)

    assert len(calls) == 1


def test_monitor_metals_writes_to_market_database(monkeypatch, tmp_path):
    """
    Test that monitor_metals writes market entries to MarketDatabase.
    
    Verifies that:
    - begin_scan() is called at loop start
    - write_market_entry() is called when market detected with correct params
    - end_scan() is called at loop end with scanned systems
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)

    class FakeResponse:
        text = HTML_TEMPLATE

    monkeypatch.setattr(monitor, "send_to_discord", Mock())
    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/123/"],
    )
    monkeypatch.setattr(monitor, "get_station_type", lambda station_id: "Outpost")
    monkeypatch.setattr(monitor.datetime, "datetime", _FixedDateTime)

    def fake_sleep(seconds):
        raise StopMonitoring

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)

    with pytest.raises(StopMonitoring):
        # This will fail because monitor_metals doesn't accept market_db yet
        monitor.monitor_metals(
            ["dummy"],
            ["Gold"],
            cooldown_hours=1,
            market_db=mock_db,
        )

    # Verify database methods were called
    mock_db.begin_scan.assert_called_once()
    mock_db.write_market_entry.assert_called_once_with(
        system_name="Example System",
        system_address="https://inara.cz/elite/system/456/",
        station_name="Example Station",
        station_type="Outpost",
        url="https://inara.cz/elite/station-market/123/",
        metal="Gold",
        stock=20000,
    )
    mock_db.end_scan.assert_called_once()
    # Verify end_scan was called with a set containing the scanned system
    call_args = mock_db.end_scan.call_args
    assert isinstance(call_args[0][0], set)
    assert "https://inara.cz/elite/system/456/" in call_args[0][0]


def test_monitor_metals_uses_database_for_cooldowns(monkeypatch, tmp_path):
    """
    Test that monitor_metals uses MarketDatabase for cooldown checking.
    
    Verifies that:
    - check_cooldown() is called before sending to Discord
    - check_cooldown() receives correct cooldown_seconds parameter
    - mark_sent() is called after sending to Discord
    - recipient_type and recipient_id are passed correctly
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)
    # Simulate cooldown not expired (allow sending)
    mock_db.check_cooldown.return_value = True

    class FakeResponse:
        text = HTML_TEMPLATE

    send_mock = Mock()
    monkeypatch.setattr(monitor, "send_to_discord", send_mock)
    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/123/"],
    )
    monkeypatch.setattr(monitor, "get_station_type", lambda station_id: "Outpost")
    monkeypatch.setattr(monitor.datetime, "datetime", _FixedDateTime)

    def fake_sleep(seconds):
        raise StopMonitoring

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)

    with pytest.raises(StopMonitoring):
        # This will fail because monitor_metals doesn't accept market_db yet
        monitor.monitor_metals(
            ["dummy"],
            ["Gold"],
            cooldown_hours=1,
            market_db=mock_db,
        )

    # Verify cooldown check was called before sending
    mock_db.check_cooldown.assert_called_once()
    call_args = mock_db.check_cooldown.call_args
    assert call_args[1]["system_name"] == "Example System"
    assert call_args[1]["station_name"] == "Example Station"
    assert call_args[1]["metal"] == "Gold"
    assert call_args[1]["cooldown_seconds"] == 3600  # 1 hour in seconds
    # Should have recipient_type and recipient_id
    assert "recipient_type" in call_args[1]
    assert "recipient_id" in call_args[1]

    # Verify send was called
    send_mock.assert_called_once()

    # Verify mark_sent was called after sending
    mock_db.mark_sent.assert_called_once()
    mark_args = mock_db.mark_sent.call_args
    assert mark_args[1]["system_name"] == "Example System"
    assert mark_args[1]["station_name"] == "Example Station"
    assert mark_args[1]["metal"] == "Gold"
    assert "recipient_type" in mark_args[1]
    assert "recipient_id" in mark_args[1]


def test_monitor_metals_respects_database_cooldown(monkeypatch, tmp_path):
    """
    Test that monitor_metals respects cooldown from MarketDatabase.
    
    Verifies that:
    - When check_cooldown() returns False, no message is sent
    - mark_sent() is NOT called when cooldown is active
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)
    # Simulate cooldown still active (prevent sending)
    mock_db.check_cooldown.return_value = False

    class FakeResponse:
        text = HTML_TEMPLATE

    send_mock = Mock()
    monkeypatch.setattr(monitor, "send_to_discord", send_mock)
    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/123/"],
    )
    monkeypatch.setattr(monitor, "get_station_type", lambda station_id: "Outpost")
    monkeypatch.setattr(monitor.datetime, "datetime", _FixedDateTime)

    def fake_sleep(seconds):
        raise StopMonitoring

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)

    with pytest.raises(StopMonitoring):
        # This will fail because monitor_metals doesn't accept market_db yet
        monitor.monitor_metals(
            ["dummy"],
            ["Gold"],
            cooldown_hours=1,
            market_db=mock_db,
        )

    # Verify cooldown check was called
    mock_db.check_cooldown.assert_called_once()

    # Verify send was NOT called (cooldown active)
    send_mock.assert_not_called()

    # Verify mark_sent was NOT called (cooldown active)
    mock_db.mark_sent.assert_not_called()
