"""Typed application config loaded from environment variables.

We use pydantic-settings so every config value is:

- Read from the environment (or .env at startup).
- Validated for type at startup. If DISCORD_TOKEN is missing or GUILD_ID
  isn't an integer, the bot fails immediately on boot rather than crashing
  mid-command somewhere far from the cause.
- Cached by `get_settings()` so we parse the env exactly once.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Discord ---
    # Defaults are deliberate placeholders so utility commands (alembic, ipython,
    # tests) can construct Settings without a real token. The actual bot startup
    # path validates these in `bot.main()` and refuses to launch with placeholders.
    discord_token: str = Field("", description="Bot token from Discord Developer Portal")
    guild_id: int = Field(0, description="Primary dev guild for fast slash-command sync")

    # --- Database / cache ---
    # Non-default host ports (5433 / 6380) — see docker-compose.yml for why.
    database_url: str = Field(
        "postgresql+asyncpg://vixen:vixen@localhost:5433/vixen",
        description="Async SQLAlchemy URL for Postgres",
    )
    redis_url: str = Field(
        "redis://localhost:6380/0",
        description="Redis URL (db 0 by default)",
    )

    # --- Runtime ---
    env: str = Field("dev", description="dev | prod")
    log_level: str = Field("INFO")


@lru_cache
def get_settings() -> Settings:
    """Lazy singleton: first caller pays parse cost, all callers cached."""
    return Settings()  # type: ignore[call-arg]  # required fields supplied by env
