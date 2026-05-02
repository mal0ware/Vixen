"""Attendance service.

Pre-migration the attendance cog kept user-id → UCID mappings in
`bot.data["ucids"]` (a JSON file loaded at boot). Now it's a single
nullable column on the User row, set the first time a user checks
into a meeting and reused on every subsequent check-in.

Surface kept tiny — get / set / clear. The cog handles modal UX; this
module handles persistence only.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import User
from .economy import get_or_create_user


async def get_ucid(session: AsyncSession, user_id: int) -> str | None:
    """Return the user's stored UCID, or None if they haven't registered."""
    user = await session.get(User, user_id)
    return user.ucid if user is not None else None


async def set_ucid(
    session: AsyncSession, user_id: int, ucid: str
) -> None:
    """Persist a UCID for a user. Creates the User row if it doesn't exist.

    Empty / whitespace-only UCIDs are rejected — the cog should validate
    upstream, but defending here keeps the data clean.
    """
    cleaned = ucid.strip()
    if not cleaned:
        raise ValueError("UCID can't be empty")

    user = await get_or_create_user(session, user_id)
    user.ucid = cleaned
    await session.flush()


async def clear_ucid(session: AsyncSession, user_id: int) -> None:
    """Remove a user's UCID. No-op if no user row exists."""
    user = await session.get(User, user_id)
    if user is not None:
        user.ucid = None
        await session.flush()
