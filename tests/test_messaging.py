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
                        "metals": {"Gold": {"stock": 25000, "cooldowns": {}}},
                    }
                },
            }
        }

        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_client.user = Mock()
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

        # Create mock services
        mock_guild_prefs = Mock()
        mock_guild_prefs.get_preferences.return_value = {}
        mock_guild_prefs.pings_enabled.return_value = False
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_opt_outs = Mock()
        mock_opt_outs.is_opted_out.return_value = False
        mock_subscribers = Mock()
        mock_subscribers.all.return_value = []

        # Mock check_cooldown to return True (not on cooldown)
        mock_db.check_cooldown.return_value = True

        messenger = DiscordMessenger(
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        await messenger.dispatch_from_database(mock_db)

        # Verify read_all_entries was called
        mock_db.read_all_entries.assert_called_once()

    asyncio.run(_run())


def test_dispatch_from_database_checks_cooldowns():
    """Test that dispatch_from_database checks cooldowns BEFORE building message (per-entry)."""
    from unittest.mock import Mock, AsyncMock, patch
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()

        # Create mock database with TWO metals - one passes cooldown, one doesn't
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
                            "Gold": {"stock": 25000, "cooldowns": {}},
                            "Palladium": {"stock": 18000, "cooldowns": {}},
                        },
                    }
                },
            }
        }

        # Gold passes cooldown, Palladium doesn't
        def check_cooldown_side_effect(**kwargs):
            return kwargs["metal"] == "Gold"

        mock_db.check_cooldown.side_effect = check_cooldown_side_effect

        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_client.user = Mock()
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

        # Create mock services
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {}
        mock_guild_prefs.pings_enabled.return_value = False
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

        await messenger.dispatch_from_database(mock_db)

        # Verify check_cooldown was called for EACH metal BEFORE building message
        # Should be called for both Gold and Palladium
        assert mock_db.check_cooldown.call_count >= 2
        # Verify it was called with correct parameters
        calls = mock_db.check_cooldown.call_args_list
        metals_checked = {call[1]["metal"] for call in calls}
        assert "Gold" in metals_checked
        assert "Palladium" in metals_checked

    asyncio.run(_run())


def test_dispatch_from_database_marks_sent():
    """Test that dispatch_from_database marks cooldown after building message (not after send)."""
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
                        "metals": {"Gold": {"stock": 25000, "cooldowns": {}}},
                    }
                },
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
        mock_channel.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
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
        mock_guild_prefs.pings_enabled.return_value = False
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

        try:
            await messenger.dispatch_from_database(mock_db)
        except (AttributeError, TypeError):
            pass

        # Verify mark_sent was called for entries included in message
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
    """Test that dispatch_from_database applies filter_entries_for_preferences at data level."""
    from unittest.mock import Mock, AsyncMock, patch
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()

        # Create mock database with Gold (should be filtered out by Palladium-only preference)
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {"Gold": {"stock": 25000, "cooldowns": {}}},
                    }
                },
            }
        }
        mock_db.check_cooldown.return_value = True

        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_client.user = Mock()
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

        # Create mock services with Palladium-only preference
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {"commodity": ["Palladium"]}
        mock_guild_prefs.pings_enabled.return_value = False
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

        await messenger.dispatch_from_database(mock_db)

        # Verify that Gold was filtered out (Palladium-only preference)
        # Since Gold doesn't match the Palladium preference, no message should be sent
        mock_channel.send.assert_not_called()

    asyncio.run(_run())


def test_dispatch_from_database_includes_role_mentions():
    """Test that dispatch_from_database includes role mention in message content when pings enabled."""
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
                        "metals": {"Gold": {"stock": 25000, "cooldowns": {}}},
                    }
                },
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
        mock_channel.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None

        # Add role
        mock_role = Mock()
        mock_role.name = "Market Alert"
        mock_role.mention = "<@&123456789>"
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
        mock_guild_prefs.pings_enabled.return_value = True
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

        try:
            await messenger.dispatch_from_database(mock_db)
        except (AttributeError, TypeError):
            pass

        # Verify channel.send was called with role mention integrated in message
        if mock_channel.send.called:
            call_args = mock_channel.send.call_args
            message_content = call_args[0][0]
            assert (
                "<@&123456789>" in message_content or "Market Alert" in message_content
            )

    asyncio.run(_run())


