# cogs/utility.py
import os, requests, discord
from discord.ext import commands
from discord import app_commands

class Utility(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @commands.hybrid_command(name="echo", help="Echo via webhook.")
    @app_commands.describe(message="Message to echo")
    async def echo(self, ctx: commands.Context, *, message: str = ""):
        try:
            url = os.getenv("WEBHOOK_URL")
            r = requests.post(url, json={"content": message})
            await ctx.reply(f"Webhook status: {r.status_code}")
        except Exception as e:
            await ctx.send(f"Error with echo: `{e}`")

    @commands.hybrid_command(help="Get a random dog image!")
    async def dog(self, ctx: commands.Context):
        try:
            r = requests.get("https://dog.ceo/api/breeds/image/random", timeout=10)
            await ctx.reply(r.json()["message"])
        except Exception as e:
            await ctx.send(f"Error: `{e}`")

async def setup(bot: commands.Bot):
    await bot.add_cog(Utility(bot))
