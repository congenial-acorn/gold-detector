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

    def _passes_station_type_filter(self, station_type: str, prefs: dict[str, Any]) -> bool:
        """Check if station type passes preference filter."""
        station_type_prefs = prefs.get("station_type", [])
        if not station_type_prefs:
            return True
        
        station_type_lower = station_type.lower()
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (station_type_lower == pref_lower or
                station_type_lower.startswith(f"{pref_lower} ") or
                station_type_lower.startswith(f"{pref_lower}(") or
                f" {pref_lower} " in f" {station_type_lower} "):
                return True
        return False
    
    def _passes_commodity_filter(self, metal: str, prefs: dict[str, Any]) -> bool:
        """Check if commodity passes preference filter."""
        commodity_prefs = prefs.get("commodity", [])
        if not commodity_prefs:
            return True
        
        metal_lower = metal.lower()
        return any(metal_lower == c.lower() for c in commodity_prefs)
    
    def _passes_powerplay_filter(self, power: str, prefs: dict[str, Any]) -> bool:
        """Check if powerplay power passes preference filter."""
        powerplay_prefs = prefs.get("powerplay", [])
        if not powerplay_prefs:
            return True
        
        power_lower = power.lower()
        return any(power_lower in p.lower() or p.lower() in power_lower for p in powerplay_prefs)
    
    def _build_message(self, market_lines: list[dict[str, Any]], powerplay_lines: list[dict[str, Any]]) -> str:
        """Build message from market and powerplay lines."""
        if market_lines:
            # Group by system
            systems = {}
            for line in market_lines:
                system_name = line["system_name"]
                if system_name not in systems:
                    systems[system_name] = {
                        "system_address": line["system_address"],
                        "stations": {}
                    }
                
                station_name = line["station_name"]
                if station_name not in systems[system_name]["stations"]:
                    systems[system_name]["stations"][station_name] = {
                        "station_type": line["station_type"],
                        "url": line["url"],
                        "metals": []
                    }
                
                systems[system_name]["stations"][station_name]["metals"].append(
                    (line["metal"], line["stock"])
                )
            
            # Build message
            messages = []
            for system_name, system_data in systems.items():
                system_address = system_data["system_address"]
                addr_label = f"<{system_address}>" if system_address else "Unknown address"
                lines = [f"Hidden markets detected in {system_name} ({addr_label}):"]
                
                for station_name, station_data in system_data["stations"].items():
                    metals_str = "; ".join(
                        f"{metal} stock: {stock}" 
                        for metal, stock in station_data["metals"]
                    )
                    lines.append(
                        f"- {station_name} ({station_data['station_type']}), "
                        f"<{station_data['url']}> - {metals_str}"
                    )
                
                # Add powerplay lines for this system
                for pp_line in powerplay_lines:
                    if pp_line["system_name"] == system_name:
                        lines.append(
                            f"{pp_line['system_name']} is a {pp_line['power']} "
                            f"{pp_line['status']} system."
                        )
                
                messages.append("\n".join(lines))
            
            return "\n\n".join(messages)
        elif powerplay_lines:
            # Only powerplay
            return "\n".join(
                f"{line['system_name']} is a {line['power']} {line['status']} system."
                for line in powerplay_lines
            )
        else:
            return ""
    
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
        
        Per-recipient flow:
        - For each recipient, filter entries at data level
        - Check cooldown per-entry before including in message
        - Build message inline with filtered entries
        - Integrate ping in message (not separate loop)
        - Mark sent after successful delivery
        """
        if not market_db:
            self.logger.warning("[dispatch_from_database] No market_db provided")
            return
        
        # Read all entries from database
        all_data = market_db.read_all_entries()
        
        # Process guilds
        for guild in self.client.guilds:
            if self.opt_outs.is_opted_out(guild.id):
                self.logger.debug("[%s] Skipping - guild opted out", guild.name)
                continue
            
            if self.settings.debug_mode and self.settings.debug_server_id:
                if guild.id != self.settings.debug_server_id:
                    self.logger.debug(
                        "[DEBUG MODE] Skipping message to server %s, only sending to %s.",
                        guild.id,
                        self.settings.debug_server_id,
                    )
                    continue
            
            prefs = self.guild_prefs.get_preferences("guild", guild.id)
            
            # Collect entries that pass filter + cooldown
            market_lines = []
            powerplay_lines = []
            cooldown_keys = []
            
            for system_name, system_data in all_data.items():
                system_address = system_data.get("system_address", "")
                
                # Process stations
                if "stations" in system_data:
                    for station_name, station_data in system_data["stations"].items():
                        station_type = station_data.get("station_type", "Unknown")
                        url = station_data.get("url", "")
                        
                        if "metals" in station_data:
                            for metal, metal_data in station_data["metals"].items():
                                stock = metal_data.get("stock", 0)
                                
                                # Check preferences at data level
                                if not self._passes_station_type_filter(station_type, prefs):
                                    continue
                                if not self._passes_commodity_filter(metal, prefs):
                                    continue
                                
                                # Check cooldown BEFORE including
                                if not market_db.check_cooldown(
                                    system_name=system_name,
                                    station_name=station_name,
                                    metal=metal,
                                    recipient_type="guild",
                                    recipient_id=str(guild.id),
                                    cooldown_seconds=self.settings.cooldown_seconds
                                ):
                                    continue
                                
                                # Entry passes - add to message
                                market_lines.append({
                                    "system_name": system_name,
                                    "system_address": system_address,
                                    "station_name": station_name,
                                    "station_type": station_type,
                                    "url": url,
                                    "metal": metal,
                                    "stock": stock,
                                })
                                cooldown_keys.append((system_name, station_name, metal))
                
                # Process powerplay
                if "powerplay" in system_data and system_data["powerplay"]:
                    powerplay = system_data["powerplay"]
                    power = powerplay.get("power")
                    status = powerplay.get("status")
                    
                    if power and status and status in ("Fortified", "Stronghold"):
                        if self._passes_powerplay_filter(power, prefs):
                            if market_db.check_cooldown(
                                system_name=system_name,
                                station_name=system_name,
                                metal="powerplay",
                                recipient_type="guild",
                                recipient_id=str(guild.id),
                                cooldown_seconds=self.settings.cooldown_seconds
                            ):
                                powerplay_lines.append({
                                    "system_name": system_name,
                                    "power": power,
                                    "status": status,
                                })
                                cooldown_keys.append((system_name, system_name, "powerplay"))
            
            if not market_lines and not powerplay_lines:
                continue
            
            # Build message inline
            message = self._build_message(market_lines, powerplay_lines)
            
            # Add ping if enabled
            if self.guild_prefs.pings_enabled(guild.id):
                role = self._find_role_by_name(guild)
                if role:
                    message = f"{role.mention}\n{message}"
            
            channel = self._resolve_sendable_channel(guild)
            if not channel:
                self.logger.warning(
                    "[%s] No sendable channel resolved; skipping.", guild.name
                )
                continue
            
            try:
                await channel.send(
                    message, 
                    allowed_mentions=AllowedMentions(
                        roles=True, users=False, everyone=False
                    ) if self.guild_prefs.pings_enabled(guild.id) else AllowedMentions.none()
                )
                
                # Mark cooldowns AFTER sending message
                for system_name, station_name, metal in cooldown_keys:
                    market_db.mark_sent(system_name, station_name, metal, "guild", str(guild.id))
                
                self.logger.info(
                    "[%s] Alert sent to #%s", guild.name, channel.name
                )
            except discord.Forbidden as exc:
                self.logger.error(
                    "[%s] Permission denied sending to #%s: %s",
                    guild.name,
                    channel.name,
                    exc,
                )
            except discord.HTTPException as exc:
                self.logger.error(
                    "[%s] HTTP error sending to #%s: %s",
                    guild.name,
                    channel.name,
                    exc,
                    exc_info=True,
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[%s] Unexpected error sending to #%s: %s",
                    guild.name,
                    channel.name,
                    exc,
                    exc_info=True,
                )
        
        # Process DM subscribers
        for user_id in self.subscribers.all():
            if self.settings.debug_mode_dms and self.settings.debug_user_id:
                if user_id != self.settings.debug_user_id:
                    self.logger.debug(
                        "[DM] Skipping user %s (DEBUG_MODE_DMS active)", user_id
                    )
                    continue
            
            prefs = self.guild_prefs.get_preferences("user", user_id)
            
            # Collect entries that pass filter + cooldown (same flow as guilds)
            market_lines = []
            powerplay_lines = []
            cooldown_keys = []
            
            for system_name, system_data in all_data.items():
                system_address = system_data.get("system_address", "")
                
                # Process stations
                if "stations" in system_data:
                    for station_name, station_data in system_data["stations"].items():
                        station_type = station_data.get("station_type", "Unknown")
                        url = station_data.get("url", "")
                        
                        if "metals" in station_data:
                            for metal, metal_data in station_data["metals"].items():
                                stock = metal_data.get("stock", 0)
                                
                                # Check preferences at data level
                                if not self._passes_station_type_filter(station_type, prefs):
                                    continue
                                if not self._passes_commodity_filter(metal, prefs):
                                    continue
                                
                                # Check cooldown BEFORE including
                                if not market_db.check_cooldown(
                                    system_name=system_name,
                                    station_name=station_name,
                                    metal=metal,
                                    recipient_type="user",
                                    recipient_id=str(user_id),
                                    cooldown_seconds=self.settings.cooldown_seconds
                                ):
                                    continue
                                
                                # Entry passes - add to message
                                market_lines.append({
                                    "system_name": system_name,
                                    "system_address": system_address,
                                    "station_name": station_name,
                                    "station_type": station_type,
                                    "url": url,
                                    "metal": metal,
                                    "stock": stock,
                                })
                                cooldown_keys.append((system_name, station_name, metal))
                
                # Process powerplay
                if "powerplay" in system_data and system_data["powerplay"]:
                    powerplay = system_data["powerplay"]
                    power = powerplay.get("power")
                    status = powerplay.get("status")
                    
                    if power and status and status in ("Fortified", "Stronghold"):
                        if self._passes_powerplay_filter(power, prefs):
                            if market_db.check_cooldown(
                                system_name=system_name,
                                station_name=system_name,
                                metal="powerplay",
                                recipient_type="user",
                                recipient_id=str(user_id),
                                cooldown_seconds=self.settings.cooldown_seconds
                            ):
                                powerplay_lines.append({
                                    "system_name": system_name,
                                    "power": power,
                                    "status": status,
                                })
                                cooldown_keys.append((system_name, system_name, "powerplay"))
            
            if not market_lines and not powerplay_lines:
                continue
            
            # Build message inline
            message = self._build_message(market_lines, powerplay_lines)
            
            # No ping for DMs
            
            try:
                user = await self.client.fetch_user(user_id)
                await user.send(message, allowed_mentions=AllowedMentions.none())
                
                # Mark cooldowns AFTER sending message
                for system_name, station_name, metal in cooldown_keys:
                    market_db.mark_sent(system_name, station_name, metal, "user", str(user_id))
                
                self.logger.debug("[DM] Sent to user %s", user_id)
            except discord.NotFound:
                self.logger.info(
                    "[DM] User %s not found (deleted account?), unsubscribing", user_id
                )
                self.subscribers.discard(user_id)
            except discord.Forbidden as exc:
                if "Cannot send messages to this user" in str(exc):
                    self.logger.info("[DM] Cannot message user %s, unsubscribing", user_id)
                    self.subscribers.discard(user_id)
                else:
                    self.logger.warning(
                        "[DM] Forbidden error for user %s: %s", user_id, exc
                    )
            except discord.HTTPException as exc:
                self.logger.error("[DM] HTTP error sending to user %s: %s", user_id, exc)
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[DM] Unexpected error sending to user %s: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
