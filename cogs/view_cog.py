"""View cog: interactive PvE games.

Currently:
    /rps [wager]   rock-paper-scissors against the bot. Optional cash wager
                   gets resolved through change_cash on win/loss (tie returns
                   stake; no cooldown for the no-wager case).

The pre-migration version had a `/menu` demo command alongside /rps. That
got dropped — it duplicated `/modal`'s demo material without contributing
new mechanics. /rps stayed because it's a real (small) game.
"""

import random

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.economy import InsufficientFundsError, change_cash

# Internal mapping for clarity. Kept symmetric so the win-table is easy
# to read: rock beats scissors, paper beats rock, scissors beats paper.
_RPS_OPTIONS: list[tuple[str, str]] = [
    ("Rock", "🪨"),
    ("Paper", "📄"),
    ("Scissors", "✂️"),
]


def _rps_outcome(player: int, ai: int) -> int:
    """Return -1 (player loses), 0 (tie), +1 (player wins).

    Encoded mathematically: with the cyclic ordering rock(0) -> paper(1)
    -> scissors(2) -> rock(0)..., player wins when their pick is one
    step ahead of the AI's modulo 3.
    """
    if player == ai:
        return 0
    if (player - ai) % 3 == 1:
        return 1
    return -1


class _RPSView(View):
    """Three-button view for one /rps round.

    On first click we lock the view (disable all buttons), settle the
    cash if a wager was placed, and edit the original message with the
    outcome embed. Only the original invoker can interact — strangers
    clicking get an ephemeral nudge.
    """

    def __init__(
        self,
        *,
        owner_id: int,
        wager: int,
        timeout: float = 60,
    ):
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.wager = wager
        # Track whether a button has been resolved. Needed because
        # discord.py's "stop after one click" pattern can be racy with
        # concurrent clicks if a tie + retry shape gets added later.
        self._settled = False

        # One button per RPS option. Each shares the same callback path
        # via _Pick — the index determines what was thrown.
        for i, (label, emoji) in enumerate(_RPS_OPTIONS):
            self.add_item(_PickButton(i, label, emoji))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Run your own `/rps` to play.", ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]


class _PickButton(Button):
    def __init__(self, pick_index: int, label: str, emoji: str):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.primary)
        self.pick_index = pick_index

    async def callback(self, interaction: discord.Interaction) -> None:
        view: _RPSView = self.view  # type: ignore[assignment]
        if view._settled:
            await interaction.response.send_message(
                "Round already resolved.", ephemeral=True
            )
            return
        view._settled = True

        # Disable every button so the row can't be replayed. Re-style the
        # picked button as success so the player sees what they chose.
        for child in view.children:
            child.disabled = True  # type: ignore[attr-defined]
            if child is self:
                child.style = discord.ButtonStyle.success  # type: ignore[attr-defined]
            else:
                child.style = discord.ButtonStyle.secondary  # type: ignore[attr-defined]

        ai_pick = random.randint(0, 2)
        result = _rps_outcome(self.pick_index, ai_pick)

        player_label, player_emoji = _RPS_OPTIONS[self.pick_index]
        ai_label, ai_emoji = _RPS_OPTIONS[ai_pick]

        # Settle the wager if one was placed. Tie is a no-op (no DB write
        # since change_cash refuses delta=0).
        cash_line = ""
        if view.wager > 0 and result != 0:
            delta = view.wager if result == 1 else -view.wager
            reason = "rps_win" if result == 1 else "rps_loss"
            try:
                async with get_session() as session:
                    new_balance = await change_cash(
                        session, view.owner_id, delta, reason=reason
                    )
            except InsufficientFundsError as e:
                # Edge case: user spent their cash between starting the
                # round and clicking. Reject the round result by undoing
                # the lock — they can /rps again with a smaller stake.
                cash_line = (
                    f"\n_(Couldn't settle wager: only {e.have:,} cash on hand.)_"
                )
            else:
                if result == 1:
                    cash_line = (
                        f"\nWon **{view.wager:,}** cash. "
                        f"Balance: **{new_balance:,}**."
                    )
                else:
                    cash_line = (
                        f"\nLost **{view.wager:,}** cash. "
                        f"Balance: **{new_balance:,}**."
                    )

        # Outcome message + colour.
        if result == 1:
            title = "You win!"
            color = discord.Color.green()
        elif result == -1:
            title = "You lose."
            color = discord.Color.red()
        else:
            title = "Tie."
            color = discord.Color.greyple()

        embed = discord.Embed(title=title, color=color)
        embed.add_field(
            name="You",
            value=f"{player_emoji} **{player_label}**",
            inline=True,
        )
        embed.add_field(
            name="Vixen",
            value=f"{ai_emoji} **{ai_label}**",
            inline=True,
        )
        if cash_line:
            embed.description = cash_line.strip()

        await interaction.response.edit_message(embed=embed, view=view)
        view.stop()


class ViewsCog(commands.Cog):
    """Interactive PvE games."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /rps
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        aliases=["rock_paper_scissors"],
        help="Play rock-paper-scissors against Vixen. Pass a wager to bet cash."
    )
    @app_commands.describe(
        wager="Optional cash wager. 0 = play for fun.",
    )
    async def rps(
        self,
        ctx: commands.Context,
        wager: int = 0,
    ) -> None:
        if wager < 0:
            await ctx.reply("Wager can't be negative.", ephemeral=True)
            return

        # Cooldown only applies when there's a wager — playing for fun
        # is harmless.
        if wager > 0:
            remaining = await try_acquire(ctx.author.id, "rps")
            if remaining > 0:
                await ctx.reply(
                    f"Slow down — try again in {remaining:.0f}s.",
                    ephemeral=True,
                )
                return

        view = _RPSView(owner_id=ctx.author.id, wager=wager)
        prompt = (
            f"Rock, paper, or scissors? Wager: **{wager:,}** cash."
            if wager > 0
            else "Rock, paper, or scissors? (No wager.)"
        )
        await ctx.reply(prompt, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ViewsCog(bot))
