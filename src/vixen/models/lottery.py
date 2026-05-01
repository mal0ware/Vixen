"""LotteryEntry — tickets a user has staked into the current lottery draw.

Why a dedicated table (instead of using inventory_items):

- Inventory holds **owned** lottery_tickets. Once a user runs /lottery enter,
  the tickets are *consumed* (removed from inventory) and become *entries*
  in the current draw. They're now committed and can't be sold back.
- Lottery rounds are episodic — once /lottery draw runs, every entry is
  paid out (or zeroed) and the table is truncated. Inventory can't model
  that lifecycle without ugly state flags.

Schema

    user_discord_id   PK + FK -> users.discord_id (CASCADE delete)
    tickets           INT, > 0

One row per (user_in_current_draw). Multiple entries from the same user
accumulate via UPSERT in the service layer. After /lottery draw runs, the
service truncates the table — fresh round.

The pot value is *not* stored. It's derived: `sum(tickets) * ticket_price`
where ticket_price is the catalog price of `lottery_ticket` at draw time.
"""

from sqlalchemy import BigInteger, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class LotteryEntry(Base, TimestampMixin):
    __tablename__ = "lottery_entries"

    user_discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.discord_id", ondelete="CASCADE"),
        primary_key=True,
    )
    tickets: Mapped[int] = mapped_column(Integer, nullable=False)
