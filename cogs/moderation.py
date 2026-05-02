"""Moderation: /ban, /unban, /kick.

Three thin wrappers around discord.py's guild moderation methods. Each
checks the invoker's permissions, runs the action, and renders a clean
embed with the reason chain. Errors are typed: missing permissions,
target-not-found, and Discord HTTP errors all get distinct user
messages and a structured log line.
"""

import discord
from discord import app_commands
from discord.ext import commands

from vixen.logging import get_logger

log = get_logger(__name__)


def _audit_reason(action: str, actor: discord.abc.User, reason: str | None) -> str:
    """Compose the audit-log reason that Discord stores on the ban/kick row.

    Format: "Banned by @username: <reason>" — discoverable in the
    server's audit log months later.
    """
    base = f"{action} by {actor}"
    if reason:
        return f"{base}: {reason}"
    return base


def _result_embed(
    *,
    action: str,
    target: discord.abc.User,
    actor: discord.abc.User,
    reason: str | None,
    color: discord.Color,
) -> discord.Embed:
    """Render a clean confirmation embed for a moderation action."""
    embed = discord.Embed(
        title=f"{action.title()} successful",
        color=color,
    )
    embed.add_field(name="Target", value=f"{target} (`{target.id}`)", inline=False)
    embed.add_field(name="Moderator", value=str(actor), inline=False)
    embed.add_field(name="Reason", value=reason or "_(none provided)_", inline=False)
    return embed


class ModerationCog(commands.Cog):
    """Kick / ban / unban with proper error handling and audit logging."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /ban
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Ban a user. Requires Ban Members permission.")
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(
        user="User to ban (mention or ID).",
        reason="Reason. Stored in Discord's audit log.",
    )
    async def ban(
        self,
        ctx: commands.Context,
        user: discord.User,
        *,
        reason: str | None = None,
    ) -> None:
        if ctx.guild is None:
            await ctx.reply("Server only.", ephemeral=True)
            return

        try:
            await ctx.guild.ban(user, reason=_audit_reason("Banned", ctx.author, reason))
        except discord.Forbidden:
            await ctx.reply(
                "I don't have permission to ban that user. Check my role hierarchy.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            log.exception("ban_failed", target_id=user.id, status=e.status)
            await ctx.reply(f"Discord rejected the ban: `{e.text}`.", ephemeral=True)
            return

        log.info(
            "ban_done",
            target_id=user.id,
            actor_id=ctx.author.id,
            guild_id=ctx.guild.id,
            reason=reason,
        )
        await ctx.reply(
            embed=_result_embed(
                action="ban",
                target=user,
                actor=ctx.author,
                reason=reason,
                color=discord.Color.red(),
            )
        )

    # ---------------------------------------------------------------- #
    # /unban
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Unban a user by ID. Requires Ban Members permission.")
    @commands.has_permissions(ban_members=True)
    @app_commands.describe(
        user_id="Discord user ID to unban (digits, no mention).",
        reason="Reason. Stored in Discord's audit log.",
    )
    async def unban(
        self,
        ctx: commands.Context,
        user_id: str,
        *,
        reason: str | None = None,
    ) -> None:
        if ctx.guild is None:
            await ctx.reply("Server only.", ephemeral=True)
            return

        # Allow either raw digits or a mention. Stripping <>!@ handles
        # mention syntax; isdigit then confirms we have a usable id.
        cleaned = user_id.strip("<@!>")
        if not cleaned.isdigit():
            await ctx.reply(
                "Pass a numeric Discord user ID (or a mention).", ephemeral=True
            )
            return

        try:
            user = await self.bot.fetch_user(int(cleaned))
        except discord.NotFound:
            await ctx.reply(f"No user with ID `{cleaned}`.", ephemeral=True)
            return

        try:
            await ctx.guild.unban(user, reason=_audit_reason("Unbanned", ctx.author, reason))
        except discord.NotFound:
            await ctx.reply(f"`{user}` isn't banned in this server.", ephemeral=True)
            return
        except discord.Forbidden:
            await ctx.reply("I don't have permission to unban here.", ephemeral=True)
            return
        except discord.HTTPException as e:
            log.exception("unban_failed", target_id=user.id, status=e.status)
            await ctx.reply(f"Discord rejected the unban: `{e.text}`.", ephemeral=True)
            return

        log.info(
            "unban_done",
            target_id=user.id,
            actor_id=ctx.author.id,
            guild_id=ctx.guild.id,
            reason=reason,
        )
        await ctx.reply(
            embed=_result_embed(
                action="unban",
                target=user,
                actor=ctx.author,
                reason=reason,
                color=discord.Color.green(),
            )
        )

    # ---------------------------------------------------------------- #
    # /kick
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(help="Kick a user. Requires Kick Members permission.")
    @commands.has_permissions(kick_members=True)
    @app_commands.describe(
        user="User to kick.",
        reason="Reason. Stored in Discord's audit log.",
    )
    async def kick(
        self,
        ctx: commands.Context,
        user: discord.Member,
        *,
        reason: str | None = None,
    ) -> None:
        # `discord.Member` is the parameter type so we get a guild member
        # — `discord.User` would let strangers be passed and the kick
        # would silently succeed against a non-member.
        if ctx.guild is None:
            await ctx.reply("Server only.", ephemeral=True)
            return

        try:
            await user.kick(reason=_audit_reason("Kicked", ctx.author, reason))
        except discord.Forbidden:
            await ctx.reply(
                "I don't have permission to kick that user. Check my role hierarchy.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            log.exception("kick_failed", target_id=user.id, status=e.status)
            await ctx.reply(f"Discord rejected the kick: `{e.text}`.", ephemeral=True)
            return

        log.info(
            "kick_done",
            target_id=user.id,
            actor_id=ctx.author.id,
            guild_id=ctx.guild.id,
            reason=reason,
        )
        await ctx.reply(
            embed=_result_embed(
                action="kick",
                target=user,
                actor=ctx.author,
                reason=reason,
                color=discord.Color.orange(),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationCog(bot))
