"""Redis async client.

Three things Redis does for us that Postgres should not:

1. Cooldowns / rate limits — `SET user:42:cmd:work EX 15 NX` returns OK only
   if the key didn't exist; failure means "still on cooldown". O(1), no
   transaction overhead.

2. Leaderboards — sorted sets. `ZADD vixen:leaderboard 1234 user:42` and
   `ZREVRANGE vixen:leaderboard 0 9 WITHSCORES` for the top 10. Rank lookup
   in O(log N), not O(N) like a SQL ORDER BY + window function.

3. Per-guild prefix cache — the prefix lookup runs on every message in
   every guild we're in. Reading from Postgres each time is wasteful;
   caching in Redis with a TTL drops it to ~50µs per call.
"""

import redis.asyncio as redis_async

from .config import get_settings

_redis: redis_async.Redis | None = None


def init_redis() -> None:
    """Open a connection pool to Redis. Call once at startup."""
    global _redis
    settings = get_settings()
    _redis = redis_async.from_url(
        settings.redis_url,
        decode_responses=True,  # bytes -> str at the boundary
        max_connections=20,
    )


async def dispose_redis() -> None:
    """Close the pool on shutdown."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
    _redis = None


def redis() -> redis_async.Redis:
    """Get the live Redis client. Raises if init_redis() wasn't called."""
    if _redis is None:
        raise RuntimeError("init_redis() was not called before redis()")
    return _redis
