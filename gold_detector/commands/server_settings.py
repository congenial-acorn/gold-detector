from __future__ import annotations

import discord
from discord import app_commands

from ..services import GuildPreferencesService, OptOutService


def register_server_settings_commands(
    tree: app_commands.CommandTree,
    guild_prefs: GuildPreferencesService,
    opt_outs: OptOutService,
) -> None:
    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="server_alerts_off",
        description="Opt this server OUT of alerts (default is ON)",
    )
    async def server_alerts_off(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        opt_outs.add(interaction.guild.id)
        await interaction.response.send_message(
            "This server is now opted OUT of alerts.", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="server_alerts_on", description="Opt this server back IN to alerts"
    )
    async def server_alerts_on(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        opt_outs.discard(interaction.guild.id)
        await interaction.response.send_message(
            "This server is now opted IN to alerts (default).", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="set_alert_channel",
        description="Set which channel the bot should post alerts to",
    )
    @app_commands.describe(channel="Pick a text channel the bot can post in")
    async def set_alert_channel(
        interaction: discord.Interaction, channel: discord.TextChannel
    ):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.set_channel(interaction.guild.id, channel.id, channel.name)
        await interaction.response.send_message(
            f"Alerts will go to **#{channel.name}**.", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="clear_alert_channel",
        description="Revert the alert channel to the default (#market-watch)",
    )
    async def clear_alert_channel(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.clear_channel(interaction.guild.id)
        await interaction.response.send_message(
            "Alert channel cleared. Using default: #market-watch.", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="set_alert_role",
        description="Set which role gets pinged when a scan cycle finishes",
    )
    @app_commands.describe(role="Pick the role to mention")
    async def set_alert_role(interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.set_role(interaction.guild.id, role.id, role.name)
        await interaction.response.send_message(
            f"Will ping **@{role.name}** at the end of each scan.", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="clear_alert_role",
        description="Revert the ping role to the default (@Market Alert)",
    )
    async def clear_alert_role(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.clear_role(interaction.guild.id)
        await interaction.response.send_message(
            "Ping role cleared. Using default: @Market Alert.", ephemeral=True
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="server_ping_off",
        description="Disable @role pings while keeping alerts enabled",
    )
    async def server_ping_off(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.set_pings_enabled(interaction.guild.id, False)
        await interaction.response.send_message(
            "Pings disabled. Alerts will continue without @role mentions.",
            ephemeral=True,
        )

    @app_commands.guild_only()
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.allowed_installs(guilds=True, users=False)
    @tree.command(
        name="server_ping_on",
        description="Re-enable @role pings in addition to alerts",
    )
    async def server_ping_on(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        guild_prefs.set_pings_enabled(interaction.guild.id, True)
        await interaction.response.send_message(
            "Pings enabled. Alerts will include @role mentions again.",
            ephemeral=True,
        )

    @tree.command(
        name="show_alert_settings",
        description="Show this server's current alert channel/role (with defaults)",
    )
    @app_commands.allowed_installs(guilds=True, users=False)
    async def show_alert_settings(interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message(
                "Run this in a server.", ephemeral=True
            )
        gid = interaction.guild.id
        ch_name = guild_prefs.effective_channel_name(gid)
        role_name = guild_prefs.effective_role_name(gid)
        cid = guild_prefs.effective_channel_id(gid)
        rid = guild_prefs.effective_role_id(gid)
        channel_src, role_src = guild_prefs.source_labels(gid)
        ping_status = "enabled" if guild_prefs.pings_enabled(gid) else "disabled"
        where = f"<#{cid}>" if cid else f"#{ch_name}"
        who = f"<@&{rid}>" if rid else f"@{role_name}"
        await interaction.response.send_message(
            (
                "Alert channel: "
                f"{where} ({channel_src})\nPing role: {who} ({role_src})"
                f"\nPings: {ping_status}"
            ),
            ephemeral=True,
        )
