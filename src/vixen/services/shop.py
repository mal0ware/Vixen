"""Shop service.

Wraps the buy/sell/list flows on top of `services.economy` and the static
`services.items` catalog.

Atomicity: each public function is one intent, but the cog defines the
transaction boundary by opening a session via `db.get_session()`. That
context manager commits on clean exit and rolls back on exception, so a
buy that debits cash but then fails to write inventory rolls the debit
back too — the user is never partially charged.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import InventoryItem
from .economy import EconomyError, InvalidAmount, change_cash, get_or_create_user
from .items import ITEMS

# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class UnknownItem(EconomyError):
    """Caller passed an item_key that isn't in the catalog."""

    def __init__(self, item_key: str):
        self.item_key = item_key
        super().__init__(f"unknown item: {item_key}")


class InsufficientItems(EconomyError):
    """User attempted to remove more of an item than they own."""

    def __init__(self, *, item_key: str, have: int, need: int):
        self.item_key = item_key
        self.have = have
        self.need = need
        super().__init__(
            f"insufficient {item_key}: have {have}, need {need}"
        )


# --------------------------------------------------------------------------- #
# Inventory primitives
# --------------------------------------------------------------------------- #


async def _get_row(
    session: AsyncSession, discord_id: int, item_key: str
) -> InventoryItem | None:
    return await session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_discord_id == discord_id,
            InventoryItem.item_key == item_key,
        )
    )


async def add_item(
    session: AsyncSession,
    discord_id: int,
    item_key: str,
    qty: int = 1,
) -> int:
    """Increment a user's quantity of `item_key`. Returns new quantity.

    Auto-registers the user (FK target) so the first item a brand-new
    player ever receives doesn't 500 on a missing users row.
    """
    if item_key not in ITEMS:
        raise UnknownItem(item_key)
    if qty <= 0:
        raise InvalidAmount(f"qty must be positive, got {qty}")

    await get_or_create_user(session, discord_id)

    row = await _get_row(session, discord_id, item_key)
    if row is None:
        row = InventoryItem(
            user_discord_id=discord_id, item_key=item_key, quantity=qty
        )
        session.add(row)
    else:
        row.quantity += qty
    await session.flush()
    return row.quantity


async def remove_item(
    session: AsyncSession,
    discord_id: int,
    item_key: str,
    qty: int = 1,
) -> int:
    """Decrement a user's quantity of `item_key`. Returns remaining quantity.

    The row is deleted when quantity reaches zero so /inventory listings
    don't show empty rows; the unique (user, item_key) constraint then
    lets a future buy re-create cleanly.
    """
    if qty <= 0:
        raise InvalidAmount(f"qty must be positive, got {qty}")

    row = await _get_row(session, discord_id, item_key)
    have = row.quantity if row is not None else 0
    if have < qty:
        raise InsufficientItems(item_key=item_key, have=have, need=qty)

    # row is guaranteed non-None here: have >= qty > 0.
    assert row is not None
    row.quantity -= qty
    if row.quantity == 0:
        await session.delete(row)
        await session.flush()
        return 0
    await session.flush()
    return row.quantity


async def has_item(
    session: AsyncSession,
    discord_id: int,
    item_key: str,
    qty: int = 1,
) -> bool:
    """Return True if the user owns at least `qty` of `item_key`.

    Cheap helper used by feature cogs that gate on inventory (fishing,
    lottery, robbery defense) without modifying it. Compared to a full
    `list_inventory` + filter, this is one indexed lookup.
    """
    row = await _get_row(session, discord_id, item_key)
    return row is not None and row.quantity >= qty


async def list_inventory(
    session: AsyncSession,
    discord_id: int,
) -> list[tuple[str, int]]:
    """Return [(item_key, qty), ...] for everything the user owns, item_key-sorted.

    Returns an empty list for users who own nothing (or don't exist yet).
    Filters out rows with quantity == 0 defensively — `remove_item` deletes
    them, but a hand-edited DB row could still have one.
    """
    rows = (
        await session.execute(
            select(InventoryItem)
            .where(
                InventoryItem.user_discord_id == discord_id,
                InventoryItem.quantity > 0,
            )
            .order_by(InventoryItem.item_key)
        )
    ).scalars().all()
    return [(r.item_key, r.quantity) for r in rows]


# --------------------------------------------------------------------------- #
# Shop transactions
# --------------------------------------------------------------------------- #


async def buy_item(
    session: AsyncSession,
    discord_id: int,
    item_key: str,
    qty: int = 1,
) -> tuple[int, int, int]:
    """Buy `qty` of `item_key`. Atomic: cash debit + inventory increment.

    Returns (total_cost, new_cash_balance, new_qty_owned).

    Raises:
        UnknownItem: item_key not in catalog.
        InvalidAmount: qty <= 0.
        InsufficientFunds: user can't afford `price * qty`.
    """
    if item_key not in ITEMS:
        raise UnknownItem(item_key)
    if qty <= 0:
        raise InvalidAmount(f"qty must be positive, got {qty}")

    item = ITEMS[item_key]
    cost = item.price * qty

    # Debit first so InsufficientFunds short-circuits before we touch
    # inventory. If add_item somehow fails afterwards, the caller's
    # session ctx rolls the debit back too.
    new_balance = await change_cash(
        session, discord_id, -cost, reason=f"shop_buy:{item_key}"
    )
    new_qty = await add_item(session, discord_id, item_key, qty)
    return cost, new_balance, new_qty


async def sell_item(
    session: AsyncSession,
    discord_id: int,
    item_key: str,
    qty: int = 1,
) -> tuple[int, int, int]:
    """Sell `qty` of `item_key` back to the shop. Atomic: inventory debit + cash credit.

    Returns (total_payout, new_cash_balance, new_qty_owned).

    Raises:
        UnknownItem: item_key not in catalog.
        InvalidAmount: qty <= 0.
        InsufficientItems: user owns fewer than `qty` of the item.
    """
    if item_key not in ITEMS:
        raise UnknownItem(item_key)
    if qty <= 0:
        raise InvalidAmount(f"qty must be positive, got {qty}")

    item = ITEMS[item_key]

    # Decrement first; if the user doesn't have enough, we abort before
    # crediting cash. Sell prices are always >= 1 (enforced in items.py),
    # so change_cash won't trip its delta=0 guard.
    new_qty = await remove_item(session, discord_id, item_key, qty)
    payout = item.sell_price * qty
    new_balance = await change_cash(
        session, discord_id, payout, reason=f"shop_sell:{item_key}"
    )
    return payout, new_balance, new_qty
