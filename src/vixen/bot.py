"""Vixen entrypoint.

Lifecycle:

    asyncio.run(main())
        ├─ setup_logging()          # structlog: JSON in prod, colored in dev
        ├─ init_db()                # async SQLAlchemy engine + sessionmaker
        ├─ init_redis()             # async Redis connection pool
        ├─ build VixenBot
        ├─ bot.start(token)         # connects to Discord
        │     ├─ setup_hook()       # discord.py one-shot startup
        │     │     ├─ load cogs from ./cogs/   (legacy, transitional)
        │     │     └─ tree.sync()  # slash commands: per-guild in dev, global in prod
        │     ├─ on_ready (just logs)
        │     └─ event loop ...
        └─ on shutdown:
              ├─ dispose_redis()
              └─ dispose_db()

Run from the project root:

    python -m vixen          # via the console-script entry in pyproject.toml
    # or
    python src/vixen/bot.py  # equivalent
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands

from .cache import dispose_redis, init_redis
from .config import get_settings
from .db import dispose_db, init_db
from .logging import get_logger, setup_logging

# Project root, derived from this file's location. Lets the bot run from
# any CWD without breaking JSON-relative paths.
#   src/vixen/bot.py  ->  parents[2] is the repo root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
COGS_DIR = PROJECT_ROOT / "cogs"

log = get_logger(__name__)


def _make_prefix_callable():
    """Return a discord.py-compatible async prefix callable.

    discord.py supports `command_prefix` being either a static value, a
    list, or a callable that returns a string / list / coroutine. We use
    the async variant so we can hit Postgres + Redis on every message
    without blocking the event loop.

    Lookup path (delegated to `services.prefix.get_prefix`):
        1. Redis cache (5-minute TTL) — fast hot path.
        2. Postgres `guilds` row — durable source of truth.
        3. Default "!"  — guild has never had a prefix set.

    The DEFAULT_PREFIX is also returned for DMs (no guild). DMs aren't a
    big use case for prefix commands; if someone wants to set a per-DM
    prefix later, the same pattern extends with author_id keys.
    """
    from .db import get_session
    from .services.prefix import DEFAULT_PREFIX, get_prefix

    async def prefix(bot: commands.Bot, message: discord.Message) -> str:
        if message.guild is None:
            return DEFAULT_PREFIX
        async with get_session() as session:
            return await get_prefix(session, message.guild.id)

    return prefix


# --------------------------------------------------------------------------- #
# Custom Bot subclass
# --------------------------------------------------------------------------- #


class VixenBot(commands.Bot):
    """Custom Bot.

    We subclass instead of using `commands.Bot` directly so we can override
    `setup_hook` — the discord.py-blessed place to load extensions and sync
    the application command tree exactly once at startup. `on_ready` fires
    on every reconnect, so loading there causes ExtensionAlreadyLoaded
    errors on flaky networks.
    """

    def __init__(self, *, intents: discord.Intents, prefix_callable):
        super().__init__(
            command_prefix=prefix_callable,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        """One-shot startup hook. Loads cogs, syncs slash tree."""
        await self._load_cogs()
        await self._sync_slash_commands()

    async def _load_cogs(self) -> None:
        """Discover and load every .py file under ./cogs/ as a cog."""
        if not COGS_DIR.is_dir():
            log.error("cogs_dir_missing", path=str(COGS_DIR))
            return

        for entry in sorted(os.listdir(COGS_DIR)):
            if not entry.endswith(".py") or entry.startswith("_"):
                continue
            ext = f"cogs.{entry[:-3]}"
            try:
                await self.load_extension(ext)
                log.info("cog_loaded", extension=ext)
            except Exception:
                # Don't crash startup on one bad cog — log and continue.
                # In prod we'd page on this; for personal use, log is fine.
                log.exception("cog_load_failed", extension=ext)

    async def _sync_slash_commands(self) -> None:
        """Sync the application command tree.

        Two modes:
        - dev  : copy global commands to the dev guild, then explicitly
                 clear the global tree on Discord. Effect: the dev guild
                 sees commands instantly, and any leftover global
                 registrations from previous runs (or the buggy old
                 main.py) get scrubbed. Idempotent — once Discord's
                 global registration is empty, subsequent runs no-op the
                 clear and the sync is fast.
        - prod : sync globally. Discord rate-limits global syncs heavily
                 (hours of propagation) — only do this when shipping a
                 stable command surface.
        """
        settings = get_settings()
        if settings.env == "dev":
            guild_obj = discord.Object(id=settings.guild_id)
            # 1. Mirror the in-memory global tree into the dev guild.
            self.tree.copy_global_to(guild=guild_obj)
            # 2. Clear the in-memory global tree so the next sync()
            #    pushes "no global commands" to Discord.
            self.tree.clear_commands(guild=None)
            # 3. Sync (now-empty) global tree -> Discord wipes any leftover
            #    global registrations from previous runs.
            await self.tree.sync()
            # 4. Sync the dev guild so the user sees the actual commands.
            synced = await self.tree.sync(guild=guild_obj)
            log.info(
                "slash_synced",
                scope="guild",
                guild_id=settings.guild_id,
                count=len(synced),
            )
        else:
            synced = await self.tree.sync()
            log.info("slash_synced", scope="global", count=len(synced))


# --------------------------------------------------------------------------- #
# Bot construction
# --------------------------------------------------------------------------- #


def _build_bot() -> VixenBot:
    """Construct the bot. Pure setup — no JSON state, no legacy aliases.

    All persistent state lives in Postgres via the services layer; the
    bot itself is now stateless beyond what discord.py's command tree
    holds.
    """
    intents = discord.Intents.default()
    # Required to read message content for prefix-style commands. Must also
    # be enabled in the Developer Portal under Bot -> Privileged Intents.
    intents.message_content = True

    bot = VixenBot(
        intents=intents,
        prefix_callable=_make_prefix_callable(),
    )

    _register_event_handlers(bot)
    return bot


def _register_event_handlers(bot: VixenBot) -> None:
    """Attach top-level event handlers.

    Defined as nested functions on the bot rather than methods on VixenBot
    because discord.py's `@bot.event` decorator pattern is more idiomatic
    here than overriding `Bot.on_*` methods.
    """

    @bot.event
    async def on_ready():
        # Fires every time the websocket reconnects. Avoid doing real work
        # here — startup logic belongs in setup_hook.
        log.info("bot_ready", user=str(bot.user), user_id=getattr(bot.user, "id", None))

    @bot.event
    async def on_message(message: discord.Message):
        if message.author.bot:
            return
        # Required when using a *dynamic* prefix callable: otherwise
        # discord.py won't actually invoke command handlers.
        await bot.process_commands(message)

    @bot.event
    async def on_command_error(
        ctx: commands.Context, error: commands.CommandError
    ) -> None:
        # User-facing, "expected" errors get a friendly reply.
        if isinstance(error, commands.MissingPermissions):
            missing = ", ".join(
                p.replace("_", " ").title() for p in error.missing_permissions
            )
            await ctx.send(f"You don't have permission. Required: **{missing}**")
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`.")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Slow down — try again in {error.retry_after:.1f}s.")
            return
        if isinstance(error, commands.CommandNotFound):
            return  # silently ignore typos like `!fnord`

        # Anything else: log with full traceback, tell the user something
        # broke. We do NOT re-raise — that would surface the traceback to
        # the websocket layer and can destabilize the event loop.
        log.exception(
            "command_error",
            command=getattr(ctx.command, "qualified_name", None),
            user_id=ctx.author.id,
            guild_id=ctx.guild.id if ctx.guild else None,
            error=repr(error),
        )
        await ctx.send(f"Something went wrong: `{type(error).__name__}`.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def main() -> None:
    setup_logging()
    settings = get_settings()

    # Fast-fail when required secrets are still placeholders. Settings allows
    # empty defaults so utility commands (alembic, tests) work, but the bot
    # itself must have a real token + dev guild.
    if not settings.discord_token:
        raise RuntimeError(
            "DISCORD_TOKEN is empty. Set it in .env before starting the bot."
        )
    if settings.env == "dev" and not settings.guild_id:
        raise RuntimeError(
            "GUILD_ID is empty (or 0). Set it in .env when running with ENV=dev "
            "so slash-command sync can target your dev guild."
        )

    # Bring up infra BEFORE the bot logs in — if Postgres or Redis is
    # unreachable we want to fail loudly here, not after Discord auth.
    init_db()
    init_redis()
    log.info("infra_ready", env=settings.env)

    bot = _build_bot()

    try:
        async with bot:
            await bot.start(settings.discord_token)
    finally:
        # Always run on shutdown, including KeyboardInterrupt and crashes.
        # Dispose order matters: highest-level (HTTP sessions, services)
        # first, then infrastructure (Redis, DB engine).
        from .services.http import close_session as close_http_session
        from .services.weather import close_session as close_weather_session

        await close_weather_session()
        await close_http_session()
        await dispose_redis()
        await dispose_db()
        log.info("infra_disposed")


def run() -> None:
    """Console-script entry point. Wired to `vixen` in pyproject.toml.

    Equivalent to `python -m vixen` or `python src/vixen/bot.py`.
    """
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Clean Ctrl-C exit — main()'s `finally` already disposed infra.
        log.info("bot_stopped")


if __name__ == "__main__":
    run()
