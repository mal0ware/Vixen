"""Redis-backed leaderboard.

The leaderboard ranks users by total wealth — `cash + bank`. We store
exactly one sorted set in Redis:

    vixen:leaderboard:wealth   ZSET of "<user_id>" -> wealth score

Sorted-set operations are O(log N) for add/rank and O(M log N) for top-M
queries. That scales fine to thousands of users; we'd swap to a periodic
materialized view only at proper-platform scale.

Sync model

`change_cash` calls `sync_user` automatically after every mutation, so the
ZSET stays current with the DB. We accept *eventual consistency* on the
edge case where a change_cash succeeds locally but the parent transaction
rolls back — the ZSET entry is now slightly wrong until the user's next
cash event refreshes it. For a leaderboard, that drift is fine; it's not
the system of record.

Soft-fail on missing Redis

If `init_redis()` hasn't been called (alembic, tests that don't care
about leaderboard, ipython sessions), `sync_user` is a no-op. This lets
us call it freely from `change_cash` without forcing every economy test
to spin up a Redis client.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import redis as get_redis
from ..models import User

# Single ZSET key. Future leaderboards (weekly winnings, fishing total,
# etc.) get their own keys with the same prefix.
_KEY = "vixen:leaderboard:wealth"


def _redis_or_none():
    """Return the live Redis client, or None when uninitialized.

    This is the soft-fail seam — production paths will always have Redis,
    tests that don't care won't, and we don't want a noisy error in either.
    """
    try:
        return get_redis()
    except RuntimeError:
        return None


# --------------------------------------------------------------------------- #
# Write hook
# --------------------------------------------------------------------------- #


async def sync_user(session: AsyncSession, user_id: int) -> None:
    """Refresh a user's leaderboard score from the DB.

    Called automatically from `change_cash`. Idempotent — calling it when
    the user's wealth hasn't actually changed just rewrites the same score
    to the ZSET. Safe to invoke as a manual "reconcile this user" hook.
    """
    redis = _redis_or_none()
    if redis is None:
        return  # Redis not initialized — soft no-op; see module docstring.

    user = await session.get(User, user_id)
    if user is None:
        return  # nothing to sync; possible if called for a phantom id

    score = float(user.cash + user.bank)
    await redis.zadd(_KEY, {str(user_id): score})


# --------------------------------------------------------------------------- #
# Read API
# --------------------------------------------------------------------------- #


async def top(n: int = 10) -> list[tuple[int, int]]:
    """Top `n` (user_id, wealth) pairs, descending. Empty list if no Redis."""
    redis = _redis_or_none()
    if redis is None:
        return []

    # ZREVRANGE: highest score first. WITHSCORES returns [(member, score), ...].
    rows = await redis.zrevrange(_KEY, 0, n - 1, withscores=True)
    return [(int(member), int(score)) for member, score in rows]


async def get_rank(user_id: int) -> tuple[int, int] | None:
    """Return (1-based rank, wealth) for a user, or None if not ranked.

    "Not ranked" means the user has never had a cash event — they're not
    in the ZSET. New accounts at $0 also won't appear until their first
    /work or seed transaction.
    """
    redis = _redis_or_none()
    if redis is None:
        return None

    rank0 = await redis.zrevrank(_KEY, str(user_id))
    if rank0 is None:
        return None

    score = await redis.zscore(_KEY, str(user_id))
    # ZSCORE returns float (or None — but rank was non-None so this won't be).
    return (rank0 + 1, int(score) if score is not None else 0)


async def total_users() -> int:
    """How many users currently appear on the leaderboard."""
    redis = _redis_or_none()
    if redis is None:
        return 0
    return await redis.zcard(_KEY)
