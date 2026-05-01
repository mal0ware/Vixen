"""/use cog: consume an inventory item to trigger its effect.

Currently bread and coffee are the only consumables — they emit flavor
text and remove one from inventory. The pattern is set up so adding a new
consumable is purely a service-layer change (catalog entry + effect
handler), no cog edits required.

Slash-choice dropdown is filtered to consumable items only — the user
can't even see fishing_rod or padlock here, since /use can't act on them.
"""

from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.items import ITEMS
from vixen.services.shop import InsufficientItems, UnknownItem
from vixen.services.use import NotConsumable, consume_item

# Built once at import. Only items with an effect are eligible for /use,
# so the dropdown matches what the command can actually do — no need to
# render "fishing_rod" then reject it with NotConsumable.
_USABLE_CHOICES: list[app_commands.Choice[str]] = [
    app_commands.Choice(name=f"{item.emoji} {item.name}", value=item.key)
    for item in ITEMS.values()
    if item.effect is not None
]


class UseCog(commands.Cog):
    """Consume items from your inventory."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(help="Use a consumable item from your inventory.")
    @app_commands.describe(item="Which consumable to use.")
    @app_commands.choices(item=_USABLE_CHOICES)
    async def use(self, ctx: commands.Context, item: str) -> None:
        # Anti-spam cooldown — same escalating curve as other mutating
        # commands. Even pure-flavor /use writes to the DB, so we still
        # gate it.
        remaining = await try_acquire(ctx.author.id, "use")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                flavor = await consume_item(session, ctx.author.id, item)
        except UnknownItem:
            await ctx.reply(f"No item with key `{item}`.", ephemeral=True)
            return
        except NotConsumable:
            # Reachable only if a non-consumable slipped through (manual
            # invocation or someone editing the choices list). The slash
            # dropdown filters these out, so this is defense-in-depth.
            await ctx.reply(
                f"`{item}` can't be used directly — it's used by another command.",
                ephemeral=True,
            )
            return
        except InsufficientItems as e:
            await ctx.reply(
                f"You don't have any `{e.item_key}` to use.", ephemeral=True
            )
            return

        await ctx.reply(flavor)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(UseCog(bot))
