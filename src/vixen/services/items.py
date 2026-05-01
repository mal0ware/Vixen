"""Item catalog.

Static dict of every purchasable item. Lives in code (not the database) on
purpose: the catalog rarely changes, code review is the right gate for
edits, and keeping it in-process avoids a round-trip on every shop
interaction. We swap to an `items` table when the catalog grows past ~30
entries, or when we want admin-runtime edits without a deploy.

Each Item carries:
    key         - stable machine identifier; persisted in inventory_items.item_key
    name        - display name in embeds and slash-command choices
    description - one-line player-facing flavor / function hint
    price       - cost to buy, in cash
    sell_price  - payout when sold back to the shop, in cash. Conventionally
                  25% of `price` (rounded down, min 1) so buying-and-selling
                  isn't a no-op cash sink and players have a real cost to
                  experiment with item-based mini-games.
    emoji       - rendered next to the name in embeds
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Item:
    key: str
    name: str
    description: str
    price: int
    sell_price: int
    emoji: str


def _sell(price: int) -> int:
    """25% of buy price, rounded down, clamped to >= 1."""
    return max(1, price // 4)


_CATALOG: tuple[Item, ...] = (
    Item(
        key="bread",
        name="Bread",
        description="A loaf of bread. Filling, dependable.",
        price=50,
        sell_price=_sell(50),
        emoji="🍞",
    ),
    Item(
        key="coffee",
        name="Coffee",
        description="Restores wakefulness. Probably.",
        price=100,
        sell_price=_sell(100),
        emoji="☕",
    ),
    Item(
        key="fishing_rod",
        name="Fishing Rod",
        description="Required to /fish (forthcoming).",
        price=1500,
        sell_price=_sell(1500),
        emoji="🎣",
    ),
    Item(
        key="lottery_ticket",
        name="Lottery Ticket",
        description="Enters the next /lottery draw (forthcoming).",
        price=500,
        sell_price=_sell(500),
        emoji="🎟️",
    ),
    Item(
        key="padlock",
        name="Padlock",
        description="Blocks one robbery attempt (forthcoming).",
        price=2500,
        sell_price=_sell(2500),
        emoji="🔒",
    ),
)


# Public lookup. Cogs and services should treat this as read-only.
ITEMS: dict[str, Item] = {item.key: item for item in _CATALOG}
