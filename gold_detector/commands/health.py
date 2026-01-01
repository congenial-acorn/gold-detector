from __future__ import annotations

from typing import List

import discord
from discord import app_commands


def register_health_commands(tree: app_commands.CommandTree) -> None:
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @tree.command(name="ping", description="Check if the bot is alive")
    async def ping_cmd(interaction: discord.Interaction):
        await interaction.response.send_message("Pong!", ephemeral=True)

    @app_commands.guild_only()
    @app_commands.allowed_installs(guilds=True, users=False)
    @app_commands.allowed_contexts(guilds=True, dms=False, private_channels=True)
    @tree.command(
        name="diagnose",
        description="Check if the bot has the right permissions in this channel",
    )
    async def diagnose_cmd(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server channel.", ephemeral=True
            )

        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            return await interaction.response.send_message(
                "Use this in a text channel or thread.", ephemeral=True
            )

        me = interaction.guild.me
        if not me:
            return await interaction.response.send_message(
                "Bot member not found in this guild.", ephemeral=True
            )

        perms = channel.permissions_for(me)
        required = {
            "view_channel": "View Channel",
            "send_messages": "Send Messages",
            "embed_links": "Embed Links",
        }

        missing: List[str] = [
            label for attr, label in required.items() if not getattr(perms, attr, False)
        ]

        if missing:
            status = f"❌ Missing: {', '.join(missing)}"
        else:
            status = "✅ OK"

        await interaction.response.send_message(status, ephemeral=True)
