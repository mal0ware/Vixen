# cogs/doge_cog.py
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from typing import Literal

DATA_PATH = "data.json"
MAX_FILES = 1

class DogeCog(commands.Cog):
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------- small state helpers ----------
    @staticmethod
    def _load_state():
        try:
            with open(DATA_PATH) as f:
                data = json.load(f)
        except Exception:
            data = {}
        data.setdefault("images", [])
        return data

    @staticmethod
    def _save_state(data):
        with open(DATA_PATH, "w") as f:
            json.dump(data, f)

    @classmethod
    def _savefig(cls, save_path: str):
        data = cls._load_state()
        imgs = data["images"]
        if len(imgs) >= MAX_FILES:
            old = imgs.pop(0)
            if os.path.exists(old):
                try:
                    os.remove(old)
                except Exception:
                    pass
        plt.savefig(save_path)
        if save_path in imgs:
            imgs.remove(save_path)
        imgs.append(save_path)
        cls._save_state(data)

    # ---------- plotting ----------
    @staticmethod
    def _dogeplot(ctx: commands.Context, savings_values):
        fig, ax = plt.subplots()
        bplot = ax.boxplot(savings_values, vert=False, patch_artist=True)

        cmap = plt.get_cmap("jet")
        colors = cmap(np.linspace(0, 1, 5))
        bplot["boxes"][0].set_facecolor(colors[0])
        bplot["medians"][0].set_color(colors[4])
        bplot["fliers"][0].set_markerfacecolor(colors[2])
        bplot["fliers"][0].set_markeredgecolor(colors[2])
        for w in bplot["whiskers"]:
            w.set_color(colors[1])
        for c in bplot["caps"]:
            c.set_color(colors[3])

        ax.set_xscale("log")
        ax.set_title("Box Plot of Savings (Log Scale)")
        ax.set_xlabel("Savings")

        out_dir = f"temp/{ctx.author.id}"
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, "savings_boxplot.png")
        DogeCog._savefig(path)
        plt.close(fig)
        return path

    # ---------- command ----------
    @commands.hybrid_command(name="doge", help="Analyze Doge savings")
    @commands.cooldown(1, 0, commands.BucketType.guild)
    @app_commands.describe(
        endpoint="grants | contracts | leases",
        sort_by="Field to sort by",
        sort_order="asc | desc",
        page="Page number",
        per_page="Items per page (1–500)",
    )
    async def doge(
        self,
        ctx: commands.Context,
        endpoint: Literal["grants", "contracts", "leases"] = "grants", #literal from typing import Literal.
        sort_by: str = "savings",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        per_page: int = 10,
    ):
        if endpoint not in {"grants", "contracts", "leases"}:
            await ctx.send("endpoint must be grants, contracts, or leases")
            return

        params = {
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page": page,
            "per_page": per_page,
        }

        url = f"https://api.doge.gov/savings/{endpoint}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=0) as resp:
                    if resp.status != 200:
                        await ctx.send(f"API error: HTTP {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            await ctx.send(f"Request failed: {type(e).__name__}")
            return

        try:
            savings = [v["savings"] for v in data["result"][endpoint]]
            if not savings:
                await ctx.send("No savings data returned")
                return
        except Exception:
            await ctx.send("API response missing expected fields")
            return

        path = self._dogeplot(ctx, savings)
        await ctx.channel.send("Your analysis here:", file=discord.File(path))

async def setup(bot: commands.Bot):
    await bot.add_cog(DogeCog(bot))
