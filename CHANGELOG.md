# Changelog

All notable changes to this project will be documented here.

---

## [Released] — 02-04-2026 — v0.0.2

### Added
- **Support Ticket System** — vollständiges Ticket-System mit Panel, Modal, privaten Channels, Claim- und Schließ-Mechanik.
  - `!ticketsetup #channel @role [@role ...]` — konfiguriert Panel-Channel, Kategorie (auto-detect) und Support-Rollen (mehrere möglich).
  - `!ticketpanel` — postet das Panel-Embed mit Button in den konfigurierten Channel.
  - Panel wird beim Bot-Start automatisch geprüft und neu gepostet falls die Nachricht gelöscht wurde.
  - Beim Claimen verlieren andere Support-Rollen Schreibzugriff — nur Claimer + Author können noch schreiben.
  - Schließen löscht den Channel nach 5 Sekunden.
  - Buttons überleben Bot-Neustarts (persistent Views via `custom_id`).
  - `TICKETS_ENABLED` feature flag — `true`/`false` in `.env`.
- **`!compare <p1> <p2>`** — Season-Vergleich zweier Spieler nebeneinander. Unterstützt `@mention` und rohen R6-Username gemischt.
- **`!leaderboard [rp|kd|wins]`** — Server-Rangliste aller getrackten Spieler. Standard: `rp`. Alias: `!lb`.
- Migration `004_add_ticket_tables.sql` — neue Tabellen: `ticket_config`, `ticket_support_roles`, `tickets`.

### Changed
- Codebase in Einzeldateien aufgeteilt: alle R6-Commands unter `bot/r6/` (`track`, `stats`, `season`, `compare`, `leaderboard`, `quote`).
- `R6_ENABLED` master switch — alle R6-API-Commands per ENV an/ausschaltbar.
- `!setquote` in eigene Datei `bot/cog_setquote.py` isoliert.
- R6Data API Retry-Logik — bei 403/429 wird 30s gewartet und einmal wiederholt.
- `asyncio.sleep(2)` zwischen User-Fetches in Snapshot- und Report-Job.
- `api_errors`-Counter im Report-Job — Lazy-Day-Post wird unterdrückt wenn alle API-Calls fehlschlagen.

---

## [Released] — 2026-04-02

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