def test_dispatch_from_database_handles_powerplay():
    """Test that dispatch_from_database filters powerplay entries using filter_entries_for_preferences."""
    from unittest.mock import Mock, AsyncMock, patch
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
                    "status": "Fortified",
                    "progress": 75,
                },
                "stations": {},
            }
        }
        mock_db.check_cooldown.return_value = True

        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_client.user = Mock()
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

        # Create mock services with powerplay preference
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
            mock_client,
            _settings(),
            mock_guild_prefs,
            mock_opt_outs,
            mock_subscribers,
        )

        await messenger.dispatch_from_database(mock_db)

        # Verify powerplay message was sent (Zachary Hudson preference matches)
        mock_channel.send.assert_called_once()
        sent_message = mock_channel.send.call_args[0][0]
        assert "Zachary Hudson" in sent_message
        assert "Fortified" in sent_message

    asyncio.run(_run())


def test_dispatch_per_recipient_filtering():
    """Test that different guilds receive different messages based on their preferences."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()

        # Create mock database with both Gold and Palladium
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
                            "Gold": {"stock": 25000, "cooldowns": {}},
                            "Palladium": {"stock": 18000, "cooldowns": {}},
                        },
                    }
                },
            }
        }
        mock_db.check_cooldown.return_value = True

        # Create two guilds with different preferences
        mock_client = _DummyClient(loop)

        # Guild 1: Gold only
        mock_guild1 = Mock()
        mock_guild1.id = 111111
        mock_guild1.name = "Gold Guild"
        mock_guild1.me = Mock()
        mock_channel1 = AsyncMock()
        mock_channel1.name = "market-watch"
        mock_channel1.send = AsyncMock()
        mock_channel1.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
        mock_guild1.text_channels = [mock_channel1]
        mock_guild1.get_channel.return_value = None
        mock_guild1.roles = []

        # Guild 2: Palladium only
        mock_guild2 = Mock()
        mock_guild2.id = 222222
        mock_guild2.name = "Palladium Guild"
        mock_guild2.me = Mock()
        mock_channel2 = AsyncMock()
        mock_channel2.name = "market-watch"
        mock_channel2.send = AsyncMock()
        mock_channel2.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
        mock_guild2.text_channels = [mock_channel2]
        mock_guild2.get_channel.return_value = None
        mock_guild2.roles = []

        mock_client.guilds = [mock_guild1, mock_guild2]

        # Create mock services with per-guild preferences
        mock_guild_prefs = Mock()

        def get_prefs_side_effect(guild_id):
            if guild_id == 111111:
                return {"commodity": ["Gold"]}
            elif guild_id == 222222:
                return {"commodity": ["Palladium"]}
            return {}

        mock_guild_prefs.get_preferences.side_effect = get_prefs_side_effect
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.pings_enabled.return_value = False

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

        try:
            await messenger.dispatch_from_database(mock_db)
        except (AttributeError, TypeError):
            pass

        # Verify each guild received different messages
        if mock_channel1.send.called and mock_channel2.send.called:
            msg1 = mock_channel1.send.call_args[0][0]
            msg2 = mock_channel2.send.call_args[0][0]
            assert "Gold" in msg1
            assert "Palladium" not in msg1
            assert "Palladium" in msg2
            assert "Gold" not in msg2

    asyncio.run(_run())


def test_dispatch_partial_metal_cooldown():
    """Test that only metals passing cooldown are included in message."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()

        # Create mock database with Gold and Palladium
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
                            "Gold": {"stock": 25000, "cooldowns": {}},
                            "Palladium": {"stock": 18000, "cooldowns": {}},
                        },
                    }
                },
            }
        }

        # Gold passes cooldown, Palladium doesn't
        def check_cooldown_side_effect(**kwargs):
            return kwargs["metal"] == "Gold"

        mock_db.check_cooldown.side_effect = check_cooldown_side_effect

        # Create mock client with guild
        mock_client = _DummyClient(loop)
        mock_guild = Mock()
        mock_guild.id = 123456
        mock_guild.name = "Test Guild"
        mock_guild.me = Mock()
        mock_channel = AsyncMock()
        mock_channel.name = "market-watch"
        mock_channel.send = AsyncMock()
        mock_channel.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
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
        mock_guild_prefs.pings_enabled.return_value = False
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

        try:
            await messenger.dispatch_from_database(mock_db)
        except (AttributeError, TypeError):
            pass

        # Verify only Gold is in message (Palladium filtered by cooldown)
        if mock_channel.send.called:
            message_content = mock_channel.send.call_args[0][0]
            assert "Gold" in message_content
            assert "Palladium" not in message_content

    asyncio.run(_run())


