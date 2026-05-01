"""/fish cog.

Requires a fishing_rod from the shop. The rod is durable — buy once, fish
forever. Each cast pays out a random catch from the weighted table in
`services.fishing.CATCH_TABLE` and audit-logs to `transactions`.
"""

from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.fishing import NoRod, do_fish


class FishingCog(commands.Cog):
    """Cast a line. Requires fishing_rod (1500 cash from /shop)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        help="Cast a line. Requires a fishing_rod from /shop. Catches pay random cash."
    )
    async def fish(self, ctx: commands.Context) -> None:
        remaining = await try_acquire(ctx.author.id, "fish")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                catch, new_balance = await do_fish(session, ctx.author.id)
        except NoRod:
            await ctx.reply(
                "You don't have a `fishing_rod`. Buy one with `/buy fishing_rod`.",
                ephemeral=True,
            )
            return

        await ctx.reply(
            f"You cast your line… and reeled in **{catch.emoji} {catch.name}**!\n"
            f"Sold for **{catch.payout:,}** cash. Balance: **{new_balance:,}**."
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FishingCog(bot))
