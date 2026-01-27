from __future__ import annotations

import asyncio
import logging
import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Any, DefaultDict, Optional, Set, Tuple

import discord
from discord import AllowedMentions

from .config import Settings
from .message_filters import filter_message_for_preferences
from .services import (
    GuildPreferencesService,
    OptOutService,
    SubscriberService,
)

if TYPE_CHECKING:
    from .market_database import MarketDatabase


class DiscordMessenger:
    def __init__(
        self,
        client: discord.Client,
        settings: Settings,
        guild_prefs: GuildPreferencesService,
        opt_outs: OptOutService,
        subscribers: SubscriberService,
        logger: Optional[logging.Logger] = None,
        market_db: Optional[MarketDatabase] = None,
    ):
        self.client = client
        self.settings = settings
        self.guild_prefs = guild_prefs
        self.opt_outs = opt_outs
        self.subscribers = subscribers
        self.logger = logger or logging.getLogger("bot.messaging")
        self.market_db = market_db

        # Message queue items are tagged with the gold.py cycle number so pings
        # only fire for guilds that actually received a message in that cycle.
        self.queue: asyncio.Queue[Tuple[int, str]] = asyncio.Queue(
            maxsize=settings.queue_max_size
        )
        self.ping_queue: asyncio.Queue[int] = asyncio.Queue(
            maxsize=settings.queue_max_size
        )
        self._cycle_lock = threading.Lock()
        self._cycle_id: int = 0
        self._delivered_by_cycle: DefaultDict[int, Set[int]] = defaultdict(set)

    def enqueue_from_thread(self, content: str) -> None:
        """Schedule a message into the dispatcher queue from any thread."""

        def _put():
            with self._cycle_lock:
                cycle = self._cycle_id

            try:
                self.queue.put_nowait((cycle, content))
            except asyncio.QueueFull:
                self.logger.warning(
                    "[queue] Message queue full (%s items), dropping message",
                    self.settings.queue_max_size,
                )

        self.client.loop.call_soon_threadsafe(_put)

    def loop_done_from_thread(self) -> None:
        asyncio.run_coroutine_threadsafe(self._drain_after_queue(), self.client.loop)
        if self.market_db:
            asyncio.run_coroutine_threadsafe(
                self.dispatch_from_database(self.market_db), self.client.loop
            )

    async def _drain_after_queue(self) -> None:
        await self.queue.join()
        self._drain_and_emit_pings()

    async def start_background_tasks(self) -> None:
        asyncio.create_task(self._dispatcher_loop())
        asyncio.create_task(self._ping_loop())

    async def _dispatcher_loop(self) -> None:
        await self.client.wait_until_ready()
        while True:
            cycle_id, msg = await self.queue.get()
            try:
                guilds = list(self.client.guilds)
                guild_tasks = [
                    asyncio.create_task(self._send_to_guild(g, msg)) for g in guilds
                ]
                dm_task = asyncio.create_task(self._dm_subscribers_broadcast(msg))

                results = await asyncio.gather(
                    *(guild_tasks + [dm_task]), return_exceptions=True
                )
                sent_guild_ids = {
                    g.id
                    for g, r in zip(guilds, results[:-1])
                    if (r is True) and not isinstance(r, Exception)
                }
                if sent_guild_ids:
                    with self._cycle_lock:
                        self._delivered_by_cycle[cycle_id].update(sent_guild_ids)
            finally:
                self.queue.task_done()

    def _drain_and_emit_pings(self) -> None:
        with self._cycle_lock:
            current_cycle = self._cycle_id
            to_ping = list(self._delivered_by_cycle.pop(current_cycle, set()))
            # Advance cycle so any deliveries after loop_done are counted for the next cycle.
            self._cycle_id += 1

        for gid in to_ping:
            if not self.guild_prefs.pings_enabled(gid):
                self.logger.debug("[ping] Skipping guild %s (pings disabled)", gid)
                continue
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
                self.logger.error(
                    "[ping_loop] Permission denied for guild %s: %s", gid, exc
                )
            except discord.HTTPException as exc:
                self.logger.error("[ping_loop] HTTP error for guild %s: %s", gid, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[ping_loop] Unexpected error for guild %s: %s",
                    gid,
                    exc,
                    exc_info=True,
                )
            finally:
                self.ping_queue.task_done()

    async def _dm_subscribers_broadcast(self, content: str) -> None:
        targets = self.subscribers.all()
        if not targets:
            return

        allowed_mentions = AllowedMentions.none()

        async def _send_one(uid: int) -> None:
            if self.settings.debug_mode_dms and self.settings.debug_user_id:
                if uid != self.settings.debug_user_id:
                    self.logger.debug(
                        "[DM] Skipping user %s (DEBUG_MODE_DMS active)", uid
                    )
                    return

            prefs = self.guild_prefs.get_preferences("user", uid)
            filtered = filter_message_for_preferences(content, prefs)
            if filtered is None:
                self.logger.debug(
                    "[DM] Skipping user %s due to preference filters", uid
                )
                return

            try:
                user = await self.client.fetch_user(uid)
                await user.send(filtered, allowed_mentions=allowed_mentions)
                self.logger.debug("[DM] Sent to user %s", uid)
            except discord.NotFound:
                self.logger.info(
                    "[DM] User %s not found (deleted account?), unsubscribing", uid
                )
                self.subscribers.discard(uid)
            except discord.Forbidden as exc:
                if "Cannot send messages to this user" in str(exc):
                    self.logger.info("[DM] Cannot message user %s, unsubscribing", uid)
                    self.subscribers.discard(uid)
                else:
                    self.logger.warning(
                        "[DM] Forbidden error for user %s: %s", uid, exc
                    )
            except discord.HTTPException as exc:
                self.logger.error("[DM] HTTP error sending to user %s: %s", uid, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[DM] Unexpected error sending to user %s: %s",
                    uid,
                    exc,
                    exc_info=True,
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

    async def _send_to_guild(self, guild: discord.Guild, content: str) -> bool:
        if self.opt_outs.is_opted_out(guild.id):
            self.logger.debug("[%s] Skipping - guild opted out", guild.name)
            return False

        if self.settings.debug_mode and self.settings.debug_server_id:
            if guild.id != self.settings.debug_server_id:
                self.logger.debug(
                    "[DEBUG MODE] Skipping message to server %s, only sending to %s.",
                    guild.id,
                    self.settings.debug_server_id,
                )
                return False

        prefs = self.guild_prefs.get_preferences("guild", guild.id)
        filtered = filter_message_for_preferences(content, prefs)
        if filtered is None:
            self.logger.debug(
                "[%s] Message filtered out by preferences; skipping.", guild.name
            )
            return False

        channel = self._resolve_sendable_channel(guild)
        if not channel:
            self.logger.warning(
                "[%s] No sendable channel resolved; skipping.", guild.name
            )
            return False

        try:
            await channel.send(filtered, allowed_mentions=AllowedMentions.none())
            self.logger.info(
                "[%s] Alert sent to #%s", guild.name, channel.name
            )
            return True
        except discord.Forbidden as exc:
            self.logger.error(
                "[%s] Permission denied sending to #%s: %s",
                guild.name,
                channel.name,
                exc,
            )
            return False
        except discord.HTTPException as exc:
            self.logger.error(
                "[%s] HTTP error sending to #%s: %s",
                guild.name,
                channel.name,
                exc,
                exc_info=True,
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

    async def dispatch_from_database(self, market_db: MarketDatabase) -> None:
        """
        Read all entries from MarketDatabase and dispatch messages to guilds and DM subscribers.
        
        For each entry:
        - Check cooldown via market_db.check_cooldown()
        - Apply preference filtering via filter_message_for_preferences()
        - Send message with role mention for guilds (when pings enabled)
        - Mark sent via market_db.mark_sent() after successful delivery
        """
        from .alert_helpers import assemble_hidden_market_messages
        
        if not market_db:
            self.logger.warning("[dispatch_from_database] No market_db provided")
            return
        
        # Read all entries from database
        all_data = market_db.read_all_entries()
        
        # Process market alerts (system -> station -> metal)
        market_entries = []
        for system_name, system_data in all_data.items():
            if "stations" not in system_data:
                continue
            
            system_address = system_data.get("system_address", "")
            
            for station_name, station_data in system_data["stations"].items():
                if "metals" not in station_data:
                    continue
                
                station_type = station_data.get("station_type", "Unknown")
                url = station_data.get("url", "")
                
                # Collect metals for this station
                metals_list = []
                for metal, metal_data in station_data["metals"].items():
                    stock = metal_data.get("stock", 0)
                    metals_list.append((metal, stock))
                
                if metals_list:
                    market_entries.append({
                        "system_name": system_name,
                        "system_address": system_address,
                        "station_name": station_name,
                        "station_type": station_type,
                        "url": url,
                        "metals": metals_list,
                    })
        
        # Build messages using existing helper
        messages = assemble_hidden_market_messages(market_entries)
        
        # Dispatch market messages
        for message in messages:
            await self._dispatch_message_to_all(message, all_data, is_powerplay=False)
        
        # Process powerplay alerts
        for system_name, system_data in all_data.items():
            if "powerplay" not in system_data or not system_data["powerplay"]:
                continue
            
            powerplay = system_data["powerplay"]
            power = powerplay.get("power")
            status = powerplay.get("status")

            if not power or not status:
                continue
            
            # Build powerplay message (similar to powerplay.py format)
            # For now, we'll use a simple format - the actual format depends on status
            if status in ("Fortified", "Stronghold"):
                # This is a simplified version - actual implementation would need commodity links
                message = f"{system_name} is a {power} {status} system."
                await self._dispatch_message_to_all(
                    message, 
                    all_data, 
                    is_powerplay=True,
                    powerplay_system=system_name
                )

    async def _dispatch_message_to_all(
        self,
        content: str,
        all_data: dict[str, Any],
        is_powerplay: bool = False,
        powerplay_system: Optional[str] = None,
    ) -> None:
        """
        Dispatch a single message to all guilds and DM subscribers.
        
        Args:
            content: Message content to send
            all_data: Full database data for cooldown tracking
            is_powerplay: Whether this is a powerplay message
            powerplay_system: System name for powerplay messages
        """
        if not self.market_db:
            return
        
        # Dispatch to guilds
        guilds = list(self.client.guilds)
        for guild in guilds:
            await self._send_to_guild_from_db(guild, content, is_powerplay, powerplay_system)
        
        # Dispatch to DM subscribers
        await self._dm_subscribers_from_db(content, is_powerplay, powerplay_system)

    async def _send_to_guild_from_db(
        self, 
        guild: discord.Guild, 
        content: str,
        is_powerplay: bool = False,
        powerplay_system: Optional[str] = None
    ) -> bool:
        """
        Send message to a guild with database-driven cooldown tracking.
        
        Returns True if message was sent successfully.
        """
        if not self.market_db:
            return False
        
        if self.opt_outs.is_opted_out(guild.id):
            self.logger.debug("[%s] Skipping - guild opted out", guild.name)
            return False

        if self.settings.debug_mode and self.settings.debug_server_id:
            if guild.id != self.settings.debug_server_id:
                self.logger.debug(
                    "[DEBUG MODE] Skipping message to server %s, only sending to %s.",
                    guild.id,
                    self.settings.debug_server_id,
                )
                return False

        # Apply preference filtering
        prefs = self.guild_prefs.get_preferences("guild", guild.id)
        filtered = filter_message_for_preferences(content, prefs)
        if filtered is None:
            self.logger.debug(
                "[%s] Message filtered out by preferences; skipping.", guild.name
            )
            return False

        # Extract system/station/metal from message for cooldown tracking
        # For market messages, we need to parse the message
        # For powerplay messages, we use the powerplay_system parameter
        
        # Parse message to extract entries for cooldown checking
        entries = self._parse_message_for_cooldown(filtered, is_powerplay, powerplay_system)
        
        # Check cooldowns for all entries in this message
        all_on_cooldown = True
        for system_name, station_name, metal in entries:
            if self.market_db.check_cooldown(
                system_name=system_name,
                station_name=station_name,
                metal=metal,
                recipient_type="guild",
                recipient_id=str(guild.id),
                cooldown_seconds=self.settings.cooldown_seconds,
            ):
                all_on_cooldown = False
                break
        
        if all_on_cooldown and entries:
            self.logger.debug(
                "[%s] All entries on cooldown; skipping.", guild.name
            )
            return False

        channel = self._resolve_sendable_channel(guild)
        if not channel:
            self.logger.warning(
                "[%s] No sendable channel resolved; skipping.", guild.name
            )
            return False

        # Build message with role mention if pings enabled
        final_message = filtered
        if self.guild_prefs.pings_enabled(guild.id):
            role = self._find_role_by_name(guild)
            if role:
                final_message = f"{role.mention}\n{filtered}"

        try:
            await channel.send(
                final_message, 
                allowed_mentions=AllowedMentions(
                    roles=True, users=False, everyone=False
                ) if self.guild_prefs.pings_enabled(guild.id) else AllowedMentions.none()
            )
            
            # Mark all entries as sent
            for system_name, station_name, metal in entries:
                self.market_db.mark_sent(
                    system_name=system_name,
                    station_name=station_name,
                    metal=metal,
                    recipient_type="guild",
                    recipient_id=str(guild.id),
                )
            
            self.logger.info(
                "[%s] Alert sent to #%s", guild.name, channel.name
            )
            return True
        except discord.Forbidden as exc:
            self.logger.error(
                "[%s] Permission denied sending to #%s: %s",
                guild.name,
                channel.name,
                exc,
            )
            return False
        except discord.HTTPException as exc:
            self.logger.error(
                "[%s] HTTP error sending to #%s: %s",
                guild.name,
                channel.name,
                exc,
                exc_info=True,
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

    async def _dm_subscribers_from_db(
        self, 
        content: str,
        is_powerplay: bool = False,
        powerplay_system: Optional[str] = None
    ) -> None:
        """
        Send message to all DM subscribers with database-driven cooldown tracking.
        """
        if not self.market_db:
            return
        
        targets = self.subscribers.all()
        if not targets:
            return

        allowed_mentions = AllowedMentions.none()

        async def _send_one(uid: int) -> None:
            if self.settings.debug_mode_dms and self.settings.debug_user_id:
                if uid != self.settings.debug_user_id:
                    self.logger.debug(
                        "[DM] Skipping user %s (DEBUG_MODE_DMS active)", uid
                    )
                    return

            prefs = self.guild_prefs.get_preferences("user", uid)
            filtered = filter_message_for_preferences(content, prefs)
            if filtered is None:
                self.logger.debug(
                    "[DM] Skipping user %s due to preference filters", uid
                )
                return

            # Parse message to extract entries for cooldown checking
            entries = self._parse_message_for_cooldown(filtered, is_powerplay, powerplay_system)
            
            # Check cooldowns for all entries in this message
            all_on_cooldown = True
            if not self.market_db:
                return
            
            for system_name, station_name, metal in entries:
                if self.market_db.check_cooldown(
                    system_name=system_name,
                    station_name=station_name,
                    metal=metal,
                    recipient_type="user",
                    recipient_id=str(uid),
                    cooldown_seconds=self.settings.cooldown_seconds,
                ):
                    all_on_cooldown = False
                    break
            
            if all_on_cooldown and entries:
                self.logger.debug(
                    "[DM] Skipping user %s - all entries on cooldown", uid
                )
                return

            try:
                user = await self.client.fetch_user(uid)
                await user.send(filtered, allowed_mentions=allowed_mentions)
                
                # Mark all entries as sent
                for system_name, station_name, metal in entries:
                    self.market_db.mark_sent(
                        system_name=system_name,
                        station_name=station_name,
                        metal=metal,
                        recipient_type="user",
                        recipient_id=str(uid),
                    )
                
                self.logger.debug("[DM] Sent to user %s", uid)
            except discord.NotFound:
                self.logger.info(
                    "[DM] User %s not found (deleted account?), unsubscribing", uid
                )
                self.subscribers.discard(uid)
            except discord.Forbidden as exc:
                if "Cannot send messages to this user" in str(exc):
                    self.logger.info("[DM] Cannot message user %s, unsubscribing", uid)
                    self.subscribers.discard(uid)
                else:
                    self.logger.warning(
                        "[DM] Forbidden error for user %s: %s", uid, exc
                    )
            except discord.HTTPException as exc:
                self.logger.error("[DM] HTTP error sending to user %s: %s", uid, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[DM] Unexpected error sending to user %s: %s",
                    uid,
                    exc,
                    exc_info=True,
                )

        await asyncio.gather(
            *[asyncio.create_task(_send_one(uid)) for uid in targets],
            return_exceptions=True,
        )

    def _parse_message_for_cooldown(
        self, 
        content: str, 
        is_powerplay: bool = False,
        powerplay_system: Optional[str] = None
    ) -> list[tuple[str, str, str]]:
        """
        Parse message content to extract (system_name, station_name, metal) tuples for cooldown tracking.
        
        Returns:
            List of (system_name, station_name, metal) tuples
        """
        import re
        
        entries = []
        
        if is_powerplay and powerplay_system:
            # For powerplay messages, use system_name as station_name and "powerplay" as metal
            entries.append((powerplay_system, powerplay_system, "powerplay"))
        else:
            # Parse market message format:
            # "Hidden markets detected in <system_name> (<system_address>):"
            # "- <station_name> (<station_type>), <url> - Gold stock: 25000; Palladium stock: 15000"
            
            lines = content.split("\n")
            current_system = None
            
            for line in lines:
                # Check for system header
                if "Hidden markets detected in" in line:
                    # Extract system name
                    match = re.search(r"Hidden markets detected in (.+?) \(", line)
                    if match:
                        current_system = match.group(1)
                # Check for station line
                elif line.strip().startswith("-") and current_system:
                    # Extract station name
                    station_match = re.search(r"- (.+?) \(", line)
                    if station_match:
                        station_name = station_match.group(1)
                        
                        # Extract metals from "Gold stock: X; Palladium stock: Y" format
                        if "Gold stock:" in line:
                            entries.append((current_system, station_name, "Gold"))
                        if "Palladium stock:" in line:
                            entries.append((current_system, station_name, "Palladium"))
        
        return entries
