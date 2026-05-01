"""Tests for vixen.services.fishing."""

from __future__ import annotations

import random

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import User
from vixen.services.fishing import CATCH_TABLE, NoRod, _pick_catch, do_fish
from vixen.services.shop import add_item

# ---------------------------------------------------------------- #
# do_fish — happy path
# ---------------------------------------------------------------- #


async def test_do_fish_credits_payout(db_session: AsyncSession):
    """A user with a rod gets a catch and the payout lands in cash."""
    await add_item(db_session, 42, "fishing_rod", 1)
    # Seed the RNG so the catch is deterministic for assertion stability.
    rng = random.Random(1)
    catch, new_balance = await do_fish(db_session, 42, rng=rng)

    assert catch in CATCH_TABLE
    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == catch.payout
    assert new_balance == catch.payout


async def test_do_fish_does_not_consume_rod(db_session: AsyncSession):
    """The rod is durable — quantity is unchanged after fishing."""
    await add_item(db_session, 42, "fishing_rod", 1)
    await do_fish(db_session, 42, rng=random.Random(0))

    from vixen.services.shop import has_item
    assert await has_item(db_session, 42, "fishing_rod")


async def test_do_fish_audit_log_reason(db_session: AsyncSession):
    """Audit reason is `fish_<catch_name_snake>` so we can later query stats."""
    from sqlalchemy import select

    from vixen.models import Transaction

    await add_item(db_session, 42, "fishing_rod", 1)
    catch, _ = await do_fish(db_session, 42, rng=random.Random(0))

    txs = (await db_session.execute(select(Transaction))).scalars().all()
    assert len(txs) == 1
    expected_reason = f"fish_{catch.name.lower().replace(' ', '_')}"
    assert txs[0].reason == expected_reason


# ---------------------------------------------------------------- #
# do_fish — error path
# ---------------------------------------------------------------- #


async def test_do_fish_raises_norod_when_no_rod(db_session: AsyncSession):
    """A user without a rod can't fish."""
    with pytest.raises(NoRod):
        await do_fish(db_session, 42)


async def test_norod_does_not_create_transaction(db_session: AsyncSession):
    """Failed fish must not write any audit row or change cash."""
    from sqlalchemy import select

    from vixen.models import Transaction

    with pytest.raises(NoRod):
        await do_fish(db_session, 42)

    txs = (await db_session.execute(select(Transaction))).scalars().all()
    assert txs == []


# ---------------------------------------------------------------- #
# _pick_catch — distribution sanity
# ---------------------------------------------------------------- #


def test_pick_catch_returns_an_entry_in_table():
    """Sanity: every pick is one of the documented catches."""
    rng = random.Random(0)
    for _ in range(50):
        c = _pick_catch(rng)
        assert c in CATCH_TABLE


def test_pick_catch_distribution_roughly_matches_weights():
    """Across 10k samples, each catch's frequency is within ~3% of its weight.

    Not a hard guarantee on RNG, but with seed=0 and N=10k the bands hold
    comfortably. If this ever flakes, increase N or widen tolerance.
    """
    rng = random.Random(0)
    counts: dict[str, int] = {c.name: 0 for c in CATCH_TABLE}
    n = 10_000
    for _ in range(n):
        counts[_pick_catch(rng).name] += 1

    total_weight = sum(c.weight for c in CATCH_TABLE)
    for c in CATCH_TABLE:
        expected = c.weight / total_weight
        observed = counts[c.name] / n
        assert abs(observed - expected) < 0.03, (
            f"{c.name}: expected ~{expected:.2%}, got {observed:.2%}"
        )
