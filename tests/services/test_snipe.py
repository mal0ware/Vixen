"""Tests for vixen.services.snipe."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from vixen.services.snipe import add_points, all_scores, get_score

# ---------------------------------------------------------------- #
# add_points
# ---------------------------------------------------------------- #


async def test_add_points_creates_row(db_session: AsyncSession):
    """First contact: row inserted with the supplied delta as initial total."""
    new_total = await add_points(db_session, 42, "Alice", 50)
    assert new_total == 50

    score = await get_score(db_session, 42)
    assert score is not None
    assert score.name == "Alice"
    assert score.points == 50


async def test_add_points_accumulates(db_session: AsyncSession):
    """Second call sums onto existing total."""
    await add_points(db_session, 42, "Alice", 50)
    new_total = await add_points(db_session, 42, "Alice", 25)
    assert new_total == 75


async def test_add_points_negative_delta_subtracts(db_session: AsyncSession):
    """Penalties / corrections via negative deltas — points can go down."""
    await add_points(db_session, 42, "Alice", 100)
    new_total = await add_points(db_session, 42, "Alice", -30)
    assert new_total == 70


# ---------------------------------------------------------------- #
# get_score / all_scores
# ---------------------------------------------------------------- #


async def test_get_score_unknown_returns_none(db_session: AsyncSession):
    assert await get_score(db_session, 9999) is None


async def test_all_scores_orders_by_points_desc(db_session: AsyncSession):
    """Leaderboard ordering: highest points first."""
    await add_points(db_session, 1, "Alice", 50)
    await add_points(db_session, 2, "Bob", 200)
    await add_points(db_session, 3, "Cal", 100)

    scores = await all_scores(db_session)
    assert [s.user_discord_id for s in scores] == [2, 3, 1]
    assert [s.points for s in scores] == [200, 100, 50]


async def test_all_scores_empty_returns_empty(db_session: AsyncSession):
    assert await all_scores(db_session) == []
