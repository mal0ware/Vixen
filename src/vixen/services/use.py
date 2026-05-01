"""/use orchestration: validate, consume, dispatch effect.

Public entry: `consume_item(session, user_id, item_key) -> str`. The string
is flavor text the cog renders to the user.

The flow is one atomic transaction (anchored at the cog's `get_session()`):

    1. Validate the item exists in the catalog            (UnknownItem)
    2. Validate it's actually consumable (has an effect)  (NotConsumable)
    3. Decrement inventory by 1                           (InsufficientItems)
    4. Look up + run the effect handler                   (handler may raise)
    5. Return the flavor string

If step 4 raises, the inventory decrement from step 3 is rolled back along
with everything else — so a flaky effect handler can't silently eat your
last loaf of bread.

The cog catches each typed error and renders a user-friendly message. None
of these errors are exceptional in the engineering sense — they all map to
plain English replies like "you don't have any bread" or "fishing rods
aren't /use-able directly."
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from .economy import EconomyError
from .effects import EFFECTS
from .items import ITEMS
from .shop import UnknownItem, remove_item

# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class NotConsumable(EconomyError):
    """Item exists in the catalog but has `effect=None`.

    Raised when a user runs /use on a non-consumable like fishing_rod or
    padlock. Those items are meaningful, but they're triggered by their
    owning command (/fish, /rob) — not /use.
    """

    def __init__(self, item_key: str):
        self.item_key = item_key
        super().__init__(f"item is not consumable: {item_key}")


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def consume_item(
    session: AsyncSession,
    user_id: int,
    item_key: str,
) -> str:
    """Consume one of `item_key` and run its effect. Returns flavor text.

    Raises:
        UnknownItem: item_key not in catalog.
        NotConsumable: item is in the catalog but has no effect handler.
        InsufficientItems: user owns zero of the item (re-raised from
            `shop.remove_item`).

    Order matters: we check catalog membership and consumability BEFORE
    decrementing inventory. That way "you can't /use fishing_rod" doesn't
    burn the user's rod when we tell them so.
    """
    if item_key not in ITEMS:
        raise UnknownItem(item_key)

    item = ITEMS[item_key]
    if item.effect is None:
        raise NotConsumable(item_key)

    # Inventory decrement. Raises InsufficientItems if the user owns zero.
    # Decrementing before running the effect is correct: real consumables
    # are spent on attempt, not on success. (A future "bread fails to chew
    # 5% of the time" mechanic can refund inside its handler if needed.)
    await remove_item(session, user_id, item_key, qty=1)

    handler = EFFECTS[item.effect]
    return await handler(session, user_id, item)
