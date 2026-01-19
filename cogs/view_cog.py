import discord
import requests
import json
from discord.ui import View, Button
from discord.ext import commands
from discord import app_commands
import json
from dotenv import load_dotenv
import os
import matplotlib.pyplot as plt
import numpy as np
import random

class SimpleView(View):
    def __init__(self, *, timeout=60):
        super().__init__(timeout=timeout)
        self.click_count = 0

    @discord.ui.button(label="Click Me!", style=discord.ButtonStyle.success, emoji="👋")
    async def hello_button(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message(
            f"Hello, {interaction.user.mention}! Thanks for clicking.",
            ephemeral=True
        )

    @discord.ui.button(label="Count: 0", style=discord.ButtonStyle.primary, emoji="🔢")
    async def count_button(self, interaction: discord.Interaction, button: Button):
        self.click_count += 1
        button.label = f"Count: {self.click_count}"
        
        await interaction.response.edit_message(view=self)
        
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True

class RPSView(View):
        def __init__(self, authorid, *, timeout=60):
            super().__init__(timeout=timeout)
            self.authorid = authorid

        # rock = 1, paper = 2, scissors = 3
            
        def close(self):
            for item in self.children:
                item.style = discord.ButtonStyle.secondary
                item.disabled = True

        async def verified(self, interaction: discord.Interaction):
            if not interaction.user.id == self.authorid:
                await interaction.response.send_message(
                    f'Not your interaction! Open your own one using the rps command!',
                    ephemeral=True
                )

                return False
            
            return True

        @discord.ui.button(label="Rock", style=discord.ButtonStyle.success, emoji="🪨")
        async def rock_button(self, interaction: discord.Interaction, button: Button):
            if not await self.verified(interaction):
                return

            choice = random.randint(1, 3)

            if choice == 1:
                await interaction.response.send_message(
                    f"AI picks rock. It's a tie.",
                    ephemeral=True
                )  
            if choice == 2:
                await interaction.response.send_message(
                    f"AI picks paper... You lose 😞",
                    ephemeral=True
                )
            if choice == 3:
                await interaction.response.send_message(
                    f"AI picks scissors!!! YOU WIN!!!!!",
                    ephemeral=True
                )

            self.close()
            self.stop()
            await interaction.message.edit(view=self)

        @discord.ui.button(label="Paper", style=discord.ButtonStyle.danger, emoji="📄")
        async def paper_button(self, interaction: discord.Interaction, button: Button):
            if not await self.verified(interaction):
                return

            choice = random.randint(1, 3)

            if choice == 1:
                await interaction.response.send_message(
                    f"AI picks rock!!! YOU WIN!!!",
                    ephemeral=True
                )  
            if choice == 2:
                await interaction.response.send_message(
                    f"AI picks paper. It's a tie ",
                    ephemeral=True
                )
            if choice == 3:
                await interaction.response.send_message(
                    f"AI picks scissors... You lose 😞",
                    ephemeral=True
                )

            self.close()
            self.stop()
            await interaction.message.edit(view=self)

        @discord.ui.button(label="Scissors", style=discord.ButtonStyle.primary, emoji="✂️")
        async def scissors_button(self, interaction: discord.Interaction, button: Button):
            if not await self.verified(interaction):
                return

            choice = random.randint(1, 3)

            if choice == 1:
                await interaction.response.send_message(
                    f"AI picks rock... You lose 😞",
                    ephemeral=True
                )  
            if choice == 2:
                await interaction.response.send_message(
                    f"AI picks paper!!! YOU WIN!!!!!",
                    ephemeral=True
                )
            if choice == 3:
                await interaction.response.send_message(
                    f"AI picks scissors. It's a tie.",
                    ephemeral=True
                )    

            self.close()
            self.stop()
            await interaction.message.edit(view=self)
            
        async def on_timeout(self):
            self.close()

class ViewsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @commands.hybrid_command(name="menu", description="Displays a message with interactive buttons.")
    async def menu(self, ctx: commands.Context):
        view = SimpleView()
        
        await ctx.send(
            "This is an interactive hybrid menu. Click a button!",
            view=view
        )

    @commands.hybrid_command(aliases=["rock_paper_scissors", "rock-paper-scissors", "paper-scissors-stone"]
                            , description="Displays a message with interactive buttons.")
    async def rps(self, ctx: commands.Context):
        view = RPSView(authorid = ctx.author.id)
        await ctx.send(
            "Rock, Paper, or Scissors? Make your choice!",
            view=view  
    )   
        
async def setup(bot: commands.Bot):
    await bot.add_cog(ViewsCog(bot))
