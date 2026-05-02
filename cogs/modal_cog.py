"""/modal — interactive demo cog.

Two buttons under the message:
    "Say Hello"   ephemeral hello reply
    "Send me a DM"   opens a modal; the bot DMs whatever the user types

This cog is mostly a discord.py UI demo — the patterns here (View, Modal,
TextInput, ephemeral responses) get reused in the real interactive
features (e.g. /chart's timeframe buttons).
"""

import discord
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View

from vixen.logging import get_logger

log = get_logger(__name__)


class _MessageModal(Modal, title="Send a message to yourself"):
    """Modal that DMs the submitter whatever text they entered."""

    message_input = TextInput(
        label="Your message",
        placeholder="Type what you want me to DM you...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1000,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await interaction.user.send(self.message_input.value)
            await interaction.response.send_message(
                "Sent — check your DMs.", ephemeral=True
            )
        except discord.Forbidden:
            # The user has DMs from server members closed. Tell them
            # politely; we can't DM them and also can't mass-spam the
            # channel.
            await interaction.response.send_message(
                "I can't DM you — open up DMs from server members in your "
                "Discord settings, then try again.",
                ephemeral=True,
            )
        except Exception:
            # Anything else (network blip, malformed payload). Log with
            # full traceback for debugging; keep the user response generic
            # so we don't leak internals.
            log.exception("modal_dm_failed", user_id=interaction.user.id)
            await interaction.response.send_message(
                "Something went wrong sending that DM.", ephemeral=True
            )


class _DemoView(View):
    """Two-button demo view — short timeout so stale messages don't pile up."""

    def __init__(self, *, timeout: float = 180):
        super().__init__(timeout=timeout)

    @discord.ui.button(label="Say Hello", style=discord.ButtonStyle.success, emoji="👋")
    async def hello(
        self, interaction: discord.Interaction, _button: Button
    ) -> None:
        await interaction.response.send_message(
            f"Hello, {interaction.user.mention}!", ephemeral=True
        )

    @discord.ui.button(label="Send me a DM", style=discord.ButtonStyle.secondary, emoji="✉️")
    async def open_modal(
        self, interaction: discord.Interaction, _button: Button
    ) -> None:
        await interaction.response.send_modal(_MessageModal())


class ModalCog(commands.Cog):
    """Interactive demo: buttons + modal + ephemeral DMs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(name="modal", help="Open the interactive demo menu.")
    async def menu(self, ctx: commands.Context) -> None:
        await ctx.send(
            "Click a button to interact:",
            view=_DemoView(),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModalCog(bot))
