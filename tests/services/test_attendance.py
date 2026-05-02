"""Tests for vixen.services.attendance."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import User
from vixen.services.attendance import clear_ucid, get_ucid, set_ucid

# ---------------------------------------------------------------- #
# get_ucid
# ---------------------------------------------------------------- #


async def test_get_ucid_unknown_user_returns_none(db_session: AsyncSession):
    """A user who's never registered → None."""
    assert await get_ucid(db_session, 42) is None


async def test_get_ucid_after_set(db_session: AsyncSession):
    await set_ucid(db_session, 42, "mdc47")
    assert await get_ucid(db_session, 42) == "mdc47"


# ---------------------------------------------------------------- #
# set_ucid
# ---------------------------------------------------------------- #


async def test_set_ucid_creates_user_row_if_missing(db_session: AsyncSession):
    """First-contact user gets a User row + the UCID at once."""
    await set_ucid(db_session, 42, "mdc47")
    user = await db_session.get(User, 42)
    assert user is not None
    assert user.ucid == "mdc47"


async def test_set_ucid_overwrites_existing(db_session: AsyncSession):
    """Re-registering replaces the prior UCID."""
    await set_ucid(db_session, 42, "old_ucid")
    await set_ucid(db_session, 42, "new_ucid")
    assert await get_ucid(db_session, 42) == "new_ucid"


async def test_set_ucid_strips_whitespace(db_session: AsyncSession):
    """Leading/trailing whitespace is stripped — keeps data tidy."""
    await set_ucid(db_session, 42, "  mdc47  ")
    assert await get_ucid(db_session, 42) == "mdc47"


async def test_set_ucid_rejects_empty(db_session: AsyncSession):
    with pytest.raises(ValueError):
        await set_ucid(db_session, 42, "")
    with pytest.raises(ValueError):
        await set_ucid(db_session, 42, "   ")


# ---------------------------------------------------------------- #
# clear_ucid
# ---------------------------------------------------------------- #


async def test_clear_ucid_removes_value(db_session: AsyncSession):
    await set_ucid(db_session, 42, "mdc47")
    await clear_ucid(db_session, 42)
    assert await get_ucid(db_session, 42) is None


async def test_clear_ucid_safe_when_no_user(db_session: AsyncSession):
    """Clearing for a non-existent user is a no-op, not an error."""
    await clear_ucid(db_session, 9999)
    assert await get_ucid(db_session, 9999) is None
