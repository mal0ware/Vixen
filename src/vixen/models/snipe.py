"""SnipeScore — per-user score for the snipe leaderboard.

Pre-migration this lived in `data/stats2.json` keyed by Discord user_id
with values like `{"name": "...", "overall points": 42, ...}`. The bot
reads-and-displays only; the actual point-awarding lives in another
process (or has been retired). Migrating to Postgres so:

1. The display path doesn't depend on a JSON file pinned in git.
2. Future point-awarding commands have a clean place to write.

Schema is deliberately narrow — discord_id, name (display string), points.
The legacy JSON had other ad-hoc fields per user; those were never read
by `snipe_cog.LeaderboardView` so we drop them on import. If any of them
turn out to matter, add explicit columns and a fresh migration.
"""

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TimestampMixin


class SnipeScore(Base, TimestampMixin):
    __tablename__ = "snipe_scores"
    __table_args__ = (
        # Index on points DESC for the leaderboard sort. Without this,
        # /snipe_leaderboard scans the whole table on every page load.
        Index("ix_snipe_scores_points", "points"),
    )

    user_discord_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.discord_id", ondelete="CASCADE"),
        primary_key=True,
    )
    # Display name as captured at score-write time. Not authoritative —
    # we don't keep it in lockstep with Discord's user.display_name (that
    # would require an event listener that we'd have to keep maintained).
    # Good enough for "who scored this?" rendering.
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
