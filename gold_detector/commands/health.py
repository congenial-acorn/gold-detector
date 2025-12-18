from __future__ import annotations

import discord
from discord import app_commands


def register_health_commands(tree: app_commands.CommandTree) -> None:
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @tree.command(name="ping", description="Check if the bot is alive")
    async def ping_cmd(interaction: discord.Interaction):
        await interaction.response.send_message("Pong!", ephemeral=True)

