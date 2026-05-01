"""Redis-backed escalating cooldown service.

The model: every (user, bucket) pair has a "burst counter". Each successful
attempt increments it, and the cooldown applied to gate the next attempt
grows with the count:

    Attempt #   Cooldown applied (gates the next attempt)
    1           1 s
    2           3 s
    3 +         5 s   (plateau — never grows past this)

The counter expires after 30 s of idle. Anyone going quiet for half a
minute starts fresh on attempt #1 with no penalty.

Why escalate at all:

- A real human firing /work every minute (or even every 10 s) never sees
  more than a 1 s cooldown — feels free, no friction.
- A script hammering as fast as possible gets clamped to 5 s gaps within
  three attempts. Sustained spam is throttled, but the door isn't slammed
  shut — just narrowed enough to make automated farming uneconomical.

Why Redis: same reasons as a flat cooldown — survives bot restarts, single
shared store, atomic SET/INCR/EXPIRE primitives. The bucket name is the
caller's responsibility (typically the command name).

Key shape — two keys per (user, bucket):

    cd:user:<discord_id>:<bucket>:lock    short TTL = remaining cooldown
    cd:user:<discord_id>:<bucket>:count   30s TTL = the burst counter

Two keys instead of one because their TTLs serve different purposes: the
lock TTL tells the user how long to wait, the count TTL is the idle reset.
"""

from __future__ import annotations

from ..cache import redis as get_redis

_KEY_PREFIX = "cd"

# Sliding window for the burst counter. After this many seconds of idle,
# the next attempt starts the curve over from #1.
_RESET_WINDOW_SECONDS = 30


def _curve(attempt: int) -> int:
    """Cooldown duration applied AFTER the Nth successful attempt (gates N+1)."""
    if attempt <= 1:
        return 1
    if attempt == 2:
        return 3
    return 5


def _lock_key(user_id: int, bucket: str) -> str:
    return f"{_KEY_PREFIX}:user:{user_id}:{bucket}:lock"


def _count_key(user_id: int, bucket: str) -> str:
    return f"{_KEY_PREFIX}:user:{user_id}:{bucket}:count"


async def try_acquire(user_id: int, bucket: str) -> float:
    """Try to claim the bucket. Returns 0.0 on acquire, remaining seconds on block.

    Side effects on acquire:
    - Increments the burst counter (or creates it at 1 on first contact).
    - Resets the counter's TTL to 30 s (any successful attempt extends the
      idle window).
    - Sets a fresh lock with the curve duration for the next attempt.
    """
    client = get_redis()
    lock_key = _lock_key(user_id, bucket)
    count_key = _count_key(user_id, bucket)

    # Currently locked? TTL > 0 means an active lock; tell the caller how
    # much longer to wait.
    ttl = await client.ttl(lock_key)
    if ttl > 0:
        return float(ttl)

    # Not locked. INCR the burst counter — atomic, creates at 1 on first
    # call, returns the new value.
    attempt = await client.incr(count_key)

    # Refresh the counter's TTL so the burst keeps "alive" as long as the
    # user keeps attempting within the window. This is the sliding part of
    # the sliding window.
    await client.expire(count_key, _RESET_WINDOW_SECONDS)

    # Set the lock that gates the NEXT attempt. Curve plateaus at 5 s.
    duration = _curve(attempt)
    await client.set(lock_key, "1", ex=duration)

    return 0.0


async def clear(user_id: int, bucket: str) -> None:
    """Drop both lock and counter for a (user, bucket). Tests + admin reset."""
    client = get_redis()
    await client.delete(
        _lock_key(user_id, bucket), _count_key(user_id, bucket)
    )
