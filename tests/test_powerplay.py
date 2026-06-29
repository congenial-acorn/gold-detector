import sys
import asyncio
from pathlib import Path

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
    """Test that powerplay writes commodity links and status."""
    # Mock http_get to return Fortified status
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    # Mock database to capture write_powerplay_entry calls
    from unittest.mock import Mock

    mock_db = Mock()
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="http://example.com/links"),
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold", "Palladium"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify powerplay entry was written to database
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"
    assert call_args[1]["power"] == "Jerome Archer"
    assert call_args[1]["status"] == "Fortified"
    assert call_args[1]["progress"] == "51.8%"


def test_powerplay_stronghold_uses_distance_30(monkeypatch):
    """Test that powerplay writes Stronghold status with distance 30."""
    # Mock http_get to return Stronghold status
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Stronghold"))
    )

    # Mock database and commodity links
    from unittest.mock import Mock

    mock_db = Mock()
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="http://example.com/links"),
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify powerplay entry was written to database
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"
    assert call_args[1]["power"] == "Jerome Archer"
    assert call_args[1]["status"] == "Stronghold"
    assert call_args[1]["progress"] == "51.8%"


def test_get_powerplay_status_writes_to_database(monkeypatch):
    """Test that get_powerplay_status writes powerplay entries to MarketDatabase."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    # Create mock database
    mock_db = Mock(spec=MarketDatabase)

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

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


def test_get_powerplay_status_writes_entry_for_fortified_system(monkeypatch):
    """Test that get_powerplay_status persists Fortified entries to MarketDatabase."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"


def test_get_powerplay_status_always_writes_regardless_of_state(monkeypatch):
    """Test that get_powerplay_status always writes to the database (no cooldown gating remains)."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    mock_db = Mock(spec=MarketDatabase)

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert call_args[1]["system_name"] == "Sol"


def test_powerplay_fortified_generates_masked_links(monkeypatch):
    """Test that powerplay generates masked commodity links for Fortified systems."""
    # Mock http_get to return Fortified status
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    # Mock database and mask_commodity_links
    from unittest.mock import Mock

    mock_db = Mock()

    # Mock mask_commodity_links to return known masked string
    monkeypatch.setattr(
        powerplay,
        "mask_commodity_links",
        Mock(return_value="[Sell gold here](https://inara.cz/test)"),
    )
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="https://inara.cz/test"),
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify powerplay entry was written with masked links
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert "commodity_urls" in call_args[1]
    assert "[Sell gold here]" in call_args[1]["commodity_urls"]


def test_powerplay_stronghold_generates_masked_links(monkeypatch):
    """Test that powerplay generates masked commodity links for Stronghold systems."""
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Stronghold"))
    )

    from unittest.mock import Mock

    mock_db = Mock()

    # Mock mask_commodity_links to return known masked string
    monkeypatch.setattr(
        powerplay,
        "mask_commodity_links",
        Mock(return_value="[Sell Palladium here](https://inara.cz/test2)"),
    )
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="https://inara.cz/test2"),
    )

    systems = [["https://inara.cz/elite/starsystem/1496596/", "Palladium"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify powerplay entry was written with masked links
    mock_db.write_powerplay_entry.assert_called_once()
    call_args = mock_db.write_powerplay_entry.call_args
    assert "commodity_urls" in call_args[1]
    assert "[Sell Palladium here]" in call_args[1]["commodity_urls"]


def test_powerplay_calls_mask_commodity_links(monkeypatch):
    """Test that powerplay calls mask_commodity_links with URLs from assemble_commodity_links."""
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )

    from unittest.mock import Mock

    mock_db = Mock()
    mock_mask = Mock(return_value="[Sell gold here](https://inara.cz/test)")

    monkeypatch.setattr(powerplay, "mask_commodity_links", mock_mask)
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="https://inara.cz/test"),
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=mock_db)

    # Verify mask_commodity_links was called
    mock_mask.assert_called_once_with("https://inara.cz/test")


def test_build_commodity_ids_includes_silver():
    """_build_commodity_ids should include Silver (Inara ID 46) when 'Silver' is in the list."""
    from gold_detector.powerplay import _build_commodity_ids

    result = _build_commodity_ids(["Gold", "Silver", "Palladium"])
    assert 42 in result  # Gold
    assert 46 in result  # Silver
    assert 45 in result  # Palladium
    assert len(result) == 3


def test_build_commodity_ids_silver_only():
    """_build_commodity_ids should return [46] for ['Silver'] alone."""
    from gold_detector.powerplay import _build_commodity_ids

    result = _build_commodity_ids(["Silver"])
    assert result == [46]


def test_powerplay_unoccupied_clears_existing_db_entry(monkeypatch, tmp_path):
    """When a system refreshes as Unoccupied, stale powerplay is cleared from DB."""
    from gold_detector.market_database import MarketDatabase

    db = MarketDatabase(tmp_path / "market_database.json")
    db.write_market_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/elite/station/-1/",
        metal="Gold",
        stock=25000,
    )
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="[Sell gold here](https://inara.cz/old)",
    )

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Unoccupied"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    result = powerplay.get_powerplay_status(systems, market_db=db)

    data = db.read_all_entries()
    assert "powerplay" not in data["Sol"]
    assert (
        data["Sol"]["stations"]["Abraham Lincoln"]["metals"]["Gold"]["stock"] == 25000
    )
    assert result == set()


def test_powerplay_no_section_clears_existing_db_entry(monkeypatch, tmp_path):
    """When a system's page has no Powerplay section, stale powerplay is cleared."""
    from gold_detector.market_database import MarketDatabase

    db = MarketDatabase(tmp_path / "market_database.json")
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="old links",
    )

    no_pp_html = "<html><body><h2>Sol</h2><div>no powerplay here</div></body></html>"
    monkeypatch.setattr(powerplay, "http_get", lambda url: FakeResponse(no_pp_html))

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    result = powerplay.get_powerplay_status(systems, market_db=db)

    data = db.read_all_entries()
    assert "powerplay" not in data["Sol"]
    assert result == set()


