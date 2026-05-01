"""/leaderboard cog: top wealth standings, sourced from Redis.

Two subcommands:
    /leaderboard top   — top 10 users by wealth
    /leaderboard rank  — your current rank + score

Both are read-only and pull from the Redis ZSET maintained by
`services.economy.change_cash`. No DB hits on the read path — that's the
whole reason the leaderboard lives in Redis.

User name resolution: ZSET stores discord_ids. We resolve names by asking
discord.py's cache (`bot.get_user`); if the bot hasn't seen a user
recently we fall back to the raw id. This is a deliberate trade-off — we
don't want to fan-out N HTTP requests just to render a leaderboard embed.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.services import leaderboard


class LeaderboardCog(commands.Cog):
    """Wealth leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    leaderboard_group = app_commands.Group(
        name="leaderboard",
        description="Wealth standings",
    )

    # ---------------------------------------------------------------- #
    # /leaderboard top
    # ---------------------------------------------------------------- #

    @leaderboard_group.command(name="top", description="Top 10 by total wealth.")
    async def top(self, interaction: discord.Interaction) -> None:
        rows = await leaderboard.top(10)

        embed = discord.Embed(
            title="Vixen — Top 10 by wealth",
            color=discord.Color.gold(),
        )
        if not rows:
            embed.description = "_No one's earned anything yet. Try `/work`._"
            await interaction.response.send_message(embed=embed)
            return

        lines: list[str] = []
        for i, (user_id, wealth) in enumerate(rows, start=1):
            # Try the bot's user cache first; fall back to mention syntax
            # which Discord renders client-side even for unseen users.
            user = self.bot.get_user(user_id)
            display = user.display_name if user else f"<@{user_id}>"
            lines.append(f"**{i}.** {display} — **{wealth:,}**")

        embed.description = "\n".join(lines)
        await interaction.response.send_message(embed=embed)

    # ---------------------------------------------------------------- #
    # /leaderboard rank
    # ---------------------------------------------------------------- #

    @leaderboard_group.command(name="rank", description="Your current rank and wealth.")
    async def rank(self, interaction: discord.Interaction) -> None:
        result = await leaderboard.get_rank(interaction.user.id)
        if result is None:
            await interaction.response.send_message(
                "You're not on the board yet — earn some cash with `/work` first.",
                ephemeral=True,
            )
            return

        rank_pos, wealth = result
        total = await leaderboard.total_users()
        await interaction.response.send_message(
            f"You're **#{rank_pos}** out of **{total}** with **{wealth:,}** wealth.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
