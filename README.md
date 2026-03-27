# R6 Tracker Bot

A Discord bot that tracks Rainbow Six Siege statistics for registered players and posts a daily AI-generated roast report every evening at 22:00.

Built with **pydantic-ai + Claude**, **discord.py**, **PostgreSQL**, and the [R6Data API](https://r6data.eu/api-docs).

---

## Features

- **`!track`** — register your R6 account; the bot fetches your Ubisoft profile ID automatically
- **Daily snapshot at 00:00** — baseline stats saved for every tracked player
- **Daily report at 22:00** — per-player embed with today's kills, deaths, wins, losses, rank delta, and most-played operator, each post pinging the Discord user
- **AI critique** — Claude generates a brutal, sarcastic German roast for each player's session
- **Lazy-day detection** — if nobody played, `@everyone` gets an AI-generated insult instead
- **`!stats`** — request your own mid-day delta at any time
- **`!report`** — admin command to trigger the full report immediately (for testing)

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
       → All users have delta == 0? → @everyone + Claude lazy-day insult
       → Otherwise: for each active user:
           1. Build DailyStats object from delta values
           2. Pass JSON to Claude via pydantic-ai critic_agent
           3. Claude returns CritiqueOutput (headline, critique, verdict, rating)
           4. Bot sends a Discord embed to the configured post channel
              with a @mention ping for that user
```

### Why Snapshots?

The R6Data API only provides **cumulative lifetime stats** — there is no per-session or per-day endpoint. The bot solves this by storing a snapshot at midnight and computing the difference (`live - snapshot`) to derive today's activity.

---

## Project Structure

```
r6_agent/
├── main.py                  # Entry point: init DB, create bot, load cogs
├── config.py                # Pydantic-Settings: reads .env
├── requirements.txt         # Python dependencies
├── docker-compose.yml       # Local PostgreSQL instance
├── .env.example             # Environment variable template
│
├── bot/
│   ├── cog_stats.py         # !track, !untrack, !stats, !setup commands
│   └── cog_daily.py         # Scheduler (APScheduler) + !report command
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
- Docker (for local PostgreSQL via `docker-compose`)
- A Discord bot token with **Message Content** and **Server Members** privileged intents enabled
- An [R6Data API key](https://r6data.eu/dashboard)
- An [Anthropic API key](https://console.anthropic.com/)

### 1. Clone & install dependencies

```bash
git clone <repo-url>
cd r6_agent
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
ANTHROPIC_API_KEY=your_anthropic_api_key

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

The schema is applied automatically on first bot start via `db/migrations/001_init.sql`.

### 4. Run the bot

```bash
python main.py
```

---

## Bot Commands

| Command | Who | Description |
|---|---|---|
| `!track <username> [platform]` | Anyone | Register your R6 account. Platform defaults to `uplay`. Valid values: `uplay`, `psn`, `xbl`. |
| `!untrack` | Anyone | Stop tracking your account and delete all your snapshots. |
| `!stats` | Anyone | Show your current day's delta (kills, W/L, rank change) since the midnight snapshot. |
| `!stats @user` | Anyone | Show another registered user's current day stats. |
| `!setup #post-channel #command-channel` | Admin | Configure which channels the bot posts reports in and accepts commands from. |
| `!report` | Admin | Manually trigger the full 22:00 report right now. Useful for testing. |

> Commands sent outside the configured command channel are silently ignored. Before `!setup` is run, all channels are accepted.

### !track Example

```
!track prinz.gg uplay
```
```
✅ prinz.gg (Diamond III) wird ab jetzt getrackt!
```

The bot calls the R6Data API to verify the username exists, fetches the Ubisoft `profileId`, and stores the Discord user ID alongside it in the database.

---

## Daily Report Example

```
@prinz

💀 Totale Enttäuschung im Ranked

[Rang]              Diamond III (+12 RP)
[K/D heute]         14K / 11D  (KD: 1.27)
[W/L heute]         4W / 3L
[Operator]          Ash (14 kills)
[Rating]            4/10 — Mittelmaß mit Einbildung

14 Kills in 7 Runden — ich habe schon Ash-Mains gesehen, die mit geschlossenen
Augen mehr reißen. Diamond III mit dieser Win-Rate zu halten ist weniger Skill
als reines Glück, dass deine Teammates noch schlechter waren.
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

Claude generates a different variation every day.

---

## Architecture Notes

### pydantic-ai Agents

Two agents are defined in `agent/critic.py`:

| Agent | Input | Output | Purpose |
|---|---|---|---|
| `critic_agent` | `DailyStats` (as JSON string) | `CritiqueOutput` | Per-player roast |
| `lazy_day_agent` | Trigger string | `LazyDayOutput` | @everyone insult |

Both use `claude-sonnet-4-6` and return structured Pydantic models, so the bot can reliably access `critique.headline`, `critique.rating`, etc. without parsing free-form text.

### Channel Guard

Every command in `cog_stats.py` calls `_in_command_channel()` before doing anything. If a `guild_config` row exists and the message was sent in a different channel, the command is silently dropped — no error message, no reaction.

### Scheduler Timezone

The APScheduler instance in `cog_daily.py` is configured with `timezone="Europe/Berlin"`. `DAILY_HOUR=22` means 22:00 CET/CEST, not UTC.

---

## Limitations

- **No match history** — the R6Data public API only exposes cumulative lifetime stats. Individual match scores, per-match kills, and round-by-round data are not available.
- **Operator delta is approximate** — operator stats are cumulative too. The bot reports the top operator by total `roundsPlayed`, not exclusively today's games.
- **Single guild assumed per user** — if the same Discord user is in multiple guilds where the bot is active, they receive one ping per guild's post channel.

---

## License

MIT
