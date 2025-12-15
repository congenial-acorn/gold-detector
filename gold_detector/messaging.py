from __future__ import annotations

import asyncio
import logging
import threading
from typing import Iterable, Optional, Set

import discord
from discord import AllowedMentions

from .config import Settings
from .services import (
    CooldownService,
    GuildPreferencesService,
    OptOutService,
    SubscriberService,
)
from .utils import message_key, now


class DiscordMessenger:
    def __init__(
        self,
        client: discord.Client,
        settings: Settings,
        guild_prefs: GuildPreferencesService,
        opt_outs: OptOutService,
        server_cooldowns: CooldownService,
        user_cooldowns: CooldownService,
        subscribers: SubscriberService,
        logger: Optional[logging.Logger] = None,
    ):
        self.client = client
        self.settings = settings
        self.guild_prefs = guild_prefs
        self.opt_outs = opt_outs
        self.server_cooldowns = server_cooldowns
        self.user_cooldowns = user_cooldowns
        self.subscribers = subscribers
        self.logger = logger or logging.getLogger("bot.messaging")

        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=settings.queue_max_size)
        self.ping_queue: asyncio.Queue[int] = asyncio.Queue(
            maxsize=settings.queue_max_size
        )
        self._sent_since_last_loop: Set[int] = set()
        self._sent_lock = threading.Lock()

    def enqueue_from_thread(self, content: str) -> None:
        """Schedule a message into the dispatcher queue from any thread."""

        def _put():
            try:
                self.queue.put_nowait(content)
            except asyncio.QueueFull:
                self.logger.warning(
                    "[queue] Message queue full (%s items), dropping message",
                    self.settings.queue_max_size,
                )

        self.client.loop.call_soon_threadsafe(_put)

    def loop_done_from_thread(self) -> None:
        self.client.loop.call_soon_threadsafe(self._drain_and_emit_pings)

    async def start_background_tasks(self) -> None:
        asyncio.create_task(self._dispatcher_loop())
        asyncio.create_task(self._ping_loop())

    async def _dispatcher_loop(self) -> None:
        await self.client.wait_until_ready()
        while True:
            msg = await self.queue.get()
            message_id = message_key(msg)
            try:
                guilds = list(self.client.guilds)
                guild_tasks = [
                    asyncio.create_task(self._send_to_guild(g, msg, message_id))
                    for g in guilds
                ]
                dm_task = asyncio.create_task(
                    self._dm_subscribers_broadcast(msg, message_id)
                )

                results = await asyncio.gather(
                    *(guild_tasks + [dm_task]), return_exceptions=True
                )
                sent_guild_ids = {
                    g.id
                    for g, r in zip(guilds, results[:-1])
                    if (r is True) and not isinstance(r, Exception)
                }
                if sent_guild_ids:
                    with self._sent_lock:
                        self._sent_since_last_loop.update(sent_guild_ids)
            finally:
                self.queue.task_done()

    def _drain_and_emit_pings(self) -> None:
        with self._sent_lock:
            to_ping = list(self._sent_since_last_loop)
            self._sent_since_last_loop.clear()

        for gid in to_ping:
            try:
                self.ping_queue.put_nowait(gid)
            except asyncio.QueueFull:
                self.logger.error("[ping] Queue full, cannot enqueue guild %s", gid)

        if to_ping:
            self.logger.info("[ping] Queued pings for %s guilds", len(to_ping))
        else:
            self.logger.debug(
                "Loop done: no guild deliveries this cycle; suppressing all pings."
            )

    async def _ping_loop(self) -> None:
        while True:
            gid = await self.ping_queue.get()
            try:
                guild = self.client.get_guild(gid)
                if not guild:
                    self.logger.warning(
                        "[ping_loop] Guild %s not found, skipping ping", gid
                    )
                    continue

                channel = self._resolve_sendable_channel(guild)
                if not channel:
                    self.logger.warning("[ping_loop] No sendable channel in %s", guild)
                    continue

                role = self._find_role_by_name(guild)
                if role:
                    await channel.send(
                        f"{role.mention}",
                        allowed_mentions=AllowedMentions(
                            roles=True, users=False, everyone=False
                        ),
                    )
                    self.logger.info("[%s] Ping sent to role %s", guild.name, role.name)
                else:
                    await channel.send(
                        "Scan complete. New results above.",
                        allowed_mentions=AllowedMentions.none(),
                    )
                    self.logger.info(
                        "[%s] Scan complete message sent (no role)", guild.name
                    )
            except discord.Forbidden as exc:
                self.logger.error("[ping_loop] Permission denied for guild %s: %s", gid, exc)
            except discord.HTTPException as exc:
                self.logger.error("[ping_loop] HTTP error for guild %s: %s", gid, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[ping_loop] Unexpected error for guild %s: %s", gid, exc, exc_info=True
                )
            finally:
                self.ping_queue.task_done()

    async def _dm_subscribers_broadcast(self, content: str, message_id: int) -> None:
        targets = self.subscribers.all()
        if not targets:
            return

        ts = now()
        allowed_mentions = AllowedMentions.none()

        async def _send_one(uid: int) -> None:
            if self.settings.debug_mode_dms and self.settings.debug_user_id:
                if uid != self.settings.debug_user_id:
                    self.logger.debug(
                        "[DM] Skipping user %s (DEBUG_MODE_DMS active)", uid
                    )
                    return

            allow, prev, remaining = self.user_cooldowns.should_send(
                uid, message_id, ts, update_on_allow=False
            )
            if not allow:
                self.logger.debug(
                    "[DM] Skipping user %s; %.2fh remaining for msg %s",
                    uid,
                    (remaining or 0) / 3600,
                    message_id,
                )
                return

            try:
                user = await self.client.fetch_user(uid)
                await user.send(content, allowed_mentions=allowed_mentions)
                self.user_cooldowns.mark_sent(uid, message_id, ts)
                self.logger.debug("[DM] Sent to user %s (prev=%s)", uid, prev)
            except discord.NotFound:
                self.logger.info(
                    "[DM] User %s not found (deleted account?), unsubscribing", uid
                )
                self.subscribers.discard(uid)
            except discord.Forbidden as exc:
                if "Cannot send messages to this user" in str(exc):
                    self.logger.info(
                        "[DM] Cannot message user %s, unsubscribing", uid
                    )
                    self.subscribers.discard(uid)
                else:
                    self.logger.warning("[DM] Forbidden error for user %s: %s", uid, exc)
            except discord.HTTPException as exc:
                self.logger.error("[DM] HTTP error sending to user %s: %s", uid, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[DM] Unexpected error sending to user %s: %s", uid, exc, exc_info=True
                )

        await asyncio.gather(
            *[asyncio.create_task(_send_one(uid)) for uid in targets],
            return_exceptions=True,
        )

    def _resolve_sendable_channel(
        self, guild: discord.Guild
    ) -> Optional[discord.TextChannel]:
        name = self.guild_prefs.effective_channel_name(guild.id).lower()
        cid = self.guild_prefs.effective_channel_id(guild.id)

        if not self.client.user:
            self.logger.error("[_resolve_sendable_channel] Bot user not initialized")
            return None

        me = guild.me
        if not me:
            self.logger.error("[%s] Bot not found in guild member list", guild.name)
            return None

        if cid:
            channel = guild.get_channel(cid)
            if isinstance(channel, discord.TextChannel):
                perms = channel.permissions_for(me)
                if perms.view_channel and perms.send_messages:
                    return channel
                self.logger.warning(
                    "[%s] Channel <#%s> exists but lacks permissions "
                    "(view: %s, send: %s)",
                    guild.name,
                    cid,
                    perms.view_channel,
                    perms.send_messages,
                )

        for channel in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
            if channel.name.lower() == name:
                perms = channel.permissions_for(me)
                if perms.view_channel and perms.send_messages:
                    return channel
                self.logger.debug(
                    "[%s] Channel #%s matches but lacks permissions",
                    guild.name,
                    channel.name,
                )

        self.logger.warning(
            "[%s] No sendable channel found (looking for '#%s' or ID %s)",
            guild.name,
            name,
            cid,
        )
        return None

    def _find_role_by_name(self, guild: discord.Guild) -> Optional[discord.Role]:
        rid = self.guild_prefs.effective_role_id(guild.id)
        rname = self.guild_prefs.effective_role_name(guild.id).lower()
        if rid:
            role = guild.get_role(rid)
            if isinstance(role, discord.Role):
                return role
        for role in guild.roles:
            if role.name.lower() == rname:
                return role
        return None

    async def _send_to_guild(
        self, guild: discord.Guild, content: str, message_id: int
    ) -> bool:
        if self.opt_outs.is_opted_out(guild.id):
            self.logger.debug("[%s] Skipping - guild opted out", guild.name)
            return False

        ts = now()
        if self.settings.debug_mode and self.settings.debug_server_id:
            if guild.id != self.settings.debug_server_id:
                self.logger.debug(
                    "[DEBUG MODE] Skipping message to server %s, only sending to %s.",
                    guild.id,
                    self.settings.debug_server_id,
                )
                return False

        allowed, prev, remaining = self.server_cooldowns.should_send(
            guild.id, message_id, ts
        )
        if not allowed:
            hrs = (remaining or 0) / 3600
            self.logger.debug(
                "[%s] Cooldown active for msg %s; skipping (~%.2fh).",
                guild.name,
                message_id,
                hrs,
            )
            return False

        channel = self._resolve_sendable_channel(guild)
        if not channel:
            self.logger.warning("[%s] No sendable channel resolved; skipping.", guild.name)
            return False

        try:
            await channel.send(content, allowed_mentions=AllowedMentions.none())
            if prev is None:
                self.logger.info("[%s] Alert sent to #%s (first time)", guild.name, channel.name)
            else:
                self.logger.info(
                    "[%s] Alert sent to #%s (cooldown expired)", guild.name, channel.name
                )
            return True
        except discord.Forbidden as exc:
            self.logger.error(
                "[%s] Permission denied sending to #%s: %s", guild.name, channel.name, exc
            )
            return False
        except discord.HTTPException as exc:
            self.logger.error(
                "[%s] HTTP error sending to #%s: %s", guild.name, channel.name, exc, exc_info=True
            )
            return False
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "[%s] Unexpected error sending to #%s: %s",
                guild.name,
                channel.name,
                exc,
                exc_info=True,
            )
            return False

    async def snapshot_cooldowns(self, interval_seconds: int = 60) -> None:
        while True:
            self.server_cooldowns.snapshot()
            self.user_cooldowns.snapshot()
            await asyncio.sleep(interval_seconds)
