"""Shop cog: /shop, /buy, /sell, /inventory.

Thin Discord layer over `vixen.services.shop`. Slash variants offer
catalog-sourced item choices; the prefix variants accept the same item
keys as plain strings. No durable state lives here — every command
opens one session via `db.get_session()` so the buy/sell pair is one
transaction (atomic cash + inventory move) at the cog boundary.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.economy import InsufficientFundsError
from vixen.services.items import ITEMS
from vixen.services.shop import (
    InsufficientItemsError,
    UnknownItemError,
    buy_item,
    list_inventory,
    sell_item,
)

# discord.py needs the choices list available at decorator-eval time, so
# we materialize it once at import. Discord's slash-choices cap is 25 —
# plenty of headroom for the current 5-item catalog.
_ITEM_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name=f"{item.emoji} {item.name}", value=item.key)
    for item in ITEMS.values()
]


class ShopCog(commands.Cog):
    """Buy/sell items and view inventory."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /shop
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Browse the item catalog.")
    async def shop(self, ctx: commands.Context) -> None:
        embed = discord.Embed(
            title="Vixen Shop",
            description="Use `/buy <item> [qty]` to purchase, `/sell <item> [qty]` to sell back.",
            color=discord.Color.blurple(),
        )
        for item in ITEMS.values():
            embed.add_field(
                name=f"{item.emoji} {item.name}",
                value=(
                    f"{item.description}\n"
                    f"Buy **{item.price:,}** · Sell **{item.sell_price:,}**\n"
                    f"`{item.key}`"
                ),
                inline=False,
            )
        await ctx.reply(embed=embed)

    # ---------------------------------------------------------------- #
    # /buy
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Buy an item from the shop.")
    @app_commands.describe(
        item="What to buy.",
        qty="How many. Default 1.",
    )
    @app_commands.choices(item=_ITEM_CHOICES)
    async def buy(
        self,
        ctx: commands.Context,
        item: str,
        qty: int = 1,
    ) -> None:
        if qty <= 0:
            await ctx.reply("Quantity must be positive.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "shop_buy")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                cost, new_balance, new_qty = await buy_item(
                    session, ctx.author.id, item, qty
                )
        except UnknownItemError:
            await ctx.reply(f"No item with key `{item}`.", ephemeral=True)
            return
        except InsufficientFundsError as e:
            await ctx.reply(
                f"You only have **{e.have:,}** cash — need **{e.need:,}**.",
                ephemeral=True,
            )
            return

        catalog_item = ITEMS[item]
        await ctx.reply(
            f"Bought **{qty}x {catalog_item.emoji} {catalog_item.name}** for "
            f"**{cost:,}** cash. You now own **{new_qty}**. "
            f"Balance: **{new_balance:,}**."
        )

    # ---------------------------------------------------------------- #
    # /sell
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Sell an item back to the shop.")
    @app_commands.describe(
        item="What to sell.",
        qty="How many. Default 1.",
    )
    @app_commands.choices(item=_ITEM_CHOICES)
    async def sell(
        self,
        ctx: commands.Context,
        item: str,
        qty: int = 1,
    ) -> None:
        if qty <= 0:
            await ctx.reply("Quantity must be positive.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "shop_sell")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                payout, new_balance, new_qty = await sell_item(
                    session, ctx.author.id, item, qty
                )
        except UnknownItemError:
            await ctx.reply(f"No item with key `{item}`.", ephemeral=True)
            return
        except InsufficientItemsError as e:
            await ctx.reply(
                f"You only have **{e.have}**x `{e.item_key}` — can't sell **{e.need}**.",
                ephemeral=True,
            )
            return

        catalog_item = ITEMS[item]
        await ctx.reply(
            f"Sold **{qty}x {catalog_item.emoji} {catalog_item.name}** for "
            f"**{payout:,}** cash. **{new_qty}** remaining. "
            f"Balance: **{new_balance:,}**."
        )

    # ---------------------------------------------------------------- #
    # /inventory
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        name="inventory",
        aliases=["inv"],
        help="View your or another user's items.",
    )
    @app_commands.describe(user="Whose inventory to show. Defaults to you.")
    async def inventory(
        self,
        ctx: commands.Context,
        user: discord.User | None = None,
    ) -> None:
        target = user or ctx.author

        async with get_session() as session:
            rows = await list_inventory(session, target.id)

        embed = discord.Embed(
            title=f"{target.display_name}'s inventory",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        if not rows:
            embed.description = "_(empty)_"
        else:
            lines: list[str] = []
            for item_key, qty in rows:
                catalog_item = ITEMS.get(item_key)
                if catalog_item is None:
                    # Item dropped from the catalog but the user still owns
                    # it. Surface by key so it isn't silently invisible.
                    lines.append(f"`{item_key}` x **{qty}**")
                else:
                    lines.append(
                        f"{catalog_item.emoji} **{catalog_item.name}** x **{qty}**"
                    )
            embed.description = "\n".join(lines)

        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShopCog(bot))
