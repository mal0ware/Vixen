import discord
from discord.ui import Label, View, Button, TextInput, Modal
from discord.ext import commands
from discord import app_commands
import json
import time
import functools
import math
import copy
from typing import Union

PAGE_SIZE = 4

class PageModal(Modal):
    def __init__(self, leaderboard):
        super().__init__(title="Enter the page to go to")
        
        self.leaderboard = leaderboard
        
    message_input = TextInput(
        label="Page",
        placeholder="ex. 3, 67",
        style=discord.TextStyle.short,
        required=True,
        max_length=3,
    )

    async def on_submit(self, interaction: discord.Interaction):
        page = self.message_input.value.strip()
        
        leaderboard = self.leaderboard
        pages = math.ceil(len(leaderboard.stats) / PAGE_SIZE)
                
        if not page.isdigit():
            await interaction.response.send_message(f"Not an positive integer. Please send an integer from 1 to {pages}.", ephemeral=True)
            return
        
        page = int(page)
        
        if page <= 0 or page > pages:
            await interaction.response.send_message(f"Out of bounds. Please send an integer from 1 to {pages}.", ephemeral=True)
            return
        
        leaderboard.page = page
        await self.leaderboard.update_and_send(interaction)
        
class LeaderboardView(View):
    def __init__(self, ctx):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.stats = self.gen_stats() 
        self.page = 1
        
        self.bb = self.bb_button(self.stats)
        self.add_item(self.bb)
        
        self.b = self.b_button(self.stats)
        self.add_item(self.b)
        
        self.goto = self.goto_button(self.stats)
        self.add_item(self.goto)
        
        self.f = self.f_button(self.stats)
        self.add_item(self.f)
        
        self.ff = self.ff_button(self.stats)
        self.add_item(self.ff)
        
    def gen_stats(self):
        data = copy.deepcopy(self.ctx.bot.stats2)
        stats = []
        
        for user_id, details in data.items():
            details['user_id'] = user_id 
            stats.append(details)

        stats = sorted(
            stats, 
            key=lambda item: int(item["overall points"]), 
            reverse=True
        )
        
        return stats
        
    async def interaction_check(self, interaction: discord.Interaction):
        if not interaction.user.id == self.ctx.author.id:
            await interaction.response.send_message(
                f'Not your interaction! Open your own one using the leaderboard command!',
                ephemeral=True
            )

            return False
        
        return True
        
    class bb_button(discord.ui.Button):
        def __init__(self, stats):
            super().__init__(label="To first page", style=discord.ButtonStyle.red, emoji="⏪", disabled=True)
            self.stats = stats
        
        async def callback(self, interaction: discord.Interaction):
            self.view.page = 1
            await self.view.update_and_send(interaction)
            
        def update(self):
            if self.view.page == 1:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            else:
                self.disabled = False
                self.style = discord.ButtonStyle.blurple

    class b_button(discord.ui.Button):
        def __init__(self, stats):
            super().__init__(label="Previous Page", style=discord.ButtonStyle.red, emoji="◀️", disabled=True)
            self.stats = stats
            
        async def callback(self, interaction: discord.Interaction):
            self.view.page -= 1 
            await self.view.update_and_send(interaction)
            
        def update(self):
            if self.view.page == 1:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            else:
                self.disabled = False
                self.style = discord.ButtonStyle.blurple
        
    class goto_button(discord.ui.Button):
        def __init__(self, stats):
            pages = math.ceil(len(stats) / PAGE_SIZE)
            
            super().__init__(label=f"1/{pages}", style=discord.ButtonStyle.blurple, emoji="⏺️")
            self.stats = stats
            
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_modal(PageModal(self.view))
            
        def update(self):
            pages = math.ceil(len(self.view.stats) / PAGE_SIZE)
        
            self.label = f"{self.view.page}/{pages}"
            
    class f_button(discord.ui.Button):
        def __init__(self, stats):
            pages = math.ceil(len(stats) / PAGE_SIZE)
            
            super().__init__(label="Next Page", style=discord.ButtonStyle.blurple, emoji="▶️")
            self.stats = stats
            
            if pages == 1:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            
        async def callback(self, interaction: discord.Interaction):
            self.view.page += 1
            await self.view.update_and_send(interaction)
            
        def update(self):
            pages = math.ceil(len(self.view.stats) / PAGE_SIZE)
        
            if self.view.page == pages:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            else:
                self.disabled = False
                self.style = discord.ButtonStyle.blurple
        
    class ff_button(discord.ui.Button):
        def __init__(self, stats):
            pages = math.ceil(len(stats) / PAGE_SIZE)
            
            super().__init__(label="Last Page", style=discord.ButtonStyle.blurple, emoji="⏩")
            self.stats = stats
            
            if pages == 1:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            
        async def callback(self, interaction: discord.Interaction):
            pages = math.ceil(len(self.stats) / PAGE_SIZE)
            self.view.page = pages
            await self.view.update_and_send(interaction)
            
        def update(self):
            pages = math.ceil(len(self.view.stats) / PAGE_SIZE)
        
            if self.view.page == pages:
                self.disabled = True
                self.style = discord.ButtonStyle.red
            else:
                self.disabled = False
                self.style = discord.ButtonStyle.blurple
                
    def generate_embed(self):
        embed = discord.Embed()
        
        embed.set_author(name=self.ctx.author.display_name,
                    icon_url=self.ctx.author.display_avatar.url)

        start = PAGE_SIZE * (self.page - 1)
        end = min(PAGE_SIZE * (self.page), len(self.stats))

        for i in range(start, end):
            embed.add_field(name=f"#{i + 1} {self.stats[i]["name"]}",
                            value=f"Points: {self.stats[i]["overall points"]}",
                            inline=False)
        return embed
        
    # the union with message is legacy
    # leaving it as is tho
    async def update_and_send(self, context: Union[discord.Interaction, discord.Message]):
        for button in self.children:
            button.update()
            
        embed = self.generate_embed()

        if isinstance(context, discord.Interaction):
            await context.response.edit_message(embed=embed, view=self)
        elif isinstance(context, discord.Message):
            await context.edit(embed=embed, view=self)
            
    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
            item.style = discord.ButtonStyle.gray
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.NotFound:
                pass

class SnipeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        
    @commands.hybrid_command(help="Send the snipe leaderboard")
    async def leaderboard(self, ctx: commands.Context):
        view = LeaderboardView(ctx)
        view.message = await ctx.reply(embed=view.generate_embed(), view=view, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(SnipeCog(bot))