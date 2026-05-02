"""/help cog.

Renders an embed listing every command, grouped by user-facing category
rather than by Python cog. Cog names like `LeaderboardCog` are an
implementation detail; users shouldn't have to know which file a command
lives in to find it.

Two modes:
    /help              overview embed grouped by category
    /help <name>       detail embed for one command — description + usage

Categories are declared statically in `_CATEGORY_BY_COG` so adding a new
cog requires one line here. Anything missing from the map falls into
"Misc" — that's intentional, not a hard error, so a half-done migration
doesn't make /help crash.
"""

import discord
from discord import app_commands
from discord.ext import commands


# Maps a cog *class name* to a (display_label, sort_order) tuple. Lower
# sort_order appears first in the overview embed. Adjust labels here to
# rename categories without touching the cogs themselves.
_CATEGORY_BY_COG: dict[str, tuple[str, int]] = {
    "EconomyCog": ("💰 Economy", 10),
    "ShopCog": ("🛒 Shop", 20),
    "UseCog": ("🛒 Shop", 20),  # /use lives in its own cog but reads as "shop" UX
    "LeaderboardCog": ("🏆 Leaderboard", 30),
    "GamesCog": ("🎰 Games", 40),
    "FishingCog": ("🎰 Games", 40),
    "LotteryCog": ("🎰 Games", 40),
    "RobberyCog": ("🎰 Games", 40),
    "FinCog": ("📊 Finance", 50),
    "WeatherCog": ("☁️ Weather", 60),
    "RemindersCog": ("⏰ Reminders", 70),
    "PrefixCog": ("⚙️ Admin", 80),
    # Legacy fat cogs go to Misc until they migrate.
}

# Default category for any cog not explicitly mapped above.
_DEFAULT_CATEGORY = ("📚 Misc", 999)


def _category_for(cog_class_name: str | None) -> tuple[str, int]:
    """Return (label, sort_order) for the cog. Unknown cogs land in Misc."""
    if cog_class_name is None:
        return _DEFAULT_CATEGORY
    return _CATEGORY_BY_COG.get(cog_class_name, _DEFAULT_CATEGORY)


def _is_ephemeral(ctx: commands.Context) -> bool:
    """Use ephemeral replies for slash invocations — they're meta-commands
    that don't need to spam the channel. Prefix invocations stay public
    so they're inline with conversation."""
    return ctx.interaction is not None


class HelpCog(commands.Cog):
    """Discoverability — list and explain every command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="help", help="Show help or details for a command.")
    @app_commands.describe(
        name="Optional command name. Omit for the full overview."
    )
    async def help(
        self,
        ctx: commands.Context,
        name: str | None = None,
    ) -> None:
        if name:
            await self._send_detail(ctx, name)
        else:
            await self._send_overview(ctx)

    # ---------------------------------------------------------------- #
    # Detail view — one command
    # ---------------------------------------------------------------- #

    async def _send_detail(self, ctx: commands.Context, name: str) -> None:
        # Try the prefix/hybrid command tree first (most commands live
        # there). Fall back to the slash-only tree (for app_commands.Group
        # children that aren't reachable from `bot.commands`).
        cmd = self.bot.get_command(name)
        if cmd is not None:
            embed = discord.Embed(
                title=f"Help • {cmd.qualified_name}",
                description=cmd.help or "_No description._",
                color=discord.Color.green(),
            )
            embed.add_field(
                name="Usage",
                value=f"`{cmd.qualified_name} {cmd.signature}`".strip(),
                inline=False,
            )
            cog_label, _ = _category_for(cmd.cog_name)
            embed.add_field(name="Category", value=cog_label, inline=False)
            await ctx.send(embed=embed, ephemeral=_is_ephemeral(ctx))
            return

        # Slash-only fallback. tree.get_commands() returns top-level only,
        # so subcommands of groups (e.g. /lottery enter) aren't discoverable
        # by their leaf name here — that's fine; users rarely pass them
        # to /help and the overview lists the group itself.
        slash_cmd = next(
            (c for c in self.bot.tree.get_commands() if c.name == name),
            None,
        )
        if slash_cmd is not None:
            embed = discord.Embed(
                title=f"Help • /{slash_cmd.name}",
                description=slash_cmd.description or "_No description._",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed, ephemeral=_is_ephemeral(ctx))
            return

        await ctx.send(
            f"No command named `{name}`.", ephemeral=_is_ephemeral(ctx)
        )

    # ---------------------------------------------------------------- #
    # Overview — every command, grouped by category
    # ---------------------------------------------------------------- #

    async def _send_overview(self, ctx: commands.Context) -> None:
        # Bucket prefix/hybrid commands by category label. We use the cog
        # class name (cog.__class__.__name__) since that's what
        # _CATEGORY_BY_COG keys on. cog.cog_name is normally the same
        # but discord.py allows overriding it — we want the class name
        # specifically so categories are stable.
        by_category: dict[tuple[str, int], list[str]] = {}

        for cmd in self.bot.commands:
            if cmd.hidden:
                continue
            cog_class = cmd.cog.__class__.__name__ if cmd.cog else None
            cat = _category_for(cog_class)
            by_category.setdefault(cat, []).append(cmd.qualified_name)

        # Slash-only commands (those not visible via bot.commands) get
        # their own bucket — typically app_commands.Group instances like
        # /leaderboard or /lottery whose subcommands aren't reflected
        # in the prefix command tree.
        prefix_names = {c.qualified_name for c in self.bot.commands}
        for slash_cmd in self.bot.tree.get_commands():
            if slash_cmd.name in prefix_names:
                continue
            cog_class = (
                slash_cmd.binding.__class__.__name__
                if hasattr(slash_cmd, "binding") and slash_cmd.binding
                else None
            )
            cat = _category_for(cog_class)
            by_category.setdefault(cat, []).append(f"/{slash_cmd.name}")

        embed = discord.Embed(
            title="Vixen — Commands",
            description=(
                "Use `/help <name>` for details on any one command.\n"
                "Slash commands also work as `!command` if your guild has "
                "a configured prefix."
            ),
            color=discord.Color.blurple(),
        )

        # Sort by the numeric sort_order so categories appear in a
        # deliberate order (Economy → Shop → Games → Finance → ...).
        for (label, _order), cmds in sorted(by_category.items(), key=lambda kv: kv[0][1]):
            embed.add_field(
                name=label,
                value=", ".join(f"`{c}`" for c in sorted(set(cmds))),
                inline=False,
            )

        await ctx.send(embed=embed, ephemeral=_is_ephemeral(ctx))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
