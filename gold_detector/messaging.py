from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import TYPE_CHECKING, Any, Optional

import discord
from discord import AllowedMentions

from .config import Settings
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

    def loop_done_from_thread(self) -> None:
        """Dispatch messages from database (called from gold.py thread)."""
        if not self.market_db:
            self.logger.warning("[loop_done_from_thread] No market_db configured")
            return

        loop = getattr(self.client, "loop", None)
        if not loop:
            self.logger.error("[loop_done_from_thread] Client event loop not available")
            return

        self.logger.info("[loop_done_from_thread] Scheduling dispatch to event loop")
        try:
            fut = asyncio.run_coroutine_threadsafe(
                self.dispatch_from_database(self.market_db), loop
            )
            fut.result(timeout=60)
        except concurrent.futures.TimeoutError:
            self.logger.error("[loop_done_from_thread] Dispatch timed out after 60s")
        except Exception as exc:
            self.logger.error(
                "[loop_done_from_thread] Dispatch failed: %s", exc, exc_info=True
            )

    async def start_background_tasks(self) -> None:
        """Initialize messenger (no background tasks needed after refactor)."""
        pass

    def _passes_station_type_filter(
        self, station_type: str, prefs: dict[str, Any]
    ) -> bool:
        """Check if station type passes preference filter."""
        station_type_prefs = prefs.get("station_type", [])
        if not station_type_prefs:
            return True

        station_type_lower = station_type.lower()
        for pref in station_type_prefs:
            pref_lower = pref.lower()
            if (
                station_type_lower == pref_lower
                or station_type_lower.startswith(f"{pref_lower} ")
                or station_type_lower.startswith(f"{pref_lower}(")
                or f" {pref_lower} " in f" {station_type_lower} "
            ):
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
        return any(
            power_lower in p.lower() or p.lower() in power_lower
            for p in powerplay_prefs
        )

    def _build_message(
        self,
        market_lines: list[dict[str, Any]],
        powerplay_lines: list[dict[str, Any]],
        all_data: dict[str, Any],
    ) -> str:
        """Build message from market and powerplay lines."""
        if market_lines:
            # Group by system
            systems = {}
            for line in market_lines:
                system_name = line["system_name"]
                if system_name not in systems:
                    systems[system_name] = {
                        "system_address": line["system_address"],
                        "stations": {},
                    }

                station_name = line["station_name"]
                if station_name not in systems[system_name]["stations"]:
                    systems[system_name]["stations"][station_name] = {
                        "station_type": line["station_type"],
                        "url": line["url"],
                        "metals": [],
                    }

                systems[system_name]["stations"][station_name]["metals"].append(
                    (line["metal"], line["stock"])
                )

            # Build message
            messages = []
            for system_name, system_data in systems.items():
                system_address = system_data["system_address"]
                addr_label = (
                    f"<{system_address}>" if system_address else "Unknown address"
                )
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
                        system_name_pp = pp_line["system_name"]
                        power = pp_line["power"]
                        status = pp_line["status"]

                        pp_entry = all_data.get(system_name_pp, {}).get("powerplay", {})
                        commodity_urls = pp_entry.get("commodity_urls", "")

                        powerplay_info = (
                            f"{system_name_pp} is a {power} {status} system."
                        )

                        if commodity_urls:
                            if status == "Fortified":
                                powerplay_info += f"\nYou can earn merits by trading for a large profit in these acquisition systems: {commodity_urls}"
                            elif status == "Stronghold":
                                powerplay_info += f"\nYou can earn merits by trading for a large profit in these acquisition systems: {commodity_urls}"

                        lines.append(powerplay_info)

                messages.append("\n".join(lines))

            return "\n\n".join(messages)
        elif powerplay_lines:
            # Only powerplay
            messages = []
            for line in powerplay_lines:
                system_name = line["system_name"]
                power = line["power"]
                status = line["status"]

                pp_entry = all_data.get(system_name, {}).get("powerplay", {})
                commodity_urls = pp_entry.get("commodity_urls", "")

                powerplay_info = f"{system_name} is a {power} {status} system."

                if commodity_urls:
                    if status == "Fortified":
                        powerplay_info += f"\nYou can earn merits by selling for large profit in these acquisition systems: {commodity_urls}"
                    elif status == "Stronghold":
                        powerplay_info += f"\nYou can earn merits by selling for large profit: {commodity_urls}"

                messages.append(powerplay_info)

            return "\n".join(messages)
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

        self.logger.info(
            "[dispatch_from_database] Starting - %d systems in database, %d guilds, %d subscribers",
            len(all_data),
            len(self.client.guilds),
            len(self.subscribers.all()),
        )

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
            powerplay_systems_to_mark = []
            candidate_count = 0

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

                                candidate_count += 1

                                # Check preferences at data level
                                if not self._passes_station_type_filter(
                                    station_type, prefs
                                ):
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
                                    cooldown_seconds=self.settings.cooldown_seconds,
                                ):
                                    continue

                                # Entry passes - add to message
                                market_lines.append(
                                    {
                                        "system_name": system_name,
                                        "system_address": system_address,
                                        "station_name": station_name,
                                        "station_type": station_type,
                                        "url": url,
                                        "metal": metal,
                                        "stock": stock,
                                    }
                                )
                                cooldown_keys.append((system_name, station_name, metal))

                # Process powerplay
                if "powerplay" in system_data and system_data["powerplay"]:
                    powerplay = system_data["powerplay"]
                    power = powerplay.get("power")
                    status = powerplay.get("status")

                    if power and status and status in ("Fortified", "Stronghold"):
                        candidate_count += 1

                        if self._passes_powerplay_filter(power, prefs):
                            if market_db.check_powerplay_cooldown(
                                system_name=system_name,
                                recipient_type="guild",
                                recipient_id=str(guild.id),
                                cooldown_seconds=self.settings.cooldown_seconds,
                            ):
                                powerplay_lines.append(
                                    {
                                        "system_name": system_name,
                                        "power": power,
                                        "status": status,
                                    }
                                )
                                powerplay_systems_to_mark.append(system_name)

            self.logger.debug(
                "[dispatch_from_database] Guild %s: %d candidate entries, %d passed filters",
                guild.name,
                candidate_count,
                len(market_lines) + len(powerplay_lines),
            )

            if not market_lines and not powerplay_lines:
                self.logger.debug(
                    "[dispatch_from_database] Guild %s: no entries to send (0 passed filters)",
                    guild.name,
                )
                continue

            # Build message inline
            message = self._build_message(market_lines, powerplay_lines, all_data)

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
                    )
                    if self.guild_prefs.pings_enabled(guild.id)
                    else AllowedMentions.none(),
                )

                # Mark cooldowns AFTER sending message
                if cooldown_keys:
                    market_db.mark_sent_batch(
                        [
                            (system_name, station_name, metal, "guild", str(guild.id))
                            for system_name, station_name, metal in cooldown_keys
                        ]
                    )

                if powerplay_systems_to_mark:
                    market_db.mark_powerplay_sent_batch(
                        [
                            (system_name, "guild", str(guild.id))
                            for system_name in powerplay_systems_to_mark
                        ]
                    )

                self.logger.info("[%s] Alert sent to #%s", guild.name, channel.name)
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
            powerplay_systems_to_mark = []

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
                                if not self._passes_station_type_filter(
                                    station_type, prefs
                                ):
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
                                    cooldown_seconds=self.settings.cooldown_seconds,
                                ):
                                    continue

                                # Entry passes - add to message
                                market_lines.append(
                                    {
                                        "system_name": system_name,
                                        "system_address": system_address,
                                        "station_name": station_name,
                                        "station_type": station_type,
                                        "url": url,
                                        "metal": metal,
                                        "stock": stock,
                                    }
                                )
                                cooldown_keys.append((system_name, station_name, metal))

                # Process powerplay
                if "powerplay" in system_data and system_data["powerplay"]:
                    powerplay = system_data["powerplay"]
                    power = powerplay.get("power")
                    status = powerplay.get("status")

                    if power and status and status in ("Fortified", "Stronghold"):
                        if self._passes_powerplay_filter(power, prefs):
                            if market_db.check_powerplay_cooldown(
                                system_name=system_name,
                                recipient_type="user",
                                recipient_id=str(user_id),
                                cooldown_seconds=self.settings.cooldown_seconds,
                            ):
                                powerplay_lines.append(
                                    {
                                        "system_name": system_name,
                                        "power": power,
                                        "status": status,
                                    }
                                )
                                powerplay_systems_to_mark.append(system_name)

            if not market_lines and not powerplay_lines:
                continue

            # Build message inline
            message = self._build_message(market_lines, powerplay_lines, all_data)

            # No ping for DMs

            try:
                user = await self.client.fetch_user(user_id)
                await user.send(message, allowed_mentions=AllowedMentions.none())

                # Mark cooldowns AFTER sending message
                if cooldown_keys:
                    market_db.mark_sent_batch(
                        [
                            (system_name, station_name, metal, "user", str(user_id))
                            for system_name, station_name, metal in cooldown_keys
                        ]
                    )

                if powerplay_systems_to_mark:
                    market_db.mark_powerplay_sent_batch(
                        [
                            (system_name, "user", str(user_id))
                            for system_name in powerplay_systems_to_mark
                        ]
                    )

                self.logger.debug("[DM] Sent to user %s", user_id)
            except discord.NotFound:
                self.logger.info(
                    "[DM] User %s not found (deleted account?), unsubscribing", user_id
                )
                self.subscribers.discard(user_id)
            except discord.Forbidden as exc:
                if "Cannot send messages to this user" in str(exc):
                    self.logger.info(
                        "[DM] Cannot message user %s, unsubscribing", user_id
                    )
                    self.subscribers.discard(user_id)
                else:
                    self.logger.warning(
                        "[DM] Forbidden error for user %s: %s", user_id, exc
                    )
            except discord.HTTPException as exc:
                self.logger.error(
                    "[DM] HTTP error sending to user %s: %s", user_id, exc
                )
            except Exception as exc:  # noqa: BLE001
                self.logger.error(
                    "[DM] Unexpected error sending to user %s: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
