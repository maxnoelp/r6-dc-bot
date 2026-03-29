"""
db/models.py — All SQL query functions for the R6 tracking bot.

Functions operate directly on an asyncpg Pool (no ORM).

Exposed functions:
- upsert_user: Register or update a tracked player.
- delete_user: Remove a player from tracking.
- get_user: Retrieve a single tracked player by Discord ID.
- get_all_users: Return all tracked players.
- upsert_guild_config: Set channel config for a guild.
- get_guild_config: Get channel config for a guild.
- upsert_snapshot: Save or overwrite a player's daily stat snapshot.
- get_snapshot: Retrieve a snapshot for a specific player and date.
"""

import asyncpg
from datetime import date
from typing import Optional


async def upsert_user(
    pool: asyncpg.Pool,
    discord_id: int,
    r6_username: str,
    r6_profile_id: str,
    platform: str,
) -> None:
    """Insert or update a user record (keyed on discord_id)."""
    await pool.execute(
        """
        INSERT INTO users (discord_id, r6_username, r6_profile_id, platform)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (discord_id) DO UPDATE
            SET r6_username   = EXCLUDED.r6_username,
                r6_profile_id = EXCLUDED.r6_profile_id,
                platform      = EXCLUDED.platform
        """,
        discord_id,
        r6_username,
        r6_profile_id,
        platform,
    )


async def delete_user(pool: asyncpg.Pool, discord_id: int) -> bool:
    """
    Delete a user (and their snapshots via CASCADE).

    Returns:
        True if a row was deleted, False if the user was not found.
    """
    result = await pool.execute(
        "DELETE FROM users WHERE discord_id = $1", discord_id
    )
    # asyncpg returns a string like "DELETE 1" or "DELETE 0"
    return result.endswith("1")


async def get_user(pool: asyncpg.Pool, discord_id: int) -> Optional[asyncpg.Record]:
    """
    Fetch a single user record by Discord ID.

    Returns:
        An asyncpg.Record or None if not found.
    """
    return await pool.fetchrow(
        "SELECT * FROM users WHERE discord_id = $1", discord_id
    )


async def get_all_users(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Return all tracked users ordered by registration date."""
    return await pool.fetch("SELECT * FROM users ORDER BY registered_at")


async def upsert_guild_config(
    pool: asyncpg.Pool,
    guild_id: int,
    post_channel_id: int,
    command_channel_id: int,
    quote_channel_id: int | None = None,
) -> None:
    """Insert or update the channel configuration for a Discord guild."""
    await pool.execute(
        """
        INSERT INTO guild_config (guild_id, post_channel_id, command_channel_id, quote_channel_id)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id) DO UPDATE
            SET post_channel_id     = EXCLUDED.post_channel_id,
                command_channel_id  = EXCLUDED.command_channel_id,
                quote_channel_id    = EXCLUDED.quote_channel_id,
                updated_at          = NOW()
        """,
        guild_id,
        post_channel_id,
        command_channel_id,
        quote_channel_id,
    )


async def get_guild_config(
    pool: asyncpg.Pool, guild_id: int
) -> Optional[asyncpg.Record]:
    """
    Fetch channel configuration for a guild.

    Returns:
        An asyncpg.Record with post_channel_id and command_channel_id, or None.
    """
    return await pool.fetchrow(
        "SELECT * FROM guild_config WHERE guild_id = $1", guild_id
    )


async def upsert_snapshot(
    pool: asyncpg.Pool,
    discord_id: int,
    snapshot_date: date,
    rank: str,
    rank_points: int,
    total_kills: int,
    total_deaths: int,
    total_wins: int,
    total_losses: int,
) -> None:
    """
    Insert or overwrite a snapshot for (discord_id, snapshot_date).

    The UNIQUE constraint on (discord_id, snapshot_date) means a second call
    for the same day will overwrite all stat columns.
    """
    await pool.execute(
        """
        INSERT INTO snapshots
            (discord_id, snapshot_date, rank, rank_points,
             total_kills, total_deaths, total_wins, total_losses)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (discord_id, snapshot_date) DO UPDATE
            SET rank        = EXCLUDED.rank,
                rank_points = EXCLUDED.rank_points,
                total_kills = EXCLUDED.total_kills,
                total_deaths= EXCLUDED.total_deaths,
                total_wins  = EXCLUDED.total_wins,
                total_losses= EXCLUDED.total_losses,
                created_at  = NOW()
        """,
        discord_id,
        snapshot_date,
        rank,
        rank_points,
        total_kills,
        total_deaths,
        total_wins,
        total_losses,
    )


async def get_snapshot(
    pool: asyncpg.Pool, discord_id: int, snapshot_date: date
) -> Optional[asyncpg.Record]:
    """
    Fetch the snapshot for a specific player and date.

    Returns:
        An asyncpg.Record or None if no snapshot exists for that day.
    """
    return await pool.fetchrow(
        """
        SELECT * FROM snapshots
        WHERE discord_id = $1 AND snapshot_date = $2
        """,
        discord_id,
        snapshot_date,
    )


async def get_latest_snapshot(
    pool: asyncpg.Pool, discord_id: int
) -> Optional[asyncpg.Record]:
    """
    Fetch the most recent snapshot for a player regardless of date.

    Returns:
        The newest asyncpg.Record or None if the player has no snapshots yet.
    """
    return await pool.fetchrow(
        """
        SELECT * FROM snapshots
        WHERE discord_id = $1
        ORDER BY snapshot_date DESC
        LIMIT 1
        """,
        discord_id,
    )
