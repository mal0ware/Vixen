# Vixen

> *Very Intelligent Xenial Evolving Network*

A personal Discord assistant + economy / mini-game bot, built for self-hosting in my own servers. Inspired by [Dank Memer](https://dankmemer.lol/) for the economy / mini-game pattern, but with first-class personal-assistant features (finance dashboards, reminders, weather, notes) layered on top.

> **Status:** v0.2 scaffolding — fresh Python rewrite (the old discord.js bot lives untouched in `vixenjavascriptarchive/`). Bot still runs on the legacy `main.py` + JSON files; the new `src/vixen/` skeleton is being filled in cog-by-cog.

> **License:** UNLICENSED. Personal use only. Repo is private.

---

## Tech stack

Deliberately conventional. Everything below is also used in [Linger](https://github.com/mal0ware/Linger), so what you learn carries over.

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Async, batteries-included, matches Linger. |
| Discord library | [`discord.py`](https://discordpy.readthedocs.io/) 2.x | Official-quality, hybrid commands (slash + prefix in one decorator), modern `setup_hook` lifecycle. |
| HTTP | `aiohttp` | Async; doesn't block the event loop the way `requests` does. |
| Config | `pydantic-settings` | Typed env vars; fail-fast at boot if anything's missing. |
| Database | PostgreSQL 16 | Relational, transactional, free, scales further than you'd expect. |
| ORM | SQLAlchemy 2.0 (async) | Standard. Pairs with Alembic for schema versioning. |
| Migrations | Alembic | Versioned schema changes that replay against any DB. |
| Cache / hot state | Redis 7 | Cooldowns, rate limits, leaderboards (sorted sets), prefix cache. |
| Logging | `structlog` | Structured logs you can grep / ship to a log aggregator. |
| Process supervisor | `systemd` (prod) / direct (dev) | Plain Python, no JS-flavored process manager. |
| Local infra | Docker Compose | Postgres + Redis in containers; no host pollution. |
| Tests | pytest + pytest-asyncio + dpytest | Standard. dpytest mocks the Discord API. |
| Lint / format | ruff | One tool replaces black + isort + flake8 + pyupgrade. |
| Type check | mypy | Strict optional, opt-in. |

### What identifies a user, across all servers

Every Discord account has a 64-bit ID (a "snowflake") that never changes. discord.py hands it to every command via `ctx.author.id`. Vixen keys its `users` table off that ID, so a user's wallet, inventory, and stats follow them across every server they meet the bot in. There's no magic — every Discord bot has access to this; the work is in actually persisting it.

---

## Repository layout

```
vixen/
├── pyproject.toml             # deps + tool config (ruff, mypy, pytest)
├── docker-compose.yml         # local Postgres + Redis
├── alembic.ini                # alembic config
├── alembic/
│   ├── env.py                 # async-aware migration runner
│   └── versions/              # generated migrations (one per schema change)
├── src/vixen/
│   ├── __init__.py
│   ├── __main__.py            # `python -m vixen` -> bot.run()
│   ├── bot.py                 # VixenBot subclass + entrypoint
│   ├── config.py              # pydantic-settings Settings
│   ├── logging.py             # structlog setup
│   ├── db.py                  # async SQLAlchemy session factory
│   ├── cache.py               # Redis async client
│   ├── models/                # ORM models — one file per table
│   │   ├── base.py            # Base + TimestampMixin
│   │   ├── user.py            # cash, bank, follows user across guilds
│   │   ├── guild.py           # per-server settings (prefix, etc.)
│   │   ├── inventory.py       # user-owned items (qty per item_key)
│   │   ├── lottery.py         # entries staked into the current lottery draw
│   │   ├── reminder.py        # scheduled reminders + fired flag
│   │   └── transaction.py     # append-only audit log of cash movements
│   └── services/              # business logic — cogs stay thin
│       ├── economy.py         # change_cash, get_or_create_user, typed errors
│       ├── shop.py            # buy/sell/list/has_item primitives
│       ├── items.py           # static item catalog
│       ├── effects.py         # /use effect-handler registry
│       ├── use.py             # /use orchestration (consume + dispatch effect)
│       ├── cooldown.py        # Redis escalating cooldown service
│       ├── leaderboard.py     # Redis ZSET wealth leaderboard
│       ├── fishing.py         # /fish weighted catch table
│       ├── lottery.py         # /lottery enter/pool/draw mechanics
│       ├── robbery.py         # /rob outcomes (blocked/failed/succeeded)
│       ├── reminders.py       # /remind create/list/cancel + due polling
│       └── prefix.py          # per-guild prefix with Redis cache
├── tests/
│   ├── conftest.py            # per-test Postgres DB + Redis db=1 fixtures
│   └── services/              # service-layer tests (real DB + Redis, no mocks)
│
├── cogs/                      # ACTIVE LOAD PATH — both new- and old-shape cogs live here
│   ├── economy.py             # NEW SHAPE — /profile, /work, /coinflip
│   ├── shop.py                # NEW SHAPE — /shop, /buy, /sell, /inventory
│   ├── use.py                 # NEW SHAPE — /use consumables
│   ├── leaderboard.py         # NEW SHAPE — /leaderboard top, /leaderboard rank
│   ├── games.py               # NEW SHAPE — /dice, /slots
│   ├── fishing.py             # NEW SHAPE — /fish
│   ├── lottery.py             # NEW SHAPE — /lottery enter/pool/draw
│   ├── robbery.py             # NEW SHAPE — /rob
│   ├── reminders.py           # NEW SHAPE — /remind set/list/cancel + polling
│   ├── prefix.py              # NEW SHAPE — /setprefix admin command
│   └── (others)               # OLD SHAPE — admin, attendance, avatar, doge,
│                              #  fin, help, modal, moderation, snipe, utility, view
├── data/                      # LEGACY — JSON state files; deleted as each cog migrates
├── main.py                    # LEGACY — old bot entrypoint, superseded by src/vixen/bot.py
├── prefixes.json              # LEGACY — no longer read; replaced by Guild + Redis prefix service
├── data.json                  # LEGACY — read by remaining old-shape cogs
│
└── vixenjavascriptarchive/    # archived discord.js v13 bot from 2022
```

Two senses of "legacy" coexist during the migration — see [Cogs and services](#cogs-and-services) below for what they mean and why the new-shape cogs live in the root `cogs/` directory rather than under `src/vixen/`.

---

## Getting started (dev)

### 1. Install Python 3.12+ and Docker

- Python: https://www.python.org/downloads/
- Docker Desktop: https://www.docker.com/products/docker-desktop/

### 2. Bring up Postgres + Redis

```bash
docker compose up -d
```

Verifies with `docker compose ps` — both should be `healthy`.

> **Ports:** Postgres is exposed on host port **5433** (not the default 5432), Redis on **6380** (not the default 6379). This is intentional — Linger uses the defaults, and Vixen needs to coexist on the same machine. Inside the containers the standard ports are used; only the host-side mapping is offset.

### 3. Set up the Python environment

From the repo root:

```bash
python -m venv .venv
.venv\Scripts\activate           # Windows
# source .venv/bin/activate      # macOS / Linux / WSL

pip install -e ".[dev]"
```

`-e` (editable) means `import vixen` resolves to your working copy, so file edits are picked up without reinstalling.

### 4. Configure `.env`

```bash
cp .env.example .env
```

Then fill in:

- `DISCORD_TOKEN` — from https://discord.com/developers/applications/&lt;APP_ID&gt;/bot → "Reset Token"
- `GUILD_ID` — your dev guild's ID. Right-click the server icon → "Copy Server ID" (Developer Mode must be enabled in Discord settings).

The default `DATABASE_URL` and `REDIS_URL` already match what `docker-compose.yml` exposes.

### 5. Apply migrations

Once `src/vixen/bot.py` is in place and the first migration is generated:

```bash
alembic upgrade head
```

This creates the `users`, `guilds`, `inventory_items`, and `transactions` tables.

To generate a new migration after editing models:

```bash
alembic revision --autogenerate -m "add foo column"
alembic upgrade head
```

### 6. Run the bot

For now (legacy entrypoint):

```bash
python main.py
```

After the cog migration:

```bash
python -m vixen
```

---

## Architecture

```
                 ┌─────────────────────┐
                 │   Discord Gateway   │ (WebSocket — events in)
                 └──────────┬──────────┘
                            │
                ┌───────────▼───────────┐
                │   discord.py 2.x      │ ─── aiohttp ──► external APIs
                │   (VixenBot subclass) │                 (yfinance, weather, …)
                └───────────┬───────────┘
                  ┌─────────┴─────────┐
                  ▼                   ▼
              Postgres              Redis
        (durable state:       (hot state:
         users, guilds,        cooldowns,
         inventory,            leaderboards,
         transactions)         prefix cache,
                               rate limits)
```

### Why two stores

Postgres is for things that must survive a restart and need real queries (joins, aggregates, transactions). Redis is for things that change every few seconds (cooldowns, presence, leaderboards) and only need fast key-based access. Trying to use one for both means you either (a) hammer Postgres with high-frequency writes that don't justify a transaction, or (b) lose user data on Redis restart. The split is the standard pattern.

### Cogs and services

A **cog** is discord.py's term for a class that groups related commands. Every command in Vixen lives in a cog. That isn't changing — what's changing is the *shape* of cogs, not the concept.

#### How a cog runs end-to-end

1. **Boot.** `bot.py` calls `setup_hook` once at startup. That walks the `cogs/` directory and loads every `.py` file as an extension. Each extension registers its `Cog` class with the bot via `await bot.add_cog(MyCog(bot))`.
2. **Sync.** `bot.py` then syncs the application command tree to Discord. In dev that targets only your guild (instant); in prod it's global (slow).
3. **Dispatch.** A user types `/buy bread 2`. Discord pushes the interaction over the gateway. discord.py routes it to `ShopCog.buy(...)` based on the registered command name.
4. **Service call.** The cog opens a session via `async with get_session() as session:`, calls `await buy_item(session, ctx.author.id, "bread", 2)`, and waits for the result.
5. **Persistence.** The service does its DB work on that session. The session's context manager **commits on clean exit** and **rolls back on exception** — that's how atomicity works at the cog boundary.
6. **Reply.** The cog formats the result into a Discord message; typed errors from the service are caught and turned into friendly `ephemeral=True` replies.

#### Two shapes — old (fat) vs. new (thin)

| | Old shape | New shape |
|---|---|---|
| Discord I/O | In the cog | In the cog |
| Business logic | In the cog | In `src/vixen/services/<feature>.py` |
| Persistence | Read/write `data/*.json` directly | SQLAlchemy models + `get_session()` |
| Logging | `print(...)` | `structlog.get_logger(...)` |
| HTTP | `requests` (blocking) | `aiohttp` (async) |
| Tests | Hard — Discord types in every function | Easy — services are plain Python |

`cogs/economy.py` and `cogs/shop.py` are new shape. The other ~12 files in `cogs/` are still old shape and get rewritten one at a time.

#### Why the new cogs are still in the root `cogs/`

The eventual home is `src/vixen/cogs/` — everything Vixen-owned under one importable package. That move hasn't happened yet because the bot's loader currently walks the root `cogs/` directory (see `bot.py`'s `_load_cogs`). Mixing two load paths during migration adds churn for no benefit, so all cogs (new shape and old) share the same directory until the very last legacy cog migrates. At that point the loader path flips to `src/vixen/cogs/` and the root directory disappears in one commit.

So when you read **"legacy"** in this repo, it means one of two independent things:

- **Legacy shape** — fat cog that mixes Discord I/O, business logic, and JSON persistence. Each one rewrites individually.
- **Legacy location** — the root `cogs/` directory. Goes away in one move once nothing legacy-shaped lives there.

The new shop cog is **new shape, legacy location**. That's the normal mid-migration state.

### Mini-game pattern

Every game follows the same shape:

1. Cooldown check via Redis (`SET user:N:cmd:slots EX 5 NX`).
2. Open a Postgres session.
3. Verify balance.
4. Compute outcome.
5. Update balance (single transaction: debit + credit + insert audit row).
6. Reply.

This is the same pattern as Dank Memer's economy and is well-trodden territory.

---

## Adding a feature

Every cog on the new stack follows the same five-step pipeline. The shop (shipped 2026-04-30) is the most recent worked example — copy its shape:

- `src/vixen/services/items.py` — static catalog
- `src/vixen/services/shop.py` — service layer
- `cogs/shop.py` — Discord cog
- `tests/services/test_shop.py` — service tests

### 1. Decide where the data lives

| Need | Where |
|---|---|
| Small fixed catalog (items, recipes, jobs, …) | Static dict in `src/vixen/services/<thing>.py`. Switch to a real DB table only when the catalog grows past ~30 entries or admins need runtime edits. |
| Durable user state that must survive restart | New SQLAlchemy model in `src/vixen/models/`. Add to `models/__init__.py`. Generate a migration. |
| Hot/ephemeral state — cooldowns, leaderboards, rate limits | Redis (when the Redis usage layer lands). For now, `@commands.cooldown` decorators are the placeholder. |

### 2. (Only if you added a model) Create and apply a migration

```bash
alembic revision --autogenerate -m "add foo table"
alembic upgrade head
```

Inspect the generated file in `alembic/versions/` before applying — `--autogenerate` is a starting point, not a contract.

### 3. Write the service (`src/vixen/services/<feature>.py`)

Pure-Python business logic. No Discord types in here — services are testable in plain Python.

Conventions:

1. **Take the session from the caller.** Each function accepts an `AsyncSession` so the cog decides the transaction boundary. Composing two service calls inside one `get_session()` block makes them atomic — both succeed or neither does (e.g. `buy_item` debits cash and adds inventory in one transaction).
2. **Auto-register on first contact.** Use `get_or_create_user(session, discord_id)` so users never see a "please register first" wall.
3. **Audit-on-write.** Every cash mutation writes a `Transaction` row. `change_cash(session, id, delta, reason="...")` does this for you — always go through it, never mutate `User.cash` directly.
4. **Raise typed domain errors.** Define `class FooError(EconomyError)` for each failure mode (e.g. `InsufficientFunds`, `UnknownItem`, `InsufficientItems`). The cog catches these and renders friendly messages. Never let a SQLAlchemy error reach the user.

### 4. Write the cog (`cogs/<feature>.py`)

A thin Discord shim: parse args, call the service, format the reply. Place new cogs at the **repo root `cogs/` directory** — that's still the active load path during the migration. Auto-discovered on next bot startup.

```python
@commands.hybrid_command(help="One-line user-facing description.")
@app_commands.describe(arg="What this argument is for.")
@app_commands.choices(arg=[app_commands.Choice(name="Display", value="key"), ...])  # for fixed-set inputs
async def my_command(self, ctx: commands.Context, arg: str) -> None:
    # Anti-spam cooldown — escalating curve, applied per-user-per-bucket.
    remaining = await try_acquire(ctx.author.id, "my_command")
    if remaining > 0:
        await ctx.reply(f"Slow down — try again in {remaining:.0f}s.", ephemeral=True)
        return

    try:
        async with get_session() as session:
            result = await my_service_call(session, ctx.author.id, arg)
    except KnownDomainError as e:
        await ctx.reply(f"Friendly message using `{e.field}`.", ephemeral=True)
        return
    await ctx.reply(f"Success: {result}")
```

Conventions:

- `@commands.hybrid_command` so both slash (`/cmd`) and prefix (`!cmd`) work in one decorator.
- User-facing errors → `ctx.reply(..., ephemeral=True)` — only the user sees them, no spam.
- Use `<t:UNIX:R>` in embeds for relative timestamps; Discord renders them in the viewer's locale.
- Cog `__init__` should be cheap. No DB calls, no network. Keep heavy lifting in command handlers.
- **Cooldowns**: use `vixen.services.cooldown.try_acquire(user_id, bucket)` for any state-mutating command. The service applies a uniform escalating curve — first attempt free, then 1 s after #1, 3 s after #2, 5 s after #3 onward. The counter resets after 30 s of idle, so casual play never hits the upper end; only sustained spam plateaus at 5 s gaps. Read-only commands (`/shop`, `/inventory`, `/profile`) don't need cooldowns; Discord's own outbound rate limit handles message flooding.

End the file with:

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```

### 5. Write tests (`tests/services/test_<feature>.py`)

Service tests use the `db_session` fixture from `tests/conftest.py` — real Postgres on the test database, schema applied once, tables truncated between tests. No DB mocking; nothing fakes around real semantics.

Cover at minimum:
- Happy path
- Each typed error path
- Any rollback / atomicity invariant (e.g. "a failed buy must not have left an inventory row")

```bash
pytest tests/services/test_<feature>.py -v
```

### 6. Run and smoke-test

```bash
.venv/bin/python3 -m vixen
```

In your dev guild, exercise each command. Slash commands sync to the dev guild on every startup (fast). Prod uses global sync (slow, hours of propagation) — only when shipping a stable surface.

### Checklist

- [ ] (If new table) model added, `models/__init__.py` updated, migration generated and applied
- [ ] Service module written; takes session from caller; raises typed errors
- [ ] Cog written; `@commands.hybrid_command`; user-facing errors are `ephemeral=True`
- [ ] Tests written and passing
- [ ] `ruff check <new files>` clean (or matches existing project warnings)
- [ ] Smoke-tested in the dev guild

---

## Roadmap

### Done

- [x] Cleanup: remove JS-era leftovers, fix broken refs, rotate leaked token
- [x] Project metadata: `pyproject.toml`, `docker-compose.yml`, `.env.example`
- [x] Source skeleton: `config.py`, `logging.py`, `db.py`, `cache.py`
- [x] Schema: `User`, `Guild`, `InventoryItem`, `Transaction`, `LotteryEntry`, `Reminder`
- [x] Alembic wired (env.py, ini, template) + three migrations applied
- [x] `src/vixen/bot.py` — entrypoint with init_db / init_redis hooks, structured logging, fault-tolerant cog loader, async per-guild prefix callable
- [x] First Alembic migration: the four base tables
- [x] Migrate `rpg_cog` → `cogs/economy.py` (Postgres-backed `/profile`, `/work`, `/coinflip`)
- [x] Service-layer test infrastructure (per-test Postgres DB + Redis db=1, truncate-between-tests, soft-fail when Redis isn't initialized)
- [x] Shop / inventory commands (`/shop`, `/buy`, `/sell`, `/inventory`, `has_item` primitive)
- [x] Redis-backed escalating cooldowns (`services/cooldown.py`; 1s/3s/5s curve, 30s idle reset; wired into every mutating command)
- [x] `/use` consumables loop + effect-handler registry (bread, coffee)
- [x] Redis-backed wealth leaderboard (sorted set; auto-syncs from `change_cash`; `/leaderboard top` + `/leaderboard rank`)
- [x] Replace `print` with `structlog` everywhere active
- [x] Mini-games: `/dice` (2d6 with 10x jackpots) + `/slots` (3-reel, 25x jackpot)
- [x] Fishing cog (`/fish`, weighted catch table, durable rod)
- [x] Lottery cog (`/lottery enter`, `/lottery pool`, `/lottery draw` admin) with new `lottery_entries` table
- [x] Robbery cog (`/rob` with 50/50 odds, padlock defense, 10% failure penalty)
- [x] Reminders cog (`/remind set/list/cancel`) with new `reminders` table and 30-second background poller
- [x] Migrate prefix lookup → `Guild` row + Redis cache (`services/prefix.py`); `/setprefix` admin command

### Deferred (and why)

These items aren't blocked technically, but each needs a decision or substantial work that didn't make sense in the same push:

- [ ] **Replace `requests` with `aiohttp` in `fin_cog`** — `yfinance` is a synchronous library, so the right fix is `asyncio.to_thread(...)` to run yfinance off the event loop, NOT a one-line aiohttp swap. Hold until the fin_cog rewrite.
- [ ] **Replace `requests` with `aiohttp` in `view_cog`, `utility`** — needs reading what each call is actually for; skipped to avoid breaking legacy paths blindly.
- [ ] **Weather cog** — needs an API choice (Open-Meteo for free / no-key, OpenWeatherMap for richer data) and config. User decision.
- [ ] **Tests with `dpytest`** — Discord-side interaction tests. Substantial harness setup; service-layer tests already cover the business logic. Worth doing once the cog surface stabilizes.
- [ ] **Migrate remaining legacy cogs** — `admin`, `attendance`, `avatar_cog`, `doge_cog`, `fin_cog`, `help_cog`, `modal_cog`, `moderation`, `snipe_cog`, `utility`, `view_cog`. Each needs reading + understanding before it can be ported. They run today in their old shape; do these incrementally as you touch them for any other reason.
- [ ] **Delete `data/rpg.json`** — orphaned (rpg_cog migrated to `cogs/economy.py`). Safe to delete after a final visual sanity check; the import script in `scripts/import_legacy_rpg.py` would still need it if you re-import, so deleting is a soft commit to "I'm done with that data."
- [ ] **Delete `data/stats2.json`** — still read by at least `cogs/attendance.py`. Delete after attendance migrates.
- [ ] **Delete `prefixes.json`** — no longer read by `bot.py`. Safe to delete.
- [ ] **Production deploy notes (systemd unit, log shipping)** — needs hosting decisions (Render? Fly.io? VPS?).

### Maybe

- Buff system: `/use` currently emits flavor text. The handler signature already takes `session` + `user_id`, so adding a "well-fed +50% next /work payout" buff is a Redis-backed temporary key away.
- Auto-draw lottery: weekly cron task that calls `services.lottery.draw` without admin invocation.
- Guild settings: extend `Guild` model for disabled commands, mod-log channel, welcome message.

---

## Deploying (forthcoming)

Production runs on a small VPS:

- Postgres + Redis: managed (Render / Neon / Upstash) or co-located.
- Bot: a `systemd` unit that runs `python -m vixen`, restarts on crash, ships stdout to journald.
- Logs: `structlog` JSON output → `journalctl` → optionally forwarded to a log aggregator.

Detailed runbook will live in `docs/DEPLOY.md` once the new `bot.py` is wired.
