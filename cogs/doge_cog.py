"""DOGE.gov savings analyzer — /doge.

Hits the DOGE government savings API for grants / contracts / leases,
renders a log-scale boxplot of the savings amounts, and ships the chart
to Discord.

Notable differences from the pre-migration version:

- Uses the Agg matplotlib backend (set in services/charts.py); no Python.app
  window appears on macOS.
- Renders to in-memory PNG bytes via a BytesIO — no temp files, no
  `temp/<user_id>/savings_boxplot.png` cleanup-on-rotate dance, no
  data.json side-channel for tracking emitted images.
- Async HTTP via the shared aiohttp session (was: `aiohttp.ClientSession`
  per call with `timeout=0`, which actually means *no* timeout — the
  bot would hang forever on a slow API).
- Anti-spam cooldown via the standard escalating curve.
"""

import io

# Force the headless Agg backend before pyplot is imported so /doge can't
# spawn a Python.app window on macOS. services/charts.py also sets this;
# `matplotlib.use("Agg")` is idempotent so the duplicate is harmless and
# makes this cog independently safe.
import matplotlib

matplotlib.use("Agg")

from typing import Literal

import discord
import matplotlib.pyplot as plt
import numpy as np
from discord import app_commands
from discord.ext import commands

from vixen.logging import get_logger
from vixen.services.cooldown import try_acquire
from vixen.services.http import get_session

log = get_logger(__name__)

_API_BASE = "https://api.doge.gov/savings"


def _render_boxplot(savings: list[float]) -> bytes:
    """Render a log-scale boxplot of savings values to PNG bytes.

    Returns the PNG payload directly so the cog can wrap it in
    discord.File(BytesIO(...)) without writing a temp file.
    """
    fig, ax = plt.subplots(figsize=(8, 4))

    bplot = ax.boxplot(savings, vert=False, patch_artist=True)

    # Coloured palette — same idea as the original, just less code.
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

    # Log scale because savings amounts span many orders of magnitude
    # (a $5k grant alongside a $5B contract).
    ax.set_xscale("log")
    ax.set_title("DOGE Savings (log scale)")
    ax.set_xlabel("Savings ($)")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


class DogeCog(commands.Cog):
    """DOGE.gov savings explorer."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="doge", help="Plot DOGE.gov savings (grants/contracts/leases).")
    @app_commands.describe(
        endpoint="Which feed to query.",
        sort_by="Field to sort by (default: savings).",
        sort_order="asc / desc (default: desc).",
        page="Page number (default: 1).",
        per_page="Items per page, 1-500 (default: 10).",
    )
    async def doge(
        self,
        ctx: commands.Context,
        endpoint: Literal["grants", "contracts", "leases"] = "grants",
        sort_by: str = "savings",
        sort_order: Literal["asc", "desc"] = "desc",
        page: int = 1,
        per_page: int = 10,
    ) -> None:
        # Validate per_page within the API's documented bounds. Out-of-range
        # values cause a 400 from upstream; better to short-circuit here
        # with a clearer message.
        if not 1 <= per_page <= 500:
            await ctx.reply(
                "`per_page` must be between 1 and 500.", ephemeral=True
            )
            return

        remaining = await try_acquire(ctx.author.id, "doge")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        if ctx.interaction is not None:
            await ctx.defer()

        params = {
            "sort_by": sort_by,
            "sort_order": sort_order,
            "page": page,
            "per_page": per_page,
        }

        try:
            session = await get_session()
            async with session.get(f"{_API_BASE}/{endpoint}", params=params) as resp:
                if resp.status != 200:
                    await ctx.reply(
                        f"DOGE API returned HTTP {resp.status}.", ephemeral=True
                    )
                    return
                data = await resp.json()
        except Exception:
            log.exception("doge_api_failed", endpoint=endpoint)
            await ctx.reply(
                "DOGE API request failed. Try again in a moment.",
                ephemeral=True,
            )
            return

        # Defensive parse — the API has changed shape before; degrade
        # cleanly rather than crashing.
        try:
            rows = data["result"][endpoint]
            savings = [float(r["savings"]) for r in rows if r.get("savings") is not None]
        except (KeyError, TypeError, ValueError):
            log.warning("doge_payload_unexpected", endpoint=endpoint)
            await ctx.reply(
                "DOGE API response missing expected fields.", ephemeral=True
            )
            return

        if not savings:
            await ctx.reply(
                f"No {endpoint} savings data on page {page}.", ephemeral=True
            )
            return

        png = _render_boxplot(savings)
        file = discord.File(io.BytesIO(png), filename="doge_savings.png")
        await ctx.reply(
            content=(
                f"DOGE {endpoint} — page {page}, sorted by `{sort_by}` ({sort_order}). "
                f"{len(savings)} entries."
            ),
            file=file,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DogeCog(bot))
