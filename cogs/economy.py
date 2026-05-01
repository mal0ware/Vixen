"""Economy cog: profile, work, coinflip.

Replaces the old rpg_cog.py. Persistent state lives in Postgres now;
business logic is in vixen.services.economy. The cog is intentionally
thin — its only jobs are arg parsing, calling the service, and rendering
the reply.
"""

import random

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import func, select

from vixen.db import get_session
from vixen.models import InventoryItem
from vixen.services.cooldown import try_acquire
from vixen.services.economy import (
    InsufficientFunds,
    change_cash,
    get_or_create_user,
)


class EconomyCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /profile
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="View your or another user's profile.")
    @app_commands.describe(user="User to look up. Defaults to you.")
    async def profile(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author

        async with get_session() as session:
            row = await get_or_create_user(session, target.id)
            # Count inventory rows for the target. `func.count()` is a SQL
            # aggregate; `scalar_one()` returns the single-cell result.
            item_count = await session.scalar(
                select(func.count(InventoryItem.id)).where(
                    InventoryItem.user_discord_id == target.id
                )
            )

        embed = discord.Embed(
            title=f"{target.display_name}'s profile",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Cash", value=f"{row.cash:,}", inline=True)
        embed.add_field(name="Bank", value=f"{row.bank:,}", inline=True)
        embed.add_field(name="Items", value=str(item_count or 0), inline=True)
        # Discord's <t:UNIX:R> renders as "3 days ago" client-side and respects
        # the viewer's locale — better than us hardcoding a format.
        embed.add_field(
            name="Account age",
            value=f"<t:{int(row.created_at.timestamp())}:R>",
            inline=False,
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        await ctx.reply(embed=embed)

    # ---------------------------------------------------------------- #
    # /work
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Earn 25–125 cash.")
    async def work(self, ctx: commands.Context) -> None:
        remaining = await try_acquire(ctx.author.id, "work")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        profit = random.randint(25, 125)
        async with get_session() as session:
            new_balance = await change_cash(
                session, ctx.author.id, profit, reason="work"
            )
        await ctx.reply(
            f"You earned **{profit:,}** cash. Balance: **{new_balance:,}**."
        )

    # ---------------------------------------------------------------- #
    # /coinflip
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        help="Flip a coin against a wager. Heads doubles your bet, tails loses it."
    )
    @app_commands.describe(wager="Amount to bet (must be positive).")
    async def coinflip(self, ctx: commands.Context, wager: int) -> None:
        if wager <= 0:
            await ctx.reply("Wager must be a positive integer.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "coinflip")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        won = random.randint(0, 1) == 1
        delta = wager if won else -wager
        reason = "coinflip_win" if won else "coinflip_loss"

        try:
            async with get_session() as session:
                new_balance = await change_cash(
                    session, ctx.author.id, delta, reason=reason
                )
        except InsufficientFunds as e:
            await ctx.reply(
                f"You only have **{e.have:,}** cash — can't wager **{wager:,}**.",
                ephemeral=True,
            )
            return

        if won:
            await ctx.reply(
                f"**HEADS!** You won **{wager:,}** cash. Balance: **{new_balance:,}**."
            )
        else:
            await ctx.reply(
                f"**TAILS.** You lost **{wager:,}** cash. Balance: **{new_balance:,}**."
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EconomyCog(bot))
