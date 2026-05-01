"""Redis-backed cooldown service.

Why Redis instead of discord.py's `@commands.cooldown`:

- Discord.py's cooldowns live in process memory. Restart the bot and every
  user's cooldown clears — they can hammer `/work`, get rate-limited, wait
  for the bot to reload, and the cooldown is gone. Trivially gameable.
- Redis gives us a single shared store with per-key TTL. `SET NX EX` is
  atomic in one round-trip — no race between check and set.
- Mini-games and leaderboards will use the same primitive, so this is the
  shared foundation rather than a feature-specific shim.

Key shape:
    cd:user:<discord_id>:<bucket>

Bucketing is per-user-per-command, not per-guild — a user hammering /work
shouldn't be able to bypass by switching guilds. The bucket name is the
caller's responsibility (typically the command name, e.g. "work",
"coinflip", "shop_buy").

Cooldown durations live in the cog, not here. This module is the mechanism;
deciding how long /work locks for is a gameplay decision and belongs next
to the command.
"""

from __future__ import annotations

from ..cache import redis as get_redis

_KEY_PREFIX = "cd"


def _key(user_id: int, bucket: str) -> str:
    return f"{_KEY_PREFIX}:user:{user_id}:{bucket}"


async def try_acquire(user_id: int, bucket: str, seconds: int) -> float:
    """Try to claim a cooldown lock for `seconds`.

    Returns 0.0 when acquired — the key is now set with TTL `seconds`,
    and the caller is free to proceed. Subsequent calls within the window
    will see a non-zero remaining time.

    Returns the remaining cooldown in seconds (>0) when the bucket is
    already locked. The caller should reply with a friendly message and
    return without doing the work.

    Atomicity: uses Redis `SET NX EX` so the check-and-set is one round
    trip. No race window between "is this on cooldown?" and "now claim it".
    """
    client = get_redis()
    key = _key(user_id, bucket)

    # Returns truthy on acquire, None when the key already exists.
    # Value is irrelevant — we only care about presence and TTL.
    acquired = await client.set(key, "1", nx=True, ex=seconds)
    if acquired:
        return 0.0

    # Already locked. Read TTL to tell the user how long to wait.
    ttl = await client.ttl(key)
    # ttl == -2: key doesn't exist (expired between SET and TTL — race).
    # ttl == -1: key exists but has no expiry (shouldn't happen with our SET).
    # In either edge case treat as "free" so we don't lie to the user.
    return float(max(ttl, 0))


async def clear(user_id: int, bucket: str) -> None:
    """Manually drop a cooldown bucket. For tests and admin reset."""
    client = get_redis()
    await client.delete(_key(user_id, bucket))
