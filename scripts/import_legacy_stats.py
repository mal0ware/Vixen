"""One-shot import: data.json["ucids"] + data/stats2.json -> Postgres.

Run once after the migration that adds `users.ucid` and the `snipe_scores`
table:

    python scripts/import_legacy_stats.py

Two imports in one script — both pull from JSON files that the legacy
bot wrote at runtime:

    data.json
        Has a top-level "ucids" object: {discord_id_str: ucid_str}
        Each entry becomes a `users.ucid` value.

    data/stats2.json
        Top-level: {discord_id_str: {"name": "...", "overall points": N, ...}}
        Each entry becomes a `snipe_scores` row.

Idempotency

- UCIDs: only set if the user row's ucid is currently NULL. Re-running
  doesn't overwrite a UCID a user manually re-registered after import.
- Snipe scores: skipped if a row already exists for that user. Same
  reasoning — first import wins.

Drop this script after the import is verified and `data/stats2.json` is
removed from the tree.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from vixen.db import dispose_db, get_session, init_db
from vixen.models import SnipeScore
from vixen.services.economy import get_or_create_user

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_JSON = PROJECT_ROOT / "data.json"
STATS_JSON = PROJECT_ROOT / "data" / "stats2.json"


def _safe_load(path: Path) -> dict:
    """Return parsed JSON or {} if missing / invalid. Logs to stderr."""
    if not path.exists():
        print(f"no file at {path}, skipping")
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"can't read {path}: {e}")
        return {}


async def _import_ucids(data: dict) -> int:
    """Import UCIDs from data.json["ucids"] -> users.ucid. Returns import count."""
    ucids = data.get("ucids") or {}
    if not ucids:
        print("data.json has no 'ucids' section; nothing to import")
        return 0

    imported = 0
    async with get_session() as session:
        for discord_id_str, ucid in ucids.items():
            discord_id = int(discord_id_str)
            ucid = str(ucid).strip()
            if not ucid:
                print(f"  skip ucid for {discord_id_str}: empty value")
                continue

            user = await get_or_create_user(session, discord_id)
            if user.ucid is not None:
                print(
                    f"  skip ucid for {discord_id_str}: already set ({user.ucid!r})"
                )
                continue

            user.ucid = ucid
            print(f"  import ucid {discord_id_str}: {ucid!r}")
            imported += 1

    return imported


async def _import_snipe(data: dict) -> int:
    """Import snipe scores from stats2.json -> snipe_scores. Returns count."""
    if not data:
        print("stats2.json is empty; nothing to import")
        return 0

    imported = 0
    async with get_session() as session:
        for discord_id_str, details in data.items():
            try:
                discord_id = int(discord_id_str)
            except ValueError:
                print(f"  skip {discord_id_str}: not a numeric discord_id")
                continue

            # The legacy schema is loose — defensively pull out what we need.
            name = str(details.get("name", "")).strip() or f"User-{discord_id_str}"
            try:
                points = int(details.get("overall points", 0))
            except (TypeError, ValueError):
                points = 0

            existing = await session.get(SnipeScore, discord_id)
            if existing is not None:
                print(
                    f"  skip score for {discord_id_str}: row exists "
                    f"(points={existing.points})"
                )
                continue

            # Guarantee the FK target exists before we add the score row.
            await get_or_create_user(session, discord_id)
            session.add(
                SnipeScore(
                    user_discord_id=discord_id,
                    name=name,
                    points=points,
                )
            )
            print(f"  import score {discord_id_str}: {name!r} = {points}")
            imported += 1

    return imported


async def main() -> None:
    init_db()
    try:
        ucid_data = _safe_load(DATA_JSON)
        snipe_data = _safe_load(STATS_JSON)

        ucid_count = await _import_ucids(ucid_data)
        snipe_count = await _import_snipe(snipe_data)

        print(f"import complete: {ucid_count} UCIDs, {snipe_count} snipe scores")
    finally:
        await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())
