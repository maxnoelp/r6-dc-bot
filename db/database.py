"""
db/database.py — asyncpg connection pool management.

Provides:
- init_db(dsn): Creates the asyncpg pool and runs the initial migration SQL.
- get_pool(): Returns the active pool; raises RuntimeError if not initialised.

The migration SQL file (db/migrations/001_init.sql) is read from disk at
startup so the schema is always applied idempotently via CREATE TABLE IF NOT EXISTS.
"""

import asyncpg
from pathlib import Path

# Module-level pool reference — set once by init_db()
_pool: asyncpg.Pool | None = None

# Path to the SQL migration file relative to this file's location
_MIGRATION_FILE = Path(__file__).parent / "migrations" / "001_init.sql"


async def init_db(dsn: str) -> asyncpg.Pool:
    """
    Initialise the asyncpg connection pool and apply the migration.

    Args:
        dsn: PostgreSQL DSN string compatible with asyncpg
             (e.g. "postgresql://user:pass@host:5432/db").

    Returns:
        The created asyncpg.Pool instance.
    """
    global _pool

    _pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)

    # Read and execute the migration SQL so schema is always up-to-date
    migration_sql = _MIGRATION_FILE.read_text(encoding="utf-8")
    async with _pool.acquire() as conn:
        await conn.execute(migration_sql)

    return _pool


def get_pool() -> asyncpg.Pool:
    """
    Return the active asyncpg pool.

    Raises:
        RuntimeError: If init_db() has not been called yet.
    """
    if _pool is None:
        raise RuntimeError("Database pool is not initialised. Call init_db() first.")
    return _pool
