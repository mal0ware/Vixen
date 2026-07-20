<div align="center">

# 🦊 Vixen

**Very Intelligent Xenial Evolving Network**

A personal Discord assistant and economy / mini-game bot, built for self-hosting.
Inspired by [Dank Memer](https://dankmemer.lol/) for the economy pattern, with
first-class personal-assistant features (finance charts, reminders, weather,
notes) layered on top.

[![CI](https://github.com/mal0ware/Vixen/actions/workflows/ci.yml/badge.svg)](https://github.com/mal0ware/Vixen/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)](#)
[![discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Postgres](https://img.shields.io/badge/postgres-16-336791?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/redis-7-DC382D?logo=redis&logoColor=white)](https://redis.io/)
[![Style: ruff](https://img.shields.io/badge/style-ruff-FCC21B)](https://docs.astral.sh/ruff/)
[![License](https://img.shields.io/badge/license-MIT-3FB950)](#license)

[![Commands](https://img.shields.io/badge/slash--commands-38-7289DA)](#commands)
[![Cogs](https://img.shields.io/badge/cogs-22-7289DA)](#project-structure)
[![Tables](https://img.shields.io/badge/postgres--tables-7-336791)](#database-schema)
[![Tests](https://img.shields.io/badge/tests-154%20passing-3FB950)](#testing)
[![LOC](https://img.shields.io/badge/python-9.4k%20LOC-3572A5)](#)

</div>

---

## Table of contents

- [Features](#features)
- [Commands](#commands)
  - [Economy](#-economy)
  - [Shop & Inventory](#-shop--inventory)
  - [Mini-games](#-mini-games)
  - [Finance / Charts](#-finance--charts)
  - [Weather](#%EF%B8%8F-weather)
  - [Reminders](#-reminders)
  - [Leaderboards](#-leaderboards)
  - [Attendance](#-attendance)
  - [Utility](#-utility)
  - [Moderation](#-moderation)
  - [Admin / Owner](#%EF%B8%8F-admin--owner-only)
  - [Help](#-help)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Architecture](#architecture)
  - [Cogs and services](#cogs-and-services)
  - [Database schema](#database-schema)
  - [How a cog runs end-to-end](#how-a-cog-runs-end-to-end)
- [Adding a feature](#adding-a-feature)
- [Testing](#testing)
- [Project structure](#project-structure)
- [Roadmap](#roadmap)
- [License](#license)

---

## Features

- 💰 **Persistent economy** — cash, bank, transaction-audit log, Postgres-backed
- 🛒 **Shop & inventory** — static catalog, atomic buy / sell / use
- 🎰 **Mini-games** — `/dice`, `/slots`, `/coinflip`, `/rps`, `/fish`, `/lottery`, `/rob`
- 📊 **Interactive finance charts** — yfinance-backed; line / candle / RSI / MACD / Bollinger; in-place timeframe buttons
- ☁️ **Weather** — Open-Meteo current conditions + multi-day forecast (no API key)
- ⏰ **Reminders** — DM yourself in `5m`, `1h30m`, `2d`, etc. Background poller fires due reminders.
- 🏆 **Live leaderboards** — Redis sorted set, auto-syncs on every cash event
- 🛡️ **Anti-spam cooldowns** — Redis-backed escalating curve (1s → 3s → 5s plateau, 30s idle reset)
- 🔧 **Per-guild prefixes** — Postgres source of truth, Redis-cached lookup
- 📚 **Discoverability** — `/help` groups every command into clean categories
- ⚙️ **Owner & moderation** — `/sync`, `/reload-cog`, `/ban`, `/unban`, `/kick` with structured audit logging

---

## Commands

Click a header to jump to the section. Permissions and cooldowns are listed in
each table; "—" means no cooldown beyond Discord's own outbound rate limit, and
"💰" means the command costs or pays cash.

### 💰 Economy

| Command | What it does | Args | Cost / Cooldown |
|---|---|---|---|
| `/profile` | Show cash, bank, item count, account age. | `[user]` | — |
| `/work` | Earn 25–125 cash. | — | escalating |
| `/coinflip` | Bet on a coin flip (1:1). | `wager` | 💰 / escalating |

### 🛒 Shop & Inventory

| Command | What it does | Args | Cost / Cooldown |
|---|---|---|---|
| `/shop` | Browse the item catalog. | — | — |
| `/buy` | Buy an item. Atomic: cash debit + inventory increment. | `item` `[qty]` | 💰 / escalating |
| `/sell` | Sell back at 25 % of buy price. | `item` `[qty]` | 💰 / escalating |
| `/inventory` | Show your or another user's inventory. | `[user]` | — |
| `/use` | Consume one of an item, run its effect handler. | `item` | escalating |

**Catalog** (5 items): 🍞 Bread, ☕ Coffee, 🎣 Fishing Rod, 🎟️ Lottery Ticket, 🔒 Padlock.
Bread and coffee are consumables; the rest are functional items used by other commands.

### 🎰 Mini-games

| Command | What it does | Args | Cost / Cooldown |
|---|---|---|---|
| `/dice` | Roll 2d6. Snake-eyes / boxcars (2 or 12) pay 10×, 7 returns wager, all else loses. | `wager` | 💰 / escalating |
| `/slots` | Spin 3 reels. All-three-match wins 25×; otherwise lose. | `wager` | 💰 / escalating |
| `/fish` | Cast a line. Random catch from a weighted table; rod is durable. | — | escalating, **needs `🎣 Fishing Rod`** |
| `/rps` | Rock-paper-scissors against the bot. Optional cash wager. | `[wager]` | 💰 if wagered |
| `/lottery enter` | Stake `lottery_ticket`s into the current draw. | `[count=1]` | escalating, **needs `🎟️ Lottery Ticket`** |
| `/lottery pool` | Show current pot + entry count. | — | — |
| `/lottery draw` *(admin)* | Pick a weighted-random winner; pay out; reset entries. | — | — |
| `/rob` | Try to steal cash from a target. 50 % success, padlock blocks once. | `target` | 💰 / escalating |

### 📊 Finance / Charts

Backed by yfinance (free historical data), rendered with matplotlib + mplfinance
in a Discord-themed dark palette at 150 DPI. All commands accept any timeframe
in `{1d, 5d, 1mo, 3mo, 1y, 5y}`.

| Command | What it does | Args |
|---|---|---|
| `/chart` | **Primary command.** Renders a chart and attaches **interactive timeframe buttons** that re-render the same message in place. | `ticker` `[timeframe=3mo]` `[chart_type=line]` |
| `/candles` | OHLC candlestick chart with volume sub-pane. | `ticker` `[timeframe]` |
| `/rsi` | Price + MAs on top, RSI on bottom. | `ticker` `[timeframe]` |
| `/moving_average` | Price + MA20 + MA50. | `ticker` `[timeframe]` |
| `/compare` | 2–6 tickers normalized to a common base (100), winner gets 🏆. | `tickers` `[timeframe]` |

`chart_type` choices: **Line + MAs**, **Candles**, **Price + RSI**, **MACD**, **Bollinger Bands**.

### ☁️ Weather

Open-Meteo geocoding + forecast — no API key required.

| Command | What it does | Args |
|---|---|---|
| `/weather` | Current conditions + 3-day forecast for a city. | `city` |
| `/forecast` | Multi-day forecast (1–7 days). | `city` `[days=5]` |

### ⏰ Reminders

Background poller wakes every 30 s, fires due reminders as DMs.

| Command | What it does | Args |
|---|---|---|
| `/remind set` | Schedule a future DM. Duration syntax: `5m`, `1h30m`, `2d`. | `duration` `message` |
| `/remind list` | Show your pending reminders. | — |
| `/remind cancel` | Cancel one of your reminders by ID. | `reminder_id` |

### 🏆 Leaderboards

Redis sorted-set, auto-synced on every cash event.

| Command | What it does | Args |
|---|---|---|
| `/leaderboard top` | Top 10 users by total wealth (cash + bank). | — |
| `/leaderboard rank` | Your rank + total wealth. | — |
| `/snipe_leaderboard` | Paginated snipe-game scoreboard (legacy points). | — |

### 📜 Attendance

| Command | What it does | Args |
|---|---|---|
| `/attendance` | Open a meeting check-in embed for a SIG role. Members click to register; first-timers get a UCID-entry modal. | `sig` |

### 🔧 Utility

| Command | What it does | Args | Permission |
|---|---|---|---|
| `/avatar` | Show a user's avatar at full size. | `[user]` | — |
| `/dog` | Random dog photo from dog.ceo. | — | — |
| `/echo` | Send a message via configured webhook. | `message` | Manage Messages |
| `/modal` | Interactive demo (button + modal patterns). | — | — |
| `/doge` | DOGE.gov savings boxplot. | `[endpoint]` `[sort_by]` `[sort_order]` `[page]` `[per_page]` | — |

### 🛡️ Moderation

| Command | What it does | Args | Permission |
|---|---|---|---|
| `/ban` | Ban a user from the server. | `user` `[reason]` | Ban Members |
| `/unban` | Unban by user ID. | `user_id` `[reason]` | Ban Members |
| `/kick` | Kick a user. | `user` `[reason]` | Kick Members |

All three log to Discord's audit log AND to structlog.

### ⚙️ Admin / Owner-only

| Command | What it does | Args | Permission |
|---|---|---|---|
| `/setprefix` | Set this server's command prefix. Updates Postgres + invalidates Redis cache. | `new_prefix` | Administrator |
| `/sync` | Resync slash commands. | `[scope=guild]` | Bot owner |
| `/reload-cog` | Hot-reload one cog by name. | `cog_name` | Bot owner |
| `/debug-commands` | List every registered slash command. | — | Bot owner |

### 📚 Help

| Command | What it does | Args |
|---|---|---|
| `/help` | Overview embed grouped by category, or detail for one command. | `[name]` |

---

## Quickstart

### 1. Install Python 3.12+ and Postgres + Redis

Two paths:

**Docker** (matches `docker-compose.yml`):

```bash
docker compose up -d
```

**Native (macOS Homebrew)** — leaner if you don't want Docker:

```bash
brew install postgresql@16 redis
brew services start postgresql@16
brew services start redis
createdb vixen
```

Default ports: Postgres `5432`, Redis `6379` (native) or `5433` / `6380` (Docker offset).

### 2. Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Configure `.env`

```bash
cp .env.example .env
```

Fill in:

| Variable | What |
|---|---|
| `DISCORD_TOKEN` | From the Discord Developer Portal → Bot → Reset Token |
| `GUILD_ID` | Your dev server's ID (Developer Mode → right-click server → Copy ID) |
| `DATABASE_URL` | Defaults match `docker-compose.yml`. Override for native Postgres. |
| `REDIS_URL` | Defaults match `docker-compose.yml`. Override for native Redis. |
| `ENV` | `dev` (per-guild fast sync) or `prod` (global sync). |

### 4. Apply migrations

```bash
alembic upgrade head
```

Creates 7 tables: `users`, `guilds`, `inventory_items`, `transactions`,
`lottery_entries`, `reminders`, `snipe_scores`.

### 5. Run the bot

```bash
python -m vixen
```

Look for `bot_ready user=<name> user_id=<id>` in the logs.

---

## Configuration

All config flows through `pydantic-settings` (see `src/vixen/config.py`).
Values are read from environment variables, falling back to `.env`.

| Variable | Default | Notes |
|---|---|---|
| `DISCORD_TOKEN` | _(empty — fast-fails on launch)_ | Bot token. Required. |
| `GUILD_ID` | `0` _(empty — required when `ENV=dev`)_ | Primary dev guild for fast slash sync. |
| `DATABASE_URL` | `postgresql+asyncpg://vixen:vixen@localhost:5433/vixen` | Async SQLAlchemy URL. |
| `REDIS_URL` | `redis://localhost:6380/0` | Redis URL. db=0 in production. |
| `ENV` | `dev` | `dev` (per-guild sync) or `prod` (global sync). |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `WEBHOOK_URL` | _(unset)_ | Optional. Used by `/echo`. |

---

## Architecture

```
                 ┌─────────────────────┐
                 │   Discord Gateway   │ (WebSocket — events in)
                 └──────────┬──────────┘
                            │
                ┌───────────▼───────────┐
                │   discord.py 2.x      │ ─── aiohttp ──► external APIs
                │   (VixenBot subclass) │                 (yfinance, Open-Meteo,
                └───────────┬───────────┘                  dog.ceo, doge.gov)
                  ┌─────────┴─────────┐
                  ▼                   ▼
              Postgres              Redis
        (durable state:       (hot state:
         users, guilds,        cooldowns,
         inventory,            leaderboards,
         transactions,         prefix cache)
         lottery, reminders,
         snipe_scores)
```

### Why two stores

Postgres is for things that must survive restart and need real queries (joins,
aggregates, transactions). Redis is for things that change every few seconds
(cooldowns, leaderboards) and only need fast key-based access. Trying to use
one for both means you either hammer Postgres with high-frequency writes or
lose user data on Redis restart. The split is the standard pattern.

### Cogs and services

A **cog** is discord.py's term for a class that groups related commands.
Every command in Vixen lives in a cog — that part is unchanged from the
JS-era bot. What's changed is the **shape** of cogs.

#### Old shape (fat) vs. new shape (thin)

| | Old shape | New shape |
|---|---|---|
| Discord I/O | In the cog | In the cog |
| Business logic | In the cog | In `src/vixen/services/<feature>.py` |
| Persistence | Read/write `data/*.json` directly | SQLAlchemy models + `get_session()` |
| Logging | `print(...)` | `structlog.get_logger(...)` |
| HTTP | `requests` (blocking) | `aiohttp` (async) |
| Tests | Hard — Discord types in every function | Easy — services are plain Python |

**All 22 active cogs are now new-shape.**

### Database schema

7 tables, all migrated by Alembic (4 migrations applied):

| Table | What it stores |
|---|---|
| `users` | One row per Discord account. `cash`, `bank`, `ucid`. |
| `guilds` | Per-server settings — currently just `prefix`. |
| `inventory_items` | UNIQUE(user, item_key) → quantity. |
| `transactions` | Append-only audit log of every cash mutation. Indexed on `(user, created_at)`. |
| `lottery_entries` | Tickets staked into the current lottery draw. Truncated on `/lottery draw`. |
| `reminders` | Scheduled future DMs. `due_at` indexed alongside `fired`. |
| `snipe_scores` | Legacy snipe-game leaderboard. Indexed on `points` for fast top-N. |

### How a cog runs end-to-end

1. **Boot** — `bot.py` walks `cogs/` and loads every `.py` as an extension via `bot.load_extension`.
2. **Sync** — `bot.tree.sync()` ships the application command tree to Discord (per-guild in dev, global in prod).
3. **Dispatch** — user runs `/buy bread 2`. Discord sends an interaction over the gateway → discord.py routes to `ShopCog.buy(...)`.
4. **Cooldown check** — cog calls `try_acquire(user_id, "shop_buy")`. Redis SET NX EX in one round-trip; if locked, reply with remaining time and bail.
5. **Service call** — cog opens `async with get_session() as session:` and invokes `await buy_item(session, user_id, "bread", 2)`.
6. **Persistence** — service writes to Postgres on the session. Context manager **commits on clean exit**, **rolls back on exception** — that's how atomicity works at the cog boundary.
7. **Reply** — cog formats the result; typed errors from the service get rendered as friendly `ephemeral=True` messages.

---

## Adding a feature

Every cog on the new stack follows the same six-step pipeline. The shop
(`cogs/shop.py` + `services/shop.py` + `tests/services/test_shop.py`) is
the canonical worked example — copy its shape.

### 1. Decide where the data lives

| Need | Where |
|---|---|
| Small fixed catalog (items, recipes, jobs) | Static dict in `services/<thing>.py`. Switch to a real DB table when the catalog grows past ~30 entries or admins need runtime edits. |
| Durable user state | New SQLAlchemy model in `models/`. Add to `models/__init__.py`. Generate a migration. |
| Hot/ephemeral state — cooldowns, leaderboards, rate limits | Redis. Use `services/cooldown.py` for anti-spam, `services/leaderboard.py` for ZSET-based rankings. |

### 2. (Only if you added a model) Create and apply a migration

```bash
alembic revision --autogenerate -m "add foo table"
alembic upgrade head
```

Inspect the generated file in `alembic/versions/` before applying — `--autogenerate` is a starting point, not a contract.

### 3. Write the service (`src/vixen/services/<feature>.py`)

Pure-Python business logic. **No Discord types** — services are testable in plain Python.

Conventions:

1. **Take the session from the caller.** Each function accepts an `AsyncSession` so the cog decides the transaction boundary.
2. **Auto-register on first contact** with `get_or_create_user(session, discord_id)`.
3. **Audit-on-write.** Every cash mutation writes a `Transaction` row via `change_cash`.
4. **Raise typed errors.** `class FooError(EconomyError)` per failure mode. The cog catches and renders friendly messages.

### 4. Write the cog (`cogs/<feature>.py`)

Thin Discord shim: parse args, call the service, format the reply.

```python
@commands.hybrid_command(help="One-line user-facing description.")
@app_commands.describe(arg="What this argument is for.")
@app_commands.choices(arg=[app_commands.Choice(name="Display", value="key"), ...])
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
- `@commands.hybrid_command` for both slash (`/cmd`) and prefix (`!cmd`) in one decorator.
- User-facing errors → `ctx.reply(..., ephemeral=True)`.
- `<t:UNIX:R>` in embeds for relative timestamps; Discord renders them client-side.
- `__init__` should be cheap — no DB calls, no network.
- Cooldowns: free → 1s → 3s → 5s plateau, 30s idle reset. Read-only commands don't need them.

End the file with:

```python
async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```

### 5. Write tests (`tests/services/test_<feature>.py`)

Service tests use the `db_session` fixture from `tests/conftest.py` — real
Postgres on a separate test database, schema applied once, tables truncated
between tests. Need Redis? Add the `redis_client` fixture too — flushes db=1
between tests. **No mocking.**

Cover at minimum: happy path, each typed error path, any rollback / atomicity invariant.

```bash
pytest tests/services/test_<feature>.py -v
```

### 6. Run and smoke-test

```bash
.venv/bin/python3 -m vixen
```

In your dev guild, exercise each command. Slash commands sync to the dev
guild on every startup (fast). Prod uses global sync (slow, hours of
propagation).

### Checklist

- [ ] (If new table) model added, `models/__init__.py` updated, migration generated and applied
- [ ] Service module written; takes session from caller; raises typed errors
- [ ] Cog written; `@commands.hybrid_command`; user-facing errors are `ephemeral=True`
- [ ] Tests written and passing
- [ ] `ruff check <new files>` clean
- [ ] Smoke-tested in the dev guild

---

## Testing

```bash
pytest                            # full suite (~5s on a hot cache)
pytest tests/services/test_shop.py -v
pytest -k "leaderboard"
```

The test infrastructure:

- **Real Postgres**, separate `vixen_test` database, dropped + recreated at session start.
- **Real Redis**, db=1 (production uses db=0), flushed between tests.
- **Per-test truncation**: every test starts on an empty database. CASCADE handles foreign keys; RESTART IDENTITY resets autoincrement sequences.
- **No mocking**: BigInteger, ondelete=CASCADE, sorted sets, transactional rollbacks — semantics SQLite or in-memory mocks fake or break. Real semantics, real bugs.

Override the test DB / Redis URLs:

```bash
TEST_DATABASE_URL="postgresql+asyncpg://user@localhost:5432/vixen_test" \
TEST_REDIS_URL="redis://localhost:6379/1" \
pytest
```

---

## Project structure

```
vixen/
├── pyproject.toml             # deps + tool config (ruff, mypy, pytest)
├── docker-compose.yml         # local Postgres + Redis
├── alembic/
│   ├── env.py                 # async-aware migration runner
│   └── versions/              # 4 migrations applied so far
├── src/vixen/
│   ├── __main__.py            # `python -m vixen` -> bot.run()
│   ├── bot.py                 # VixenBot subclass + entrypoint
│   ├── config.py              # pydantic-settings Settings
│   ├── logging.py             # structlog setup
│   ├── db.py                  # async SQLAlchemy session factory
│   ├── cache.py               # Redis async client
│   ├── models/                # 7 ORM tables
│   └── services/              # business logic — 20 modules
├── cogs/                      # 22 cogs, all new-shape
├── scripts/                   # one-off CLI utilities
│   ├── import_legacy_rpg.py   # legacy economy import
│   └── import_legacy_stats.py # legacy UCID + snipe scores import
├── tests/
│   ├── conftest.py            # db_session + redis_client fixtures
│   └── services/              # 154 service-layer tests
│
└── vixenjavascriptarchive/    # archived discord.js v13 bot from 2022
```

---

## Roadmap

### Done

<details>
<summary>Foundation (click to expand)</summary>

- [x] Project metadata, source skeleton, structlog logging, async SQLAlchemy, Redis client
- [x] Schema: User, Guild, InventoryItem, Transaction, LotteryEntry, Reminder, SnipeScore
- [x] Alembic — 4 migrations applied
- [x] `bot.py` entrypoint with init_db / init_redis hooks, fault-tolerant cog loader, async per-guild prefix callable
- [x] Service-layer test infrastructure — per-test Postgres DB + Redis db=1, soft-fail without Redis
- [x] Redis-backed escalating cooldowns (1s → 3s → 5s plateau, 30s idle reset)

</details>

<details>
<summary>Features</summary>

- [x] Economy — `/profile`, `/work`, `/coinflip`
- [x] Shop & inventory — `/shop`, `/buy`, `/sell`, `/inventory`, `/use` (with effect-handler registry)
- [x] Leaderboard — Redis ZSET, `/leaderboard top` and `/leaderboard rank`, auto-syncs from `change_cash`
- [x] Mini-games — `/dice`, `/slots`, `/rps` (with optional cash wager)
- [x] Fishing — `/fish` with weighted catch table; durable rod
- [x] Lottery — `/lottery enter`/`pool`/`draw`, weighted random winner, dedicated table
- [x] Robbery — `/rob` with 50/50 odds, padlock defense, 10 % failure penalty
- [x] Reminders — `/remind set`/`list`/`cancel` with 30s background poller
- [x] Per-guild prefix — Postgres + Redis cache, `/setprefix` admin command
- [x] Finance — async yfinance, dark theme, 150 DPI in-memory PNGs
- [x] `/chart` with interactive timeframe buttons + chart-type selector
- [x] `/candles`, `/rsi`, `/moving_average`, MACD, Bollinger Bands, `/compare`
- [x] Weather — `/weather` and `/forecast` via Open-Meteo (no API key)
- [x] Help — category-grouped overview + per-command detail
- [x] Admin — `/sync`, `/reload-cog`, `/debug-commands`
- [x] Moderation — typed error handling + structured audit log

</details>

<details>
<summary>Migration sweep</summary>

- [x] Migrate `rpg_cog` → `cogs/economy.py`
- [x] Migrate `attendance` → uses `users.ucid`
- [x] Migrate `snipe_cog` → uses `snipe_scores` table
- [x] Migrate `fin_cog`, `help_cog`, `avatar_cog`, `modal_cog`, `utility`, `doge_cog`, `admin`, `moderation`, `view_cog`
- [x] Replace blocking `requests` with `aiohttp` (or `to_thread` where the upstream lib is sync — yfinance)
- [x] Replace `print` with `structlog` everywhere
- [x] Delete orphaned legacy files: `data/rpg.json`, `data/stats2.json`, `main.py`, `prefixes.json` (gitignored)
- [x] Drop `bot.legacy_data` / `bot.legacy_stats2` aliases — bot is JSON-free at runtime

</details>

### Deferred

- [ ] **Tests with `dpytest`** — Discord-side interaction tests. 154 service-layer tests already cover the business logic; dpytest worth doing once the cog surface stabilizes.
- [ ] **Production deploy notes** — needs a hosting decision (Render? Fly.io? VPS?). Once chosen: systemd unit, log shipping config, deploy runbook.

### Maybe / future

- Buff system: `/use` currently emits flavor text. The handler signature already takes `session` + `user_id`, so adding "well-fed +50 % next /work payout" via a Redis temp key is a small change.
- Auto-draw lottery: weekly cron task that calls `services.lottery.draw` without admin invocation.
- Indicator-switching dropdown on `/chart` alongside the timeframe buttons.
- News / earnings / options-chain commands via yfinance's other endpoints.
- Multi-server snipe leaderboards via `/snipe-add-points` admin command.

---

## License

**MIT** — see [LICENSE](LICENSE).

This bot is built for self-hosting on the author's own servers, but the code
is free to read, fork, and reuse under the MIT terms.

---

<div align="center">

Built with ❤️ and a lot of `async with`.

</div>
