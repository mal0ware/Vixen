"""
V.I.X.E.N.

Very Intelligent Xenial Evolving Network
Virtual Interactive Xenodochial Entity Nexus
Vexingly Ingenious Xenagogue Emulating Nonsense
Very Important Xylophone Emitting Noise
Variable Interface for Xenic Extraplanar Nomenclature
Very Impressive Xenomorphous Extraterrestrial Neologism




This version uses the modern discord.py 2.x pattern:

- A custom Bot subclass (so we can override setup_hook).
- All cogs/extensions are loaded exactly once in setup_hook.
- Application commands (slash / hybrid) are synced exactly once in setup_hook.
- The event loop is driven via asyncio.run(main()).
- on_ready is used only for logging, not for loading or syncing anything.

The goal is:
- No more ExtensionAlreadyLoaded errors on reconnect.
- Clean lifecycle: startup -> load cogs -> sync commands -> run.
- Clear separation between configuration, bot construction, and runtime.
"""

import os
import json
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load .env file so we can access DISCORD_TOKEN and GUILD_ID
load_dotenv()

# ---------------------------------------------------------------------------#
# Prefix handling
# ---------------------------------------------------------------------------#

# Default fallback prefix if no guild/user-specific prefix is found
default_prefix = "!"

# prefixes.json should map guild_id (or user_id for DMs) to string prefixes
# Example:
# {
#   "123456789012345678": "!",
#   "987654321098765432": "?"
# }
with open("prefixes.json", encoding="utf-8") as f:
    prefixes = json.load(f)


def prefix(bot: commands.Bot, message: discord.Message) -> str:
    """
    Dynamic prefix function.

    - If message comes from a guild, use the guild ID as the key.
    - If message comes from DMs, use the author's ID as the key.
    - Fall back to default_prefix if nothing is defined in prefixes.json.

    This function is passed directly as command_prefix to the Bot.
    """
    gid = message.guild.id if message.guild else message.author.id
    return prefixes.get(str(gid), default_prefix)


# ---------------------------------------------------------------------------#
# Bot data loading
# ---------------------------------------------------------------------------#

# General bot configuration / persistent data (arbitrary structure)
with open("data.json", encoding="utf-8") as f:
    bot_data = json.load(f)

# Snipe / leaderboard data (used by SnipeCog and related features)
with open("data/stats2.json", "r", encoding="utf-8") as f:
    stats2 = json.load(f)



# ---------------------------------------------------------------------------#
# Custom Bot subclass
# ---------------------------------------------------------------------------#


class VixenBot(commands.Bot):
    """
    Custom Bot subclass so we can:

    - Store shared data on the bot (self.data, self.stats2).
    - Override setup_hook() to load all cogs and sync the app command tree
      exactly once, at startup, before on_ready.

    This avoids:
      - Loading cogs inside on_ready (which fires on every reconnect).
      - Calling tree.sync repeatedly.
      - ExtensionAlreadyLoaded errors.
    """

    def __init__(self, *, intents: discord.Intents):
        # Note: we pass the dynamic prefix function directly here.
        super().__init__(command_prefix=prefix, intents=intents, help_command=None)

        # Attach shared data so cogs can access bot.data and bot.stats2
        self.data = bot_data
        self.stats2 = stats2

    async def setup_hook(self) -> None:
        """
        setup_hook is called by discord.py once:

        - After the bot logs in,
        - Before on_ready fires,
        - On every startup (but not on reconnects).

        This is the ideal place to:

        - Load all extensions (cogs).
        - Sync application commands (slash / hybrid) once.
        """
        # --- Load all cogs from ./cogs directory ---
        for filename in os.listdir("./cogs"):
            if filename.endswith(".py"):
                ext = f"cogs.{filename[:-3]}"
                # load_extension handles import & setup() inside each cog file
                await self.load_extension(ext)
                print(f"Loaded extension: {ext}")

        # --- Sync the app command tree for a specific guild ---
        # Using per-guild sync makes command changes propagate instantly
        # in that guild, which is convenient during development.
        guild_id_str = os.getenv("GUILD_ID")
        if not guild_id_str:
            raise RuntimeError("GUILD_ID is not set in your environment (.env).")

        guild_id = int(guild_id_str)
        guild_obj = discord.Object(id=guild_id)

        # Syncing per guild:
        # - Only this guild sees command changes immediately.
        # - No rate-limit pain from global syncs during development.
        await self.tree.sync(guild=guild_obj)
        
        print(f"Synced application commands for guild {guild_id}.")

        # If you ever want global rollout instead:
        await self.tree.sync()

        print("All cogs loaded and commands synced. Startup hook complete.")


# ---------------------------------------------------------------------------#
# Bot construction (outside of main)
# ---------------------------------------------------------------------------#

# Configure intents. message_content must be enabled in the Developer Portal too.
intents = discord.Intents.default()
intents.message_content = True

# Instantiate the custom bot
bot = VixenBot(intents=intents)
with open("data/rpg.json", "r") as f:
    rpg = json.load(f)

bot.rpg = rpg



# ---------------------------------------------------------------------------#
# Events
# ---------------------------------------------------------------------------#


@bot.event
async def on_ready():
    """
    Called when the bot has finished logging in and is ready to use.

    IMPORTANT:
    - We do NOT load cogs or sync commands here.
      That all happens exactly once in setup_hook().
    """
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    print("we are so ready gang. >:)")


@bot.event
async def on_message(message: discord.Message):
    """
    Basic on_message handler:

    - Ignores messages from bots (including itself).
    - Passes messages down to the command processor so text commands still work
      when using a dynamic prefix function.
    """
    if message.author.bot:
        return

    # This lets commands (e.g. !ping) still be recognized
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """
    Centralized error handler for command errors.

    - Handles common cases (missing permissions, missing arguments).
    - For all other errors, it notifies the user and re-raises the error
      so you still see the traceback in the console for debugging.
    """
    if isinstance(error, commands.MissingPermissions):
        missing = ", ".join(p.replace("_", " ").title() for p in error.missing_permissions)
        await ctx.send(f"You don’t have permission. Required: **{missing}**")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"Missing argument: `{error.param.name}`.")
    else:
        await ctx.send(f"An unexpected error occurred: {error}")
        # Re-raise so the error still appears in logs / console
        raise error
    
    
    
    
# ---------------------------------------------------------------------------#
# Entry point
# ---------------------------------------------------------------------------#


async def main():
    """
    Main async entry point.

    - Uses an async context manager for the bot to ensure proper startup/shutdown.
    - Calls bot.start(), which connects to Discord and runs until disconnect.
    """
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is not set in your environment (.env).")

    # async with ensures graceful cleanup of internal HTTP sessions, etc.
    async with bot:
        await bot.start(token)


# Standard Python "if run as script" guard
if __name__ == "__main__":
    # asyncio.run drives the entire lifecycle:
    #   create loop -> run main() -> close loop.
    asyncio.run(main())