def test_powerplay_non_fortified_stronghold_status_clears_db(monkeypatch, tmp_path):
    """When status is Contested/Exploited (not Fortified/Stronghold), stale powerplay cleared."""
    from gold_detector.market_database import MarketDatabase

    db = MarketDatabase(tmp_path / "market_database.json")
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="old links",
    )

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Contested"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    result = powerplay.get_powerplay_status(systems, market_db=db)

    data = db.read_all_entries()
    assert "powerplay" not in data["Sol"]
    assert result == set()


def test_powerplay_fortified_no_links_clears_db(monkeypatch, tmp_path):
    """Fortified system with no commodity links clears stale powerplay."""
    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    db = MarketDatabase(tmp_path / "market_database.json")
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        power="Zachary Hudson",
        status="Fortified",
        progress=75,
        commodity_urls="old links",
    )

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value=""),
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    result = powerplay.get_powerplay_status(systems, market_db=db)

    data = db.read_all_entries()
    assert "powerplay" not in data["Sol"]
    assert result == set()


def test_powerplay_fortified_writes_to_real_db_no_regression(monkeypatch, tmp_path):
    """Fortified happy path still writes powerplay entry to real DB."""
    import json

    from unittest.mock import Mock

    from gold_detector.market_database import MarketDatabase

    db_path = tmp_path / "market_database.json"
    db = MarketDatabase(db_path)
    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Fortified"))
    )
    monkeypatch.setattr(
        powerplay,
        "assemble_commodity_links",
        Mock(return_value="http://example.com/links"),
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    result = powerplay.get_powerplay_status(systems, market_db=db)

    with open(db_path) as f:
        data = json.load(f)
    assert data["Sol"]["powerplay"]["status"] == "Fortified"
    assert result == {"Sol"}


def test_powerplay_stale_clear_preserves_market_data(monkeypatch, tmp_path):
    """Clearing stale powerplay preserves all station/metal market data."""
    from gold_detector.market_database import MarketDatabase

    db = MarketDatabase(tmp_path / "market_database.json")
    db.write_market_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/elite/station/-1/",
        metal="Gold",
        stock=25000,
    )
    db.write_market_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        station_name="Abraham Lincoln",
        station_type="Coriolis Starport",
        url="https://inara.cz/elite/station/-1/",
        metal="Silver",
        stock=60000,
    )
    db.write_powerplay_entry(
        system_name="Sol",
        system_address="https://inara.cz/elite/starsystem/345798/",
        power="Zachary Hudson",
        status="Stronghold",
        progress=80,
        commodity_urls="old links",
    )

    monkeypatch.setattr(
        powerplay, "http_get", lambda url: FakeResponse(_pp_html("Unoccupied"))
    )

    systems = [["https://inara.cz/elite/starsystem/345798/", "Gold"]]
    powerplay.get_powerplay_status(systems, market_db=db)

    data = db.read_all_entries()
    assert "powerplay" not in data["Sol"]
    metals = data["Sol"]["stations"]["Abraham Lincoln"]["metals"]
    assert metals["Gold"]["stock"] == 25000
    assert metals["Silver"]["stock"] == 60000


