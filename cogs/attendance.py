import discord
import json
import random
import time
from discord.ui import View, Button, Modal, TextInput
from discord.ext import commands

# save json file & handle races
def save_json(filename: str, data: dict):
    unfinished = True
    delay = 1
    while unfinished and delay < 10:
        try:
            with open(filename, 'w') as f: 
                f.write(json.dumps(data))
            unfinished = False
        except IOError as e:
            time.sleep(2 + 3 * random.random())
            delay += 1
    
    if unfinished:
        print(f"Failed to save at {filename}")

class UCIDModal(Modal, title="Check into your meeting!"):

    def __init__(self, ctx: commands.Context, sig: discord.Role):
        super().__init__()
        self.ctx = ctx
        self.sig = sig

    message_input = TextInput(
        label="Enter your UCID",
        placeholder="Example: mdc47",
        style=discord.TextStyle.short,
        required=True,
        max_length=6,
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_message = self.message_input.value
        self.ctx.bot.data["ucids"][str(interaction.user.id)] = user_message
        save_json("data.json", self.ctx.bot.data)
        await interaction.response.send_message(
                f"Successfully registered user: {user_message}", ephemeral=True
            )

#Each button is a discord.ui.button()
class AttendanceView(View):
    def __init__(self, ctx: commands.Context, sig: discord.Role, *, timeout=60*60):
        super().__init__(timeout=timeout)
        self.sig = sig
        self.ctx = ctx
        self.check_in_button = discord.ui.Button(
            label=f"Check into {self.sig.name}",  #only way to add signame into button
            style=discord.ButtonStyle.success,
            emoji="📜"
        )
        self.check_in_button.callback = self.check_in_button_callback
        self.add_item(self.check_in_button)
    

    async def check_in_button_callback(self, interaction: discord.Interaction):
        if str(interaction.user.id) in self.ctx.bot.data["ucids"]:
            await interaction.response.send_message(
                f"Successfully registered user: {self.ctx.bot.data["ucids"][str(interaction.user.id)]}", ephemeral=True
            )
        else:
            await interaction.response.send_modal(UCIDModal(self.ctx, self.sig))

# --- Define the Cog ---
class attendance(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def generate_embed(self, ctx: commands.Context,  sig: discord.Role) -> discord.Embed:

        embed = discord.Embed(title=f"Meeting started for {sig.name}!",
                      description="**Click the button to register your attendance!*",
                      colour=sig.colour)
        
        embed.set_author(name=ctx.author.display_name,
                        icon_url=ctx.author.display_avatar.url)
        
        embed.add_field(name="",
                        value=f"Meeting started <t:{int(ctx.message.created_at.timestamp())}:R>\n" +
                        f"Registration ends in <t:{int(ctx.message.created_at.timestamp())+3600}:R>",
                        inline=False)
        return embed
    
    # -- Attendance Command --
    @commands.hybrid_command(name="attendance", description="Modal menu")
    async def attendance(self, ctx: commands.Context, sig: discord.Role):
        """Sends a message with a View that includes a button to open a modal."""
        await ctx.send(
            "This is an interactive menu. Try sending yourself a DM!",
            embed=self.generate_embed(ctx, sig),
            view=AttendanceView(ctx, sig)
        )

async def setup(bot: commands.Bot):

    await bot.add_cog(attendance(bot))