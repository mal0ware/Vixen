"""ORM models. Importing this package registers every table on Base.metadata
so Alembic can autogenerate migrations against the full schema.
"""

from .base import Base, TimestampMixin
from .guild import Guild
from .inventory import InventoryItem
from .lottery import LotteryEntry
from .reminder import Reminder
from .snipe import SnipeScore
from .transaction import Transaction
from .user import User

__all__ = [
    "Base",
    "Guild",
    "InventoryItem",
    "LotteryEntry",
    "Reminder",
    "SnipeScore",
    "TimestampMixin",
    "Transaction",
    "User",
]
