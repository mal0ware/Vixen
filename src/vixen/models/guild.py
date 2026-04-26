"""Guild — per-Discord-server settings.

Right now this only stores the custom command prefix. As features grow
(disabled commands, mod-log channel ID, welcome message), columns get
added here via Alembic migrations.
"""

from sqlalchemy import BigInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class Guild(Base, TimestampMixin):
    __tablename__ = "guilds"

    discord_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    prefix: Mapped[str] = mapped_column(String(10), default="!", nullable=False)
