"""Per-guild prefix lookup with Redis caching.

The legacy `prefixes.json` file is read at startup; this service replaces
it with a Postgres-backed Guild row + Redis cache. Hot-path semantics:

- Cache layer: `prefix:guild:<id>` -> string with 5-minute TTL.
- Cache miss: read the Guild row, populate cache, return.
- Guild row missing: return the default ("!") and DON'T cache the negative
  — we'd rather pay one DB hit per message until the row is created than
  pollute the cache with stale defaults.

Why cache at all: prefix lookup runs on EVERY message in EVERY channel
the bot can see. A 50µs Redis hit is dramatically cheaper than a 1ms
Postgres query at human-Discord scale, and lookups dominate writes
(prefixes change very rarely).

Invalidation: `set_prefix` writes through both stores in order — Postgres
first (durable), Redis second (overwrites the cached value). If the Redis
write fails, the cache will catch up on its own when the TTL expires.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..cache import redis as get_redis
from ..models import Guild

DEFAULT_PREFIX = "!"
_CACHE_TTL_SECONDS = 300


def _cache_key(guild_id: int) -> str:
    return f"prefix:guild:{guild_id}"


def _redis_or_none():
    """Return the Redis client or None when uninitialized.

    Tests and alembic don't init Redis. Soft-fail mirrors leaderboard.py.
    """
    try:
        return get_redis()
    except RuntimeError:
        return None


# --------------------------------------------------------------------------- #
# Read path
# --------------------------------------------------------------------------- #


async def get_prefix(session: AsyncSession, guild_id: int) -> str:
    """Return the guild's prefix. Reads Redis first, falls through to Postgres."""
    redis = _redis_or_none()

    if redis is not None:
        cached = await redis.get(_cache_key(guild_id))
        if cached is not None:
            return cached

    # Cache miss (or no Redis). Hit Postgres.
    row = await session.get(Guild, guild_id)
    prefix = row.prefix if row is not None else DEFAULT_PREFIX

    # Populate cache only when the row actually existed; the default is
    # cheap to compute and we don't want to remember "this guild has no
    # row" — that lets a fresh /setprefix flow pick up immediately.
    if redis is not None and row is not None:
        await redis.set(_cache_key(guild_id), prefix, ex=_CACHE_TTL_SECONDS)

    return prefix


# --------------------------------------------------------------------------- #
# Write path
# --------------------------------------------------------------------------- #


async def set_prefix(
    session: AsyncSession, guild_id: int, prefix: str
) -> None:
    """Upsert the guild's prefix and write through to the cache.

    Raises:
        ValueError: prefix is empty or longer than the column allows (10 chars).
    """
    if not prefix or len(prefix) > 10:
        raise ValueError("prefix must be 1..10 characters")

    row = await session.get(Guild, guild_id)
    if row is None:
        row = Guild(discord_id=guild_id, prefix=prefix)
        session.add(row)
    else:
        row.prefix = prefix
    await session.flush()

    redis = _redis_or_none()
    if redis is not None:
        # Overwrite (or set) the cache value so subsequent messages see the
        # new prefix immediately. TTL refreshes too.
        await redis.set(_cache_key(guild_id), prefix, ex=_CACHE_TTL_SECONDS)


async def invalidate(guild_id: int) -> None:
    """Drop the cached prefix for a guild. Used by tests + admin reset."""
    redis = _redis_or_none()
    if redis is not None:
        await redis.delete(_cache_key(guild_id))
