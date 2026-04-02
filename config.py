"""
config.py — Application configuration loaded from environment variables.

Uses pydantic-settings BaseSettings so that values are automatically read from
the process environment or a .env file in the working directory.

Key settings:
- DISCORD_TOKEN: Bot token for the Discord API.
- R6DATA_API_KEY: API key for api.r6data.eu.
- DATABASE_URL: asyncpg-compatible PostgreSQL DSN.
- ANTHROPIC_API_KEY: Key for the Anthropic Claude API used by pydantic-ai.
- DAILY_HOUR / DAILY_MINUTE: When the daily report job runs (default 22:00).
- SNAPSHOT_HOUR / SNAPSHOT_MINUTE: When the baseline snapshot is taken (default 00:00).
- COMMAND_PREFIX: Prefix for bot commands (default "!").
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Discord
    discord_token: str

    # R6Data API
    r6data_api_key: str

    # Database (asyncpg DSN, e.g. postgresql://user:pass@host:5432/db)
    database_url: str

    # Anthropic Claude / pydantic-ai
    anthropic_api_key: str

    # Scheduler: when to post the daily report (24-hour clock)
    daily_hour: int = 22
    daily_minute: int = 0

    # Scheduler: when to take the baseline snapshot
    snapshot_hour: int = 0
    snapshot_minute: int = 0

    # Bot command prefix
    command_prefix: str = "!"

    # Feature flags
    r6_enabled:      bool = True   # master switch for all R6 API commands
    quote_enabled:   bool = True   # !quote specifically (requires r6_enabled)
    tickets_enabled: bool = True   # support ticket system


# Singleton instance used throughout the application
settings = Settings()
