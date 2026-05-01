"""Tests for vixen.services.lottery."""

from __future__ import annotations

import random

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import LotteryEntry, User
from vixen.services.economy import InvalidAmount
from vixen.services.items import ITEMS
from vixen.services.lottery import NoEntries, draw, enter, pool
from vixen.services.shop import InsufficientItems, add_item

_TICKET_PRICE = ITEMS["lottery_ticket"].price


# ---------------------------------------------------------------- #
# enter
# ---------------------------------------------------------------- #


async def test_enter_consumes_tickets_and_creates_row(db_session: AsyncSession):
    await add_item(db_session, 42, "lottery_ticket", 5)
    new_total = await enter(db_session, 42, 3)

    assert new_total == 3

    row = await db_session.get(LotteryEntry, 42)
    assert row is not None
    assert row.tickets == 3


async def test_enter_accumulates_for_same_user(db_session: AsyncSession):
    """Multiple /enter calls for the same user UPSERT into one row."""
    await add_item(db_session, 42, "lottery_ticket", 10)
    await enter(db_session, 42, 3)
    new_total = await enter(db_session, 42, 4)

    assert new_total == 7

    rows = (await db_session.execute(select(LotteryEntry))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tickets == 7


async def test_enter_without_tickets_raises(db_session: AsyncSession):
    """No lottery_tickets in inventory → InsufficientItems, no row written."""
    with pytest.raises(InsufficientItems):
        await enter(db_session, 42, 1)

    rows = (await db_session.execute(select(LotteryEntry))).scalars().all()
    assert rows == []


async def test_enter_zero_or_negative_raises(db_session: AsyncSession):
    with pytest.raises(InvalidAmount):
        await enter(db_session, 42, 0)
    with pytest.raises(InvalidAmount):
        await enter(db_session, 42, -1)


# ---------------------------------------------------------------- #
# pool
# ---------------------------------------------------------------- #


async def test_pool_empty(db_session: AsyncSession):
    entries, pot = await pool(db_session)
    assert entries == 0
    assert pot == 0


async def test_pool_sums_across_users(db_session: AsyncSession):
    """Pot reflects entries from every user."""
    await add_item(db_session, 1, "lottery_ticket", 2)
    await add_item(db_session, 2, "lottery_ticket", 3)
    await enter(db_session, 1, 2)
    await enter(db_session, 2, 3)

    entries, pot = await pool(db_session)
    assert entries == 5
    assert pot == 5 * _TICKET_PRICE


# ---------------------------------------------------------------- #
# draw
# ---------------------------------------------------------------- #


async def test_draw_pays_winner_and_clears_entries(db_session: AsyncSession):
    """Winner gets the pot; LotteryEntry table is wiped clean."""
    await add_item(db_session, 1, "lottery_ticket", 5)
    await enter(db_session, 1, 5)

    winner_id, pot_won, total_entries = await draw(
        db_session, rng=random.Random(0)
    )

    assert winner_id == 1
    assert total_entries == 5
    assert pot_won == 5 * _TICKET_PRICE

    user = await db_session.get(User, 1)
    assert user is not None
    assert user.cash == pot_won

    # Table is empty now.
    rows = (await db_session.execute(select(LotteryEntry))).scalars().all()
    assert rows == []


async def test_draw_weighted_by_entries(db_session: AsyncSession):
    """Across many seeded draws, a heavier-staked user wins more often.

    Set up: user 1 has 1 ticket, user 2 has 9. Probability user 2 wins
    is 90%. With 200 draws, observed share should be in [80%, 95%].
    """
    wins_by_user: dict[int, int] = {1: 0, 2: 0}
    n = 200
    rng = random.Random(0)

    # Ensure both users exist once — FK targets must outlive every
    # iteration. Inside the loop we only re-seed entries.
    for uid in (1, 2):
        if await db_session.get(User, uid) is None:
            db_session.add(User(discord_id=uid, cash=0, bank=0))
    await db_session.flush()

    for _ in range(n):
        # Re-seed entries for each draw (since draw clears them).
        # User 1 has 1 ticket weight, user 2 has 9.
        db_session.add_all(
            [
                LotteryEntry(user_discord_id=1, tickets=1),
                LotteryEntry(user_discord_id=2, tickets=9),
            ]
        )
        await db_session.flush()

        winner_id, _, _ = await draw(db_session, rng=rng)
        wins_by_user[winner_id] += 1

    user2_share = wins_by_user[2] / n
    assert 0.80 < user2_share < 0.95, (
        f"Expected user 2 to win ~90%, got {user2_share:.0%}"
    )


async def test_draw_with_no_entries_raises(db_session: AsyncSession):
    with pytest.raises(NoEntries):
        await draw(db_session)
