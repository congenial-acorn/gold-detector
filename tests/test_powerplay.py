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
    calls = []

    monkeypatch.setattr(powerplay, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold", "Palladium"]]
    powerplay.get_powerplay_status(systems)

    assert len(calls) == 2  # Fortified alert + info message
    assert "Fortified" in calls[0]
    assert "Sol" in calls[0]
    assert "pa1%5B%5D=42" in calls[0] and "pa1%5B%5D=45" in calls[0]
    assert "pi11=20" in calls[0]  # distance for Fortified branch


def test_powerplay_stronghold_uses_distance_30(monkeypatch):
    calls = []

    monkeypatch.setattr(powerplay, "send_to_discord", lambda msg: calls.append(msg))
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Stronghold"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems)

    assert len(calls) == 2  # Stronghold alert + info message
    assert "Stronghold" in calls[0]
    assert "pa1%5B%5D=42" in calls[0]
    assert "pa1%5B%5D=45" not in calls[0]
    assert "pi11=30" in calls[0]  # distance for Stronghold branch


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
    """Test that get_powerplay_status uses database for cooldown checks."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = True  # Allow sending

    mock_send = Mock()
    monkeypatch.setattr(powerplay, "send_to_discord", mock_send)
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify check_cooldown called before send_to_discord
    mock_db.check_cooldown.assert_called_once()
    call_args = mock_db.check_cooldown.call_args

    # Verify cooldown parameters
    assert call_args[1]["system_name"] == "Sol"
    assert "cooldown_seconds" in call_args[1]

    # Verify mark_sent called after sending
    mock_db.mark_sent.assert_called_once()
    mark_args = mock_db.mark_sent.call_args
    assert mark_args[1]["system_name"] == "Sol"

    # Verify message was sent
    assert mock_send.call_count == 1


def test_get_powerplay_status_respects_database_cooldown(monkeypatch):
    """Test that get_powerplay_status respects database cooldown and doesn't send when cooldown active."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)
    mock_db.check_cooldown.return_value = False  # Cooldown still active

    mock_send = Mock()
    monkeypatch.setattr(powerplay, "send_to_discord", mock_send)
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify check_cooldown was called
    mock_db.check_cooldown.assert_called_once()

    # Verify message was NOT sent
    assert mock_send.call_count == 0

    # Verify mark_sent was NOT called
    mock_db.mark_sent.assert_not_called()
