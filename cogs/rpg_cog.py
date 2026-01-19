import discord
from discord.ui import View, Button, Modal, TextInput, RoleSelect, UserSelect
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import os
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import random
import functools
import schedule
import subprocess



register_str = "Please register using `/register`!"

async def registered(self, ctx: commands.Context, *args, **kwargs):
    return str(ctx.author.id) in ctx.bot.rpg

broke_str = "your broke!"
async def afford(self, ctx: commands.Context, wager: int, *args, **kwargs):
    return self.bot.rpg[str(ctx.author.id)]["cash"] >= wager

def run_if(condition_check_func, error):
    def decorator(func_to_run):
        @functools.wraps(func_to_run)
        async def wrapper(*args, **kwargs):
            if await condition_check_func(*args, **kwargs):
                return await func_to_run(*args, **kwargs)
            else:
                raise PermissionError(error)
        
        return wrapper
    return decorator

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

class RPGCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        schedule.every(5).minutes.do(self.save_rpg) #updates every 5 minutes
    def save_rpg(self):
        save_json("data/rpg.json", self.bot.rpg)
        
    @commands.hybrid_command(help="Register yourself!")
    async def register(self, ctx: commands.Context):
        self.bot.rpg[str(ctx.author.id)] = {}
        d = self.bot.rpg[str(ctx.author.id)]
        
        d["inventory"] = {}
        d["cash"] = 0
        
        await ctx.reply("Successfully registered!")
        
    @commands.hybrid_command(help="Check a users profile")
    @app_commands.describe(
        user = "User whose profile to get, specify none to get the author's profile"
    )
    @run_if(registered, register_str)
    async def profile(self, ctx: commands.Context, user: discord.User = None):
        user = user if user else ctx.author
        
        # TODO: send an embed with multipage fucntionality
        await ctx.reply(
            str(self.bot.rpg[str(user.id)]),
            ephemeral=True
        )
        
    @commands.hybrid_command(help="Make some money!")
    @commands.cooldown(1, 15, commands.BucketType.user)
    @run_if(registered, register_str)
    async def work(self, ctx: commands.Context):
        profit = random.randint(25, 125)
        d = self.bot.rpg[str(ctx.author.id)]
        
        d["cash"] = int(d["cash"]) + profit
        await ctx.reply(f"Made {profit} cash!")
        
    @commands.hybrid_command(help="Flip a coin!, win if you get heads!")
    @app_commands.describe(
        wager = "Amount to bet"
        )
    @commands.cooldown(1, 15, commands.BucketType.user)
    @run_if(registered, register_str)
    @run_if(afford, broke_str)
    async def coinflip(self, ctx: commands.Context, wager: int):
        '''
        check if user can afford to flip (use run_if)
        generate random number
        check if won or lost
        update balance
        '''
        coin = random.randint(0,1)
        cash = self.bot.rpg[str(ctx.author.id)]["cash"]
        if coin == 1: #heads
            cash = int(cash) + wager
            self.bot.rpg[str(ctx.author.id)]["cash"] = cash
            await ctx.reply(f"HEADS!!! You won {wager} cash!")
        else: #tails
            cash = int(cash) - wager
            self.bot.rpg[str(ctx.author.id)]["cash"] = cash
            await ctx.reply(f"TAILS. You lost {wager} cash!")
        save_json("data/rpg.json", self.bot.rpg)
            
            
        
        
async def setup(bot: commands.Bot):
    await bot.add_cog(RPGCog(bot))
