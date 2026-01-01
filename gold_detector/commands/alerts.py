from __future__ import annotations

import discord
from discord import app_commands

from ..services import SubscriberService


def register_alert_commands(
    tree: app_commands.CommandTree, subscribers: SubscriberService, help_url: str
) -> None:

    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @tree.command(name="alerts_on", description="DM me future alerts")
    @app_commands.checks.cooldown(1, 5)
    async def alerts_on(interaction: discord.Interaction):
        try:
            user_id = interaction.user.id
            subscribers.add(user_id)
            dm_sent = True
            try:
                await interaction.user.send("Subscribed. I will DM you future alerts.")
            except Exception:
                dm_sent = False
            await interaction.response.send_message(
                (
                    "You are subscribed to DMs."
                    if dm_sent
                    else "You are subscribed, but I could not DM you. Check your Message Requests."
                ),
                ephemeral=True,
            )
        except Exception as exc:  # noqa: BLE001
            await interaction.response.send_message(
                f"Could not subscribe: {exc}", ephemeral=True
            )

    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @tree.command(name="alerts_off", description="Stop DMs")
    @app_commands.checks.cooldown(1, 5)
    async def alerts_off(interaction: discord.Interaction):
        try:
            subscribers.discard(interaction.user.id)
            await interaction.response.send_message(
                "You are unsubscribed. No more DMs.", ephemeral=True
            )
        except Exception as exc:  # noqa: BLE001
            await interaction.response.send_message(
                f"Could not unsubscribe: {exc}", ephemeral=True
            )

    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @tree.command(name="help", description="Show help and commands for this bot")
    async def help_cmd(interaction: discord.Interaction):
        await interaction.response.send_message(
            (
                "ATTENTION: Bot permissions were incorrectly set. The permissions are now correct as of 1/1/2026.\n"
                'If you invited the bot to a server before that date, please grant it the "View Channels" permission.\n\n'
                f"Gold Detector commands and docs: <{help_url}>"
            ),
            ephemeral=True,
        )
