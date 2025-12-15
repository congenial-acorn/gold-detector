from __future__ import annotations

import discord
from discord import app_commands
from discord.app_commands import CommandOnCooldown


def attach_error_handler(tree: app_commands.CommandTree, logger) -> None:
    @tree.error
    async def on_app_command_error(interaction: discord.Interaction, error: Exception):
        if isinstance(error, CommandOnCooldown):
            retry = int(error.retry_after)
            msg = f"Slow down; try again in ~{retry}s."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except discord.HTTPException as exc:
                logger.error("[slash] Failed to send cooldown message: %s", exc)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[slash] Unexpected error in cooldown handler: %s",
                    exc,
                    exc_info=True,
                )
            return

        logger.error(
            "[slash] Command error: %s: %s", type(error).__name__, error, exc_info=True
        )

        try:
            error_msg = "An error occurred while processing your command."
            if interaction.response.is_done():
                await interaction.followup.send(error_msg, ephemeral=True)
            else:
                await interaction.response.send_message(error_msg, ephemeral=True)
        except Exception:
            pass
