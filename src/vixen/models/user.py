"""User — keyed off the Discord user_id.

One row per Discord account that has ever interacted with Vixen, regardless
of which guild they were in. This is the table that makes the bot feel
"personal" across servers — wallet balance, inventory, and stats all follow
the user, not the guild.

`discord_id` is a 64-bit Discord snowflake; we store it directly as the
primary key (no surrogate `id` column), so foreign keys from other tables
are also Discord IDs. Easier to grep, no extra join.
"""

from sqlalchemy import BigInteger, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)

    # Two purses. `cash` is what you risk in mini-games; `bank` is safe
    # storage that has to be deposited/withdrawn explicitly. Same pattern
    # Dank Memer uses — gives you a reason to gate big bets behind a
    # /withdraw friction step so single bad clicks don't wipe everything.
    cash: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bank: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    inventory_items: Mapped[list["InventoryItem"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
    transactions: Mapped[list["Transaction"]] = relationship(  # noqa: F821
        back_populates="user"
    )
