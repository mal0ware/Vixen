"""Robbery service.

Players can /rob another user. Three outcomes:

    blocked    — target owned a padlock; it's consumed defending. No cash moved.
    failed     — 50% chance; thief loses a fraction of their own cash as penalty.
    succeeded  — 50% chance; thief steals a random fraction of target's cash.

Tunables (kept as module-level constants so they're easy to find and adjust)

    SUCCESS_RATE      probability of success when no padlock blocks
    STEAL_PCT_MIN/MAX random fraction of target's cash that's stolen on success
    FAILURE_PENALTY_PCT fraction of thief's cash they lose on a failed attempt

Audit log

A theft writes TWO transactions: positive `rob_steal_from:<target>` for the
thief, negative `rob_stolen_by:<thief>` for the target. That way the audit
log makes both sides reconstructible by sum-of-deltas just like every other
cash event. A failed attempt writes one `rob_failure_penalty` for the
thief. A blocked attempt writes no transactions — only an inventory
decrement on the target's padlock.

Self-rob and validation (target alive, target != thief) is the COG's job —
this service trusts the caller. Keeping the trust boundary at the cog
edge means the service can be called from a future "auto-rob" feature
or admin tool without re-checking those rules.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from .economy import EconomyError, change_cash, get_or_create_user
from .shop import has_item, remove_item

# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #


SUCCESS_RATE = 0.50
STEAL_PCT_MIN = 0.10
STEAL_PCT_MAX = 0.25
FAILURE_PENALTY_PCT = 0.10


# --------------------------------------------------------------------------- #
# Result type
# --------------------------------------------------------------------------- #


RobOutcome = Literal["blocked", "failed", "succeeded"]


@dataclass(frozen=True, slots=True)
class RobResult:
    """Outcome of a single /rob attempt.

    Fields:
        outcome:        which branch ran; cog uses this to pick its reply.
        cash_moved:     0 if blocked; penalty paid by thief on fail;
                        amount stolen from target on success.
        thief_balance:  thief's cash AFTER the rob settles.
        target_balance: target's cash AFTER the rob settles.
    """

    outcome: RobOutcome
    cash_moved: int
    thief_balance: int
    target_balance: int


# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class TargetBroke(EconomyError):
    """Target has zero cash — nothing worth stealing."""


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


async def do_rob(
    session: AsyncSession,
    thief_id: int,
    target_id: int,
    *,
    rng: random.Random | None = None,
) -> RobResult:
    """Run one robbery attempt. See module docstring for outcomes.

    Raises:
        TargetBroke: target has 0 cash, nothing to steal. We reject before
            consuming the target's padlock — defense-in-depth so the
            target doesn't lose a 2500-cash padlock blocking a 0-cash rob.
    """
    rng = rng or random

    # Make sure both rows exist for FK + balance reads.
    thief = await get_or_create_user(session, thief_id)
    target = await get_or_create_user(session, target_id)

    if target.cash <= 0:
        raise TargetBroke("target has nothing to steal")

    # Defense check: padlock blocks one rob, then is consumed. The check
    # runs BEFORE the success roll, so the rng position is still
    # available for tests (tests can seed and predict success/failure).
    if await has_item(session, target_id, "padlock"):
        await remove_item(session, target_id, "padlock", qty=1)
        return RobResult(
            outcome="blocked",
            cash_moved=0,
            thief_balance=thief.cash,
            target_balance=target.cash,
        )

    if rng.random() < SUCCESS_RATE:
        # Success: steal a random fraction of target's cash.
        pct = rng.uniform(STEAL_PCT_MIN, STEAL_PCT_MAX)
        # Round to int. Min 1 so a tiny target still loses something to a
        # successful rob — otherwise the roll succeeded but cash_moved=0
        # would be confusing in the reply.
        amount = max(1, int(target.cash * pct))

        new_target = await change_cash(
            session, target_id, -amount, reason=f"rob_stolen_by:{thief_id}"
        )
        new_thief = await change_cash(
            session, thief_id, amount, reason=f"rob_steal_from:{target_id}"
        )
        return RobResult(
            outcome="succeeded",
            cash_moved=amount,
            thief_balance=new_thief,
            target_balance=new_target,
        )

    # Failure: thief loses a fraction of their own cash. If thief has 0
    # cash, the penalty is 0 — change_cash refuses zero-delta calls, so
    # we skip the DB write and report the no-op penalty.
    penalty = max(0, int(thief.cash * FAILURE_PENALTY_PCT))
    if penalty > 0:
        new_thief = await change_cash(
            session, thief_id, -penalty, reason="rob_failure_penalty"
        )
    else:
        new_thief = thief.cash

    return RobResult(
        outcome="failed",
        cash_moved=penalty,
        thief_balance=new_thief,
        target_balance=target.cash,
    )
