"""Transaction — append-only audit log for every cash/bank movement.

Why: when a user reports "I had X cash and now I have Y, what happened?",
this table answers in one query. It also lets us implement features like
/balance-history and detect economy bugs (a sudden net-positive spike
across many users probably means a game's payout math is wrong).

Append-only: never UPDATE or DELETE rows here. `delta` is signed: positive
for credits, negative for debits. The current `User.cash` should always
equal SUM(delta) over all transactions for that user with reasons that
affect cash — we can verify this with a periodic reconciliation query.
"""

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.discord_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Signed amount. e.g. +100 for "work", -50 for "coinflip_loss".
    delta: Mapped[int] = mapped_column(Integer, nullable=False)

    # Short machine-readable reason. Used for filtering, e.g. "show me all
    # coinflip results for user X". Keep these short and stable.
    reason: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    user: Mapped["User"] = relationship(back_populates="transactions")  # noqa: F821
