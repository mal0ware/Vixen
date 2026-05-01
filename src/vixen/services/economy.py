"""Economy service.

Cogs call these functions to manipulate the persistent economy state.

Design rules:

1. **Sessions come from the caller.** Each function takes an `AsyncSession`
   so the cog can decide the transaction boundary. This makes it possible
   to compose multiple service calls inside one transaction (e.g. a future
   shop command might do `change_cash(-price)` and `add_inventory(item)`
   atomically — both succeed or neither does).

2. **Auto-registration.** `get_or_create_user` silently creates a row on
   first contact. The user never sees a "please register first" wall.

3. **Audit-on-write.** Every cash mutation records a row in `transactions`.
   Past balance state is reconstructible by summing deltas, which is
   useful for debugging and for `/balance-history` later.

4. **Domain errors are typed.** Cogs catch `InsufficientFunds` and friends
   and turn them into user-facing messages. Don't leak SQLAlchemy errors
   to the user.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Transaction, User
from . import leaderboard

# --------------------------------------------------------------------------- #
# Domain errors
# --------------------------------------------------------------------------- #


class EconomyError(Exception):
    """Base class for economy-layer errors."""


class InsufficientFunds(EconomyError):
    """User attempted to spend more cash than they have."""

    def __init__(self, *, have: int, need: int):
        self.have = have
        self.need = need
        super().__init__(f"insufficient funds: have {have}, need {need}")


class InvalidAmount(EconomyError):
    """Caller passed a non-positive or otherwise invalid amount."""


# --------------------------------------------------------------------------- #
# User lifecycle
# --------------------------------------------------------------------------- #


async def get_or_create_user(session: AsyncSession, discord_id: int) -> User:
    """Return the User row for `discord_id`, creating it if it doesn't exist.

    First-contact creation. The session is NOT committed here — the caller's
    `async with get_session()` block does that on clean exit.
    """
    user = await session.get(User, discord_id)
    if user is None:
        user = User(discord_id=discord_id, cash=0, bank=0)
        session.add(user)
        # flush() pushes the INSERT to the DB without committing the
        # transaction, so created_at / updated_at get populated and any
        # subsequent reads in this session see the row.
        await session.flush()
    return user


# --------------------------------------------------------------------------- #
# Cash mutations
# --------------------------------------------------------------------------- #


async def change_cash(
    session: AsyncSession,
    discord_id: int,
    delta: int,
    *,
    reason: str,
) -> int:
    """Apply a signed cash delta to a user, record an audit row, return new balance.

    Args:
        session: Active DB session.
        discord_id: Target user's Discord snowflake.
        delta: Signed integer. Positive credits, negative debits.
        reason: Short machine-readable label, e.g. "work", "coinflip_win".
            Stored in `transactions.reason` for filtering.

    Raises:
        InvalidAmount: delta is 0. Zero-delta calls are bugs (no-ops shouldn't
            create transaction rows).
        InsufficientFunds: delta would push the user's cash below zero.
    """
    if delta == 0:
        raise InvalidAmount("delta=0 is a bug — refusing to write a no-op transaction")

    user = await get_or_create_user(session, discord_id)
    new_cash = user.cash + delta
    if new_cash < 0:
        raise InsufficientFunds(have=user.cash, need=-delta)

    user.cash = new_cash
    session.add(
        Transaction(
            user_discord_id=discord_id,
            delta=delta,
            reason=reason,
        )
    )

    # Keep the leaderboard ZSET in step with the DB. Soft-fails when Redis
    # isn't initialized (alembic, plain economy tests), so callers don't
    # have to know whether Redis is up. See services.leaderboard.sync_user.
    await leaderboard.sync_user(session, discord_id)

    return new_cash
