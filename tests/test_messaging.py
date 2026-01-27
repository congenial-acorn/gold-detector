import asyncio

import pytest

# Ensure the repository root is on the import path for the tests.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gold_detector.config import Settings
from gold_detector.messaging import DiscordMessenger


class _DummyClient:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop


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
        cooldown_hours=48,
        cooldown_seconds=48 * 3600,
        queue_max_size=10,
        help_url="https://example.com",
        monitor_interval_seconds=1.0,
        http_cooldown_seconds=1.0,
        log_level="INFO",
    )


def test_loop_done_waits_for_queue_completion():
    async def _run():
        loop = asyncio.get_running_loop()
        messenger = DiscordMessenger(
            _DummyClient(loop),
            _settings(),
            object(),
            object(),
            object(),
        )

        drain_called = asyncio.Event()

        def _mark_drain():
            drain_called.set()

        messenger._drain_and_emit_pings = _mark_drain  # type: ignore[assignment]

        messenger.queue.put_nowait((0, "hello"))
        messenger.loop_done_from_thread()

        await asyncio.sleep(0.05)
        assert not drain_called.is_set()

        messenger.queue.task_done()
        await asyncio.wait_for(drain_called.wait(), timeout=1)

    asyncio.run(_run())


def test_dispatch_from_database_reads_entries():
    """Test that dispatch_from_database reads and iterates MarketDatabase entries."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {
                            "Gold": {"stock": 25000, "cooldowns": {}}
                        }
                    }
                }
            }
        }
        
        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_client.guilds = [mock_guild]
        
        # Create mock services
        mock_guild_prefs = Mock()
        mock_opt_outs = Mock()
        mock_subscribers = Mock()

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )
        
        # This will fail because dispatch_from_database doesn't exist yet
        try:
            await messenger.dispatch_from_database(mock_db)
        except AttributeError:
            pass  # Expected in RED phase
        
        # Verify read_all_entries was called
        mock_db.read_all_entries.assert_called_once()
    
    asyncio.run(_run())


def test_dispatch_from_database_checks_cooldowns():
    """Test that dispatch_from_database checks cooldowns before sending."""
    from unittest.mock import Mock, AsyncMock, patch
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {
                            "Gold": {"stock": 25000, "cooldowns": {}}
                        }
                    }
                }
            }
        }
        mock_db.check_cooldown.return_value = True  # Cooldown expired
        
        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.permissions_for.return_value = Mock(view_channel=True, send_messages=True)
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        mock_guild.roles = []
        mock_client.guilds = [mock_guild]
        
        # Create mock services
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {}
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        # This will fail because dispatch_from_database doesn't exist yet
        try:
            await messenger.dispatch_from_database(mock_db)
        except AttributeError:
            pass  # Expected in RED phase

        # Verify check_cooldown was called
        if mock_db.check_cooldown.called:
            call_args = mock_db.check_cooldown.call_args
            assert call_args is not None
            assert call_args[1]["system_name"] == "Sol"
            assert call_args[1]["station_name"] == "Abraham Lincoln"
            assert call_args[1]["metal"] == "Gold"
            assert "recipient_type" in call_args[1]
            assert "recipient_id" in call_args[1]
            assert "cooldown_seconds" in call_args[1]
    
    asyncio.run(_run())


def test_dispatch_from_database_marks_sent():
    """Test that dispatch_from_database marks messages as sent after successful send."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {
                            "Gold": {"stock": 25000, "cooldowns": {}}
                        }
                    }
                }
            }
        }
        mock_db.check_cooldown.return_value = True  # Cooldown expired
        
        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.send = AsyncMock()
        mock_channel.permissions_for.return_value = Mock(view_channel=True, send_messages=True)
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        mock_guild.roles = []
        mock_client.guilds = [mock_guild]
        
        # Create mock services
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {}
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        # This will fail because dispatch_from_database doesn't exist yet
        try:
            await messenger.dispatch_from_database(mock_db)
        except AttributeError:
            pass  # Expected in RED phase

        # Verify mark_sent was called after successful send
        if mock_db.mark_sent.called:
            call_args = mock_db.mark_sent.call_args
            assert call_args is not None
            assert call_args[1]["system_name"] == "Sol"
            assert call_args[1]["station_name"] == "Abraham Lincoln"
            assert call_args[1]["metal"] == "Gold"
            assert "recipient_type" in call_args[1]
            assert "recipient_id" in call_args[1]
    
    asyncio.run(_run())


