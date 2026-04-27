"""One-shot data import: data/rpg.json -> Postgres `users` + `transactions`.

Run once after the schema migration to preserve any pre-existing balances:

    python scripts/import_legacy_rpg.py

Idempotent: re-running does NOT double-import. If a user row already exists,
it's left alone. Drop this script after you've verified the import and
removed `data/rpg.json` from the working tree.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from vixen.db import dispose_db, get_session, init_db
from vixen.models import Transaction, User

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RPG_JSON = PROJECT_ROOT / "data" / "rpg.json"


async def main() -> None:
    init_db()
    try:
        if not RPG_JSON.exists():
            print(f"no file at {RPG_JSON}, nothing to import")
            return

        with RPG_JSON.open(encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            print("rpg.json is empty, nothing to import")
            return

        print(f"importing {len(data)} user(s) from {RPG_JSON}")

        async with get_session() as session:
            for discord_id_str, info in data.items():
                discord_id = int(discord_id_str)
                cash = int(info.get("cash", 0))

                existing = await session.get(User, discord_id)
                if existing is not None:
                    print(
                        f"  skip {discord_id_str}: row exists "
                        f"(cash={existing.cash})"
                    )
                    continue

                session.add(User(discord_id=discord_id, cash=cash, bank=0))
                # Audit row so the imported balance has a paper trail.
                # Skip if cash is 0 — change_cash refuses zero-deltas, and we
                # follow the same rule here for consistency.
                if cash != 0:
                    session.add(
                        Transaction(
                            user_discord_id=discord_id,
                            delta=cash,
                            reason="import_legacy_rpg",
                        )
                    )
                print(f"  import {discord_id_str}: cash={cash}")

        print("import complete")
    finally:
        await dispose_db()


if __name__ == "__main__":
    asyncio.run(main())
