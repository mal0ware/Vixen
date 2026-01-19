import json
import discord
from discord.ext import commands
from discord import app_commands

PREFIX_FILE = "prefixes.json"


def load_prefixes() -> dict:
    """
    Load prefix mappings from disk.

    File format example:
    {
        "123456789012345678": "!",
        "987654321098765432": "?"
    }
    """
    try:
        with open(PREFIX_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # If file is missing / invalid, return empty mapping.
        return {}


def save_prefixes(prefixes: dict) -> None:
    """Persist prefix mappings back to disk."""
    with open(PREFIX_FILE, "w", encoding="utf-8") as f:
        json.dump(prefixes, f, ensure_ascii=False, indent=2)


class Admin(commands.Cog):
    """
    Admin utilities:

    - /change_prefix or !change_prefix : change the bot prefix per-server.
    - !sync                            : owner-only text command to resync slash commands.
    - /sync                            : owner-only slash command to resync slash commands.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.prefixes = load_prefixes()

    # ------------------------------------------------------------------ #
    # Prefix management
    # ------------------------------------------------------------------ #

    @commands.hybrid_command(help="Change the bot prefix for this server.")
    @commands.has_permissions(manage_guild=True)
    @app_commands.describe(prefix="Requested prefix")
    async def change_prefix(self, ctx: commands.Context, prefix: str):
        """
        Hybrid command to change the prefix for the current guild.

        - Requires 'Manage Server' (manage_guild) permissions.
        - Updates prefixes.json and the in-memory mapping.
        """
        if ctx.guild is None:
            await ctx.reply("This command must be used in a server, not in DMs.")
            return

        self.prefixes[str(ctx.guild.id)] = prefix
        save_prefixes(self.prefixes)
        await ctx.reply(f"Prefix updated to `{prefix}`.")

    # ------------------------------------------------------------------ #
    # Owner-only sync commands
    # ------------------------------------------------------------------ #

    @commands.command(name="sync", help="Owner-only: resync slash commands for this guild.")
    @commands.is_owner()
    async def sync_prefix(self, ctx: commands.Context):
        """
        Text command: !sync

        - Only the bot owner can use this.
        - Resyncs app commands for the current guild only.
        """
        if ctx.guild is None:
            await ctx.send("This command must be used in a server, not in DMs.")
            return

        synced = await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"Synced {len(synced)} commands to this guild.")

    @app_commands.command(
        name="sync",
        description="Owner-only: resync slash commands for this guild."
    )
    async def sync_slash(self, interaction: discord.Interaction):
        """
        Slash command: /sync

        - Only the bot owner can use this.
        - Resyncs app commands for the current guild only.
        """
        # Get owner id; if not set, fetch from application info once.
        owner_id = self.bot.owner_id
        if owner_id is None:
            app_info = await self.bot.application_info()
            owner_id = app_info.owner.id

        if interaction.user.id != owner_id:
            await interaction.response.send_message(
                "You are not the bot owner.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.response.send_message(
                "This command must be used in a server.",
                ephemeral=True,
            )
            return

        #synced = await self.bot.tree.sync(guild=interaction.guild)
        synced = await self.bot.tree.sync()

        await interaction.response.send_message(
            f"Synced {len(synced)} commands to this guild.",
            ephemeral=True,
        )
        
        
    @commands.command(name="debug_commands")
    @commands.is_owner()
    async def debug_commands(self, ctx: commands.Context):
        cmds = self.bot.tree.get_commands()
        names = [c.name for c in cmds]
        await ctx.send(f"App commands I know about: {names}")


async def setup(bot: commands.Bot):
    """Standard async setup function used by discord.py to load this cog."""
    await bot.add_cog(Admin(bot))