def test_dispatch_refresh_shows_fresh_powerplay_links_in_same_market_message(
    monkeypatch,
):
    from typing import Any, cast
    from unittest.mock import AsyncMock, Mock

    import discord

    import gold_detector.messaging as messaging_module
    from gold_detector.config import Settings
    from gold_detector.market_database import MarketDatabase
    from gold_detector.messaging import DiscordMessenger

    class _DummyClient:
        user: Any
        guilds: list[Any]

        def __init__(self, loop: asyncio.AbstractEventLoop):
            self.loop = loop
            self.user = Mock()
            self.guilds = []

    def _discord_client(client: object) -> discord.Client:
        return cast(discord.Client, cast(object, client))

    def _settings() -> Settings:
        return Settings(
            token="token",
            default_alert_channel="market-watch",
            default_role_name="Market Alert",
            alert_channel_override="",
            role_name_override="",
            bot_verbose=False,
            debug_mode=False,
            debug_server_id=None,
            debug_mode_dms=False,
            debug_user_id=None,
            queue_max_size=10,
            help_url="https://example.com",
            monitor_interval_seconds=1.0,
            http_cooldown_seconds=1.0,
            log_level="INFO",
        )

    async def _run():
        loop = asyncio.get_running_loop()

        initial_data = {
            "Sol": {
                "system_address": "https://inara.cz/elite/starsystem/1234/",
                "powerplay": {
                    "power": "Zachary Hudson",
                    "status": "Fortified",
                    "progress": "75%",
                    "commodity_urls": "",
                },
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/elite/station/1234/",
                        "metals": {"Gold": {"stock": 25000, "sent_to": {}}},
                    }
                },
            }
        }
        refreshed_data = {
            "Sol": {
                "system_address": "https://inara.cz/elite/starsystem/1234/",
                "powerplay": {
                    "power": "Zachary Hudson",
                    "status": "Fortified",
                    "progress": "75%",
                    "commodity_urls": "[Sell gold here](https://inara.cz/fresh)",
                },
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/elite/station/1234/",
                        "metals": {"Gold": {"stock": 25000, "sent_to": {}}},
                    }
                },
            }
        }

        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.side_effect = [initial_data, refreshed_data]
        mock_db.has_market_alert_been_sent.return_value = False

        async def fake_to_thread(func, *args):
            return func(*args)

        mock_get_powerplay_status = Mock(return_value={"Sol"})
        original_to_thread = messaging_module.asyncio.to_thread
        original_get_powerplay_status = messaging_module.get_powerplay_status
        messaging_module.asyncio.to_thread = fake_to_thread
        messaging_module.get_powerplay_status = mock_get_powerplay_status
        try:
            mock_client = _DummyClient(loop)
            mock_guild = Mock()
            mock_guild.id = 123456
            mock_guild.name = "Test Guild"
            mock_guild.me = Mock()
            mock_channel = Mock()
            mock_channel.name = "market-watch"
            mock_channel.send = AsyncMock()
            mock_channel.permissions_for = Mock(
                return_value=Mock(view_channel=True, send_messages=True)
            )
            mock_channel.position = 0
            mock_channel.id = 999
            mock_guild.text_channels = [mock_channel]
            mock_guild.get_channel.return_value = None
            mock_guild.roles = []
            mock_client.guilds = [mock_guild]

            mock_guild_prefs = Mock()
            mock_guild_prefs.effective_channel_name.return_value = "market-watch"
            mock_guild_prefs.effective_channel_id.return_value = None
            mock_guild_prefs.effective_role_name.return_value = "Market Alert"
            mock_guild_prefs.effective_role_id.return_value = None
            mock_guild_prefs.get_preferences.return_value = {
                "powerplay": ["Zachary Hudson"]
            }
            mock_guild_prefs.pings_enabled.return_value = False
            mock_opt_outs = Mock()
            mock_opt_outs.is_opted_out.return_value = False
            mock_subscribers = Mock()
            mock_subscribers.all.return_value = []

            messenger = DiscordMessenger(
                _discord_client(mock_client),
                _settings(),
                mock_guild_prefs,
                mock_opt_outs,
                mock_subscribers,
            )

            await messenger.dispatch_from_database(mock_db)
        finally:
            messaging_module.asyncio.to_thread = original_to_thread
            messaging_module.get_powerplay_status = original_get_powerplay_status

        sent_message = mock_channel.send.call_args[0][0]
        assert "[Sell gold here](https://inara.cz/fresh)" in sent_message
        assert mock_db.read_all_entries.call_count == 2

    asyncio.run(_run())
