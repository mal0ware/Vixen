"""Mini-games: /dice and /slots.

Pattern matches /coinflip:

    1. Validate wager
    2. Acquire anti-spam cooldown
    3. Open one DB session
    4. Compute outcome (random)
    5. Apply signed delta via change_cash (audit-logged + leaderboard-synced)
    6. Reply with the outcome

Both commands debit the wager up front via change_cash with a negative
delta — that fails fast if the player can't afford it (raises
InsufficientFundsError, which we render). On a win, we credit the gross payout
back. The session boundary makes both halves atomic: if anything between
debit and credit raises, the wager is refunded automatically.

Game odds (documented per command for transparency)
"""

import random

from discord import app_commands
from discord.ext import commands

from vixen.db import get_session
from vixen.services.cooldown import try_acquire
from vixen.services.economy import InsufficientFundsError, change_cash

# Slots reel composition. Five distinct symbols, equally weighted, three
# reels. Probability of three-of-a-kind = 5/125 = 4%. Anything less than
# all three matching is a loss; pair wins are not paid (deliberately
# brutal — the rare jackpot is what makes the game interesting).
_SLOT_SYMBOLS: tuple[str, ...] = ("🍒", "🍋", "🍊", "🍇", "💎")
_SLOTS_JACKPOT_MULTIPLIER = 25  # All-three-match payout (gross). 25x makes it ~even-money EV.


# Dice payout table for a 2d6 sum. The remaining 28/36 outcomes lose the
# wager — this is where the house edge lives (~28%).
_DICE_PAYOUT_BY_SUM: dict[int, int] = {
    2: 10,    # snake eyes — 1/36
    12: 10,   # boxcars    — 1/36
    7: 1,     # lucky 7 — break even (1x payout = wager returned)
}


class GamesCog(commands.Cog):
    """Casino-style mini-games. Each command wagers cash against an RNG outcome."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ---------------------------------------------------------------- #
    # /dice
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        # Discord caps slash-command descriptions at 100 characters; keep
        # this string short enough to pass that validation.
        help="Roll 2d6. Snake eyes/boxcars pay 10x, 7 returns your wager, else loses."
    )
    @app_commands.describe(wager="Cash to risk (positive integer).")
    async def dice(self, ctx: commands.Context, wager: int) -> None:
        if wager <= 0:
            await ctx.reply("Wager must be a positive integer.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "dice")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        # Roll first so the message reflects the actual outcome.
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2

        # Look up the payout multiplier (gross, including the wager). Default
        # to 0 = lose. Net delta is (multiplier - 1) * wager.
        multiplier = _DICE_PAYOUT_BY_SUM.get(total, 0)
        delta = (multiplier - 1) * wager

        try:
            async with get_session() as session:
                # Even on a loss the delta is non-zero (= -wager). On break-
                # even outcomes (7), delta is 0 — but change_cash refuses
                # zero-delta calls, so we skip the DB write entirely there.
                if delta != 0:
                    new_balance = await change_cash(
                        session, ctx.author.id, delta, reason=f"dice_{total}"
                    )
                else:
                    # No state change. Look up the user's current balance for
                    # the reply without writing anything.
                    from vixen.services.economy import get_or_create_user

                    user = await get_or_create_user(session, ctx.author.id)
                    new_balance = user.cash
        except InsufficientFundsError as e:
            await ctx.reply(
                f"You only have **{e.have:,}** cash — can't wager **{wager:,}**.",
                ephemeral=True,
            )
            return

        # Compose the outcome message.
        roll_str = f"🎲 **{d1}** + 🎲 **{d2}** = **{total}**"
        if multiplier == 10:
            outcome = f"**JACKPOT!** {roll_str}\nYou won **{(multiplier - 1) * wager:,}** cash."
        elif multiplier == 1:
            outcome = f"**LUCKY 7.** {roll_str}\nWager returned, no profit."
        else:
            outcome = f"{roll_str}\nYou lost **{wager:,}** cash."

        await ctx.reply(f"{outcome}\nBalance: **{new_balance:,}**.")

    # ---------------------------------------------------------------- #
    # /slots
    # ---------------------------------------------------------------- #

    @commands.hybrid_command(
        help="Spin 3 reels. Match all three for 25x your wager. Anything else loses."
    )
    @app_commands.describe(wager="Cash to risk (positive integer).")
    async def slots(self, ctx: commands.Context, wager: int) -> None:
        if wager <= 0:
            await ctx.reply("Wager must be a positive integer.", ephemeral=True)
            return

        remaining = await try_acquire(ctx.author.id, "slots")
        if remaining > 0:
            await ctx.reply(
                f"Slow down — try again in {remaining:.0f}s.", ephemeral=True
            )
            return

        # Spin three reels independently.
        reels: tuple[str, str, str] = (
            random.choice(_SLOT_SYMBOLS),
            random.choice(_SLOT_SYMBOLS),
            random.choice(_SLOT_SYMBOLS),
        )
        is_jackpot = reels[0] == reels[1] == reels[2]
        delta = (_SLOTS_JACKPOT_MULTIPLIER - 1) * wager if is_jackpot else -wager
        reason = "slots_jackpot" if is_jackpot else "slots_loss"

        try:
            async with get_session() as session:
                new_balance = await change_cash(
                    session, ctx.author.id, delta, reason=reason
                )
        except InsufficientFundsError as e:
            await ctx.reply(
                f"You only have **{e.have:,}** cash — can't wager **{wager:,}**.",
                ephemeral=True,
            )
            return

        line = " | ".join(reels)
        if is_jackpot:
            outcome = (
                f"🎰 **{line}** 🎰\n"
                f"**JACKPOT!** You won **{(_SLOTS_JACKPOT_MULTIPLIER - 1) * wager:,}** cash."
            )
        else:
            outcome = f"🎰 {line} 🎰\nNo match. You lost **{wager:,}** cash."

        await ctx.reply(f"{outcome}\nBalance: **{new_balance:,}**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GamesCog(bot))