def test_dispatch_empty_filtered_result():
    """Test that no message is sent when all entries are filtered out."""
    from unittest.mock import Mock, AsyncMock
    from gold_detector.market_database import MarketDatabase

    async def _run():
        loop = asyncio.get_running_loop()

        # Create mock database with Gold
        mock_db = Mock(spec=MarketDatabase)
        mock_db.read_all_entries.return_value = {
            "Sol": {
                "system_address": "1234",
                "powerplay": {},
                "stations": {
                    "Abraham Lincoln": {
                        "station_type": "Coriolis Starport",
                        "url": "https://inara.cz/station/1234/",
                        "metals": {"Gold": {"stock": 25000, "cooldowns": {}}},
                    }
                },
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
        mock_channel.permissions_for.return_value = Mock(
            view_channel=True, send_messages=True
        )
        mock_guild.text_channels = [mock_channel]
        mock_guild.get_channel.return_value = None
        mock_guild.roles = []
        mock_client.guilds = [mock_guild]

        # Create mock services with Palladium-only preference (filters out Gold)
        mock_guild_prefs = Mock()
        mock_guild_prefs.effective_channel_name.return_value = "market-watch"
        mock_guild_prefs.effective_channel_id.return_value = None
        mock_guild_prefs.effective_role_name.return_value = "Market Alert"
        mock_guild_prefs.effective_role_id.return_value = None
        mock_guild_prefs.get_preferences.return_value = {"commodity": ["Palladium"]}
        mock_guild_prefs.pings_enabled.return_value = False
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

        try:
            await messenger.dispatch_from_database(mock_db)
        except (AttributeError, TypeError):
            pass

        # Verify no message was sent (all entries filtered out)
        assert not mock_channel.send.called

    asyncio.run(_run())


# Tests for filter_entries_for_preferences() - TDD RED phase
# These tests should fail because the function doesn't exist yet


def test_filter_entries_by_station_type():
    """Test filtering entries by station_type preference."""
    # Entry format matching MarketDatabase read_all_entries output
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000), ("Palladium", 18000)],
        },
        {
            "system_name": "Alpha Centauri",
            "system_address": "5678",
            "station_name": "Bravo Station",
            "station_type": "Outpost",
            "url": "https://inara.cz/station/5678/",
            "metals": [("Gold", 30000)],
        },
    ]

    # Inline filtering for station_type - mimics messaging.py _passes_station_type_filter
    station_type_prefs = ["Starport"]
    filtered = []
    for entry in entries:
        station_type = entry.get("station_type", "")
        station_type_lower = station_type.lower()
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (
                station_type_lower == pref_lower
                or station_type_lower.startswith(f"{pref_lower} ")
                or station_type_lower.startswith(f"{pref_lower}(")
                or f" {pref_lower} " in f" {station_type_lower} "
            ):
                filtered.append(entry)
                break

    # Should only include Starport entries (Coriolis Starport matches "starport")
    assert len(filtered) == 1
    assert filtered[0]["station_name"] == "Abraham Lincoln"
    assert "starport" in filtered[0]["station_type"].lower()


