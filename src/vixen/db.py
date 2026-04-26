"""Async SQLAlchemy session factory.

Pattern:
    async with get_session() as session:
        user = await session.get(User, ctx.author.id)
        user.cash += 100
        # session auto-commits on clean exit, rolls back on exception

Sessions are short-lived. Open one per command handler, do the read/write,
let the context manager commit. Do not hold a session across long-running
network calls — open a fresh one after the network call.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

# Module-level singletons populated by init_db(). Both are None before init.
_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def init_db() -> None:
    """Create the engine + sessionmaker. Call once at startup (in setup_hook)."""
    global _engine, _sessionmaker

    settings = get_settings()
    _engine = create_async_engine(
        settings.database_url,
        # Flip to True for query tracing during dev. Very verbose.
        echo=False,
        # Validate connections before handing them out (drops dead pool entries).
        pool_pre_ping=True,
    )
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_db() -> None:
    """Cleanly close the engine on shutdown. Call from bot.close()."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Open one transactional session. Commits on clean exit, rolls back on error."""
    if _sessionmaker is None:
        raise RuntimeError("init_db() was not called before get_session()")

    async with _sessionmaker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
