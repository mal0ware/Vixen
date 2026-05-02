"""/attendance — meeting check-in for SIG roles.

Workflow:
    1. A meeting host runs `/attendance sig:<role>` to post a check-in
       embed in the channel.
    2. Members click the button on that embed.
       - If they've already registered a UCID, the bot confirms their
         attendance and shows the UCID.
       - If not, a modal pops asking them to enter their UCID. The
         submission is persisted to the User table.

Notable migration changes from the pre-migration cog:

- UCIDs now live in `users.ucid` (Postgres) instead of
  `data.json["ucids"]`. Survives bot restarts trivially; falls in step
  with everything else that touches the User row.
- Bot's legacy `bot.data["ucids"]` attribute is no longer touched. The
  rest of the legacy state (data.json) can go too once nothing else
  reads it.
- Use of structlog throughout instead of print/silent failure.
"""

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View

from vixen.db import get_session
from vixen.logging import get_logger
from vixen.services.attendance import get_ucid, set_ucid

log = get_logger(__name__)


class _UCIDModal(Modal, title="Check into your meeting!"):
    """Asks the user for their UCID, persists it, and confirms attendance."""

    ucid_input = TextInput(
        label="Enter your UCID",
        placeholder="Example: mdc47",
        style=discord.TextStyle.short,
        required=True,
        max_length=32,
    )

    def __init__(self, sig: discord.Role):
        super().__init__()
        self.sig = sig

    async def on_submit(self, interaction: discord.Interaction) -> None:
        ucid = self.ucid_input.value.strip()
        if not ucid:
            await interaction.response.send_message(
                "UCID can't be empty.", ephemeral=True
            )
            return

        try:
            async with get_session() as session:
                await set_ucid(session, interaction.user.id, ucid)
        except Exception:
            log.exception("ucid_save_failed", user_id=interaction.user.id)
            await interaction.response.send_message(
                "Couldn't save your UCID — please try again.", ephemeral=True
            )
            return

        log.info(
            "ucid_registered",
            user_id=interaction.user.id,
            sig=self.sig.name,
            ucid=ucid,
        )
        await interaction.response.send_message(
            f"Registered for **{self.sig.name}**: `{ucid}`", ephemeral=True
        )


class _AttendanceView(View):
    """Single-button view attached to the attendance announcement.

    Click → resolve UCID. If known, confirm; if not, open modal.
    Times out after one hour (matches the registration window shown in
    the embed).
    """

    def __init__(self, sig: discord.Role, *, timeout: float = 60 * 60):
        super().__init__(timeout=timeout)
        self.sig = sig

        button = Button(
            label=f"Check into {sig.name}",
            style=discord.ButtonStyle.success,
            emoji="📜",
        )
        button.callback = self._on_click
        self.add_item(button)

    async def _on_click(self, interaction: discord.Interaction) -> None:
        async with get_session() as session:
            existing = await get_ucid(session, interaction.user.id)

        if existing is not None:
            await interaction.response.send_message(
                f"Already registered as `{existing}` for **{self.sig.name}**.",
                ephemeral=True,
            )
            return

        # No UCID on file — open the modal so they can register one.
        await interaction.response.send_modal(_UCIDModal(self.sig))


class AttendanceCog(commands.Cog):
    """Meeting check-in via modal."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="attendance",
        help="Open a meeting check-in embed for the given SIG role.",
    )
    @app_commands.describe(sig="Role representing the SIG / meeting.")
    async def attendance(self, ctx: commands.Context, sig: discord.Role) -> None:
        if ctx.guild is None:
            await ctx.reply("Server only.", ephemeral=True)
            return

        embed = self._build_embed(ctx, sig)
        await ctx.send(
            "This is an interactive menu. Try sending yourself a DM!",
            embed=embed,
            view=_AttendanceView(sig),
        )

    def _build_embed(
        self, ctx: commands.Context, sig: discord.Role
    ) -> discord.Embed:
        """Compose the announcement embed: header + countdown line.

        Uses Discord's <t:UNIX:R> tokens so the time-since and time-until
        update client-side every minute without us editing the message.
        """
        started = int(ctx.message.created_at.timestamp())
        ends = started + 3600  # 1 hour registration window.

        embed = discord.Embed(
            title=f"Meeting started for {sig.name}",
            description="Click the button to register your attendance.",
            colour=sig.colour,
        )
        embed.set_author(
            name=ctx.author.display_name,
            icon_url=ctx.author.display_avatar.url,
        )
        embed.add_field(
            name="​",  # zero-width — we just want the value to flow without a label
            value=(
                f"Meeting started <t:{started}:R>\n"
                f"Registration ends <t:{ends}:R>"
            ),
            inline=False,
        )
        return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AttendanceCog(bot))
