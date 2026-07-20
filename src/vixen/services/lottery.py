"""Lottery service.

Lifecycle of a draw

    /lottery enter N   user spends N lottery_tickets, adds N entries
    /lottery pool      anyone can read total entries + pot value
    /lottery draw      admin picks a weighted random winner; pot pays out;
                       all entries cleared

The pot is computed as `total_entries * ticket_price`. The catalog price
of `lottery_ticket` is the source of truth; if you change it, future
draws will be larger or smaller. Past draws aren't retconned (we read the
price at draw time).

Atomicity

`enter` and `draw` are both single-transaction operations from the cog's
perspective. `enter` decrements inventory and writes the LotteryEntry row
in one session — if the row write fails, the ticket isn't burned. `draw`
selects the winner, credits the pot, and truncates the table — if the
credit fails, no entries are cleared, so we don't lose state.
"""

from __future__ import annotations

import random

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import LotteryEntry
from .economy import EconomyError, change_cash
from .items import ITEMS
from .shop import remove_item

# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class NoEntriesError(EconomyError):
    """/lottery draw called with zero entries — nothing to draw against."""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def enter(
    session: AsyncSession,
    user_id: int,
    count: int,
) -> int:
    """Stake `count` lottery_tickets into the current draw.

    Returns the user's NEW total ticket count for this lottery (not their
    inventory).

    Raises:
        InvalidAmountError: count <= 0.
        InsufficientItemsError: user owns fewer than `count` lottery_tickets.
    """
    if count <= 0:
        from .economy import InvalidAmountError
        raise InvalidAmountError(f"count must be positive, got {count}")

    # Burn the tickets from inventory first. If they don't have them,
    # InsufficientItemsError propagates and we never touch lottery state.
    await remove_item(session, user_id, "lottery_ticket", qty=count)

    # UPSERT the LotteryEntry row — the model's PK is user_discord_id, so
    # at most one row exists per user per draw.
    existing = await session.get(LotteryEntry, user_id)
    if existing is None:
        existing = LotteryEntry(user_discord_id=user_id, tickets=count)
        session.add(existing)
    else:
        existing.tickets += count

    await session.flush()
    return existing.tickets


async def pool(session: AsyncSession) -> tuple[int, int]:
    """Return (total_entries, pot_in_cash) for the current draw.

    Pot = total_entries * lottery_ticket.price.
    """
    total = await session.scalar(select(func.coalesce(func.sum(LotteryEntry.tickets), 0)))
    total_entries = int(total or 0)
    pot = total_entries * ITEMS["lottery_ticket"].price
    return total_entries, pot


async def draw(
    session: AsyncSession,
    *,
    rng: random.Random | None = None,
) -> tuple[int, int, int]:
    """Pick a winner weighted by entries, credit them the pot, clear entries.

    Returns (winner_id, pot_won, total_entries_in_draw).

    Raises:
        NoEntriesError: nobody has staked anything yet.
    """
    rng = rng or random

    rows = (
        await session.execute(
            select(LotteryEntry.user_discord_id, LotteryEntry.tickets)
        )
    ).all()
    if not rows:
        raise NoEntriesError("nobody is in the current draw")

    user_ids = [r[0] for r in rows]
    weights = [r[1] for r in rows]
    total_entries = sum(weights)
    pot = total_entries * ITEMS["lottery_ticket"].price

    winner_id: int = rng.choices(user_ids, weights=weights, k=1)[0]

    # Credit the winner first. If this raises, we abort before clearing
    # entries — losing the pot would be worse than re-running /draw.
    await change_cash(session, winner_id, pot, reason="lottery_win")

    # Clear all entries so the next draw starts fresh.
    await session.execute(delete(LotteryEntry))
    await session.flush()

    return winner_id, pot, total_entries
