# Changelog

All notable changes to this project will be documented here.

---

## [Release 0.3.1] — 2026-03-30

### Added
- **`!compare <p1> <p2> [platform]`** — side-by-side season stat comparison embed.
  Accepts `@mention` (tracked players, uses stored platform) or raw R6 username (any player).
  Mixed input supported: `!compare @user SomeUsername`.
  Shows Rang, K/D, Win Rate, Kills, W/L, Main Operator — winner per category bolded.
  Embed color reflects overall winner (green / red / grey).
- **`!leaderboard [metric]`** (alias `!lb`) — ranked leaderboard of all tracked players.
  Metrics: `rp` / `rank` (default), `kd` / `k/d`, `wins` / `win`.
  All API calls run in parallel. Embed accent color matches the #1 player's rank tier.

---

## [Unreleased] — 2026-03-29

### Added
- **`!quote` command** — AI-generated R6 operator quote via `quote_agent` (Claude Haiku).
  Attributed to a randomly chosen operator, posted as a Discord embed.
- **`quote_agent`** in `agent/critic.py` — new pydantic-ai agent with `QuoteOutput` model (`quote`, `operator`).
- **`QUOTE_ENABLED` feature flag** — `true`/`false` in `.env`. Disables `!quote` and hides it from `!info` when `false`.
- **Quote channel support** — `guild_config` now has an optional `quote_channel_id` column (migration `002_add_quote_channel.sql`).
  - `!setup #post #commands [#quotes]` — accepts optional third channel argument.
  - `!setquote #channel` — sets the quote channel without re-running `!setup`. Preserves existing post/command channel config.
  - `_in_quote_channel()` guard — enforces quote channel if set, falls back to command channel otherwise.
- **`!info` health checks** — on every `!info` call, three checks run concurrently:
  - **Database** → `SELECT 1` on the asyncpg pool
  - **R6Data API** → `GET https://api.r6data.eu`
  - **Claude API** → `GET https://api.anthropic.com/v1/models`
  - Results shown as a `diff` code block (green / red / orange). Overall: `ONLINE` / `DEGRADED` / `OFFLINE`.
- **`!info` embed redesign** — `diff` status block, `fix` schedule block, `yaml` command blocks with inline comments. Snapshot and report times pulled live from ENV.
- **Multi-file migration runner** — `db/database.py` now applies all files in `db/migrations/` in order at startup.

### Changed
- `!setup` reply now shows the quote channel (or `_(nicht gesetzt)_` if unset).
- `!info` description updated to reflect Claude (was previously Gemini in comments/README).
- README fully updated: commands table, DB schema, architecture notes, `.env` reference, agents table.

---

## [Prior] — before 2026-03-29

- Initial bot with `!track`, `!untrack`, `!stats`, `!season`, `!setup`, `!snapshot`, `!report`, `!showsnapshot`, `!info`
- Daily snapshot job at 00:00 and report job at 22:00 (APScheduler, Europe/Berlin)
- `critic_agent` and `lazy_day_agent` via pydantic-ai + Claude Haiku
- PostgreSQL schema: `users`, `guild_config`, `snapshots`
- R6Data API client (`httpx`) for account info, ranked stats, operator stats
