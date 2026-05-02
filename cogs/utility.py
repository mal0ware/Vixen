"""Utility cog: small one-shot commands that don't fit elsewhere.

Currently:
    /dog     random dog photo from dog.ceo
    /echo    send a message via webhook (kept; useful for testing)

Both swapped from blocking `requests` to the shared aiohttp session in
`services.http` so the event loop stays responsive while the API
fetches.
"""

import os

import discord
from discord import app_commands
from discord.ext import commands

from vixen.logging import get_logger
from vixen.services.cooldown import try_acquire
from vixen.services.http import get_session

log = get_logger(__name__)

_DOG_API = "https://dog.ceo/api/breeds/image/random"


class UtilityCog(commands.Cog):
    """Small misc commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /dog
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Random dog photo from dog.ceo.")
    async def dog(self, ctx: commands.Context) -> None:
        # Anti-spam — same escalating curve as everything else.
        remaining = await try_acquire(ctx.author.id, "dog")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            session = await get_session()
            async with session.get(_DOG_API) as resp:
                resp.raise_for_status()
                payload = await resp.json()
        except Exception:
            # Upstream API can flake — log with traceback, give the user a
            # tidy message rather than dumping the exception class.
            log.exception("dog_api_failed")
            await ctx.reply(
                "Couldn't fetch a dog photo right now. Try again in a moment.",
                ephemeral=True,
            )
            return

        url = payload.get("message")
        if not url:
            await ctx.reply(
                "Dog API returned an unexpected payload.", ephemeral=True
            )
            return

        # Send as an embed so the image renders inline + has a tidy frame.
        embed = discord.Embed(color=discord.Color.gold())
        embed.set_image(url=url)
        embed.set_footer(text="Powered by dog.ceo")
        await ctx.reply(embed=embed)

    # ---------------------------------------------------------------- #
    # /echo
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(name="echo", help="Echo a message via webhook (admin/dev).")
    @app_commands.describe(message="Message to send through the webhook.")
    @commands.has_permissions(manage_messages=True)
    async def echo(
        self,
        ctx: commands.Context,
        *,
        message: str = "",
    ) -> None:
        # Webhook URL lives in env. If unset, /echo is effectively disabled —
        # don't crash, just tell the invoker.
        url = os.getenv("WEBHOOK_URL")
        if not url:
            await ctx.reply(
                "`WEBHOOK_URL` env var isn't set — /echo is unavailable.",
                ephemeral=True,
            )
            return

        if not message.strip():
            await ctx.reply("Empty message — nothing to echo.", ephemeral=True)
            return

        try:
            session = await get_session()
            async with session.post(url, json={"content": message}) as resp:
                status = resp.status
        except Exception:
            log.exception("echo_webhook_failed")
            await ctx.reply(
                "Webhook request failed. Check WEBHOOK_URL.", ephemeral=True
            )
            return

        await ctx.reply(f"Webhook delivered (HTTP {status}).", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UtilityCog(bot))
