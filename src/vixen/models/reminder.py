"""Reminder — a single scheduled DM to send to a user at a future time.

Lifecycle: a row is created when /remind set runs. A background task in
the cog polls every ~30 s for rows where `due_at <= now AND fired = false`,
DMs each user, then sets `fired = true`. We keep the row (instead of
deleting) so /remind list can show recently-fired reminders if we want.

Why a `fired` boolean instead of deleting on send: deletes are forever; if
we ever want to show "you got these reminders this week" we'd have lost
the data. The `fired` index makes the polling query just as cheap.
"""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Reminder(Base, TimestampMixin):
    __tablename__ = "reminders"
    __table_args__ = (
        # Composite index for the polling query: due_at + fired.
        # Postgres can use this to find unfired due reminders fast even with
        # millions of rows.
        Index("ix_reminders_due_fired", "due_at", "fired"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.discord_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Display text shown back to the user when the reminder fires. Cap at
    # 500 characters; anything longer was probably an accident anyway.
    message: Mapped[str] = mapped_column(String(500), nullable=False)

    # Absolute UTC timestamp when the reminder fires. Stored with timezone
    # so we don't get bit by daylight saving across server moves.
    due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # False until the cog's poll task fires the DM. Always set to True
    # after attempting to fire — even on DM-failed paths, so we don't spam
    # the user retrying.
    fired: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