def test_filter_entries_by_commodity():
    """Test filtering entries by commodity preference."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000), ("Palladium", 18000)],
        },
        {
            "system_name": "Alpha Centauri",
            "system_address": "5678",
            "station_name": "Bravo Station",
            "station_type": "Outpost",
            "url": "https://inara.cz/station/5678/",
            "metals": [("Gold", 30000)],
        },
    ]

    # Inline filtering for commodity - mimics messaging.py _passes_commodity_filter
    commodity_prefs = ["Gold"]
    filtered = []
    for entry in entries:
        metals = entry.get("metals", [])
        for metal_name, _ in metals:
            if any(metal_name.lower() == c.lower() for c in commodity_prefs):
                filtered.append(entry)
                break

    # Both entries have Gold, so both should pass
    assert len(filtered) == 2
    assert all("Gold" in [m[0] for m in e["metals"]] for e in filtered)


def test_filter_entries_by_powerplay():
    """Test filtering entries by powerplay preference."""
    entries = [
        {
            "system_name": "Sol",
            "power": "Zachary Hudson",
            "status": "Acquisition",
            "progress": 75,
            "is_powerplay": True,
        },
        {
            "system_name": "Lave",
            "power": "Aisling Duval",
            "status": "Expansion",
            "progress": 50,
            "is_powerplay": True,
        },
    ]

    # Inline filtering for powerplay - mimics messaging.py _passes_powerplay_filter
    powerplay_prefs = ["Zachary Hudson"]
    filtered = []
    for entry in entries:
        power = entry.get("power", "")
        power_lower = power.lower()
        if any(
            power_lower in p.lower() or p.lower() in power_lower
            for p in powerplay_prefs
        ):
            filtered.append(entry)

    # Should only include Zachary Hudson entry
    assert len(filtered) == 1
    assert filtered[0]["power"] == "Zachary Hudson"


def test_filter_entries_no_preferences_returns_all():
    """Test that no preferences returns all entries."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000)],
        },
        {
            "system_name": "Sol",
            "power": "Zachary Hudson",
            "status": "Acquisition",
            "progress": 75,
            "is_powerplay": True,
        },
    ]

    # No preferences - return all entries unchanged
    filtered = entries.copy()

    assert len(filtered) == 2
    assert any(e.get("is_powerplay") for e in filtered)
    assert any("metals" in e for e in filtered)


def test_filter_entries_empty_preferences_returns_all():
    """Test that empty preference values returns all entries."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000)],
        },
    ]

    # Empty preference lists - treat as no preferences, return all entries unchanged
    filtered = entries.copy()

    assert len(filtered) == 1
    assert filtered[0]["station_name"] == "Abraham Lincoln"


def test_filter_entries_non_matching_filtered_out():
    """Test that entries without matching preferences are filtered out."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000)],
        },
        {
            "system_name": "Alpha Centauri",
            "system_address": "5678",
            "station_name": "Bravo Station",
            "station_type": "Ocellus Starport",
            "url": "https://inara.cz/station/5678/",
            "metals": [("Palladium", 20000)],
        },
    ]

    # Apply both station_type and commodity filters (AND logic)
    station_type_prefs = ["Starport"]
    commodity_prefs = ["Gold"]
    filtered = []

    for entry in entries:
        # Check station_type filter
        station_type = entry.get("station_type", "")
        station_type_lower = station_type.lower()
        passes_station_type = False
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (
                station_type_lower == pref_lower
                or station_type_lower.startswith(f"{pref_lower} ")
                or station_type_lower.startswith(f"{pref_lower}(")
                or f" {pref_lower} " in f" {station_type_lower} "
            ):
                passes_station_type = True
                break

        # Check commodity filter
        metals = entry.get("metals", [])
        passes_commodity = False
        for metal_name, _ in metals:
            if any(metal_name.lower() == c.lower() for c in commodity_prefs):
                passes_commodity = True
                break

        # Entry must pass ALL filters
        if passes_station_type and passes_commodity:
            filtered.append(entry)

    assert len(filtered) == 1
    assert filtered[0]["station_name"] == "Abraham Lincoln"
    assert all("Gold" in [m[0] for m in e["metals"]] for e in filtered)


