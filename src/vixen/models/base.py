"""Declarative base for all ORM models, plus a mixin for created/updated timestamps.

Every model should subclass `Base`. Models that want auto-tracked timestamps
should additionally mix in `TimestampMixin`.
"""

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Single declarative base for the whole project. Alembic introspects
    `Base.metadata` to autogenerate migrations.
    """


class TimestampMixin:
    """Adds `created_at` and `updated_at` columns. Times are stored in UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