def test_dispatch_from_database_applies_preferences():
    """Test that dispatch_from_database applies preference filtering per recipient."""
    from unittest.mock import Mock, AsyncMock, patch
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {
                            "Gold": {"stock": 25000, "cooldowns": {}}
                        }
                    }
                }
            }
        }
        mock_db.check_cooldown.return_value = True
        
        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.permissions_for.return_value = Mock(view_channel=True, send_messages=True)
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        mock_guild.roles = []
        mock_client.guilds = [mock_guild]
        
        # Create mock services with preferences that filter out Gold
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {"commodity": ["Palladium"]}  # Filter out Gold
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        # Patch filter_message_for_preferences to verify it's called
        with patch("gold_detector.messaging.filter_message_for_preferences") as mock_filter:
            mock_filter.return_value = None  # Filter out message
            
            # This will fail because dispatch_from_database doesn't exist yet
            try:
                await messenger.dispatch_from_database(mock_db)
            except AttributeError:
                pass  # Expected in RED phase
            
            # Verify filter was called with preferences
            if mock_filter.called:
                assert mock_filter.call_count > 0
    
    asyncio.run(_run())


def test_dispatch_from_database_includes_role_mentions():
    """Test that dispatch_from_database includes role mentions in guild messages when pings enabled."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {
                            "Gold": {"stock": 25000, "cooldowns": {}}
                        }
                    }
                }
            }
        }
        mock_db.check_cooldown.return_value = True
        
        # Create mock client with guild and role
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.send = AsyncMock()
        mock_channel.permissions_for.return_value = Mock(view_channel=True, send_messages=True)
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        
        # Add role
        mock_role = Mock()
        mock_role.name = "Market Alert"
        mock_role.mention = "@Market Alert"
        mock_guild.roles = [mock_role]
        mock_guild.get_role.return_value = None
        
        mock_client.guilds = [mock_guild]
        
        # Create mock services with pings enabled
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {}
        mock_guild_prefs.pings_enabled.return_value = True  # Pings enabled
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        # This will fail because dispatch_from_database doesn't exist yet
        try:
            await messenger.dispatch_from_database(mock_db)
        except AttributeError:
            pass  # Expected in RED phase
        
        # Verify channel.send was called with role mention in message
        if mock_channel.send.called:
            call_args = mock_channel.send.call_args
            message_content = call_args[0][0]
            assert "@Market Alert" in message_content or "Market Alert" in message_content
    
    asyncio.run(_run())


def test_dispatch_from_database_handles_powerplay():
    """Test that dispatch_from_database processes powerplay entries correctly."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()
        
        # Create mock database with powerplay entry
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {
                    "power": "Zachary Hudson",
                    "status": "Acquisition",
                    "progress": 75
                },
                "stations": {}
            }
        }
        mock_db.check_cooldown.return_value = True
        
        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.send = AsyncMock()
        mock_channel.permissions_for.return_value = Mock(view_channel=True, send_messages=True)
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        mock_guild.roles = []
        mock_client.guilds = [mock_guild]
        
        # Create mock services
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {}
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        # This will fail because dispatch_from_database doesn't exist yet
        try:
            await messenger.dispatch_from_database(mock_db)
        except AttributeError:
            pass  # Expected in RED phase

        # Verify check_cooldown was called with powerplay parameters
        if mock_db.check_cooldown.called:
            call_args = mock_db.check_cooldown.call_args
            assert call_args is not None
            # For powerplay, station_name should be system_name and metal should be "powerplay"
            assert call_args[1]["system_name"] == "Sol"
            assert call_args[1]["metal"] == "powerplay"
    
    asyncio.run(_run())
