"""Snipe leaderboard service.

Wraps the SnipeScore table for the legacy /snipe_leaderboard cog. Two
read functions and an upsert — the legacy bot didn't have a way to add
points from inside the cog, but exposing `add_points` here means a
future /snipe-add-points admin command is one cog edit away.
"""

from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import SnipeScore
from .economy import get_or_create_user


async def all_scores(session: AsyncSession) -> list[SnipeScore]:
    """Every score row, sorted by points descending. Used by paginated views."""
    result = await session.execute(
        select(SnipeScore).order_by(desc(SnipeScore.points))
    )
    return list(result.scalars().all())


async def get_score(
    session: AsyncSession, user_id: int
) -> SnipeScore | None:
    """Return one user's score row, or None if they're not on the board."""
    return await session.get(SnipeScore, user_id)


async def add_points(
    session: AsyncSession,
    user_id: int,
    name: str,
    delta: int,
) -> int:
    """Add `delta` points to a user. Creates the row on first contact.

    Returns the user's new total. `name` is stored only when the row is
    first created or when explicitly updated by an admin command — the
    legacy data is full of stale display names, but updating them on
    every point-event would defeat "kept frozen at score time" tracking.
    """
    # Ensure FK target exists. add_points is the entry point most likely
    # called for users who've never had a cash event before.
    await get_or_create_user(session, user_id)

    row = await session.get(SnipeScore, user_id)
    if row is None:
        row = SnipeScore(user_discord_id=user_id, name=name, points=delta)
        session.add(row)
    else:
        row.points += delta
    await session.flush()
    return row.points
