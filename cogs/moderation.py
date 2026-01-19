# cogs/moderation.py
import discord
from discord.ext import commands
from discord import app_commands

class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(help="Ban a user by mention, ID, or selection. Optionally add a reason.")
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(user="User to ban", reason="Reason")
    async def ban(self, ctx: commands.Context, user: discord.User, *, reason: str | None = None):
        try:
            reason = f"Banned by {ctx.author}: {reason}"
            await ctx.guild.ban(user, reason=reason)
            await ctx.send(f"Banned **{user.name}**. Reason: {reason}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @commands.hybrid_command(help="Unban a user by ID. Optionally add a reason.")
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(user_id="User ID", reason="Reason")
    async def unban(self, ctx: commands.Context, user_id: str, *, reason: str | None = None):
        try:
            user = await ctx.bot.fetch_user(int(user_id.strip('<@!>')))
            reason = f"Unbanned by {ctx.author}: {reason}"
            await ctx.guild.unban(user, reason=reason)
            await ctx.send(f"Unbanned **{user.name}**. Reason: {reason}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

    @commands.hybrid_command(help="Kick a user by mention, ID, or selection. Optionally add a reason.")
    @commands.has_permissions(kick_members=True)
    @app_commands.describe(user="User to kick", reason="Reason")
    async def kick(self, ctx: commands.Context, user: discord.User, *, reason: str | None = None):
        try:
            reason = f"Kicked by {ctx.author}: {reason}"
            await ctx.guild.kick(user, reason=reason)
            await ctx.send(f"Kicked **{user.name}**. Reason: {reason}")
        except Exception as e:
            await ctx.send(f"Error: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
