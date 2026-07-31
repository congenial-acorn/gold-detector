import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import cast, final

import discord

from gold_detector.bgs_states import (
    BgsFetcher,
    BgsStateError,
    SystemBgsQuery,
    SystemStationWarnings,
)
from gold_detector.config import Settings
from gold_detector.market_database import MarketDatabase
from gold_detector.messaging import DiscordMessenger
from gold_detector.services import (
    GuildPreferencesService,
    OptOutService,
    SubscriberService,
)


@final
class FakeChannel:
    def __init__(self) -> None:
        self.name: str = "market-watch"
        self.position: int = 0
        self.id: int = 999
        self.sent_messages: list[str] = []

    def permissions_for(self, _member: discord.Member) -> discord.Permissions:
        return discord.Permissions(view_channel=True, send_messages=True)

    async def send(
        self,
        content: str,
        *,
        allowed_mentions: discord.AllowedMentions,
    ) -> None:
        _ = allowed_mentions
        self.sent_messages.append(content)


@final
class FakeGuild:
    def __init__(self, channel: FakeChannel) -> None:
        self.id: int = 123456
        self.name: str = "Test Guild"
        self.me: discord.Member = cast(discord.Member, cast(object, self))
        self.text_channels: list[FakeChannel] = [channel]
        self.roles: list[discord.Role] = []

    def get_channel(self, _channel_id: int) -> None:
        return None


@final
class FakeClient:
    def __init__(self, guild: FakeGuild) -> None:
        self.user: discord.ClientUser = cast(discord.ClientUser, cast(object, self))
        self.guilds: list[discord.Guild] = [cast(discord.Guild, cast(object, guild))]


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


def _build_scenario(
    tmp_path: Path,
    bgs_fetcher: BgsFetcher,
) -> tuple[DiscordMessenger, MarketDatabase, FakeChannel]:
    market_db = MarketDatabase(tmp_path / "market.json")
    market_db.write_market_entry(
        system_name="Albarib",
        system_address="https://inara.cz/elite/starsystem/3207/",
        station_name="Hale Orbital",
        station_type="Coriolis Starport",
        url="https://inara.cz/elite/station-market/5894/",
        metal="Gold",
        stock=25000,
    )
    channel = FakeChannel()
    guild = FakeGuild(channel)
    client = FakeClient(guild)
    guild_prefs = GuildPreferencesService(
        tmp_path / "guild_prefs.json",
        default_channel="market-watch",
        default_role="Market Alert",
        channel_override="",
        role_override="",
    )
    guild_prefs.set_pings_enabled(guild.id, False)
    messenger = DiscordMessenger(
        cast(discord.Client, cast(object, client)),
        _settings(),
        guild_prefs,
        OptOutService(tmp_path / "opt_outs.json"),
        SubscriberService(tmp_path / "subscribers.json"),
        bgs_fetcher=bgs_fetcher,
    )
    return messenger, market_db, channel


def test_dispatch_appends_reduced_supply_state_warning(tmp_path: Path) -> None:
    async def run_scenario() -> None:
        # Given
        async def fake_fetch_system_reduced_supply_states(
            queries: Sequence[SystemBgsQuery],
        ) -> SystemStationWarnings:
            assert queries == [
                SystemBgsQuery(
                    system_name="Albarib",
                    system_address="https://inara.cz/elite/starsystem/3207/",
                    station_names=frozenset({"Hale Orbital"}),
                )
            ]
            return {
                "Albarib": {
                    "Hale Orbital": ("Boom",),
                }
            }

        messenger, market_db, channel = _build_scenario(
            tmp_path,
            fake_fetch_system_reduced_supply_states,
        )

        # When
        await messenger.dispatch_from_database(market_db)

        # Then
        assert (
            "Boom state is present, supply will be reduced." in channel.sent_messages[0]
        )

    asyncio.run(run_scenario())


def test_dispatch_sends_market_alert_when_bgs_enrichment_fails(tmp_path: Path) -> None:
    async def run_scenario() -> None:
        # Given
        async def failing_fetcher(
            queries: Sequence[SystemBgsQuery],
        ) -> SystemStationWarnings:
            assert queries
            raise BgsStateError("CSV data unavailable")

        messenger, market_db, channel = _build_scenario(tmp_path, failing_fetcher)

        # When
        try:
            await messenger.dispatch_from_database(market_db)
        except BgsStateError:
            pass

        # Then
        expected_message = (
            "Hidden markets detected in "
            + "[Albarib](<https://inara.cz/elite/starsystem/3207/>):\n"
            + "- [Hale Orbital](<https://inara.cz/elite/station-market/5894/>) "
            + "(Coriolis Starport) - Gold stock: 25,000"
        )
        assert channel.sent_messages == [expected_message]

    asyncio.run(run_scenario())
