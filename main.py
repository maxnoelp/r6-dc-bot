"""
main.py — Entry point for the R6 tracking Discord bot.

Responsibilities:
1. Load configuration via config.Settings (reads .env).
2. Initialise the asyncpg database pool and run migrations.
3. Create the discord.ext.commands.Bot instance.
4. Attach the db pool and R6DataClient as attributes on the bot so cogs
   can access them without global state.
5. Load the StatsCog and DailyCog extensions.
6. Start the bot.

The bot uses the command prefix defined in config (default "!") and requests
the Members and Message Content privileged intents required by the cogs.
"""

import asyncio
import logging

import discord
from discord.ext import commands

from config import settings
from db.database import init_db
from r6api.client import R6DataClient

# ---------------------------------------------------------------------------
# Logging setup — INFO level for the bot, WARNING for noisy third-party libs
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logging.getLogger("r6api.client").setLevel(logging.DEBUG)
log = logging.getLogger(__name__)


async def main() -> None:
    """Async entry point: initialise all resources and run the bot."""

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    log.info("Connecting to database...")
    pool = await init_db(settings.database_url)
    log.info("Database ready.")

    # ------------------------------------------------------------------
    # R6Data API client
    # ------------------------------------------------------------------
    r6_client = R6DataClient(settings.r6data_api_key)

    # ------------------------------------------------------------------
    # Discord bot
    # ------------------------------------------------------------------
    # We need Members intent to resolve @mentions inside embeds and the
    # Message Content intent to read command text in messages.
    intents = discord.Intents.default()
    intents.members = True
    intents.message_content = True

    bot = commands.Bot(
        command_prefix=settings.command_prefix,
        intents=intents,
        description="Rainbow Six Siege daily stats tracker",
    )

    # Attach shared resources as bot attributes so cogs can access them
    # without importing globals or using dependency injection frameworks.
    bot.db_pool   = pool      # type: ignore[attr-defined]
    bot.r6_client = r6_client  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Load cogs
    # ------------------------------------------------------------------
    if settings.r6_enabled:
        await bot.load_extension("bot.r6.track")
        await bot.load_extension("bot.r6.stats")
        await bot.load_extension("bot.r6.season")
        await bot.load_extension("bot.r6.compare")
        await bot.load_extension("bot.r6.leaderboard")
        if settings.quote_enabled:
            await bot.load_extension("bot.r6.quote")
    await bot.load_extension("bot.cog_setup")
    await bot.load_extension("bot.cog_setquote")
    await bot.load_extension("bot.cog_admin")
    await bot.load_extension("bot.cog_daily")
    if settings.tickets_enabled:
        await bot.load_extension("bot.support_system.cog_ticket_actions")
        await bot.load_extension("bot.support_system.cog_ticket_setup")
    log.info("Cogs loaded.")

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    try:
        async with bot:
            log.info("Starting bot...")
            await bot.start(settings.discord_token)
    finally:
        # Ensure the R6 HTTP client and DB pool are closed on exit
        await r6_client.aclose()
        await pool.close()
        log.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
