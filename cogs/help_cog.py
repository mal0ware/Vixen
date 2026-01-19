# cogs/help.py
import discord
from discord.ext import commands
from discord import app_commands

class helpCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="help", help="Show help or details for a command.")
    @app_commands.describe(name="Optional command name, e.g., rps or doge")
    async def help(self, ctx: commands.Context, name: str | None = None):
        bot = self.bot

        # detail for one command
        if name:
            cmd = bot.get_command(name)
            if cmd:
                e = discord.Embed(title=f"Help • {cmd.name}", color=discord.Color.green())
                e.add_field(name="Description", value=cmd.help or "No description.", inline=False)
                e.add_field(name="Usage", value=cmd.signature or cmd.qualified_name, inline=False)
                await ctx.send(embed=e, ephemeral=True if hasattr(ctx, "interaction") else False)
                return
            # slash-only lookup
            ac = next((c for c in bot.tree.get_commands() if c.name == name), None)
            if ac:
                e = discord.Embed(title=f"Help • /{ac.name}", description=ac.description or "No description.", color=discord.Color.green())
                await ctx.send(embed=e, ephemeral=True if hasattr(ctx, "interaction") else False)
                return
            await ctx.send(f"No command named `{name}`.", ephemeral=True if hasattr(ctx, "interaction") else False)
            return

        # overview
        e = discord.Embed(title="Help", color=discord.Color.blurple())
        # prefix/hybrid
        by_cog: dict[str, list[str]] = {}
        for c in bot.commands:
            if c.hidden: 
                continue
            by_cog.setdefault(c.cog_name or "No Category", []).append(c.name)
        for cog_name, names in sorted(by_cog.items()):
            e.add_field(name=f"{cog_name}", value=", ".join(sorted(names)), inline=False)

        # slash-only
        prefix_names = {c.name for c in bot.commands}
        slash_only = [c.name for c in bot.tree.get_commands() if c.name not in prefix_names]
        if slash_only:
            e.add_field(name="Slash-only", value=", ".join(sorted(slash_only)), inline=False)

        await ctx.send(embed=e, ephemeral=True if hasattr(ctx, "interaction") else False)

async def setup(bot: commands.Bot):
    await bot.add_cog(helpCog(bot))
