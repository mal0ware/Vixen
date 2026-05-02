"""/avatar — show a user's avatar in full size.

The pre-migration version was non-functional (the inner function wasn't
decorated as a command and used `(user.mention)` as a literal string).
This rewrite makes it actually work and renders the result as an embed
so the avatar links in Discord clients show a clean preview.
"""

import discord
from discord import app_commands
from discord.ext import commands


class AvatarCog(commands.Cog):
    """Show user avatars at full resolution."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(help="Show a user's avatar at full size.")
    @app_commands.describe(
        user="Whose avatar to show. Defaults to you."
    )
    async def avatar(
        self,
        ctx: commands.Context,
        user: discord.User | discord.Member | None = None,
    ) -> None:
        target = user or ctx.author

        # display_avatar resolves to the guild-specific avatar when the
        # target is a Member with one set, falling back to the global
        # avatar otherwise. .url gives the largest size Discord will hand
        # out — exactly what /avatar should show.
        url = target.display_avatar.url

        embed = discord.Embed(
            title=f"{target.display_name}'s avatar",
            url=url,
            color=discord.Color.blurple(),
        )
        embed.set_image(url=url)
        # Footer holds the snowflake — useful when someone wants to copy
        # the user ID out of an avatar lookup.
        embed.set_footer(text=f"User ID: {target.id}")

        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AvatarCog(bot))
