"""/rob cog: attempt to steal cash from another user.

Outcomes (all decided server-side in `services.robbery.do_rob`):
- target had a padlock → blocked, padlock consumed
- 50/50 success roll on remaining attempts:
    - succeeded → steal 10–25% of target's cash
    - failed    → lose 10% of your own as penalty

Validation lives here, not in the service:
- can't rob yourself
- can't rob a bot
- target must have positive cash
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.robbery import TargetBroke, do_rob


class RobberyCog(commands.Cog):
    """Risk-vs-reward PvP rob command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        help="Try to rob another user. 50% success, padlocks block."
    )
    @app_commands.describe(target="Who to rob.")
    async def rob(
        self,
        ctx: commands.Context,
        target: discord.Member,
    ) -> None:
        # Validation: refuse self-rob and bot-rob.
        if target.id == ctx.author.id:
            await ctx.reply("You can't rob yourself.", ephemeral=True)
            return
        if target.bot:
            await ctx.reply("You can't rob bots.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "rob")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                result = await do_rob(session, ctx.author.id, target.id)
        except TargetBroke:
            await ctx.reply(
                f"{target.display_name} has nothing worth stealing.",
                ephemeral=True,
            )
            return

        # Branch the reply on outcome. Each message uses public, non-
        # ephemeral replies so other users can see the action — robberies
        # are part of the social game.
        if result.outcome == "blocked":
            await ctx.reply(
                f"🔒 {target.mention}'s padlock held — your attempt failed and "
                f"their padlock is now broken."
            )
        elif result.outcome == "succeeded":
            await ctx.reply(
                f"💰 You robbed **{result.cash_moved:,}** cash from {target.mention}!\n"
                f"Your balance: **{result.thief_balance:,}**."
            )
        else:  # failed
            if result.cash_moved > 0:
                await ctx.reply(
                    f"🚓 Caught! You paid **{result.cash_moved:,}** in penalties "
                    f"trying to rob {target.mention}.\n"
                    f"Your balance: **{result.thief_balance:,}**."
                )
            else:
                await ctx.reply(
                    "🚓 Caught! Lucky for you, you had no cash to lose."
                )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RobberyCog(bot))
