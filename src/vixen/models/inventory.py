"""Inventory — what items each user owns and how many.

Pattern: one row per (user, item_key). UNIQUE constraint on the pair makes
"give the user 3 fishing rods" a single UPSERT instead of a check-then-write.

`item_key` is a short string identifier ("fishing_rod", "lottery_ticket")
that joins to a separate items catalog at the application level — we don't
model items as a table yet, because the catalog is small and lives in code.
We add a real `items` table when the catalog grows or admins need to edit
items at runtime.
"""

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("user_discord_id", "item_key", name="uq_user_item"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    user_discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.discord_id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    item_key: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    user: Mapped["User"] = relationship(back_populates="inventory_items")  # noqa: F821
