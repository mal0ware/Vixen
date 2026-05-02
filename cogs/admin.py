"""Admin / owner utilities.

Migrated to the new shape:
- Dropped `change_prefix`. Per-guild prefix lives in Postgres + Redis now;
  the prefix admin lives in `cogs/prefix.py` as `/setprefix`. Keeping the
  duplicate here would let two users with different permissions write
  different things.
- Dropped the `prefixes.json` read on init. The file is no longer the
  source of truth.
- `/sync` consolidated into a single hybrid command, owner-only.
- Added `/reload-cog` for hot-reloading a cog during development.

Every command in here is owner-only — these are footguns (a wrong sync
in prod can wipe a guild's slash commands until propagation completes).
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.logging import get_logger

log = get_logger(__name__)


class AdminCog(commands.Cog):
    """Owner-only utilities — not for general use."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # Owner check helper
    # ---------------------------------------------------------------- #

    async def _is_owner(self, user_id: int) -> bool:
        """Resolve owner_id lazily; cache after first lookup.

        `bot.owner_id` is None until application_info() runs; this lets
        owner-checks work whether or not the bot has been "bootstrapped"
        with the application info already.
        """
        if self.bot.owner_id is None:
            info = await self.bot.application_info()
            self.bot.owner_id = info.owner.id
        return user_id == self.bot.owner_id

    # ---------------------------------------------------------------- #
    # /sync
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        name="sync",
        help="(Owner) Resync slash commands.",
    )
    @app_commands.describe(
        scope="Where to sync: 'guild' (this server) or 'global' (slow).",
    )
    @commands.is_owner()
    async def sync(
        self,
        ctx: commands.Context,
        scope: str = "guild",
    ) -> None:
        """Resync slash commands. Defaults to the current guild — use
        scope='global' for a global sync (hours of propagation).
        """
        if scope not in {"guild", "global"}:
            await ctx.reply("Scope must be 'guild' or 'global'.", ephemeral=True)
            return

        if scope == "guild":
            if ctx.guild is None:
                await ctx.reply(
                    "Use scope='global' from DMs.", ephemeral=True
                )
                return
            synced = await self.bot.tree.sync(guild=ctx.guild)
            log.info("sync_done", scope="guild", guild_id=ctx.guild.id, count=len(synced))
            await ctx.reply(
                f"Synced **{len(synced)}** commands to this guild.",
                ephemeral=True,
            )
        else:  # global
            synced = await self.bot.tree.sync()
            log.info("sync_done", scope="global", count=len(synced))
            await ctx.reply(
                f"Synced **{len(synced)}** commands globally. "
                "Propagation can take up to an hour.",
                ephemeral=True,
            )

    # ---------------------------------------------------------------- #
    # /reload-cog
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        name="reload-cog",
        help="(Owner) Hot-reload a cog by name (e.g. shop, fin_cog).",
    )
    @app_commands.describe(
        cog_name="Name of the cog file under cogs/ (no .py extension).",
    )
    @commands.is_owner()
    async def reload_cog(
        self,
        ctx: commands.Context,
        cog_name: str,
    ) -> None:
        """Reload one cog's extension without restarting the bot.

        Useful during development — edit a cog, /reload-cog <name>, see
        the change immediately. Slash command schema changes still need
        a /sync afterwards.
        """
        ext = f"cogs.{cog_name}"
        try:
            await self.bot.reload_extension(ext)
        except commands.ExtensionNotLoaded:
            # Try loading fresh; maybe it never loaded due to a startup
            # error. This makes the command useful for "I just fixed the
            # bug, please load me now" too.
            try:
                await self.bot.load_extension(ext)
            except Exception as e:
                log.exception("reload_cog_failed", extension=ext)
                await ctx.reply(
                    f"Couldn't load `{cog_name}`: `{type(e).__name__}`",
                    ephemeral=True,
                )
                return
        except Exception as e:
            log.exception("reload_cog_failed", extension=ext)
            await ctx.reply(
                f"Reload of `{cog_name}` failed: `{type(e).__name__}: {e}`",
                ephemeral=True,
            )
            return

        log.info("reload_cog_ok", extension=ext)
        await ctx.reply(f"Reloaded `{cog_name}`.", ephemeral=True)

    # ---------------------------------------------------------------- #
    # /debug-commands
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        name="debug-commands",
        help="(Owner) List all registered application commands.",
    )
    @commands.is_owner()
    async def debug_commands(self, ctx: commands.Context) -> None:
        """Print every name in the bot's slash-command tree.

        Sanity check for "did my new cog actually register?" without
        needing to run a sync first.
        """
        names = sorted(c.name for c in self.bot.tree.get_commands())
        embed = discord.Embed(
            title=f"Registered commands ({len(names)})",
            description=", ".join(f"`{n}`" for n in names) or "_(none)_",
            color=discord.Color.dark_grey(),
        )
        await ctx.reply(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
