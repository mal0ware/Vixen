"""/lottery cog: enter, view pool, draw a winner.

Three subcommands:
    /lottery enter <count>   spend lottery_ticket inventory to stake entries
    /lottery pool            show pot size + current entries
    /lottery draw            (admin only) pick a winner; pay out; reset

The pot is funded entirely by ticket purchases — when a player runs /buy
lottery_ticket, the cash already left their wallet to the void. /lottery
enter then converts those tickets into pot entries; /lottery draw pays
out one lucky winner the cumulative pot. Net result: ticket buyers
collectively fund a winner-take-all jackpot.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.economy import InvalidAmount
from vixen.services.lottery import NoEntries, draw, enter, pool
from vixen.services.shop import InsufficientItems


class LotteryCog(commands.Cog):
    """Weekly-style lottery. Stake tickets, win the pot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    lottery_group = app_commands.Group(
        name="lottery",
        description="Stake lottery_tickets, win the pot.",
    )

    # ---------------------------------------------------------------- #
    # /lottery enter
    # ---------------------------------------------------------------- #

    @lottery_group.command(
        name="enter",
        description="Stake lottery_tickets into the current draw.",
    )
    @app_commands.describe(count="How many tickets to stake (default 1).")
    async def enter_cmd(
        self,
        interaction: discord.Interaction,
        count: int = 1,
    ) -> None:
        if count <= 0:
            await interaction.response.send_message(
                "Count must be positive.", ephemeral=True
            )
            return

        remaining = await try_acquire(interaction.user.id, "lottery_enter")
        if remaining > 0:
            await interaction.response.send_message(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                new_total = await enter(session, interaction.user.id, count)
        except InvalidAmount:
            await interaction.response.send_message(
                "Count must be positive.", ephemeral=True
            )
            return
        except InsufficientItems as e:
            await interaction.response.send_message(
                f"You only have **{e.have}** lottery_tickets — can't stake **{e.need}**.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"Staked **{count}** ticket(s). You now have **{new_total}** entries in the current draw."
        )

    # ---------------------------------------------------------------- #
    # /lottery pool
    # ---------------------------------------------------------------- #

    @lottery_group.command(
        name="pool",
        description="Show the current pot and total entries.",
    )
    async def pool_cmd(self, interaction: discord.Interaction) -> None:
        async with get_session() as session:
            entries, pot = await pool(session)

        if entries == 0:
            await interaction.response.send_message(
                "The pot is empty. Buy a `lottery_ticket` and `/lottery enter` to start it."
            )
            return

        await interaction.response.send_message(
            f"🎟️ **Pot:** {pot:,} cash  ·  **Entries:** {entries}"
        )

    # ---------------------------------------------------------------- #
    # /lottery draw  (admin)
    # ---------------------------------------------------------------- #

    @lottery_group.command(
        name="draw",
        description="(Admin) Draw a winner and pay out the pot.",
    )
    @app_commands.default_permissions(administrator=True)
    async def draw_cmd(self, interaction: discord.Interaction) -> None:
        # Defensive permission check. `default_permissions` above hides the
        # command from non-admins in Discord's UI, but a server admin
        # could still grant it via channel overrides. Re-check here.
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
                winner_id, pot_won, entries = await draw(session)
        except NoEntries:
            await interaction.response.send_message(
                "Nobody's entered the lottery yet — nothing to draw."
            )
            return

        # Resolve winner display via discord.py's user cache.
        winner = self.bot.get_user(winner_id)
        winner_display = winner.mention if winner else f"<@{winner_id}>"

        await interaction.response.send_message(
            f"🎉 The winner is {winner_display}!\n"
            f"They take home **{pot_won:,}** cash from **{entries}** entries."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LotteryCog(bot))
