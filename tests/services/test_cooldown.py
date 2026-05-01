"""Tests for vixen.services.cooldown.

Real Redis on db=1, flushed between tests by the conftest fixture. We
test the wrapper behavior, not Redis itself — but on a real client, so
the SET NX EX semantics under load are the actual ones we ship with.
"""

from __future__ import annotations

import asyncio

from vixen.services.cooldown import clear, try_acquire

# ---------------------------------------------------------------- #
# Acquire / block
# ---------------------------------------------------------------- #


async def test_first_call_acquires(redis_client):
    """A bucket that's never been used returns 0.0 — caller proceeds."""
    remaining = await try_acquire(user_id=42, bucket="work", seconds=10)
    assert remaining == 0.0


async def test_second_call_within_window_blocked(redis_client):
    """Second call inside the TTL returns positive remaining seconds."""
    await try_acquire(user_id=42, bucket="work", seconds=10)
    remaining = await try_acquire(user_id=42, bucket="work", seconds=10)
    # TTL is integer seconds in Redis. We may have ticked down by 1s
    # between SET and the second call, so accept (8, 10].
    assert 8 < remaining <= 10


async def test_third_call_still_blocked(redis_client):
    """Multiple blocked calls each see decreasing remaining time."""
    await try_acquire(user_id=42, bucket="work", seconds=10)
    first_blocked = await try_acquire(user_id=42, bucket="work", seconds=10)
    second_blocked = await try_acquire(user_id=42, bucket="work", seconds=10)
    # Both are > 0 and the second isn't greater than the first.
    assert first_blocked > 0
    assert second_blocked > 0
    assert second_blocked <= first_blocked


# ---------------------------------------------------------------- #
# Independence
# ---------------------------------------------------------------- #


async def test_different_buckets_are_independent(redis_client):
    """Locking /work doesn't lock /coinflip for the same user."""
    await try_acquire(user_id=42, bucket="work", seconds=10)
    remaining = await try_acquire(user_id=42, bucket="coinflip", seconds=10)
    assert remaining == 0.0


async def test_different_users_are_independent(redis_client):
    """One user's cooldown doesn't affect another user."""
    await try_acquire(user_id=1, bucket="work", seconds=10)
    remaining = await try_acquire(user_id=2, bucket="work", seconds=10)
    assert remaining == 0.0


# ---------------------------------------------------------------- #
# Clear / expiry
# ---------------------------------------------------------------- #


async def test_clear_releases_lock(redis_client):
    """clear() lets the next call re-acquire."""
    await try_acquire(user_id=42, bucket="work", seconds=10)
    await clear(user_id=42, bucket="work")
    remaining = await try_acquire(user_id=42, bucket="work", seconds=10)
    assert remaining == 0.0


async def test_clear_is_safe_when_no_lock(redis_client):
    """Clearing an unlocked bucket is a no-op, not an error."""
    await clear(user_id=42, bucket="work")  # nothing to clear
    remaining = await try_acquire(user_id=42, bucket="work", seconds=10)
    assert remaining == 0.0


async def test_lock_expires_naturally(redis_client):
    """After the TTL passes, the bucket is free again — verifies that we
    actually set EX (an expiry), not just NX.
    """
    await try_acquire(user_id=42, bucket="work", seconds=1)
    # Wait just past the 1s TTL. Slightly slow test (~1.1s) but proves
    # the TTL is real, which is the whole point of this service.
    await asyncio.sleep(1.2)
    remaining = await try_acquire(user_id=42, bucket="work", seconds=10)
    assert remaining == 0.0
