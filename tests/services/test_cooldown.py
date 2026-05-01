"""Tests for vixen.services.cooldown.

Real Redis on db=1, flushed between tests by the conftest fixture.

The escalating curve is exercised by clearing the lock key between
attempts (simulating "time passed"), so the curve test doesn't need to
sleep through 1+3+5 seconds. One slow test still asserts that the lock
TTL is real — it's the whole point of the service.
"""

from __future__ import annotations

import asyncio

from vixen.services.cooldown import _RESET_WINDOW_SECONDS, clear, try_acquire


def _lock_key(user_id: int, bucket: str) -> str:
    return f"cd:user:{user_id}:{bucket}:lock"


def _count_key(user_id: int, bucket: str) -> str:
    return f"cd:user:{user_id}:{bucket}:count"


# ---------------------------------------------------------------- #
# Curve: 1s → 3s → 5s plateau
# ---------------------------------------------------------------- #


async def test_first_attempt_is_free_and_sets_1s_lock(redis_client):
    """Attempt #1 returns 0.0 and arms a 1s lock for attempt #2."""
    remaining = await try_acquire(user_id=42, bucket="work")
    assert remaining == 0.0

    ttl = await redis_client.ttl(_lock_key(42, "work"))
    assert ttl == 1


async def test_curve_advances_through_attempts(redis_client):
    """Attempt 1 → 1s lock; #2 → 3s; #3 → 5s; #4+ → 5s plateau.

    We clear the lock key between attempts to simulate the wait without
    actually sleeping. The counter persists, so each attempt sees the
    correct burst position.
    """
    durations: list[int] = []
    for _ in range(5):
        await try_acquire(user_id=42, bucket="work")
        durations.append(await redis_client.ttl(_lock_key(42, "work")))
        await redis_client.delete(_lock_key(42, "work"))

    assert durations == [1, 3, 5, 5, 5]


async def test_blocked_call_returns_remaining(redis_client):
    """A second attempt while the lock is live returns positive remaining."""
    await try_acquire(user_id=42, bucket="work")  # arms 1s lock
    remaining = await try_acquire(user_id=42, bucket="work")
    # TTL is integer seconds; could be 1 (just set) or 0.x rounded up to 1.
    assert 0 < remaining <= 1


async def test_blocked_call_does_not_advance_counter(redis_client):
    """Spamming while blocked must not escalate the curve.

    Otherwise a script could spam through the 1s lock and immediately be
    on attempt #4 (5s plateau) — that's fine for them, but it means a
    real user accidentally double-clicking gets escalated unfairly.
    """
    await try_acquire(user_id=42, bucket="work")  # attempt #1, count=1
    await try_acquire(user_id=42, bucket="work")  # blocked, count must stay 1
    await try_acquire(user_id=42, bucket="work")  # blocked, count must stay 1

    count = await redis_client.get(_count_key(42, "work"))
    assert count == "1"


# ---------------------------------------------------------------- #
# Independence
# ---------------------------------------------------------------- #


async def test_different_buckets_are_independent(redis_client):
    """/work cooldown doesn't lock /coinflip for the same user."""
    await try_acquire(user_id=42, bucket="work")
    remaining = await try_acquire(user_id=42, bucket="coinflip")
    assert remaining == 0.0


async def test_different_users_are_independent(redis_client):
    """One user's burst doesn't affect another's curve position."""
    await try_acquire(user_id=1, bucket="work")
    await try_acquire(user_id=1, bucket="work")  # blocked
    # Drain user 1's lock so we can test that user 2 starts fresh.
    await redis_client.delete(_lock_key(1, "work"))
    await try_acquire(user_id=1, bucket="work")  # attempt #2 for user 1, sets 3s

    # User 2's first attempt should still be a fresh attempt #1 → 1s lock.
    await try_acquire(user_id=2, bucket="work")
    ttl = await redis_client.ttl(_lock_key(2, "work"))
    assert ttl == 1


# ---------------------------------------------------------------- #
# Reset window
# ---------------------------------------------------------------- #


async def test_count_key_has_reset_window_ttl(redis_client):
    """The counter's TTL is the idle-reset window."""
    await try_acquire(user_id=42, bucket="work")
    ttl = await redis_client.ttl(_count_key(42, "work"))
    # Should be at the configured value, possibly 1s less if the test
    # crossed a second boundary between SET and TTL.
    assert ttl in (_RESET_WINDOW_SECONDS - 1, _RESET_WINDOW_SECONDS)


async def test_idle_resets_curve(redis_client):
    """If the count_key expires, the next attempt is treated as #1 again."""
    await try_acquire(user_id=42, bucket="work")  # attempt #1
    await redis_client.delete(_lock_key(42, "work"))
    await try_acquire(user_id=42, bucket="work")  # attempt #2 → 3s
    assert await redis_client.ttl(_lock_key(42, "work")) == 3

    # Simulate a 30+ second idle window: nuke both keys.
    await clear(user_id=42, bucket="work")

    # Next attempt should be a fresh attempt #1 → 1s lock.
    await try_acquire(user_id=42, bucket="work")
    assert await redis_client.ttl(_lock_key(42, "work")) == 1


# ---------------------------------------------------------------- #
# Clear
# ---------------------------------------------------------------- #


async def test_clear_releases_both_keys(redis_client):
    """clear() drops both the lock and the counter."""
    await try_acquire(user_id=42, bucket="work")
    assert await redis_client.exists(_lock_key(42, "work")) == 1
    assert await redis_client.exists(_count_key(42, "work")) == 1

    await clear(user_id=42, bucket="work")

    assert await redis_client.exists(_lock_key(42, "work")) == 0
    assert await redis_client.exists(_count_key(42, "work")) == 0


async def test_clear_is_safe_when_unset(redis_client):
    """Clearing an unused bucket is a no-op, not an error."""
    await clear(user_id=42, bucket="work")
    remaining = await try_acquire(user_id=42, bucket="work")
    assert remaining == 0.0


# ---------------------------------------------------------------- #
# Real-time expiry — sanity check that the TTL is actually enforced
# ---------------------------------------------------------------- #


async def test_lock_expires_naturally(redis_client):
    """After the 1s lock expires, the next attempt is free again.

    Slow (~1.2s) but proves the EX argument actually does what we think.
    """
    await try_acquire(user_id=42, bucket="work")  # arms 1s lock
    await asyncio.sleep(1.2)
    remaining = await try_acquire(user_id=42, bucket="work")
    assert remaining == 0.0
