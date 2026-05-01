"""Tests for vixen.services.leaderboard.

These tests use BOTH the per-test Postgres `db_session` and the per-test
Redis `redis_client` fixtures — leaderboard reads come from Redis, but
sync_user reads from the DB to compute the score, so we need both stores
clean and isolated.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import User
from vixen.services import leaderboard
from vixen.services.economy import change_cash

# ---------------------------------------------------------------- #
# sync_user — explicit calls
# ---------------------------------------------------------------- #


async def test_sync_user_writes_score(db_session: AsyncSession, redis_client):
    """sync_user pulls cash + bank from the DB and ZADDs the total."""
    user = User(discord_id=42, cash=500, bank=200)
    db_session.add(user)
    await db_session.flush()

    await leaderboard.sync_user(db_session, 42)

    score = await redis_client.zscore("vixen:leaderboard:wealth", "42")
    assert score == 700.0


async def test_sync_user_unknown_user_is_noop(
    db_session: AsyncSession, redis_client
):
    """Calling sync_user for a user that doesn't exist must not crash or zadd."""
    await leaderboard.sync_user(db_session, 9999)
    # ZSET is empty.
    assert await redis_client.zcard("vixen:leaderboard:wealth") == 0


async def test_sync_user_overwrites_score(
    db_session: AsyncSession, redis_client
):
    """A second sync after a wealth change replaces the first score."""
    user = User(discord_id=42, cash=100, bank=0)
    db_session.add(user)
    await db_session.flush()
    await leaderboard.sync_user(db_session, 42)

    user.cash = 250
    await db_session.flush()
    await leaderboard.sync_user(db_session, 42)

    score = await redis_client.zscore("vixen:leaderboard:wealth", "42")
    assert score == 250.0


# ---------------------------------------------------------------- #
# Auto-sync via change_cash
# ---------------------------------------------------------------- #


async def test_change_cash_auto_syncs_leaderboard(
    db_session: AsyncSession, redis_client
):
    """Every change_cash call should leave the ZSET in step with the DB."""
    await change_cash(db_session, 42, 100, reason="test")
    score = await redis_client.zscore("vixen:leaderboard:wealth", "42")
    assert score == 100.0

    await change_cash(db_session, 42, 50, reason="test")
    score = await redis_client.zscore("vixen:leaderboard:wealth", "42")
    assert score == 150.0


# ---------------------------------------------------------------- #
# top()
# ---------------------------------------------------------------- #


async def test_top_orders_by_wealth_descending(
    db_session: AsyncSession, redis_client
):
    """top() returns highest-wealth users first."""
    await change_cash(db_session, 1, 100, reason="seed")
    await change_cash(db_session, 2, 500, reason="seed")
    await change_cash(db_session, 3, 250, reason="seed")

    rows = await leaderboard.top(10)
    assert rows == [(2, 500), (3, 250), (1, 100)]


async def test_top_n_limits_results(db_session: AsyncSession, redis_client):
    """top(n) returns at most n rows."""
    for i in range(1, 6):
        await change_cash(db_session, i, i * 100, reason="seed")

    rows = await leaderboard.top(3)
    assert len(rows) == 3
    assert rows == [(5, 500), (4, 400), (3, 300)]


async def test_top_empty_returns_empty(redis_client):
    """No users seeded → empty list, no errors."""
    rows = await leaderboard.top(10)
    assert rows == []


# ---------------------------------------------------------------- #
# get_rank()
# ---------------------------------------------------------------- #


async def test_get_rank_first_place(db_session: AsyncSession, redis_client):
    """The user with the most wealth ranks #1."""
    await change_cash(db_session, 1, 100, reason="seed")
    await change_cash(db_session, 2, 500, reason="seed")

    result = await leaderboard.get_rank(2)
    assert result == (1, 500)


async def test_get_rank_unknown_user(db_session: AsyncSession, redis_client):
    """A user who's never had a cash event isn't on the board."""
    await change_cash(db_session, 1, 100, reason="seed")

    result = await leaderboard.get_rank(9999)
    assert result is None


async def test_get_rank_last_place(db_session: AsyncSession, redis_client):
    """Lowest scorer is at the bottom rank."""
    await change_cash(db_session, 1, 100, reason="seed")
    await change_cash(db_session, 2, 500, reason="seed")
    await change_cash(db_session, 3, 250, reason="seed")

    result = await leaderboard.get_rank(1)
    assert result == (3, 100)


# ---------------------------------------------------------------- #
# Soft-fail: no Redis
# ---------------------------------------------------------------- #


async def test_sync_user_no_op_when_redis_missing(
    db_session: AsyncSession, monkeypatch
):
    """Without an initialized Redis client, sync_user is a quiet no-op.

    This is the seam that lets `change_cash` be called from alembic /
    test setups that don't bring Redis up.
    """
    from vixen import cache as cache_module

    monkeypatch.setattr(cache_module, "_redis", None)

    user = User(discord_id=42, cash=500, bank=0)
    db_session.add(user)
    await db_session.flush()

    # Must not raise even though Redis is unset.
    await leaderboard.sync_user(db_session, 42)
