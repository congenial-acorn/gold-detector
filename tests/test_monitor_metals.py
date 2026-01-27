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
    """Test that monitor_metals writes to database and doesn't directly send messages."""
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = False  # Simulate cooldown active

    class FakeResponse:
        text = HTML_TEMPLATE

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
        monitor.monitor_metals(["dummy"], ["Gold", "Gold"], cooldown_hours=1, market_db=mock_db)

    # Verify database methods were called
    mock_db.begin_scan.assert_called_once()
    mock_db.check_cooldown.assert_called()  # Called twice (once for each "Gold")
    mock_db.mark_sent.assert_not_called()  # Should NOT mark sent if cooldown active


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

    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = True  # Allow sending

    class FakeResponse:
        text = HTML_TEMPLATE

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
    Test that monitor_metals writes to database when cooldown allows.

    With database-driven dispatch, monitor_metals only writes to database.
    Dispatch happens via messenger.dispatch_from_database() after scan completes.
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = True  # Allow sending

    class FakeResponse:
        text = HTML_TEMPLATE

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
        monitor.monitor_metals(
            ["dummy"],
            ["Gold"],
            cooldown_hours=1,
            market_db=mock_db,
        )

    mock_db.write_market_entry.assert_called_once()
    mock_db.mark_sent.assert_called_once()
    call_args = mock_db.write_market_entry.call_args
    assert call_args[1]["system_name"] == "Example System"
    assert call_args[1]["station_name"] == "Example Station"
    assert call_args[1]["metal"] == "Gold"


def test_monitor_metals_respects_database_cooldown(monkeypatch, tmp_path):
    """
    Test that monitor_metals respects cooldown from MarketDatabase.

    Verifies that:
    - When check_cooldown() returns False, no message is sent
    - mark_sent() is NOT called when cooldown is active
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)
    # Simulate cooldown still active (prevent sending)
    mock_db.check_cooldown.return_value = False

    class FakeResponse:
        text = HTML_TEMPLATE

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
        monitor.monitor_metals(
            ["dummy"],
            ["Gold"],
            cooldown_hours=1,
            market_db=mock_db,
        )

    # Verify cooldown check was called
    mock_db.check_cooldown.assert_called_once()

    # Verify mark_sent was NOT called (cooldown active)
    mock_db.mark_sent.assert_not_called()
