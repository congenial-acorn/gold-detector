from __future__ import annotations

from typing import Iterable, Literal, Sequence

import discord
from discord import app_commands

from ..services import GuildPreferencesService, PREFERENCE_OPTIONS


def _choices_for(category: str) -> Sequence[str]:
    return PREFERENCE_OPTIONS.get(category, ())


CATEGORIES: tuple[str, ...] = tuple(PREFERENCE_OPTIONS.keys())


class PreferencesGroup(app_commands.Group):
    def __init__(self, prefs: GuildPreferencesService):
        super().__init__(
            name="set_preferences",
            description="Set personal or server preferences for alerts.",
        )
        self._prefs = prefs

    @staticmethod
    def _parse_selections(category: str, raw: str) -> list[str]:
        allowed = _choices_for(category)
        if not allowed:
            raise ValueError(f"Unknown preference category: {category}")

        if not raw:
            raise ValueError("Pick at least one option from the list.")

        canon = {opt.lower(): opt for opt in allowed}
        selections: list[str] = []
        invalid: list[str] = []
        for part in raw.split(","):
            token = part.strip()
            if not token:
                continue
            key = token.lower()
            match = canon.get(key)
            if match:
                if match not in selections:
                    selections.append(match)
            else:
                invalid.append(token)

        if invalid:
            raise ValueError(f"Invalid selection(s): {', '.join(invalid)}")
        if not selections:
            raise ValueError("Pick at least one option from the list.")
        return selections

    async def _set_pref(
        self,
        interaction: discord.Interaction,
        category: str,
        raw_values: str,
        target: Literal["user", "server"],
    ) -> None:
        try:
            selections = self._parse_selections(category, raw_values)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        scope: Literal["guild", "user"] = "user"
        scope_id = interaction.user.id
        scope_label = "your user"

        if target == "server":
            if not interaction.guild:
                await interaction.response.send_message(
                    "Run this in a server to set server preferences.", ephemeral=True
                )
                return
            if not interaction.user.guild_permissions.manage_guild:
                await interaction.response.send_message(
                    "You need the Manage Guild permission to change server preferences.",
                    ephemeral=True,
                )
                return
            scope = "guild"
            scope_id = interaction.guild.id
            scope_label = f"server '{interaction.guild.name}'"

        saved = self._prefs.set_preferences(scope, scope_id, category, selections)
        saved_display = ", ".join(saved) if saved else "none"
        await interaction.response.send_message(
            f"Updated {scope_label} {category.replace('_', ' ')} preferences: {saved_display}.",
            ephemeral=True,
        )

    def _autocomplete(self, category: str, current: str):
        allowed = _choices_for(category)
        if not allowed:
            return []

        parts = [p.strip() for p in current.split(",")]
        prefix = parts[-1] if parts else ""
        already = {p.lower() for p in parts[:-1] if p}
        prefix_lower = prefix.lower()

        matches = []
        for opt in allowed:
            lower = opt.lower()
            if lower in already:
                continue
            if not prefix or lower.startswith(prefix_lower):
                matches.append(opt)

        return [
            app_commands.Choice(name=opt, value=opt) for opt in matches[:25]
        ]

    def _resolve_scope(
        self,
        interaction: discord.Interaction,
        target: Literal["user", "server"],
        for_view: bool = False,
    ):
        scope: Literal["guild", "user"] = "user"
        scope_id = interaction.user.id
        scope_label = "your user"

        if target == "server":
            if not interaction.guild:
                raise ValueError("Run this in a server for server preferences.")
            if not interaction.user.guild_permissions.manage_guild:
                action = "view" if for_view else "change"
                raise ValueError(
                    f"You need the Manage Guild permission to {action} server preferences."
                )
            scope = "guild"
            scope_id = interaction.guild.id
            scope_label = f"server '{interaction.guild.name}'"

        return scope, scope_id, scope_label

    @app_commands.command(
        name="station_type", description="Set preferred station types."
    )
    @app_commands.describe(
        values="Comma-separated list of station types",
        target="Apply to your user (default) or this server",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def station_type(
        self,
        interaction: discord.Interaction,
        values: str,
        target: Literal["user", "server"] = "user",
    ):
        await self._set_pref(interaction, "station_type", values, target)

    @station_type.autocomplete("values")
    async def station_type_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        return self._autocomplete("station_type", current)

    @app_commands.command(name="commodity", description="Set preferred commodities.")
    @app_commands.describe(
        values="Comma-separated list of commodities",
        target="Apply to your user (default) or this server",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def commodity(
        self,
        interaction: discord.Interaction,
        values: str,
        target: Literal["user", "server"] = "user",
    ):
        await self._set_pref(interaction, "commodity", values, target)

    @commodity.autocomplete("values")
    async def commodity_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        return self._autocomplete("commodity", current)

    @app_commands.command(name="powerplay", description="Set preferred Powerplay leaders.")
    @app_commands.describe(
        values="Comma-separated list of Powerplay leaders",
        target="Apply to your user (default) or this server",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def powerplay(
        self,
        interaction: discord.Interaction,
        values: str,
        target: Literal["user", "server"] = "user",
    ):
        await self._set_pref(interaction, "powerplay", values, target)

    @powerplay.autocomplete("values")
    async def powerplay_autocomplete(
        self, interaction: discord.Interaction, current: str
    ):
        return self._autocomplete("powerplay", current)

    @app_commands.command(name="show", description="Show current preferences.")
    @app_commands.describe(
        target="Show preferences for your user (default) or this server",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def show(
        self,
        interaction: discord.Interaction,
        target: Literal["user", "server"] = "user",
    ):
        try:
            scope, scope_id, scope_label = self._resolve_scope(
                interaction, target, for_view=True
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        prefs = self._prefs.get_preferences(scope, scope_id)
        if not prefs:
            await interaction.response.send_message(
                f"No preferences set for {scope_label}.", ephemeral=True
            )
            return

        lines = [
            f"{category.replace('_', ' ').title()}: {', '.join(values)}"
            for category, values in prefs.items()
            if values
        ]
        await interaction.response.send_message(
            f"{scope_label.title()} preferences:\n" + "\n".join(lines),
            ephemeral=True,
        )

    @app_commands.command(
        name="remove", description="Remove specific options from preferences."
    )
    @app_commands.describe(
        category="Which preference category to modify",
        values="Comma-separated options to remove",
        target="Apply to your user (default) or this server",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="Station type", value="station_type"),
            app_commands.Choice(name="Commodity", value="commodity"),
            app_commands.Choice(name="Powerplay", value="powerplay"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def remove(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        values: str,
        target: Literal["user", "server"] = "user",
    ):
        try:
            scope, scope_id, scope_label = self._resolve_scope(
                interaction, target, for_view=False
            )
            selections = self._parse_selections(category.value, values)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        remaining = self._prefs.remove_preferences(
            scope, scope_id, category.value, selections
        )
        removed_display = ", ".join(selections)
        remaining_display = ", ".join(remaining) if remaining else "none"
        await interaction.response.send_message(
            (
                f"Removed {removed_display} from {scope_label} "
                f"{category.value.replace('_', ' ')} preferences. "
                f"Remaining: {remaining_display}."
            ),
            ephemeral=True,
        )

    @app_commands.command(name="clear", description="Clear preferences.")
    @app_commands.describe(
        target="Clear preferences for your user (default) or this server",
        category="Which preference category to clear",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name="All", value="__all__"),
            app_commands.Choice(name="Station type", value="station_type"),
            app_commands.Choice(name="Commodity", value="commodity"),
            app_commands.Choice(name="Powerplay", value="powerplay"),
        ]
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def clear(
        self,
        interaction: discord.Interaction,
        category: app_commands.Choice[str],
        target: Literal["user", "server"] = "user",
    ):
        try:
            scope, scope_id, scope_label = self._resolve_scope(
                interaction, target, for_view=False
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        cat_value = category.value
        targets: Iterable[str]
        if cat_value == "__all__":
            targets = CATEGORIES
        else:
            targets = (cat_value,)

        for cat in targets:
            self._prefs.set_preferences(scope, scope_id, cat, [])

        label = "all preferences" if cat_value == "__all__" else cat_value.replace(
            "_", " "
        )
        await interaction.response.send_message(
            f"Cleared {label} for {scope_label}.", ephemeral=True
        )


def register_preference_commands(
    tree: app_commands.CommandTree, prefs: GuildPreferencesService
) -> None:
    tree.add_command(PreferencesGroup(prefs))
