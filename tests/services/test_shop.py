"""Tests for vixen.services.shop.

Real Postgres, real SQLAlchemy. The conftest fixtures hand us a per-test
session with the schema in place and tables truncated between runs, so
every test starts on an empty database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import InventoryItem, Transaction, User
from vixen.services.economy import (
    InsufficientFunds,
    InvalidAmount,
    change_cash,
)
from vixen.services.items import ITEMS
from vixen.services.shop import (
    InsufficientItems,
    UnknownItem,
    add_item,
    buy_item,
    list_inventory,
    remove_item,
    sell_item,
)

# ---------------------------------------------------------------- #
# add_item
# ---------------------------------------------------------------- #


async def test_add_item_creates_row(db_session: AsyncSession):
    """First add of an item creates a single inventory row at the given qty."""
    new_qty = await add_item(db_session, 42, "bread", 3)

    assert new_qty == 3
    rows = (
        await db_session.execute(
            select(InventoryItem).where(InventoryItem.user_discord_id == 42)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].item_key == "bread"
    assert rows[0].quantity == 3


async def test_add_item_increments_existing_row(db_session: AsyncSession):
    """Repeated adds for the same (user, item_key) update one row, not insert."""
    await add_item(db_session, 42, "bread", 2)
    new_qty = await add_item(db_session, 42, "bread", 5)

    assert new_qty == 7
    rows = (
        await db_session.execute(
            select(InventoryItem).where(InventoryItem.user_discord_id == 42)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].quantity == 7


async def test_add_item_auto_registers_user(db_session: AsyncSession):
    """First-contact add still works even if the user row doesn't exist yet."""
    await add_item(db_session, 99, "bread", 1)
    assert await db_session.get(User, 99) is not None


async def test_add_item_rejects_unknown_item(db_session: AsyncSession):
    with pytest.raises(UnknownItem):
        await add_item(db_session, 42, "fnord", 1)


async def test_add_item_rejects_non_positive_qty(db_session: AsyncSession):
    with pytest.raises(InvalidAmount):
        await add_item(db_session, 42, "bread", 0)
    with pytest.raises(InvalidAmount):
        await add_item(db_session, 42, "bread", -1)


# ---------------------------------------------------------------- #
# remove_item
# ---------------------------------------------------------------- #


async def test_remove_item_decrements(db_session: AsyncSession):
    await add_item(db_session, 42, "bread", 5)
    new_qty = await remove_item(db_session, 42, "bread", 2)
    assert new_qty == 3


async def test_remove_item_deletes_row_when_zero(db_session: AsyncSession):
    """Hitting quantity zero deletes the row so listings stay clean."""
    await add_item(db_session, 42, "bread", 2)
    new_qty = await remove_item(db_session, 42, "bread", 2)

    assert new_qty == 0
    row = await db_session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_discord_id == 42,
            InventoryItem.item_key == "bread",
        )
    )
    assert row is None


async def test_remove_item_raises_when_insufficient(db_session: AsyncSession):
    await add_item(db_session, 42, "bread", 2)

    with pytest.raises(InsufficientItems) as exc:
        await remove_item(db_session, 42, "bread", 5)

    assert exc.value.item_key == "bread"
    assert exc.value.have == 2
    assert exc.value.need == 5


async def test_remove_item_raises_when_user_owns_none(db_session: AsyncSession):
    """Removing from an empty (or absent) inventory raises with have=0."""
    with pytest.raises(InsufficientItems) as exc:
        await remove_item(db_session, 42, "bread", 1)
    assert exc.value.have == 0


async def test_remove_item_rejects_non_positive_qty(db_session: AsyncSession):
    with pytest.raises(InvalidAmount):
        await remove_item(db_session, 42, "bread", 0)


# ---------------------------------------------------------------- #
# list_inventory
# ---------------------------------------------------------------- #


async def test_list_inventory_empty(db_session: AsyncSession):
    assert await list_inventory(db_session, 42) == []


