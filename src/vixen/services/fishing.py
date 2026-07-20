"""Fishing service.

Players who own a `fishing_rod` (durable — kept and re-used) can /fish to
get a random weighted catch and a cash payout. The rod is not consumed;
the buy-in (1500 cash) is the only gate.

Catch table

    Catch                 Rarity   Cash
    🪨  Old boot           30 %     5
    🐟  Common fish        30 %    25
    🐠  Tropical fish      20 %    75
    🐡  Pufferfish         12 %   150
    🦈  Shark               5 %   500
    🦑  Kraken              3 %  2000

Expected value per cast = 0.30·5 + 0.30·25 + 0.20·75 + 0.12·150 + 0.05·500
                        + 0.03·2000  ≈ 127 cash.

That's higher than /work's average of ~75, so the fishing rod is a real
investment with a real payback (~12 casts to pay for itself).

The function reads the rod check, picks the catch, and writes cash —
all on one session for atomicity. If the cog's session rolls back, the
catch is undone.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from .economy import EconomyError, change_cash
from .shop import has_item


@dataclass(frozen=True, slots=True)
class Catch:
    """One row of the fishing-catch table."""

    name: str
    emoji: str
    weight: int  # relative probability — does NOT have to sum to 100
    payout: int


# Catch table. Weights are relative; we normalize at pick time.
# Order is descending rarity for readability — the picker is order-
# independent.
CATCH_TABLE: tuple[Catch, ...] = (
    Catch(name="Kraken",        emoji="🦑", weight=3,  payout=2000),
    Catch(name="Shark",         emoji="🦈", weight=5,  payout=500),
    Catch(name="Pufferfish",    emoji="🐡", weight=12, payout=150),
    Catch(name="Tropical fish", emoji="🐠", weight=20, payout=75),
    Catch(name="Common fish",   emoji="🐟", weight=30, payout=25),
    Catch(name="Old boot",      emoji="🪨", weight=30, payout=5),
)


# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class NoRodError(EconomyError):
    """User attempted /fish without a fishing_rod in their inventory."""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def _pick_catch(rng: random.Random | None = None) -> Catch:
    """Pick one catch using the weight column. Test seam: pass a seeded RNG."""
    rng = rng or random
    return rng.choices(
        population=CATCH_TABLE,
        weights=[c.weight for c in CATCH_TABLE],
        k=1,
    )[0]


async def do_fish(
    session: AsyncSession,
    user_id: int,
    *,
    rng: random.Random | None = None,
) -> tuple[Catch, int]:
    """Cast once. Returns (catch, new_balance).

    Raises:
        NoRodError: user doesn't own a fishing_rod.

    The rod is NOT consumed. Each cast goes to change_cash so the catch is
    audit-logged (`reason="fish_<catch_name>"`) and the leaderboard updates.
    """
    if not await has_item(session, user_id, "fishing_rod"):
        raise NoRodError("user has no fishing_rod")

    catch = _pick_catch(rng)
    # Snake-case the catch name for the audit reason. Old boot → "fish_old_boot".
    reason = f"fish_{catch.name.lower().replace(' ', '_')}"
    new_balance = await change_cash(session, user_id, catch.payout, reason=reason)
    return catch, new_balance
