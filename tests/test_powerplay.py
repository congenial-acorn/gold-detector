import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gold_detector.powerplay as powerplay  # noqa: E402


class FakeResponse:
    def __init__(self, text: str):
        self.text = text


def _pp_html(status: str, percent: str = "51.8%"):
    return f"""
    <html>
      <body>
        <h2>Sol \\ue81d</h2>
        <div>
          <span class="uppercase minor small">Powerplay</span><br/>
          <a href="/elite/power/12/">Jerome Archer</a>
          <small>(Controlling)</small><br/>
          <span class="bigger"><span class="positive">{status}</span></span>
          <span class="negative"><br/>{percent}</span>
        </div>
      </body>
    </html>
    """


def test_powerplay_fortified_builds_links(monkeypatch):
    """Test that powerplay no longer calls send_to_discord (database-driven dispatch)."""
    calls = []

    monkeypatch.setattr(powerplay, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold", "Palladium"]]
    powerplay.get_powerplay_status(systems)

    assert len(calls) == 0


def test_powerplay_stronghold_uses_distance_30(monkeypatch):
    """Test that powerplay no longer calls send_to_discord (database-driven dispatch)."""
    calls = []

    monkeypatch.setattr(powerplay, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Stronghold"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems)

    assert len(calls) == 0


def test_get_powerplay_status_writes_to_database(monkeypatch):
    """Test that get_powerplay_status writes powerplay entries to MarketDatabase."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = True  # Allow sending

    monkeypatch.setattr(powerplay, "send_to_discord", Mock())
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    # This should fail because get_powerplay_status doesn't accept market_db yet
    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify database methods were called
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args

    # Verify correct parameters passed
    assert call_args[1]["system_name"] == "Sol"
    assert call_args[1]["power"] == "Jerome Archer"
    assert call_args[1]["status"] == "Fortified"
    assert call_args[1]["progress"] == "51.8%"


def test_get_powerplay_status_uses_database_for_cooldowns(monkeypatch):
    """Test that get_powerplay_status writes to database but does NOT call send_to_discord."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = True

    mock_send = Mock()
    monkeypatch.setattr(powerplay, "send_to_discord", mock_send)
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    mock_send.assert_not_called()
    
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"


def test_get_powerplay_status_respects_database_cooldown(monkeypatch):
    """Test that get_powerplay_status writes to database regardless of cooldown (dispatch handles cooldown)."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = False

    mock_send = Mock()
    monkeypatch.setattr(powerplay, "send_to_discord", mock_send)
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    mock_send.assert_not_called()
    
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"
