"""Item effect registry.

Each consumable item in `services.items.ITEMS` declares an `effect` string.
This module owns the dispatch table that maps each effect name to its
async handler.

Why a separate module instead of putting effect callables on Item:

- `Item` is a frozen dataclass — pure data. Putting business logic on it
  would couple the catalog file to the entire service stack, and you'd
  have to import the database session machinery just to define an item.
- Effects often need DB access (a future stamina buff would write to the
  user row; a cash bonus calls `change_cash`). Sessions belong in services.
- The registry pattern means adding a new consumable is two edits: add an
  Item with `effect="<name>"`, add a handler here. No string-matching in
  the cog, no growing match statement.

Adding a new effect

1. Write an `async def my_effect(session, user_id, item) -> str` here.
2. Register it in `EFFECTS` below.
3. Reference it from a catalog entry: `Item(..., effect="my_effect")`.

The handler signature is fixed:
- `session`: the active AsyncSession the cog opened. Use it for any DB work.
- `user_id`: Discord snowflake of the consumer.
- `item`: the catalog `Item` itself (handler can read price, name, emoji).
- Returns: a flavor string the cog renders to Discord.

If the handler raises, the cog's session context manager rolls everything
back (including the inventory decrement that already happened in
`services.use.consume_item`). So effects that conditionally fail can raise
typed `EconomyError` subclasses freely.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from .items import Item

# Public type alias so handlers and the registry agree on shape.
EffectHandler = Callable[[AsyncSession, int, Item], Awaitable[str]]


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #


async def _feast(session: AsyncSession, user_id: int, item: Item) -> str:
    """Bread (and future hearty foods).

    Pure flavor for now. Once a stamina/buff system lands this will set a
    short-lived "well-fed" key in Redis and the next /work payout will
    bump up by some percentage. The handler stays the seam for that.
    """
    return f"You eat the {item.name.lower()}. Crusty, warm, satisfying."


async def _caffeinate(session: AsyncSession, user_id: int, item: Item) -> str:
    """Coffee (and future stimulants).

    Also pure flavor for now. Hooking point for a "caffeinated" buff that
    shortens the /work cooldown by a tier on the next attempt.
    """
    return f"You sip the {item.name.lower()}. Energy returns."


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


EFFECTS: dict[str, EffectHandler] = {
    "feast": _feast,
    "caffeinate": _caffeinate,
}
