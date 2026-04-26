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
│   ├── bot.py                 # (forthcoming) VixenBot + entrypoint
│   ├── config.py              # pydantic-settings Settings
│   ├── logging.py             # structlog setup
│   ├── db.py                  # async SQLAlchemy session factory
│   ├── cache.py               # Redis async client
│   ├── models/                # ORM models
│   │   ├── base.py            # Base + TimestampMixin
│   │   ├── user.py            # cash, bank, follows user across guilds
│   │   ├── guild.py           # per-server settings (prefix, etc.)
│   │   ├── inventory.py       # user-owned items (qty per item_key)
│   │   └── transaction.py     # append-only audit log of cash movements
│   ├── services/              # (forthcoming) business logic — cogs stay thin
│   └── cogs/                  # (forthcoming) command modules, organized by domain
├── tests/                     # (forthcoming)
│
├── cogs/                      # LEGACY — still live, JSON-backed; migrating to src/vixen/cogs/
├── data/                      # LEGACY — JSON state files; migrating to Postgres
├── main.py                    # LEGACY — current bot entrypoint
├── prefixes.json              # LEGACY
├── data.json                  # LEGACY
│
└── vixenjavascriptarchive/    # archived discord.js v13 bot from 2022
```

The legacy files at the root keep the bot running while migration proceeds. They get deleted once `src/vixen/` is feature-complete.

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

### Cogs vs services

A **cog** is discord.py's term for a module of related commands. In Vixen, cogs are kept *thin* — they parse arguments, call a service, and format the reply. The actual logic (compute payout, debit balance, write audit row) lives in `src/vixen/services/`. This keeps tests easy: services have no Discord dependency, so they can be tested in plain Python without mocking the API.

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

## Roadmap

- [x] Cleanup: remove JS-era leftovers, fix broken refs, rotate leaked token
- [x] Project metadata: `pyproject.toml`, `docker-compose.yml`, `.env.example`
- [x] Source skeleton: `config.py`, `logging.py`, `db.py`, `cache.py`
- [x] Schema: `User`, `Guild`, `InventoryItem`, `Transaction`
- [x] Alembic wired (env.py, ini, template)
- [ ] `src/vixen/bot.py` — refactored entrypoint with init_db / init_redis hooks
- [ ] First Alembic migration: create the four base tables
- [ ] Migrate `rpg_cog` to use `User` + `Transaction` instead of `data/rpg.json`
- [ ] Migrate prefix lookup to `Guild` + Redis cache
- [ ] Replace `requests` with `aiohttp` in `fin_cog`, `view_cog`, `utility`
- [ ] Replace `print` with `structlog` everywhere
- [ ] Mini-games: blackjack, slots, dice, fishing, lottery
- [ ] Shop / inventory commands
- [ ] Leaderboards via Redis sorted sets
- [ ] Reminders cog
- [ ] Weather cog
- [ ] Tests with `dpytest`
- [ ] Production deploy notes (systemd unit, log shipping)

---

## Deploying (forthcoming)

Production runs on a small VPS:

- Postgres + Redis: managed (Render / Neon / Upstash) or co-located.
- Bot: a `systemd` unit that runs `python -m vixen`, restarts on crash, ships stdout to journald.
- Logs: `structlog` JSON output → `journalctl` → optionally forwarded to a log aggregator.

Detailed runbook will live in `docs/DEPLOY.md` once the new `bot.py` is wired.
