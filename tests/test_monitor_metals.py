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
    # end_scan receives active opportunity tuples, not scanned system names
    call_args = mock_db.end_scan.call_args
    assert call_args[0][0] == {("Example System", "Example Station", "Gold")}


HTML_SILVER_TEMPLATE = """
<html>
  <body>
    <h2>
      <a href="/elite/station/789/">Silver Station</a>
      <a href="/elite/system/1011/">Silver System</a>
    </h2>
    <table>
      <tr>
        <td>col1</td>
        <td>col2</td>
        <td><a href="#">Silver</a></td>
        <td data-order="35000">35,000</td>
        <td data-order="52000">52,000</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_monitor_metals_detects_silver(monkeypatch, tmp_path):
    """
    Test that monitor_metals detects Silver markets with the same logic as Gold.

    Verifies that Silver is treated identically to Gold/Palladium in logic,
    differing only by its higher stock threshold:
    price > 28,000 and stock > 50,000 triggers a market entry write.
    """
    from unittest.mock import Mock
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)

    class FakeResponse:
        text = HTML_SILVER_TEMPLATE

    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/789/"],
    )
    monkeypatch.setattr(monitor, "get_station_type", lambda station_id: "Starport")
    monkeypatch.setattr(monitor.datetime, "datetime", _FixedDateTime)

    def fake_sleep(seconds):
        raise StopMonitoring

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)

    with pytest.raises(StopMonitoring):
        monitor.monitor_metals(
            ["dummy"],
            ["Silver"],
            market_db=mock_db,
        )

    # Verify database methods were called
    mock_db.begin_scan.assert_called_once()
    mock_db.write_market_entry.assert_called_once_with(
        system_name="Silver System",
        system_address="https://inara.cz/elite/system/1011/",
        station_name="Silver Station",
        station_type="Starport",
        url="https://inara.cz/elite/station-market/789/",
        metal="Silver",
        stock=52000,
    )
    mock_db.end_scan.assert_called_once()
    call_args = mock_db.end_scan.call_args
    assert call_args[0][0] == {("Silver System", "Silver Station", "Silver")}


# ---------------------------------------------------------------------------
# Per-commodity threshold tests
# ---------------------------------------------------------------------------

HTML_CUSTOM_THRESHOLD = """
<html>
  <body>
    <h2>
      <a href="/elite/station/555/">Custom Station</a>
      <a href="/elite/system/666/">Custom System</a>
    </h2>
    <table>
      <tr>
        <td>col1</td>
        <td>col2</td>
        <td><a href="#">Gold</a></td>
        <td data-order="25000">25,000</td>
        <td data-order="12000">12,000</td>
      </tr>
    </table>
  </body>
</html>
"""


def test_monitor_uses_per_commodity_thresholds_lower(monkeypatch):
    """Monitor should write entry when price/stock exceed a custom *lower* threshold
    even though they fall below the default 28k/15k."""
    from unittest.mock import Mock

    from gold_detector.commodities import Commodity
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)

    custom_gold = Commodity(
        name="Gold",
        inara_id=42,
        price_threshold=20_000,
        stock_threshold=10_000,
        mask_text="Sell gold here",
    )
    monkeypatch.setattr(monitor, "get_commodity", lambda name: custom_gold)

    class FakeResponse:
        text = HTML_CUSTOM_THRESHOLD

    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/555/"],
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
            market_db=mock_db,
        )

    mock_db.write_market_entry.assert_called_once()
    call = mock_db.write_market_entry.call_args
    assert call[1]["metal"] == "Gold"
    assert call[1]["stock"] == 12000


HTML_HIGH_THRESHOLD = """
<html>
  <body>
    <h2>
      <a href="/elite/station/555/">High Station</a>
      <a href="/elite/system/666/">High System</a>
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


def test_monitor_uses_per_commodity_thresholds_higher(monkeypatch):
    """Monitor should NOT write entry when price/stock fall below a custom *higher* threshold
    even though they exceed the default 28k/15k."""
    from unittest.mock import Mock

    from gold_detector.commodities import Commodity
    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)

    custom_gold = Commodity(
        name="Gold",
        inara_id=42,
        price_threshold=50_000,
        stock_threshold=30_000,
        mask_text="Sell gold here",
    )
    monkeypatch.setattr(monitor, "get_commodity", lambda name: custom_gold)

    class FakeResponse:
        text = HTML_HIGH_THRESHOLD

    monkeypatch.setattr(monitor, "http_get", lambda url: FakeResponse())
    monkeypatch.setattr(
        monitor,
        "get_station_market_urls",
        lambda near_urls: ["https://inara.cz/elite/station-market/555/"],
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
            market_db=mock_db,
        )

    mock_db.write_market_entry.assert_not_called()
    # Non-threshold commodity must NOT appear in active opportunities
    call_args = mock_db.end_scan.call_args
    assert call_args[0][0] == set()