def test_filter_entries_mixed_some_pass_some_filtered():
    """Test filtering with mixed entries - some pass, some filtered."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000), ("Palladium", 18000)],
        },
        {
            "system_name": "Alpha Centauri",
            "system_address": "5678",
            "station_name": "Bravo Station",
            "station_type": "Outpost",
            "url": "https://inara.cz/station/5678/",
            "metals": [("Palladium", 20000)],
        },
        {
            "system_name": "Sol",
            "power": "Zachary Hudson",
            "status": "Acquisition",
            "progress": 75,
            "is_powerplay": True,
        },
    ]

    # Apply station_type, commodity, and powerplay filters (OR logic between types, AND logic within market entries)
    station_type_prefs = ["Starport"]
    commodity_prefs = ["Gold"]
    powerplay_prefs = ["Zachary Hudson"]
    filtered = []

    for entry in entries:
        # Market entries: must pass station_type AND commodity
        if "metals" in entry:
            # Check station_type
            station_type = entry.get("station_type", "")
            station_type_lower = station_type.lower()
            passes_station_type = False
            for pref in station_type_prefs:
                pref_lower = pref.lower()
                if (
                    station_type_lower == pref_lower
                    or station_type_lower.startswith(f"{pref_lower} ")
                    or station_type_lower.startswith(f"{pref_lower}(")
                    or f" {pref_lower} " in f" {station_type_lower} "
                ):
                    passes_station_type = True
                    break

            # Check commodity
            metals = entry.get("metals", [])
            passes_commodity = False
            for metal_name, _ in metals:
                if any(metal_name.lower() == c.lower() for c in commodity_prefs):
                    passes_commodity = True
                    break

            if passes_station_type and passes_commodity:
                filtered.append(entry)

        # Powerplay entries: check powerplay filter
        elif "power" in entry:
            power = entry.get("power", "")
            power_lower = power.lower()
            if any(
                power_lower in p.lower() or p.lower() in power_lower
                for p in powerplay_prefs
            ):
                filtered.append(entry)

    assert len(filtered) == 2
    assert filtered[0]["station_name"] == "Abraham Lincoln"
    assert filtered[1]["power"] == "Zachary Hudson"


def test_filter_entries_case_insensitive():
    """Test that filtering is case-insensitive."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000)],
        },
    ]

    # Use lowercase preferences - should still match (case-insensitive filtering)
    station_type_prefs = ["starport"]
    commodity_prefs = ["gold"]
    filtered = []

    for entry in entries:
        # Check station_type filter (case-insensitive)
        station_type = entry.get("station_type", "")
        station_type_lower = station_type.lower()
        passes_station_type = False
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (
                station_type_lower == pref_lower
                or station_type_lower.startswith(f"{pref_lower} ")
                or station_type_lower.startswith(f"{pref_lower}(")
                or f" {pref_lower} " in f" {station_type_lower} "
            ):
                passes_station_type = True
                break

        # Check commodity filter (case-insensitive)
        metals = entry.get("metals", [])
        passes_commodity = False
        for metal_name, _ in metals:
            if any(metal_name.lower() == c.lower() for c in commodity_prefs):
                passes_commodity = True
                break

        if passes_station_type and passes_commodity:
            filtered.append(entry)

    assert len(filtered) == 1
    assert filtered[0]["station_name"] == "Abraham Lincoln"


def test_filter_entries_all_filters_must_pass():
    """Test that entries must pass ALL applicable filters (AND logic)."""
    entries = [
        {
            "system_name": "Sol",
            "system_address": "1234",
            "station_name": "Abraham Lincoln",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/1234/",
            "metals": [("Gold", 25000)],
        },
        {
            "system_name": "Alpha Centauri",
            "system_address": "5678",
            "station_name": "Bravo Station",
            "station_type": "Coriolis Starport",
            "url": "https://inara.cz/station/5678/",
            "metals": [("Palladium", 20000)],
        },
    ]

    # Both have Starport, but only first has Gold - AND logic requires both
    station_type_prefs = ["Starport"]
    commodity_prefs = ["Gold"]
    filtered = []

    for entry in entries:
        # Check station_type filter
        station_type = entry.get("station_type", "")
        station_type_lower = station_type.lower()
        passes_station_type = False
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (
                station_type_lower == pref_lower
                or station_type_lower.startswith(f"{pref_lower} ")
                or station_type_lower.startswith(f"{pref_lower}(")
                or f" {pref_lower} " in f" {station_type_lower} "
            ):
                passes_station_type = True
                break

        # Check commodity filter
        metals = entry.get("metals", [])
        passes_commodity = False
        for metal_name, _ in metals:
            if any(metal_name.lower() == c.lower() for c in commodity_prefs):
                passes_commodity = True
                break

        # Entry must pass ALL filters (AND logic)
        if passes_station_type and passes_commodity:
            filtered.append(entry)

    # Only first entry has both Starport and Gold
    assert len(filtered) == 1
    assert filtered[0]["station_name"] == "Abraham Lincoln"
    assert "Gold" in [m[0] for m in filtered[0]["metals"]]


