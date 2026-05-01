"""Reminders service.

Public API:

    parse_duration(s)            "5m", "1h30m", "2d" -> seconds. Raises ValueError.
    create(session, ...)         insert a Reminder row, return it
    list_for_user(session, uid)  open reminders for one user
    cancel(session, id, uid)     delete one (must own it)
    due(session, now)            unfired reminders with due_at <= now
    mark_fired(session, id)      flip the `fired` flag

The cog wires `due` into a `discord.ext.tasks.loop` polling every ~30 s,
DMs the user, then calls `mark_fired`. Polling at this rate means the
worst-case lag is half the loop interval (~15 s) — fine for a reminder.
A future enhancement could swap to a sleep-until-next-due pattern if the
table grows large.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Reminder
from .economy import get_or_create_user

# --------------------------------------------------------------------------- #
# Duration parsing
# --------------------------------------------------------------------------- #

# Matches one or more "<number><unit>" pairs separated by optional whitespace.
# Units: s (seconds), m (minutes), h (hours), d (days). Case-insensitive.
_DURATION_TOKEN = re.compile(r"(\d+)\s*([smhd])", re.IGNORECASE)
_DURATION_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def parse_duration(s: str) -> int:
    """Parse a human-readable duration like "5m", "1h30m", "2d" -> total seconds.

    Multiple components compose: "1d2h30m" = 1 day + 2 hours + 30 minutes.
    Whitespace between components is allowed and ignored.

    Raises:
        ValueError: no recognizable tokens, or the result is <= 0.
    """
    matches = _DURATION_TOKEN.findall(s.strip())
    if not matches:
        raise ValueError(f"can't parse duration: {s!r} (try '5m' or '1h30m')")
    total = sum(int(n) * _DURATION_UNIT_SECONDS[u.lower()] for n, u in matches)
    if total <= 0:
        raise ValueError(f"duration must be positive: {s!r}")
    return total


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def create(
    session: AsyncSession,
    user_id: int,
    message: str,
    seconds_from_now: int,
    *,
    now: datetime | None = None,
) -> Reminder:
    """Insert a new reminder due `seconds_from_now` from now (or `now` arg).

    The `now` parameter is a test seam — pass an explicit datetime so the
    test is deterministic. Production passes nothing and we use UTC now.
    """
    # Reminder.user_discord_id is FK -> users; ensure the row exists so a
    # user who has never had a cash event can still set a reminder.
    await get_or_create_user(session, user_id)

    base = now or datetime.now(UTC)
    due_at = base + timedelta(seconds=seconds_from_now)
    reminder = Reminder(
        user_discord_id=user_id,
        message=message,
        due_at=due_at,
        fired=False,
    )
    session.add(reminder)
    await session.flush()
    return reminder


async def list_for_user(
    session: AsyncSession, user_id: int
) -> list[Reminder]:
    """Return the user's unfired reminders, soonest first."""
    rows = (
        await session.execute(
            select(Reminder)
            .where(
                Reminder.user_discord_id == user_id,
                Reminder.fired.is_(False),
            )
            .order_by(Reminder.due_at)
        )
    ).scalars().all()
    return list(rows)


async def cancel(
    session: AsyncSession, reminder_id: int, user_id: int
) -> bool:
    """Delete a reminder. Returns True if a row was actually removed.

    Scopes by both id AND user_id so users can't cancel each other's
    reminders by guessing IDs.
    """
    result = await session.execute(
        delete(Reminder).where(
            Reminder.id == reminder_id,
            Reminder.user_discord_id == user_id,
        )
    )
    return (result.rowcount or 0) > 0


async def due(
    session: AsyncSession, now: datetime | None = None
) -> list[Reminder]:
    """Return all unfired reminders whose due_at has passed.

    Uses the composite index (due_at, fired) so this scales fine as the
    table grows.
    """
    when = now or datetime.now(UTC)
    rows = (
        await session.execute(
            select(Reminder)
            .where(
                Reminder.fired.is_(False),
                Reminder.due_at <= when,
            )
            .order_by(Reminder.due_at)
        )
    ).scalars().all()
    return list(rows)


async def mark_fired(session: AsyncSession, reminder_id: int) -> None:
    """Set fired=True on a reminder. Idempotent — a no-op if already fired."""
    reminder = await session.get(Reminder, reminder_id)
    if reminder is not None:
        reminder.fired = True
        await session.flush()
