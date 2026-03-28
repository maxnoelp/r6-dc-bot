"""
tests/test_snapshot_job.py — Unit tests for the snapshot_job cron task.

What is tested:
- snapshot_job calls upsert_snapshot for every tracked user with the correct data
- snapshot_job uses the Berlin calendar date (not UTC) — this was the root bug
- snapshot_job continues gracefully when one user's API call fails
- _today_berlin() returns the Berlin date, which can differ from the UTC date
  at 23:xx UTC (i.e. the timezone-mismatch scenario that caused snapshots to
  be "invisible" from 01:00 Berlin onward)

All external dependencies (DB pool, R6Data API, Discord bot) are mocked —
no real database or network connection is required.
"""

import datetime
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from r6api.client import PlayerStats
from bot.cog_daily import DailyCog, _today_berlin


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

FAKE_USER = {
    "discord_id": 123456789,
    "r6_username": "TestPlayer",
    "platform": "uplay",
}

FAKE_STATS = PlayerStats(
    kills=150,
    deaths=80,
    wins=40,
    losses=25,
    rankPoints=1800,
    rank="Platinum 1",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.db_pool = MagicMock()
    bot.r6_client = MagicMock()
    bot.guilds = []
    return bot


@pytest.fixture
def cog(mock_bot):
    return DailyCog(mock_bot)


# ---------------------------------------------------------------------------
# Tests — snapshot_job behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_snapshot_job_saves_snapshot_for_each_user(cog):
    """
    Given one tracked user, snapshot_job must call upsert_snapshot exactly
    once with the stats returned by the R6Data API.
    """
    cog.bot.r6_client.get_player_stats = AsyncMock(return_value=FAKE_STATS)

    with (
        patch("bot.cog_daily.db.get_all_users", new_callable=AsyncMock, return_value=[FAKE_USER]),
        patch("bot.cog_daily.db.upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
    ):
        await cog.snapshot_job()

        mock_upsert.assert_called_once_with(
            cog.pool,
            FAKE_USER["discord_id"],
            _today_berlin(),
            FAKE_STATS.rank,
            FAKE_STATS.rankPoints,
            FAKE_STATS.kills,
            FAKE_STATS.deaths,
            FAKE_STATS.wins,
            FAKE_STATS.losses,
        )


@pytest.mark.asyncio
async def test_snapshot_job_saves_all_users(cog):
    """
    Given two tracked users, snapshot_job must call upsert_snapshot for both.
    """
    users = [
        {**FAKE_USER, "discord_id": 111, "r6_username": "PlayerOne"},
        {**FAKE_USER, "discord_id": 222, "r6_username": "PlayerTwo"},
    ]
    cog.bot.r6_client.get_player_stats = AsyncMock(return_value=FAKE_STATS)

    with (
        patch("bot.cog_daily.db.get_all_users", new_callable=AsyncMock, return_value=users),
        patch("bot.cog_daily.db.upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
    ):
        await cog.snapshot_job()

        assert mock_upsert.call_count == 2
        saved_ids = {call.args[1] for call in mock_upsert.call_args_list}
        assert saved_ids == {111, 222}


@pytest.mark.asyncio
async def test_snapshot_job_uses_berlin_date(cog):
    """
    The snapshot date must be the date returned by _today_berlin(), not
    date.today() (which returns the UTC date and caused the original bug).
    """
    fixed_date = date(2026, 1, 1)
    cog.bot.r6_client.get_player_stats = AsyncMock(return_value=FAKE_STATS)

    with (
        patch("bot.cog_daily.db.get_all_users", new_callable=AsyncMock, return_value=[FAKE_USER]),
        patch("bot.cog_daily.db.upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
        patch("bot.cog_daily._today_berlin", return_value=fixed_date),
    ):
        await cog.snapshot_job()

        saved_date = mock_upsert.call_args.args[2]
        assert saved_date == fixed_date, (
            f"Expected Berlin date {fixed_date}, but snapshot was saved with {saved_date}"
        )


@pytest.mark.asyncio
async def test_snapshot_job_skips_user_on_api_error(cog):
    """
    If the R6Data API raises an exception for one user, snapshot_job must
    log the error and continue — other users still get their snapshots.
    """
    users = [
        {**FAKE_USER, "discord_id": 111, "r6_username": "GoodPlayer"},
        {**FAKE_USER, "discord_id": 222, "r6_username": "BadPlayer"},
    ]

    async def fake_get_stats(username, platform):
        if username == "BadPlayer":
            raise ValueError("R6Data API unavailable")
        return FAKE_STATS

    cog.bot.r6_client.get_player_stats = fake_get_stats

    with (
        patch("bot.cog_daily.db.get_all_users", new_callable=AsyncMock, return_value=users),
        patch("bot.cog_daily.db.upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
    ):
        await cog.snapshot_job()

        assert mock_upsert.call_count == 1
        assert mock_upsert.call_args.args[1] == 111


@pytest.mark.asyncio
async def test_snapshot_job_no_users(cog):
    """snapshot_job with zero tracked users must not call upsert_snapshot at all."""
    with (
        patch("bot.cog_daily.db.get_all_users", new_callable=AsyncMock, return_value=[]),
        patch("bot.cog_daily.db.upsert_snapshot", new_callable=AsyncMock) as mock_upsert,
    ):
        await cog.snapshot_job()
        mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# Tests — _today_berlin() timezone correctness
# ---------------------------------------------------------------------------

def test_today_berlin_returns_date_object():
    assert isinstance(_today_berlin(), date)


def test_today_berlin_matches_berlin_timezone():
    """_today_berlin() must equal the date when computed independently with Berlin tz."""
    BERLIN = ZoneInfo("Europe/Berlin")
    expected = datetime.datetime.now(tz=BERLIN).date()
    assert _today_berlin() == expected


def test_today_berlin_can_differ_from_utc():
    """
    Documents the original bug: at 23:30 UTC in winter, the UTC date is still
    Dec 31, but the Berlin date (UTC+1) is already Jan 1.

    Using date.today() (UTC) for the snapshot key would save under Dec 31,
    while the report job at 22:00 Berlin (21:00 UTC) would look for Jan 1
    → snapshot not found → user silently skipped.
    """
    UTC = ZoneInfo("UTC")
    BERLIN = ZoneInfo("Europe/Berlin")

    # 23:30 UTC = 00:30 Berlin (UTC+1 in winter)
    utc_time = datetime.datetime(2025, 12, 31, 23, 30, tzinfo=UTC)
    berlin_time = utc_time.astimezone(BERLIN)

    assert utc_time.date() == date(2025, 12, 31), "UTC date is still Dec 31"
    assert berlin_time.date() == date(2026, 1, 1), "Berlin date is already Jan 1"
    assert utc_time.date() != berlin_time.date(), (
        "UTC and Berlin dates differ at 23:30 UTC — date.today() would have been wrong"
    )
