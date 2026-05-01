"""/remind cog.

Three subcommands:
    /remind set <duration> <message>   schedule a future DM
    /remind list                       your unfired reminders
    /remind cancel <id>                cancel one of your reminders

Background poller

A `discord.ext.tasks.loop` runs every 30 s. Each tick:
    1. Query unfired reminders with `due_at <= now`.
    2. DM the user. If they have DMs closed (Forbidden), we silently skip
       — better than spamming the channel or stalling the loop.
    3. Mark fired.

Worst-case lag from due time to DM is ~30 s (one full loop interval).
Acceptable for a personal reminders bot — if you need second-precision,
swap the polling for a sleep-until-next-due cursor pattern.
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks

from vixen.db import get_session
from vixen.logging import get_logger
from vixen.services import reminders

log = get_logger(__name__)


class RemindersCog(commands.Cog):
    """Schedule DM reminders to yourself."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Start the polling loop. Cancellation happens in cog_unload below.
        self._poll.start()

    def cog_unload(self) -> None:
        self._poll.cancel()

    # ---------------------------------------------------------------- #
    # Background poller
    # ---------------------------------------------------------------- #

    @tasks.loop(seconds=30)
    async def _poll(self) -> None:
        """Fire any reminders whose time has come.

        We open one session per loop tick, find the due rows, and process
        them inline. If DMing fails (user closed DMs, network blip), we
        still mark fired — retrying would either succeed forever or fail
        forever, neither helpful.
        """
        try:
            async with get_session() as session:
                due = await reminders.due(session)
                for reminder in due:
                    user = self.bot.get_user(reminder.user_discord_id)
                    if user is not None:
                        try:
                            await user.send(f"⏰ Reminder: {reminder.message}")
                        except discord.Forbidden:
                            # User has DMs closed. Mark fired anyway so we
                            # don't retry every 30 s forever.
                            log.info(
                                "reminder_dm_closed",
                                user_id=reminder.user_discord_id,
                                reminder_id=reminder.id,
                            )
                    else:
                        log.warning(
                            "reminder_user_uncached",
                            user_id=reminder.user_discord_id,
                            reminder_id=reminder.id,
                        )
                    await reminders.mark_fired(session, reminder.id)
        except Exception:
            # Never let the polling loop die. Swallow + log — the next
            # tick gets a fresh attempt.
            log.exception("reminder_poll_failed")

    @_poll.before_loop
    async def _wait_until_ready(self) -> None:
        # Don't start polling until the bot is logged in. Otherwise
        # `bot.get_user` returns None for everyone.
        await self.bot.wait_until_ready()

    # ---------------------------------------------------------------- #
    # /remind set
    # ---------------------------------------------------------------- #

    remind_group = app_commands.Group(
        name="remind",
        description="Schedule reminders.",
    )

    @remind_group.command(name="set", description="Set a reminder.")
    @app_commands.describe(
        duration="When to remind, e.g. '5m', '1h30m', '2d'.",
        message="What to remind you about.",
    )
    async def set_cmd(
        self,
        interaction: discord.Interaction,
        duration: str,
        message: str,
    ) -> None:
        try:
            seconds = reminders.parse_duration(duration)
        except ValueError as e:
            await interaction.response.send_message(
                f"Couldn't parse duration: {e}", ephemeral=True
            )
            return

        async with get_session() as session:
            reminder = await reminders.create(
                session, interaction.user.id, message, seconds
            )

        # Render the due time as Discord's <t:UNIX:R> so the user sees a
        # relative time their client localizes ("in 30 minutes").
        await interaction.response.send_message(
            f"OK — reminding you <t:{int(reminder.due_at.timestamp())}:R>: "
            f"_{message}_",
            ephemeral=True,
        )

    # ---------------------------------------------------------------- #
    # /remind list
    # ---------------------------------------------------------------- #

    @remind_group.command(name="list", description="Show your pending reminders.")
    async def list_cmd(self, interaction: discord.Interaction) -> None:
        async with get_session() as session:
            rows = await reminders.list_for_user(session, interaction.user.id)

        if not rows:
            await interaction.response.send_message(
                "No pending reminders.", ephemeral=True
            )
            return

        lines = [
            f"**{r.id}.** <t:{int(r.due_at.timestamp())}:R> — {r.message}"
            for r in rows
        ]
        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True
        )

    # ---------------------------------------------------------------- #
    # /remind cancel
    # ---------------------------------------------------------------- #

    @remind_group.command(name="cancel", description="Cancel a pending reminder.")
    @app_commands.describe(reminder_id="ID from /remind list.")
    async def cancel_cmd(
        self,
        interaction: discord.Interaction,
        reminder_id: int,
    ) -> None:
        async with get_session() as session:
            removed = await reminders.cancel(
                session, reminder_id, interaction.user.id
            )

        if removed:
            await interaction.response.send_message(
                f"Cancelled reminder #{reminder_id}.", ephemeral=True
            )
        else:
            # Either the id doesn't exist or it belongs to someone else.
            # Same response either way — don't leak whether other users'
            # reminders exist.
            await interaction.response.send_message(
                f"No reminder #{reminder_id} in your list.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RemindersCog(bot))
