"""Tests for vixen.services.economy.

Real Postgres, real SQLAlchemy, real models. The fixtures in conftest.py
give us a session bound to a per-test rollback transaction, so the database
is always clean entering and leaving each test.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import Transaction, User
from vixen.services.economy import (
    InsufficientFunds,
    InvalidAmount,
    change_cash,
    get_or_create_user,
)


# ---------------------------------------------------------------- #
# get_or_create_user
# ---------------------------------------------------------------- #


async def test_get_or_create_user_creates_new_row(db_session: AsyncSession):
    """First contact creates a User with cash=0, bank=0."""
    user = await get_or_create_user(db_session, discord_id=42)

    assert user.discord_id == 42
    assert user.cash == 0
    assert user.bank == 0
    # Timestamps populated by the flush() inside get_or_create_user.
    assert user.created_at is not None
    assert user.updated_at is not None


async def test_get_or_create_user_is_idempotent(db_session: AsyncSession):
    """Calling twice with the same id returns the same row, no duplicate."""
    first = await get_or_create_user(db_session, discord_id=42)
    first.cash = 999  # mark it so we can identify it
    await db_session.flush()

    second = await get_or_create_user(db_session, discord_id=42)

    assert second.discord_id == 42
    assert second.cash == 999  # same row, not a fresh one

    # Confirm only one row in users for this id.
    rows = (
        await db_session.execute(select(User).where(User.discord_id == 42))
    ).scalars().all()
    assert len(rows) == 1


async def test_get_or_create_user_distinguishes_users(db_session: AsyncSession):
    """Different discord_ids get separate rows."""
    a = await get_or_create_user(db_session, discord_id=1)
    b = await get_or_create_user(db_session, discord_id=2)

    a.cash = 100
    b.cash = 200
    await db_session.flush()

    rows = (await db_session.execute(select(User).order_by(User.discord_id))).scalars().all()
    assert len(rows) == 2
    assert rows[0].discord_id == 1 and rows[0].cash == 100
    assert rows[1].discord_id == 2 and rows[1].cash == 200


# ---------------------------------------------------------------- #
# change_cash — happy paths
# ---------------------------------------------------------------- #


async def test_change_cash_credits_and_writes_audit(db_session: AsyncSession):
    """Positive delta: cash goes up, transaction row recorded with the right reason."""
    new_balance = await change_cash(db_session, 42, 100, reason="work")

    assert new_balance == 100

    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == 100

    # Exactly one transaction row, matching the call.
    txs = (await db_session.execute(select(Transaction))).scalars().all()
    assert len(txs) == 1
    assert txs[0].user_discord_id == 42
    assert txs[0].delta == 100
    assert txs[0].reason == "work"


async def test_change_cash_debits_when_balance_sufficient(db_session: AsyncSession):
    """Negative delta with enough cash: cash decreases, audit row recorded."""
    await change_cash(db_session, 42, 200, reason="work")
    new_balance = await change_cash(db_session, 42, -50, reason="shop_buy")

    assert new_balance == 150
    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == 150

    txs = (
        await db_session.execute(
            select(Transaction).order_by(Transaction.id)
        )
    ).scalars().all()
    assert [(t.delta, t.reason) for t in txs] == [(200, "work"), (-50, "shop_buy")]


async def test_change_cash_accumulates_across_calls(db_session: AsyncSession):
    """Repeated calls compose: end state matches sum of deltas."""
    deltas = [100, -25, 50, -10, 200]
    for d in deltas:
        sign = "credit" if d > 0 else "debit"
        await change_cash(db_session, 42, d, reason=sign)

    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == sum(deltas)

    txs = (await db_session.execute(select(Transaction))).scalars().all()
    # Audit log row count == number of calls.
    assert len(txs) == len(deltas)
    # Sum of deltas in audit log equals current balance — the invariant.
    assert sum(t.delta for t in txs) == user.cash


async def test_change_cash_auto_registers_unknown_user(db_session: AsyncSession):
    """Calling change_cash on a user that doesn't exist yet still works."""
    new_balance = await change_cash(db_session, 99, 50, reason="welcome_bonus")

    assert new_balance == 50
    user = await db_session.get(User, 99)
    assert user is not None
    assert user.cash == 50


# ---------------------------------------------------------------- #
# change_cash — error paths
# ---------------------------------------------------------------- #


async def test_change_cash_zero_delta_raises_invalid_amount(db_session: AsyncSession):
    """delta=0 is a bug, not a silent no-op."""
    with pytest.raises(InvalidAmount):
        await change_cash(db_session, 42, 0, reason="oops")


async def test_change_cash_overdraft_raises_insufficient_funds(db_session: AsyncSession):
    """Negative delta exceeding balance raises with `have` and `need`."""
    await change_cash(db_session, 42, 50, reason="work")  # balance: 50

    with pytest.raises(InsufficientFunds) as exc_info:
        await change_cash(db_session, 42, -100, reason="coinflip_loss")

    assert exc_info.value.have == 50
    assert exc_info.value.need == 100


async def test_change_cash_overdraft_does_not_mutate_balance(db_session: AsyncSession):
    """A failed change_cash must not have changed cash OR written an audit row."""
    await change_cash(db_session, 42, 50, reason="work")

    with pytest.raises(InsufficientFunds):
        await change_cash(db_session, 42, -100, reason="bad_bet")

    # Balance unchanged from the successful first call.
    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == 50

    # No audit row for the failed attempt — only the work credit.
    txs = (await db_session.execute(select(Transaction))).scalars().all()
    assert len(txs) == 1
    assert txs[0].reason == "work"
