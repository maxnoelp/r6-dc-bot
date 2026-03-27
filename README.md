# R6 Tracker Bot

A Discord bot that tracks Rainbow Six Siege statistics for registered players and posts a daily AI-generated roast report every evening at 22:00.

Built with **pydantic-ai + Google Gemini**, **discord.py**, **PostgreSQL**, and the [R6Data API](https://r6data.eu/api-docs).

---

## Features

- **`!track`** — register your R6 account; the bot fetches your Ubisoft profile ID automatically. Accepts `ubisoft` as a platform alias.
- **`!season`** — full season stats embed with rank badge, player avatar, K/D, W/L, win rate, and top 3 most-played operators with operator artwork
- **Daily snapshot at 00:00** — baseline stats saved for every tracked player
- **Daily report at 22:00** — per-player embed with today's kills, deaths, wins, losses, rank delta, and most-played operator, each post pinging the Discord user
- **AI critique** — Gemini generates a brutal, sarcastic German roast for each player's session
- **Lazy-day detection** — if nobody played, `@everyone` gets an AI-generated insult instead
- **`!stats`** — mid-day delta since the midnight snapshot
- **`!snapshot`** — admin command to manually save a baseline snapshot
- **`!report`** — admin command to trigger the full report immediately
- **`!showsnapshot`** — admin command to inspect the stored snapshot for any registered user (shows date, time, rank, kills, deaths, wins, losses)
- **`!info`** — posts a styled help embed in the command channel

---

## How It Works

### Daily Cycle

```
00:00  Snapshot job runs
       → Fetches current cumulative stats from R6Data API for every tracked user
       → Saves as baseline in PostgreSQL (keyed by discord_id + date)

22:00  Report job runs
       → Fetches live stats again for every user
       → Computes delta: kills, deaths, wins, losses, rank points
       → delta == 0 for a user?  → skip that user (no post)
       → All users have delta == 0? → @everyone + Gemini lazy-day insult
       → Otherwise: for each active user:
           1. Build DailyStats object from delta values
           2. Pass JSON to Gemini via pydantic-ai critic_agent
           3. Gemini returns CritiqueOutput (headline, critique, verdict, rating)
           4. Bot sends a Discord embed to the configured post channel
              with a @mention ping for that user
```

### Why Snapshots?

The R6Data API only provides **cumulative season stats** — there is no per-session or per-day endpoint. The bot solves this by storing a snapshot at midnight and computing the difference (`live - snapshot`) to derive today's activity.

> **Season Reset:** At the start of a new season all stats reset to 0. On reset day the delta may behave unexpectedly. This is a known limitation.

---

## Project Structure

```
r6_agent/
├── main.py                  # Entry point: init DB, create bot, load cogs
├── config.py                # Pydantic-Settings: reads .env
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Local PostgreSQL instance (Podman-compatible)
├── .env.example             # Environment variable template
│
├── bot/
│   ├── cog_stats.py         # !track, !untrack, !stats, !season, !info, !setup
│   └── cog_daily.py         # Scheduler (APScheduler) + !snapshot, !report
│
├── r6api/
│   └── client.py            # Async httpx client for api.r6data.eu
│
├── agent/
│   └── critic.py            # pydantic-ai Agent definitions + Pydantic models
│
└── db/
    ├── database.py          # asyncpg pool init + migration runner
    ├── models.py            # All SQL query functions (no ORM)
    └── migrations/
        └── 001_init.sql     # CREATE TABLE IF NOT EXISTS schema
```

---

## Database Schema

```sql
-- Tracked Discord users
CREATE TABLE users (
    discord_id      BIGINT PRIMARY KEY,         -- Discord user ID (used for pings)
    r6_username     VARCHAR(64) NOT NULL,        -- In-game name
    r6_profile_id   VARCHAR(64) NOT NULL,        -- Ubisoft profile ID (fetched on !track)
    platform        VARCHAR(16) NOT NULL DEFAULT 'uplay',
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Per-guild channel configuration
CREATE TABLE guild_config (
    guild_id            BIGINT PRIMARY KEY,
    post_channel_id     BIGINT NOT NULL,         -- Where daily reports are posted
    command_channel_id  BIGINT NOT NULL,         -- Where bot commands are accepted
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Daily baseline snapshots for delta calculation
CREATE TABLE snapshots (
    id              SERIAL PRIMARY KEY,
    discord_id      BIGINT REFERENCES users(discord_id) ON DELETE CASCADE,
    snapshot_date   DATE NOT NULL,
    rank            VARCHAR(32),
    rank_points     INT,
    total_kills     INT,
    total_deaths    INT,
    total_wins      INT,
    total_losses    INT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (discord_id, snapshot_date)
);
```

---

## Setup

### Prerequisites

- Python 3.11+
- Docker or Podman (for local PostgreSQL via `docker-compose`)
- A Discord bot token with **Message Content** and **Server Members** privileged intents enabled
- An [R6Data API key](https://r6data.eu/dashboard)
- A [Google Gemini API key](https://aistudio.google.com) (free tier available)

### 1. Clone & install dependencies

```bash
git clone <repo-url>
cd r6_agent
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
DISCORD_TOKEN=your_discord_bot_token
R6DATA_API_KEY=your_r6data_api_key
DATABASE_URL=postgresql://r6bot:r6bot@localhost:5432/r6bot
GOOGLE_API_KEY=your_gemini_api_key

# Optional — defaults shown
DAILY_HOUR=22
DAILY_MINUTE=0
SNAPSHOT_HOUR=0
SNAPSHOT_MINUTE=0
COMMAND_PREFIX=!
```

### 3. Start PostgreSQL

```bash
docker-compose up -d
```

> On Fedora/Podman: the `docker-compose.yml` uses `docker.io/library/postgres:16` explicitly to avoid registry resolution issues.

The schema is applied automatically on first bot start via `db/migrations/001_init.sql`.

### 4. Run the bot

```bash
python main.py
```

### 5. First-time Discord setup

Run this once in any channel (before `!setup`, all channels are accepted):

```
!setup #bashing #bot-commands
```

Then register your account:

```
!track YourUsername uplay
```

---

## Bot Commands

| Command | Who | Description |
|---|---|---|
| `!track <username> [platform]` | Anyone | Register your R6 account. Platform defaults to `uplay`. Aliases: `ubisoft` → `uplay`, `xbox` → `xbl`, `ps4`/`ps5` → `psn`. |
| `!untrack` | Anyone | Stop tracking your account and delete all your snapshots. |
| `!stats` | Anyone | Show today's delta (kills, W/L, rank change) since the midnight snapshot. |
| `!stats @user` | Anyone | Show another registered user's today delta. |
| `!season` | Anyone | Full season stats embed: rank badge, avatar, K/D, W/L, win rate, top 3 operators. |
| `!season @user` | Anyone | Season stats for another registered user. |
| `!info` | Anyone | Posts a styled help embed listing all commands and how to register. |
| `!setup #post #commands` | Admin | Set the channel for daily reports and the channel for commands. |
| `!snapshot` | Admin | Manually save a baseline snapshot for all users right now. |
| `!report` | Admin | Manually trigger the full 22:00 report right now. |
| `!showsnapshot [@user]` | Admin | Show the stored snapshot for a user: creation time, rank, kills, deaths, wins, losses. |

> Commands sent outside the configured command channel are silently ignored. Before `!setup` is run, all channels are accepted.

---

## !season Embed

The `!season` command produces a rich embed:

- **Accent color** matched to rank tier (Copper = brown, Silver = grey, Gold = yellow, Platinum = teal, Emerald = green, Diamond = blue, Champion = orange)
- **Rank badge** from `r6data.eu/assets/img/r6_ranks_img/{rank}.webp` as the author icon
- **Player avatar** from the Ubisoft CDN as the embed thumbnail
- **Stats fields:** Kills, Deaths, K/D · Wins, Losses, Win Rate
- **Top 3 operators** with lifetime rounds played and W/L
- **Most-played operator artwork** as the embed image

---

## Daily Report Example

```
@prinz

💀 Totale Enttäuschung im Ranked

Rang         Platinum 1 (+12 RP)
K/D heute    14K / 11D  (KD: 1.27)
W/L heute    4W / 3L
Operator     Tachanka (8 Runden)
Rating       4/10 — Mittelmaß mit Einbildung

"14 Kills in 7 Runden — ich habe schon Ash-Mains gesehen, die mit
geschlossenen Augen mehr reißen..."
```

---

## Lazy-Day Report Example (all deltas = 0)

```
@everyone

💤 Komplettes Totalversagen heute.
Keiner von euch hat auch nur eine Runde angefasst. Ihr sitzt auf der Couch,
esst Chips und habt Angst vor dem Ranked-Abbau. Nächstes Mal melde ich euch
beim Fortnite-Kids-Turnier an — da passen eure Skills besser hin.
```

Gemini generates a different variation every day.

---

## Architecture Notes

### pydantic-ai Agents

Two agents are defined in `agent/critic.py`, both using `google-gla:gemini-2.0-flash` via `GoogleProvider`:

| Agent | Input | Output | Purpose |
|---|---|---|---|
| `critic_agent` | `DailyStats` as JSON string | `CritiqueOutput` (headline, critique, verdict, rating) | Per-player daily roast |
| `lazy_day_agent` | Trigger string | `LazyDayOutput` (message) | @everyone insult when nobody played |

Agents use `output_type=` (pydantic-ai ≥ 1.x) and results are accessed via `result.output`.

### R6Data API

All stats are fetched from `https://api.r6data.eu` with the `api-key` header. The key endpoints used:

| Endpoint | Purpose |
|---|---|
| `GET /api/stats?type=accountInfo` | Profile lookup, player avatar URL |
| `GET /api/stats?type=stats` | Ranked season stats (deeply nested under `platform_families_full_profiles`) |
| `GET /api/stats?type=operatorStats` | Per-operator lifetime rounds across all playlists |
| `GET /api/operators?name=<name>` | Operator metadata including `icon_url` |

> Operator names containing non-ASCII characters (e.g. **Jäger**) are percent-encoded via `urllib.parse.quote()` before being embedded in image URLs.

All three stats endpoints require `nameOnPlatform`, `platformType`, and `platform_families` parameters.

### Rank System

Ranks are mapped by ID (0–36) returned from the stats API:
- 0 = Unranked
- 1–5 = Copper 5–1, 6–10 = Bronze 5–1, ..., 31–35 = Diamond 5–1, 36 = Champion

Rank badge images are served by r6data.eu at:
```
https://r6data.eu/assets/img/r6_ranks_img/{rank-slug}.webp
```
e.g. `platinum-1.webp`, `diamond-3.webp`, `champion.webp`

### Channel Guard

Every command calls `_in_command_channel()` before executing. If a `guild_config` row exists and the message was sent in a different channel, the command is silently dropped.

### Scheduler Timezone

APScheduler runs with `timezone="Europe/Berlin"`. `DAILY_HOUR=22` means 22:00 CET/CEST, not UTC.

---

## Limitations

- **No match history** — the R6Data API only exposes cumulative season stats. Individual match scores and round-by-round data are not available.
- **Operator stats are cumulative** — operator stats are lifetime totals, not per-day. Both `!stats` and `!season` show the top operator by total rounds played, not exclusively today's games.
- **Seasonal data only** — stats reset each season. At season start, deltas will be 0 until the snapshot catches up.
- **Single guild per user** — if the same Discord user is in multiple guilds where the bot is active, they receive one ping per guild's post channel.

---

## License

MIT