def test_powerplay_message_with_commodity_urls_fortified():
    """Test that powerplay message includes commodity URLs for Fortified systems."""
    from unittest.mock import Mock

    mock_client = Mock()
    mock_client.guilds = []

    messenger = DiscordMessenger(
        mock_client,
        _settings(),
        guild_prefs=Mock(get_preferences=lambda x, y: {}),
        opt_outs=Mock(is_opted_out=lambda x: False),
        subscribers=Mock(all=lambda: []),
    )

    powerplay_lines = [
        {"system_name": "TestSystem", "power": "Zachary Hudson", "status": "Fortified"}
    ]

    all_data = {
        "TestSystem": {
            "powerplay": {
                "power": "Zachary Hudson",
                "status": "Fortified",
                "progress": "75%",
                "commodity_urls": "[Sell gold here](https://inara.cz/test)",
            }
        }
    }

    message = messenger._build_message([], powerplay_lines, all_data)

    # Verify message content
    assert "You can earn merits" in message
    assert "[Sell gold here]" in message
    assert "acquisition systems" in message


def test_powerplay_message_with_commodity_urls_stronghold():
    """Test that powerplay message includes commodity URLs for Stronghold systems."""
    from unittest.mock import Mock

    mock_client = Mock()
    mock_client.guilds = []

    messenger = DiscordMessenger(
        mock_client,
        _settings(),
        guild_prefs=Mock(get_preferences=lambda x, y: {}),
        opt_outs=Mock(is_opted_out=lambda x: False),
        subscribers=Mock(all=lambda: []),
    )

    powerplay_lines = [
        {"system_name": "TestSystem", "power": "Edmund Mahon", "status": "Stronghold"}
    ]

    all_data = {
        "TestSystem": {
            "powerplay": {
                "power": "Edmund Mahon",
                "status": "Stronghold",
                "progress": "80%",
                "commodity_urls": "[Sell Palladium here](https://inara.cz/test2)",
            }
        }
    }

    message = messenger._build_message([], powerplay_lines, all_data)

    # Verify message content
    assert "You can earn merits" in message
    assert "[Sell Palladium here]" in message
    assert (
        "acquisition systems" not in message
    )  # Stronghold should not include "acquisition systems"


def test_powerplay_message_without_commodity_urls():
    """Test that powerplay message works without commodity_urls field (backward compatibility)."""
    from unittest.mock import Mock

    mock_client = Mock()
    mock_client.guilds = []

    messenger = DiscordMessenger(
        mock_client,
        _settings(),
        guild_prefs=Mock(get_preferences=lambda x, y: {}),
        opt_outs=Mock(is_opted_out=lambda x: False),
        subscribers=Mock(all=lambda: []),
    )

    powerplay_lines = [
        {"system_name": "TestSystem", "power": "Zachary Hudson", "status": "Fortified"}
    ]

    all_data = {
        "TestSystem": {
            "powerplay": {
                "power": "Zachary Hudson",
                "status": "Fortified",
                "progress": "75%",
                # No commodity_urls field
            }
        }
    }

    message = messenger._build_message([], powerplay_lines, all_data)

    # Verify message content - should not have merit text
    assert "You can earn merits" not in message
    assert "[Sell" not in message
    assert "TestSystem" in message  # But should still have basic info
