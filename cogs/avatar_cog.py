import discord

from discord import app_commands
from discord.ext import commands
class AvatarCog(commands.Cog):
    def __init__(self, bot:commands.Bot):
            self.bot = bot
            
    def avatar(ctx: commands.Context, user: discord.User):
          ctx.reply(f"(user.mention)", ephemeral=True)
          
async def setup(bot:commands.Bot):
      await bot.add_cog(AvatarCog(bot))