async def test_list_inventory_returns_owned_sorted(db_session: AsyncSession):
    """Returns (key, qty) tuples ordered by item_key for stable rendering."""
    await add_item(db_session, 42, "fishing_rod", 1)
    await add_item(db_session, 42, "bread", 3)
    await add_item(db_session, 42, "coffee", 2)

    rows = await list_inventory(db_session, 42)
    assert rows == [("bread", 3), ("coffee", 2), ("fishing_rod", 1)]


async def test_list_inventory_isolates_users(db_session: AsyncSession):
    """One user's inventory doesn't leak into another's listing."""
    await add_item(db_session, 1, "bread", 1)
    await add_item(db_session, 2, "coffee", 1)

    assert await list_inventory(db_session, 1) == [("bread", 1)]
    assert await list_inventory(db_session, 2) == [("coffee", 1)]


# ---------------------------------------------------------------- #
# buy_item
# ---------------------------------------------------------------- #


async def test_buy_item_debits_cash_and_credits_inventory(db_session: AsyncSession):
    """Happy path: cash goes down, inventory goes up, audit row written."""
    await change_cash(db_session, 42, 1000, reason="seed")
    bread = ITEMS["bread"]

    cost, new_balance, new_qty = await buy_item(db_session, 42, "bread", 2)

    assert cost == bread.price * 2
    assert new_balance == 1000 - cost
    assert new_qty == 2

    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == new_balance

    txs = (
        await db_session.execute(select(Transaction).order_by(Transaction.id))
    ).scalars().all()
    # seed credit + shop_buy debit.
    assert [(t.delta, t.reason) for t in txs] == [
        (1000, "seed"),
        (-cost, "shop_buy:bread"),
    ]


async def test_buy_item_insufficient_funds_writes_nothing(db_session: AsyncSession):
    """A failed buy leaves cash AND inventory untouched."""
    await change_cash(db_session, 42, 10, reason="seed")  # bread costs 50

    with pytest.raises(InsufficientFunds):
        await buy_item(db_session, 42, "bread", 1)

    user = await db_session.get(User, 42)
    assert user is not None
    assert user.cash == 10  # debit never applied

    assert await list_inventory(db_session, 42) == []  # no inventory row

    # Only the seed transaction exists.
    txs = (await db_session.execute(select(Transaction))).scalars().all()
    assert [t.reason for t in txs] == ["seed"]


async def test_buy_item_unknown_item_raises(db_session: AsyncSession):
    await change_cash(db_session, 42, 1000, reason="seed")
    with pytest.raises(UnknownItem):
        await buy_item(db_session, 42, "fnord", 1)


async def test_buy_item_rejects_non_positive_qty(db_session: AsyncSession):
    await change_cash(db_session, 42, 1000, reason="seed")
    with pytest.raises(InvalidAmount):
        await buy_item(db_session, 42, "bread", 0)


# ---------------------------------------------------------------- #
# sell_item
# ---------------------------------------------------------------- #


async def test_sell_item_decrements_inventory_and_credits_cash(db_session: AsyncSession):
    """Buy 3 bread, sell 2, check final cash and remaining qty."""
    await change_cash(db_session, 42, 1000, reason="seed")
    bread = ITEMS["bread"]
    await buy_item(db_session, 42, "bread", 3)

    payout, new_balance, new_qty = await sell_item(db_session, 42, "bread", 2)

    assert payout == bread.sell_price * 2
    assert new_qty == 1

    expected_balance = 1000 - 3 * bread.price + 2 * bread.sell_price
    assert new_balance == expected_balance


async def test_sell_item_insufficient_items(db_session: AsyncSession):
    with pytest.raises(InsufficientItems):
        await sell_item(db_session, 42, "bread", 1)


async def test_sell_item_unknown_item_raises(db_session: AsyncSession):
    with pytest.raises(UnknownItem):
        await sell_item(db_session, 42, "fnord", 1)


async def test_sell_all_clears_inventory_row(db_session: AsyncSession):
    """Selling the last copy deletes the inventory row entirely."""
    await change_cash(db_session, 42, 1000, reason="seed")
    await buy_item(db_session, 42, "bread", 1)

    _, _, new_qty = await sell_item(db_session, 42, "bread", 1)

    assert new_qty == 0
    rows = await list_inventory(db_session, 42)
    assert rows == []
