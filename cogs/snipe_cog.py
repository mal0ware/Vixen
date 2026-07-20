"""/snipe_leaderboard — paginated points leaderboard.

Pre-migration the cog read points from `bot.stats2` (loaded from
`data/stats2.json` at boot). Now backed by `services.snipe` which reads
the Postgres `snipe_scores` table — same display, no JSON file needed.

The pagination view supports:
    << / <      jump to first / previous page
    [N/total]   page indicator (clickable: opens a "go to page" modal)
    > / >>      next / last page

5 buttons per row, the discord.py max. Owner-locked: only the original
invoker can flip pages, otherwise a stranger could repaginate someone
else's leaderboard.
"""

import math

import discord
from discord.ext import commands
from discord.ui import Button, Modal, TextInput, View

from vixen.db import get_session
from vixen.models import SnipeScore
from vixen.services import snipe

PAGE_SIZE = 4


# --------------------------------------------------------------------------- #
# Modal — "go to page" jump
# --------------------------------------------------------------------------- #


class _PageModal(Modal):
    """Lets the user type a page number directly. Validates 1..total."""

    page_input = TextInput(
        label="Page",
        placeholder="e.g. 3, 12",
        style=discord.TextStyle.short,
        required=True,
        max_length=4,
    )

    def __init__(self, view: "_LeaderboardView"):
        super().__init__(title="Go to page")
        self._view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = self.page_input.value.strip()
        if not raw.isdigit():
            await interaction.response.send_message(
                "Page must be a positive integer.", ephemeral=True
            )
            return

        target = int(raw)
        total_pages = max(1, math.ceil(len(self._view.scores) / PAGE_SIZE))
        if not 1 <= target <= total_pages:
            await interaction.response.send_message(
                f"Out of range — pages 1 to {total_pages}.",
                ephemeral=True,
            )
            return

        self._view.page = target
        await self._view.update_message(interaction)


# --------------------------------------------------------------------------- #
# Buttons
# --------------------------------------------------------------------------- #


class _NavButton(Button):
    """Generic navigation button. `direction` decides the effect.

    Using one class with a direction param is cleaner than the original
    five separate Button subclasses — same behaviour, less duplication.
    """

    def __init__(
        self,
        *,
        label: str,
        emoji: str,
        direction: str,  # 'first' | 'prev' | 'next' | 'last'
    ):
        super().__init__(
            label=label, emoji=emoji, style=discord.ButtonStyle.blurple
        )
        self.direction = direction

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _LeaderboardView = self.view  # type: ignore[assignment]
        total_pages = max(1, math.ceil(len(view.scores) / PAGE_SIZE))

        if self.direction == "first":
            view.page = 1
        elif self.direction == "prev":
            view.page = max(1, view.page - 1)
        elif self.direction == "next":
            view.page = min(total_pages, view.page + 1)
        elif self.direction == "last":
            view.page = total_pages

        await view.update_message(interaction)


class _GotoButton(Button):
    """The center page-indicator button. Click → opens a Modal to jump."""

    def __init__(self, label: str):
        super().__init__(label=label, emoji="⏺️", style=discord.ButtonStyle.blurple)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _LeaderboardView = self.view  # type: ignore[assignment]
        await interaction.response.send_modal(_PageModal(view))


# --------------------------------------------------------------------------- #
# View
# --------------------------------------------------------------------------- #


class _LeaderboardView(View):
    """Paginated leaderboard. Builds 5 buttons; owner-locked."""

    def __init__(self, ctx: commands.Context, scores: list[SnipeScore]):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.scores = scores
        self.page = 1

        # Five buttons in the order they should appear in Discord.
        self.first = _NavButton(label="First", emoji="⏪", direction="first")
        self.prev = _NavButton(label="Prev", emoji="◀️", direction="prev")
        self.goto = _GotoButton(label=self._page_label())
        self.next = _NavButton(label="Next", emoji="▶️", direction="next")
        self.last = _NavButton(label="Last", emoji="⏩", direction="last")

        for btn in (self.first, self.prev, self.goto, self.next, self.last):
            self.add_item(btn)

        self._refresh_button_state()

    def _page_label(self) -> str:
        total_pages = max(1, math.ceil(len(self.scores) / PAGE_SIZE))
        return f"{self.page}/{total_pages}"

    def _refresh_button_state(self) -> None:
        """Disable nav buttons that don't apply at the current edge."""
        total_pages = max(1, math.ceil(len(self.scores) / PAGE_SIZE))

        at_first = self.page == 1
        at_last = self.page == total_pages

        self.first.disabled = at_first
        self.prev.disabled = at_first
        self.next.disabled = at_last
        self.last.disabled = at_last

        # Edge buttons go red when disabled to match the original styling.
        for btn, disabled in (
            (self.first, at_first),
            (self.prev, at_first),
            (self.next, at_last),
            (self.last, at_last),
        ):
            btn.style = (
                discord.ButtonStyle.red if disabled else discord.ButtonStyle.blurple
            )

        self.goto.label = self._page_label()

    async def interaction_check(
        self, interaction: discord.Interaction
    ) -> bool:
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "Run your own `/snipe_leaderboard` to scroll the board.",
                ephemeral=True,
            )
            return False
        return True

    async def update_message(self, interaction: discord.Interaction) -> None:
        """Refresh button state, rebuild the embed, edit the message."""
        self._refresh_button_state()
        await interaction.response.edit_message(
            embed=self.generate_embed(), view=self
        )

    def generate_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Snipe Leaderboard",
            color=discord.Color.dark_purple(),
        )
        embed.set_author(
            name=self.ctx.author.display_name,
            icon_url=self.ctx.author.display_avatar.url,
        )

        if not self.scores:
            embed.description = "_No scores yet._"
            return embed

        start = PAGE_SIZE * (self.page - 1)
        end = min(PAGE_SIZE * self.page, len(self.scores))

        for i in range(start, end):
            score = self.scores[i]
            embed.add_field(
                name=f"#{i + 1} {score.name}",
                value=f"Points: **{score.points:,}**",
                inline=False,
            )
        return embed

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
            child.style = discord.ButtonStyle.gray  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Cog
# --------------------------------------------------------------------------- #


class SnipeCog(commands.Cog):
    """Snipe-game points leaderboard."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="snipe_leaderboard",
        help="Show the snipe-game leaderboard.",
    )
    async def snipe_leaderboard(self, ctx: commands.Context) -> None:
        async with get_session() as session:
            scores = await snipe.all_scores(session)

        view = _LeaderboardView(ctx, scores)
        await ctx.reply(embed=view.generate_embed(), view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SnipeCog(bot))
