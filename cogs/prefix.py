"""/setprefix admin command.

Sets the prefix for the current guild. Updates the Postgres row AND the
Redis cache so the new prefix takes effect on the very next message.

Permission model: requires Administrator. Discord's UI hides the slash
command from non-admins via `default_permissions`, but a server admin can
override that with channel permissions, so the handler re-checks.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.prefix import set_prefix


class PrefixCog(commands.Cog):
    """Per-guild command-prefix management."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="setprefix",
        description="(Admin) Set this server's command prefix.",
    )
    @app_commands.describe(new_prefix="New prefix (1-10 characters).")
    @app_commands.default_permissions(administrator=True)
    @app_commands.guild_only()
    async def setprefix(
        self,
        interaction: discord.Interaction,
        new_prefix: str,
    ) -> None:
        # Defensive permission check (see module docstring).
        if (
            interaction.guild is None
            or not interaction.user.guild_permissions.administrator  # type: ignore[union-attr]
        ):
            await interaction.response.send_message(
                "Admin only.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                await set_prefix(session, interaction.guild.id, new_prefix)
        except ValueError as e:
            await interaction.response.send_message(
                f"Invalid prefix: {e}", ephemeral=True
            )
            return

        await interaction.response.send_message(
            f"Prefix set to `{new_prefix}`. Try `{new_prefix}help`."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PrefixCog(bot))
