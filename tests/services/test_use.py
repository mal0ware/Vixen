"""Tests for vixen.services.use.

The use service composes shop.remove_item + an effect handler from the
EFFECTS registry. Tests verify both the orchestration (validation, ordering,
rollback) and the integration with real catalog items.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from vixen.models import InventoryItem
from vixen.services.shop import InsufficientItemsError, UnknownItemError, add_item
from vixen.services.use import NotConsumableError, consume_item

# ---------------------------------------------------------------- #
# Happy path
# ---------------------------------------------------------------- #


async def test_consume_decrements_and_returns_flavor(db_session: AsyncSession):
    """Successful /use removes one and returns a non-empty flavor string."""
    await add_item(db_session, 42, "bread", 3)
    flavor = await consume_item(db_session, 42, "bread")

    assert flavor  # non-empty
    assert "bread" in flavor.lower()  # references the item

    row = await db_session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_discord_id == 42,
            InventoryItem.item_key == "bread",
        )
    )
    assert row is not None
    assert row.quantity == 2


async def test_consume_last_deletes_inventory_row(db_session: AsyncSession):
    """Going from qty=1 to 0 removes the row entirely (matches shop.remove_item)."""
    await add_item(db_session, 42, "bread", 1)
    await consume_item(db_session, 42, "bread")

    row = await db_session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_discord_id == 42,
            InventoryItem.item_key == "bread",
        )
    )
    assert row is None


async def test_consume_coffee_uses_caffeinate_handler(db_session: AsyncSession):
    """Coffee's effect handler is distinct from bread's — verify dispatch works."""
    await add_item(db_session, 42, "coffee", 1)
    flavor = await consume_item(db_session, 42, "coffee")
    assert "coffee" in flavor.lower()


# ---------------------------------------------------------------- #
# Error paths
# ---------------------------------------------------------------- #


async def test_consume_unknown_item_raises(db_session: AsyncSession):
    with pytest.raises(UnknownItemError):
        await consume_item(db_session, 42, "fnord")


async def test_consume_non_consumable_raises_before_inventory_check(
    db_session: AsyncSession,
):
    """/use fishing_rod must reject without touching the user's inventory.

    Otherwise we'd get the misleading "you don't have any fishing_rod"
    when the real reason is that fishing_rods aren't /use-able.
    """
    await add_item(db_session, 42, "fishing_rod", 1)
    with pytest.raises(NotConsumableError):
        await consume_item(db_session, 42, "fishing_rod")

    # Inventory unchanged — we did NOT decrement.
    row = await db_session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_discord_id == 42,
            InventoryItem.item_key == "fishing_rod",
        )
    )
    assert row is not None
    assert row.quantity == 1


async def test_consume_without_owning_raises_insufficient(db_session: AsyncSession):
    """/use bread without owning any raises InsufficientItemsError with item_key set."""
    with pytest.raises(InsufficientItemsError) as exc:
        await consume_item(db_session, 42, "bread")
    assert exc.value.item_key == "bread"
    assert exc.value.have == 0
