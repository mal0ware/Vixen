"""Shared pytest fixtures.

Strategy:

1. **Separate test database** (`vixen_test`) on the same Postgres container.
   We never touch `vixen` (the dev DB with your real data). Created fresh
   at session start, dropped at session end.

2. **Function-scoped engine, NullPool.** asyncpg connections are bound to
   the event loop they were created on. pytest-asyncio gives each async
   test its own event loop, so an engine created in a session-scoped
   fixture would hand out connections born on the wrong loop. We set up
   the schema once (session scope), then create + dispose an engine per
   test (function scope) using NullPool to avoid pooling overhead.

3. **TRUNCATE between tests** (CASCADE for foreign keys, RESTART IDENTITY
   for sequences). Each test starts on an empty database.

4. **Real Postgres, not SQLite.** Our schema uses `BigInteger`, `ondelete=
   CASCADE`, indexes — semantics SQLite either fakes or breaks.

Run tests:

    pytest                    # all tests
    pytest tests/services     # one path
    pytest -v -k coinflip     # one keyword
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
import redis.asyncio as redis_async
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from vixen import cache as cache_module
from vixen.models import Base

# --- Connection URLs ---
_BOOTSTRAP_URL = os.environ.get(
    "TEST_BOOTSTRAP_URL",
    "postgresql+asyncpg://vixen:vixen@localhost:5433/vixen",
)
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://vixen:vixen@localhost:5433/vixen_test",
)

# Redis test DB. Defaults to db=1 so we never collide with the bot's db=0.
# Override with TEST_REDIS_URL if your dev Redis already uses db=1 for
# something else.
TEST_REDIS_URL = os.environ.get(
    "TEST_REDIS_URL",
    "redis://localhost:6380/1",
)


async def _recreate_test_db() -> None:
    """DROP + CREATE the test DB. AUTOCOMMIT because CREATE/DROP DATABASE
    can't run inside a transaction in Postgres.
    """
    engine = create_async_engine(_BOOTSTRAP_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            # Boot any leftover connections to the test DB so DROP succeeds.
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = 'vixen_test' AND pid <> pg_backend_pid()"
                )
            )
            await conn.execute(text("DROP DATABASE IF EXISTS vixen_test"))
            await conn.execute(text("CREATE DATABASE vixen_test"))
    finally:
        await engine.dispose()


async def _drop_test_db() -> None:
    engine = create_async_engine(_BOOTSTRAP_URL, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = 'vixen_test' AND pid <> pg_backend_pid()"
                )
            )
            await conn.execute(text("DROP DATABASE IF EXISTS vixen_test"))
    finally:
        await engine.dispose()


# --- Fixtures ---


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _test_db_url() -> AsyncIterator[str]:
    """Session-scoped: spin up `vixen_test`, install schema, yield the URL.

    Returning a string (not an engine) keeps this fixture's event loop
    private. Per-test fixtures create their own engine on their own loop.
    """
    await _recreate_test_db()

    # Create the schema once for the whole test session. The engine is
    # created and disposed inside this function — it never escapes to a
    # different event loop.
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    yield TEST_DATABASE_URL

    await _drop_test_db()


@pytest_asyncio.fixture
async def db_session(_test_db_url: str) -> AsyncIterator[AsyncSession]:
    """Function-scoped session. Engine is created on the test's own event
    loop, NullPool avoids cross-test connection reuse, tables truncated
    in teardown.
    """
    # NullPool: no pooling. Each connection is opened fresh and closed on
    # release. For tests, the latency is irrelevant and it eliminates an
    # entire class of "connection from previous test still in flight" bugs.
    engine = create_async_engine(_test_db_url, poolclass=NullPool)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with SessionLocal() as session:
            try:
                yield session
            finally:
                await session.rollback()

        # Wipe tables for the next test. CASCADE handles FKs; RESTART
        # IDENTITY resets autoincrement sequences so transaction.id starts
        # at 1 again every test (asserts can compare specific IDs).
        table_names = ", ".join(
            f'"{t.name}"' for t in Base.metadata.sorted_tables
        )
        async with engine.begin() as conn:
            await conn.execute(
                text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE")
            )
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# Redis fixture
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def redis_client() -> AsyncIterator[redis_async.Redis]:
    """Per-test Redis client pointed at db=1, flushed entering and leaving.

    Patches `vixen.cache._redis` so any service that calls `cache.redis()`
    (cooldown, future leaderboards) talks to the test db automatically.
    The bot uses db=0 by default, so we never touch real cooldowns. We
    also `flushdb` at the start to wipe any leftover state from a crashed
    previous run.
    """
    client = redis_async.from_url(TEST_REDIS_URL, decode_responses=True)
    original = cache_module._redis
    cache_module._redis = client

    try:
        await client.flushdb()
        yield client
    finally:
        await client.flushdb()
        await client.aclose()
        cache_module._redis = original
