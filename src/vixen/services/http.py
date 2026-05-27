"""Shared aiohttp session for outbound HTTP.

Cogs that talk to upstream APIs (utility's /dog, doge_cog, future news/
options endpoints) share one ClientSession per process. Re-creating
sessions per request leaks sockets, burns DNS lookups, and prevents
connection reuse — all of which add up at human-Discord scale.

Public surface:

    get_session() -> aiohttp.ClientSession   (lazily creates on first call)
    close_session()                           (called from bot shutdown)

`services.weather` predates this module and keeps its own session. We
could fold weather into here later — both run a single shared pool —
but the migration isn't urgent.
"""

from __future__ import annotations

import aiohttp

_session: aiohttp.ClientSession | None = None


async def get_session() -> aiohttp.ClientSession:
    """Return the shared session, creating it on first call.

    10-second total timeout matches Discord's interaction window — a
    slow upstream is preferable to a stalled command. The User-Agent
    identifies us politely to upstream services.
    """
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10),
            headers={"User-Agent": "Vixen-Bot (personal Discord assistant)"},
        )
    return _session


async def close_session() -> None:
    """Close the shared session. Call from bot shutdown."""
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
