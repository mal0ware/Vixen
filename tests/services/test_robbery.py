"""Tests for vixen.services.robbery.

The service uses a `random.Random` instance for outcome rolls. Tests pass
a seeded RNG so the success/failure branch is deterministic. Real Postgres
+ Redis (for change_cash → leaderboard sync), per-test truncation.
"""

from __future__ import annotations

import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import User
from vixen.services.economy import change_cash
from vixen.services.robbery import (
    FAILURE_PENALTY_PCT,
    STEAL_PCT_MAX,
    STEAL_PCT_MIN,
    TargetBrokeError,
    do_rob,
)
from vixen.services.shop import add_item, has_item

# ---------------------------------------------------------------- #
# Padlock blocks robbery (and is consumed)
# ---------------------------------------------------------------- #


async def test_padlock_blocks_and_is_consumed(
    db_session: AsyncSession, redis_client
):
    """If the target owns a padlock, the rob is blocked and the padlock vanishes."""
    await change_cash(db_session, 2, 1000, reason="seed")  # target has cash
    await add_item(db_session, 2, "padlock", 1)

    result = await do_rob(db_session, thief_id=1, target_id=2)

    assert result.outcome == "blocked"
    assert result.cash_moved == 0
    # Padlock consumed.
    assert not await has_item(db_session, 2, "padlock")


async def test_padlock_check_runs_before_target_balance(
    db_session: AsyncSession, redis_client
):
    """Edge case: target has padlock AND zero cash → TargetBrokeError wins.

    We reject the rob before consuming the padlock — otherwise a target
    could lose a 2,500-cash padlock blocking a 0-cash rob.
    """
    await add_item(db_session, 2, "padlock", 1)

    with pytest.raises(TargetBrokeError):
        await do_rob(db_session, thief_id=1, target_id=2)

    # Padlock NOT consumed — TargetBrokeError fired first.
    assert await has_item(db_session, 2, "padlock")


# ---------------------------------------------------------------- #
# Success path
# ---------------------------------------------------------------- #


async def test_successful_rob_transfers_cash(db_session: AsyncSession, redis_client):
    """Successful rob moves a fraction of target's cash to thief."""
    await change_cash(db_session, 1, 100, reason="seed")  # thief
    await change_cash(db_session, 2, 1000, reason="seed")  # target

    # Force success: rng.random() must be < SUCCESS_RATE (0.5).
    # random.Random(1).random() ≈ 0.134, so this seeds a success.
    result = await do_rob(
        db_session, thief_id=1, target_id=2, rng=random.Random(1)
    )

    assert result.outcome == "succeeded"
    # Stolen amount is between 10% and 25% of target's pre-rob cash.
    assert int(1000 * STEAL_PCT_MIN) <= result.cash_moved <= int(1000 * STEAL_PCT_MAX)

    # Cash actually moved.
    thief = await db_session.get(User, 1)
    target = await db_session.get(User, 2)
    assert thief is not None
    assert target is not None
    assert thief.cash == 100 + result.cash_moved
    assert target.cash == 1000 - result.cash_moved


# ---------------------------------------------------------------- #
# Failure path
# ---------------------------------------------------------------- #


async def test_failed_rob_costs_thief_penalty(
    db_session: AsyncSession, redis_client
):
    """Failed rob: thief pays 10% of their own cash, target untouched."""
    await change_cash(db_session, 1, 1000, reason="seed")  # thief
    await change_cash(db_session, 2, 500, reason="seed")  # target

    # Force failure: rng.random() must be >= 0.5.
    # random.Random(2).random() ≈ 0.956, so failure.
    result = await do_rob(
        db_session, thief_id=1, target_id=2, rng=random.Random(2)
    )

    assert result.outcome == "failed"
    expected_penalty = int(1000 * FAILURE_PENALTY_PCT)
    assert result.cash_moved == expected_penalty

    thief = await db_session.get(User, 1)
    target = await db_session.get(User, 2)
    assert thief is not None and target is not None
    assert thief.cash == 1000 - expected_penalty
    assert target.cash == 500  # untouched


async def test_failed_rob_with_no_thief_cash_is_zero_penalty(
    db_session: AsyncSession, redis_client
):
    """A broke thief who fails owes nothing — no transaction written."""
    await change_cash(db_session, 2, 500, reason="seed")  # target has cash

    # Thief has 0 cash. Force failure.
    result = await do_rob(
        db_session, thief_id=1, target_id=2, rng=random.Random(2)
    )

    assert result.outcome == "failed"
    assert result.cash_moved == 0
    assert result.thief_balance == 0


# ---------------------------------------------------------------- #
# TargetBrokeError
# ---------------------------------------------------------------- #


async def test_target_with_no_cash_raises(db_session: AsyncSession, redis_client):
    """Can't rob a target who has zero cash."""
    await change_cash(db_session, 1, 1000, reason="seed")  # thief has cash
    # target user 2 doesn't exist yet; do_rob auto-creates with cash=0

    with pytest.raises(TargetBrokeError):
        await do_rob(db_session, thief_id=1, target_id=2)
