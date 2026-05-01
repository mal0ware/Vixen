"""Tests for vixen.services.reminders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.services.reminders import (
    cancel,
    create,
    due,
    list_for_user,
    mark_fired,
    parse_duration,
)

# ---------------------------------------------------------------- #
# parse_duration
# ---------------------------------------------------------------- #


def test_parse_duration_simple_units():
    assert parse_duration("30s") == 30
    assert parse_duration("5m") == 300
    assert parse_duration("1h") == 3600
    assert parse_duration("2d") == 2 * 86400


def test_parse_duration_compound():
    assert parse_duration("1h30m") == 3600 + 30 * 60
    assert parse_duration("1d2h30m") == 86400 + 2 * 3600 + 30 * 60


def test_parse_duration_case_insensitive():
    assert parse_duration("5M") == 300
    assert parse_duration("1H30M") == 3600 + 30 * 60


def test_parse_duration_with_whitespace():
    assert parse_duration(" 1h  30m ") == 3600 + 30 * 60


def test_parse_duration_rejects_garbage():
    with pytest.raises(ValueError):
        parse_duration("yesterday")


def test_parse_duration_rejects_zero():
    with pytest.raises(ValueError):
        parse_duration("0s")


# ---------------------------------------------------------------- #
# create + list
# ---------------------------------------------------------------- #


async def test_create_inserts_row(db_session: AsyncSession):
    """Created reminder has the right user, message, and due_at."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    reminder = await create(
        db_session, 42, "buy bread", seconds_from_now=300, now=now
    )

    assert reminder.user_discord_id == 42
    assert reminder.message == "buy bread"
    assert reminder.due_at == now + timedelta(seconds=300)
    assert reminder.fired is False
    assert reminder.id is not None  # row got an autoincrement id


async def test_list_for_user_filters_to_user(db_session: AsyncSession):
    """list_for_user returns one user's reminders, ordered soonest first."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    await create(db_session, 1, "first", 600, now=base)
    await create(db_session, 1, "second", 60, now=base)
    await create(db_session, 2, "other user", 60, now=base)

    rows = await list_for_user(db_session, 1)
    assert [r.message for r in rows] == ["second", "first"]


async def test_list_for_user_excludes_fired(db_session: AsyncSession):
    """Fired reminders don't appear in /list."""
    r = await create(db_session, 1, "old", 60)
    await mark_fired(db_session, r.id)

    rows = await list_for_user(db_session, 1)
    assert rows == []


# ---------------------------------------------------------------- #
# cancel
# ---------------------------------------------------------------- #


async def test_cancel_removes_reminder(db_session: AsyncSession):
    """A user can cancel their own reminder."""
    r = await create(db_session, 1, "cancel me", 60)
    removed = await cancel(db_session, r.id, 1)
    assert removed is True
    assert await list_for_user(db_session, 1) == []


async def test_cancel_other_users_reminder_fails(db_session: AsyncSession):
    """Users can't cancel each other's reminders by guessing IDs."""
    r = await create(db_session, 1, "user1's reminder", 60)

    removed = await cancel(db_session, r.id, user_id=2)
    assert removed is False

    # Reminder still there for the real owner.
    rows = await list_for_user(db_session, 1)
    assert len(rows) == 1


async def test_cancel_unknown_id_returns_false(db_session: AsyncSession):
    """Cancelling a non-existent ID is a no-op, returns False."""
    removed = await cancel(db_session, 9999, user_id=1)
    assert removed is False


# ---------------------------------------------------------------- #
# due
# ---------------------------------------------------------------- #


async def test_due_returns_only_passed_reminders(db_session: AsyncSession):
    """due() filters by time AND fired flag."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    await create(db_session, 1, "past", -60, now=base)  # 60s ago
    await create(db_session, 1, "now-ish", 0, now=base)
    await create(db_session, 1, "future", 600, now=base)

    rows = await due(db_session, now=base)
    # past + now-ish are due; future isn't.
    assert sorted(r.message for r in rows) == ["now-ish", "past"]


async def test_due_excludes_fired(db_session: AsyncSession):
    """Once fired, a reminder isn't returned by due() anymore."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    r = await create(db_session, 1, "old", -60, now=base)
    await mark_fired(db_session, r.id)

    rows = await due(db_session, now=base)
    assert rows == []


# ---------------------------------------------------------------- #
# mark_fired
# ---------------------------------------------------------------- #


async def test_mark_fired_is_idempotent(db_session: AsyncSession):
    """Calling mark_fired twice doesn't error and stays fired."""
    r = await create(db_session, 1, "msg", 60)
    await mark_fired(db_session, r.id)
    await mark_fired(db_session, r.id)  # second call: no-op

    rows = await list_for_user(db_session, 1)
    assert rows == []


async def test_mark_fired_unknown_id_is_safe(db_session: AsyncSession):
    """mark_fired(non-existent) doesn't crash."""
    await mark_fired(db_session, 9999)
