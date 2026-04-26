"""structlog setup.

structlog gives us *structured* logs — every log line is a dict (key/value
pairs), not free-form text. This matters in production because:

- You can grep on `event=command_failed user_id=123` instead of guessing
  at substring matches.
- A log shipper (Loki / Datadog / Cloudwatch) can index the fields.

In dev we render the dict as colored text via ConsoleRenderer; in prod
we render JSON so log shippers can ingest it directly.
"""

import logging
import sys

import structlog

from .config import get_settings


def setup_logging() -> None:
    """Call once at startup, before any log line is emitted."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # Send stdlib `logging` output to stdout at the configured level so that
    # discord.py's own logger (which uses stdlib logging) flows through too.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    if settings.env == "prod":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Module-level convenience: `log = get_logger(__name__)`."""
    return structlog.get_logger(name)
