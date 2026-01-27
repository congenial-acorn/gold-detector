import asyncio
import sys
from pathlib import Path

import discord
from discord import app_commands

from gold_detector.commands.alerts import register_alert_commands
from gold_detector.commands.errors import attach_error_handler
from gold_detector.commands.health import register_health_commands
from gold_detector.commands.preferences import register_preference_commands
from gold_detector.commands.server_settings import register_server_settings_commands
from gold_detector.config import Settings, configure_logging
from gold_detector.gold_runner import GoldRunner
from gold_detector.market_database import MarketDatabase
from gold_detector.messaging import DiscordMessenger
from gold_detector.services import (
    CooldownService,
    GuildPreferencesService,
    OptOutService,
    SubscriberService,
    default_paths,
)

settings = Settings.from_env()
logger = configure_logging(settings.log_level)

intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

paths = default_paths()
guild_prefs = GuildPreferencesService(
    paths["guild_prefs"],
    default_channel=settings.default_alert_channel,
    default_role=settings.default_role_name,
    channel_override=settings.alert_channel_override,
    role_override=settings.role_name_override,
)
subscribers = SubscriberService(paths["subs"])
opt_outs = OptOutService(paths["guild_optout"])
server_cooldowns = CooldownService(
    paths["server_cooldowns"], ttl_seconds=settings.cooldown_seconds
)
user_cooldowns = CooldownService(
    paths["user_cooldowns"], ttl_seconds=settings.cooldown_seconds
)

db_path = Path("market_database.json")
market_db = MarketDatabase(db_path)

messenger = DiscordMessenger(
    client=client,
    settings=settings,
    guild_prefs=guild_prefs,
    opt_outs=opt_outs,
    server_cooldowns=server_cooldowns,
    user_cooldowns=user_cooldowns,
    subscribers=subscribers,
    logger=logger.getChild("messaging"),
    market_db=market_db,
)

register_alert_commands(tree, subscribers, settings.help_url)
register_server_settings_commands(tree, guild_prefs, opt_outs)
register_preference_commands(tree, guild_prefs)
register_health_commands(tree)
attach_error_handler(tree, logger)

_background_started = False


@client.event
async def on_ready():
    await client.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="/help if you don't receive alerts"),
        status=discord.Status.online,
    )
    logger.info("=== Bot Ready ===")
    logger.info("Logged in as %s (ID: %s)", client.user, client.user.id)
    logger.info("Connected to %s guilds", len(client.guilds))
    logger.info(
        "Default channel: #%s",
        settings.alert_channel_override or settings.default_alert_channel,
    )
    logger.info(
        "Default ping role: @%s",
        settings.role_name_override or settings.default_role_name,
    )
    logger.info("Cooldown after each message: %sh", settings.cooldown_hours)
    logger.info("Monitor interval: %ss", settings.monitor_interval_seconds)
    logger.info("HTTP cooldown: %ss", settings.http_cooldown_seconds)

    global _background_started
    if _background_started:
        logger.info(
            "on_ready(): background tasks already running; skipping re-initialization."
        )
        return

    _background_started = True
    try:
        await messenger.start_background_tasks()
        asyncio.create_task(messenger.snapshot_cooldowns())

        try:
            await tree.sync()
            logger.info("Slash commands synced.")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Slash command sync failed: %s", exc)

        GoldRunner(
            emit=messenger.enqueue_from_thread,
            loop_done=messenger.loop_done_from_thread,
            logger=logger.getChild("gold_runner"),
        ).start()
        logger.info("Started gold.py in background thread.")
    except Exception:
        _background_started = False
        raise


@client.event
async def on_disconnect():
    logger.warning("Discord connection lost (on_disconnect event)")


@client.event
async def on_resumed():
    logger.info("Discord connection resumed successfully")


@client.event
async def on_error(event, *args, **kwargs):
    logger.error("Discord event error in %s: %s %s", event, args, kwargs, exc_info=True)


@client.event
async def on_guild_join(guild):
    logger.info(
        "Joined new guild: %s (ID: %s, members: %s)",
        guild.name,
        guild.id,
        guild.member_count,
    )


@client.event
async def on_guild_remove(guild):
    logger.info("Removed from guild: %s (ID: %s)", guild.name, guild.id)


if __name__ == "__main__":
    logger.info("Starting Discord bot...")
    logger.info("Python version: %s", sys.version)
    logger.info("Discord.py version: %s", discord.__version__)
    try:
        client.run(settings.token)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down")
    except Exception as exc:  # noqa: BLE001
        logger.critical("Fatal error running bot: %s", exc, exc_info=True)
        raise
