"""Tests for vixen.services.prefix."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import Guild
from vixen.services.prefix import (
    DEFAULT_PREFIX,
    get_prefix,
    invalidate,
    set_prefix,
)

# ---------------------------------------------------------------- #
# get_prefix
# ---------------------------------------------------------------- #


async def test_get_prefix_default_when_no_row(
    db_session: AsyncSession, redis_client
):
    """Brand-new guild → default prefix, nothing cached yet."""
    prefix = await get_prefix(db_session, 1)
    assert prefix == DEFAULT_PREFIX


async def test_get_prefix_reads_from_postgres(
    db_session: AsyncSession, redis_client
):
    """Setting up a Guild row directly is reflected in get_prefix."""
    db_session.add(Guild(discord_id=1, prefix="?"))
    await db_session.flush()

    prefix = await get_prefix(db_session, 1)
    assert prefix == "?"


async def test_get_prefix_populates_cache(
    db_session: AsyncSession, redis_client
):
    """A successful Postgres lookup fills the Redis key for next time."""
    db_session.add(Guild(discord_id=1, prefix="?"))
    await db_session.flush()

    await get_prefix(db_session, 1)

    cached = await redis_client.get("prefix:guild:1")
    assert cached == "?"


async def test_get_prefix_uses_cache(
    db_session: AsyncSession, redis_client
):
    """If Redis has the value, Postgres isn't queried.

    We assert this indirectly: there's no Guild row, but the cache has
    a value, so get_prefix should return the cached value (not the default).
    """
    await redis_client.set("prefix:guild:1", "?", ex=300)
    prefix = await get_prefix(db_session, 1)
    assert prefix == "?"


# ---------------------------------------------------------------- #
# set_prefix
# ---------------------------------------------------------------- #


async def test_set_prefix_inserts_row_and_caches(
    db_session: AsyncSession, redis_client
):
    """First /setprefix creates the Guild row + sets the cache."""
    await set_prefix(db_session, 1, ".")

    row = await db_session.get(Guild, 1)
    assert row is not None
    assert row.prefix == "."

    cached = await redis_client.get("prefix:guild:1")
    assert cached == "."


async def test_set_prefix_overwrites_existing(
    db_session: AsyncSession, redis_client
):
    """Subsequent /setprefix updates row + cache."""
    db_session.add(Guild(discord_id=1, prefix="?"))
    await db_session.flush()

    await set_prefix(db_session, 1, "!")

    row = await db_session.get(Guild, 1)
    assert row is not None
    assert row.prefix == "!"
    assert await redis_client.get("prefix:guild:1") == "!"


async def test_set_prefix_rejects_empty(db_session: AsyncSession, redis_client):
    with pytest.raises(ValueError):
        await set_prefix(db_session, 1, "")


async def test_set_prefix_rejects_too_long(
    db_session: AsyncSession, redis_client
):
    with pytest.raises(ValueError):
        await set_prefix(db_session, 1, "x" * 11)


# ---------------------------------------------------------------- #
# invalidate
# ---------------------------------------------------------------- #


async def test_invalidate_drops_cache(redis_client):
    """invalidate() removes the cached entry — next lookup will hit Postgres."""
    await redis_client.set("prefix:guild:1", "?", ex=300)
    await invalidate(1)
    assert await redis_client.get("prefix:guild:1") is None


# ---------------------------------------------------------------- #
# Soft-fail without Redis
# ---------------------------------------------------------------- #


async def test_get_prefix_works_without_redis(
    db_session: AsyncSession, monkeypatch
):
    """Tests / alembic that don't init Redis still get a working prefix lookup."""
    from vixen import cache as cache_module

    monkeypatch.setattr(cache_module, "_redis", None)

    db_session.add(Guild(discord_id=1, prefix="?"))
    await db_session.flush()

    # No Redis client, but Postgres is fine.
    prefix = await get_prefix(db_session, 1)
    assert prefix == "?"
