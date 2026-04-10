"""
bot/cog_daily.py — APScheduler-based daily snapshot and report cog.

Scheduled jobs:
- snapshot_job (runs at SNAPSHOT_HOUR:SNAPSHOT_MINUTE, default 00:00):
    Fetches current stats for every tracked user and stores a baseline snapshot.
- daily_report_job (runs at DAILY_HOUR:DAILY_MINUTE, default 22:00):
    Calculates each user's daily delta, generates AI critiques via pydantic-ai,
    and posts embeds to all configured guild post-channels.
    If ALL deltas are zero, posts an @everyone lazy-day insult instead.

Commands:
- !report  (Admin only) — manually triggers daily_report_job immediately.
"""

from __future__ import annotations

import datetime
import logging
from datetime import date, timezone
from zoneinfo import ZoneInfo

import discord
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from agent.critic import (
    CritiqueOutput,
    DailyStats,
    LazyDayOutput,
    critic_agent,
    lazy_day_agent,
)
from config import settings
from db import models as db
from r6api.client import R6DataClient

log = logging.getLogger(__name__)

_BERLIN = ZoneInfo("Europe/Berlin")


def _today_berlin() -> date:
    """Return the current calendar date in Europe/Berlin timezone."""
    return datetime.datetime.now(tz=_BERLIN).date()


def _kd(kills: int, deaths: int) -> float:
    """Safe K/D ratio calculation — avoids ZeroDivisionError."""
    return round(kills / deaths, 2) if deaths > 0 else float(kills)


def _rank_delta_str(delta: int) -> str:
    """Format a rank-point delta with an explicit sign, e.g. '+12 RP'."""
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} RP"


def _delta_color(delta: int) -> discord.Color:
    """Return green for gains, red for losses, grey for neutral."""
    if delta > 0:
        return discord.Color.green()
    if delta < 0:
        return discord.Color.red()
    return discord.Color.greyple()


class DailyCog(commands.Cog, name="Daily"):
    """Cog that manages scheduled snapshot + report jobs."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    @property
    def pool(self):
        """Convenience accessor for the asyncpg pool stored on the bot."""
        return self.bot.db_pool

    @property
    def r6(self) -> R6DataClient:
        """Convenience accessor for the R6DataClient stored on the bot."""
        return self.bot.r6_client

    # ------------------------------------------------------------------
    # Cog lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        """Called by discord.py when the cog is added to the bot. Starts the scheduler."""
        self._scheduler.add_job(
            self.snapshot_job,
            trigger="cron",
            hour=settings.snapshot_hour,
            minute=settings.snapshot_minute,
            id="snapshot_job",
            replace_existing=True,
        )
        self._scheduler.add_job(
            self.daily_report_job,
            trigger="cron",
            hour=settings.daily_hour,
            minute=settings.daily_minute,
            id="daily_report_job",
            replace_existing=True,
        )
        self._scheduler.start()
        log.info(
            "Scheduler started. Snapshot @ %02d:%02d, Report @ %02d:%02d",
            settings.snapshot_hour,
            settings.snapshot_minute,
            settings.daily_hour,
            settings.daily_minute,
        )

    async def cog_unload(self) -> None:
        """Shut down the scheduler gracefully when the cog is removed."""
        self._scheduler.shutdown(wait=False)

    # ------------------------------------------------------------------
    # Scheduled jobs
    # ------------------------------------------------------------------

    async def snapshot_job(self) -> None:
        """
        Baseline snapshot job — runs at midnight (SNAPSHOT_HOUR:SNAPSHOT_MINUTE).

        Fetches current stats for every tracked user and saves a snapshot
        keyed on today's date. ON CONFLICT DO UPDATE makes re-runs safe.
        """
        log.info("snapshot_job: starting")
        users = await db.get_all_users(self.pool)
        today = _today_berlin()

        for user in users:
            username: str  = user["r6_username"]
            platform: str  = user["platform"]
            discord_id: int = user["discord_id"]
            try:
                live = await self.r6.get_player_stats(username, platform)
                await db.upsert_snapshot(
                    self.pool,
                    discord_id,
                    today,
                    live.rank,
                    live.rankPoints,
                    live.kills,
                    live.deaths,
                    live.wins,
                    live.losses,
                )
                log.info("snapshot_job: saved snapshot for %s", username)
            except Exception as exc:  # noqa: BLE001
                log.error("snapshot_job: error for %s: %s", username, exc)

        log.info("snapshot_job: done (%d users)", len(users))

    async def daily_report_job(self, snapshot_date: date | None = None) -> None:
        """
        Daily report job — runs at DAILY_HOUR:DAILY_MINUTE (default 22:00).

        For each tracked user:
          1. Load baseline snapshot (latest, or specific date if snapshot_date given).
          2. Fetch current live stats from the R6Data API.
          3. Compute delta (kills, deaths, wins, losses, rank points).
          4. Determine most-played operator by current season ranking.
          5. If activity delta > 0: generate an AI critique and collect it.

        After processing all users:
          - If nobody played (all deltas == 0): post @everyone lazy-day message.
          - Otherwise: send each critique embed to all configured post channels,
            pinging the respective Discord user.
        """
        log.info("daily_report_job: starting (snapshot_date=%s)", snapshot_date or "latest")
        users = await db.get_all_users(self.pool)

        # Accumulate (discord_id, username, embed, ping) tuples for posting
        posts: list[tuple[int, str, discord.Embed, str]] = []

        for user in users:
            discord_id: int = user["discord_id"]
            username: str   = user["r6_username"]
            platform: str   = user["platform"]

            if snapshot_date is not None:
                snapshot = await db.get_snapshot(self.pool, discord_id, snapshot_date)
            else:
                snapshot = await db.get_latest_snapshot(self.pool, discord_id)
            if snapshot is None:
                log.info("daily_report_job: no snapshot yet for %s (new user), skipping", username)
                continue

            try:
                live     = await self.r6.get_player_stats(username, platform)
                op_stats = await self.r6.get_operator_stats(username, platform)
            except Exception as exc:  # noqa: BLE001
                log.error("daily_report_job: API error for %s: %s", username, exc)
                continue

            # Calculate deltas against the midnight baseline snapshot
            kill_delta  = live.kills      - (snapshot["total_kills"]   or 0)
            death_delta = live.deaths     - (snapshot["total_deaths"]  or 0)
            win_delta   = live.wins       - (snapshot["total_wins"]    or 0)
            loss_delta  = live.losses     - (snapshot["total_losses"]  or 0)
            rp_delta    = live.rankPoints - (snapshot["rank_points"]   or 0)

            # Skip users who haven't done anything measurable today
            total_activity = abs(kill_delta) + abs(win_delta) + abs(loss_delta)
            if total_activity == 0:
                log.info("daily_report_job: %s has delta=0, skipping", username)
                continue

            # Most-played operator: use the top operator by roundsPlayed
            # (get_operator_stats already sorts by roundsPlayed desc)
            most_played   = op_stats[0].name         if op_stats else "Unbekannt"
            op_rounds_day = op_stats[0].roundsPlayed if op_stats else 0

            daily_stats = DailyStats(
                username=username,
                platform=platform,
                rank=live.rank,
                rank_delta=rp_delta,
                kills=kill_delta,
                deaths=death_delta,
                kd_today=_kd(kill_delta, death_delta),
                wins=win_delta,
                losses=loss_delta,
            )

            # Ask the pydantic-ai critic agent to roast this player
            try:
                result   = await critic_agent.run(daily_stats.model_dump_json())
                critique: CritiqueOutput = result.output
            except Exception as exc:  # noqa: BLE001
                log.error("daily_report_job: critic agent error for %s: %s", username, exc)
                continue

            embed, ping = self._build_critique_embed(discord_id, username, daily_stats, critique, most_played, op_rounds_day)
            posts.append((discord_id, username, embed, ping))

        # Gather all guild post-channel destinations
        guild_configs = []
        for guild in self.bot.guilds:
            cfg = await db.get_guild_config(self.pool, guild.id)
            if cfg:
                guild_configs.append((guild, cfg))

        if not guild_configs:
            log.warning("daily_report_job: no guild configs found, nowhere to post")
            return

        if not posts:
            # Nobody played today — generate and post the lazy-day insult
            log.info("daily_report_job: all deltas zero, posting lazy-day message")
            try:
                lazy_result = await lazy_day_agent.run("Generiere die heutige Nachricht.")
                lazy: LazyDayOutput = lazy_result.output
                message_text = lazy.message
            except Exception as exc:  # noqa: BLE001
                log.error("daily_report_job: lazy_day_agent error: %s", exc)
                message_text = "@everyone Ihr habt heute alle nicht gespielt. Schämt euch."

            for guild, cfg in guild_configs:
                channel = guild.get_channel(cfg["post_channel_id"])
                if channel and isinstance(channel, discord.TextChannel):
                    try:
                        await channel.send(message_text)
                    except discord.HTTPException as exc:
                        log.error(
                            "daily_report_job: failed to send lazy-day to %s: %s",
                            guild.name, exc,
                        )
        else:
            # Post each player's critique embed with a user ping
            for discord_id, username, embed, ping in posts:
                for guild, cfg in guild_configs:
                    channel = guild.get_channel(cfg["post_channel_id"])
                    if channel and isinstance(channel, discord.TextChannel):
                        try:
                            # Send the ping as message content so Discord notifies the user,
                            # and attach the embed for the formatted stats display
                            await channel.send(content=ping, embed=embed)
                        except discord.HTTPException as exc:
                            log.error(
                                "daily_report_job: failed to send report for %s to %s: %s",
                                username, guild.name, exc,
                            )

        log.info("daily_report_job: done (%d posts sent)", len(posts))

    # ------------------------------------------------------------------
    # Embed builder
    # ------------------------------------------------------------------

    def _build_critique_embed(
        self,
        discord_id: int,
        username: str,
        stats: DailyStats,
        critique: CritiqueOutput,
        most_played: str = "Unbekannt",
        op_rounds: int = 0,
    ) -> tuple[discord.Embed, str]:
        """
        Build the Discord Embed for a player's daily critique.

        Looks up the Discord member across all guilds for a proper @mention.

        Returns:
            Tuple of (embed, ping_string).
        """
        # Try to resolve the Discord member for a proper @mention
        member: discord.Member | None = None
        for guild in self.bot.guilds:
            member = guild.get_member(discord_id)
            if member:
                break

        # Fall back to a raw mention that still pings even without a Member object
        ping = member.mention if member else f"<@{discord_id}>"

        embed = discord.Embed(
            title=f"💀 {critique.headline}",
            description=critique.critique,
            color=_delta_color(stats.rank_delta),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.set_author(name=f"Tagesbericht: {username}")
        embed.add_field(
            name="Rang",
            value=f"{stats.rank} ({_rank_delta_str(stats.rank_delta)})",
            inline=True,
        )
        embed.add_field(
            name="K/D heute",
            value=f"{stats.kills}K / {stats.deaths}D (KD: {stats.kd_today})",
            inline=True,
        )
        embed.add_field(
            name="W/L heute",
            value=f"{stats.wins}W / {stats.losses}L",
            inline=True,
        )
        embed.add_field(
            name="Operator",
            value=f"{most_played} ({op_rounds} Runden)",
            inline=True,
        )
        embed.add_field(
            name="Rating",
            value=f"{critique.rating}/10 — {critique.verdict}",
            inline=False,
        )

        return embed, ping

    # ------------------------------------------------------------------
    # Manual trigger command
    # ------------------------------------------------------------------

    @commands.command(name="snapshot")
    @commands.has_permissions(administrator=True)
    async def snapshot_cmd(self, ctx: commands.Context) -> None:
        """
        Manually trigger the midnight snapshot job right now.

        Requires administrator permission.
        Usage: !snapshot
        """
        await ctx.reply("⏳ Snapshot wird erstellt...")
        try:
            await self.snapshot_job()
            await ctx.reply("✅ Snapshot für alle User gespeichert.")
        except Exception as exc:
            log.error("!snapshot command error: %s", exc)
            await ctx.reply(f"❌ Fehler beim Snapshot: {exc}")

    @snapshot_cmd.error
    async def snapshot_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    @commands.command(name="report")
    @commands.has_permissions(administrator=True)
    async def report_cmd(self, ctx: commands.Context, offset: int = 0) -> None:
        """
        Manually trigger the daily report job right now.

        Requires administrator permission.
        Usage: !report        — use latest snapshot
               !report -1     — use snapshot from yesterday as baseline
               !report -2     — use snapshot from 2 days ago as baseline
        """
        if offset == 0:
            snapshot_date = None
            date_hint = "neuester Snapshot"
        else:
            snapshot_date = _today_berlin() + datetime.timedelta(days=offset)
            date_hint = str(snapshot_date)

        await ctx.reply(f"⏳ Starte manuellen Report... (Baseline: {date_hint})")
        try:
            await self.daily_report_job(snapshot_date=snapshot_date)
            await ctx.reply("✅ Report abgeschlossen.")
        except Exception as exc:  # noqa: BLE001
            log.error("!report command error: %s", exc)
            await ctx.reply(f"❌ Fehler beim Report: {exc}")

    @report_cmd.error
    async def report_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")


    @commands.command(name="showsnapshot")
    @commands.has_permissions(administrator=True)
    async def showsnapshot_cmd(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
        offset: int = 0,
    ) -> None:
        """
        Show the stored snapshot for a user (default: yourself, latest snapshot).

        Requires administrator permission.
        Usage: !showsnapshot              — your latest snapshot
               !showsnapshot -1           — snapshot from yesterday
               !showsnapshot @member -2   — snapshot from 2 days ago for another user
        """
        target = member or ctx.author
        user_record = await db.get_user(self.pool, target.id)

        if user_record is None:
            await ctx.reply(f"❌ {target.display_name} ist nicht registriert.")
            return

        if offset == 0:
            snapshot = await db.get_latest_snapshot(self.pool, target.id)
        else:
            lookup_date = _today_berlin() + datetime.timedelta(days=offset)
            snapshot = await db.get_snapshot(self.pool, target.id, lookup_date)

        if snapshot is None:
            hint = f"vom {_today_berlin() + datetime.timedelta(days=offset)}" if offset != 0 else ""
            await ctx.reply(
                f"📭 Kein Snapshot {hint} für **{user_record['r6_username']}** vorhanden. "
                "Nutze `!snapshot` um einen manuell zu erstellen."
            )
            return

        created_at = snapshot["created_at"]

        embed = discord.Embed(
            title=f"🗄️ Snapshot: {user_record['r6_username']}",
            color=discord.Color.blurple(),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.add_field(name="📅 Datum",       value=str(snapshot["snapshot_date"]), inline=True)
        embed.add_field(name="🕐 Erstellt um", value=created_at.strftime("%H:%M:%S") if created_at else "—", inline=True)
        embed.add_field(name="​",         value="", inline=False)
        embed.add_field(name="🏆 Rang",        value=f"{snapshot['rank']} ({snapshot['rank_points']:,} RP)", inline=True)
        embed.add_field(name="💀 Kills",       value=str(snapshot["total_kills"]),  inline=True)
        embed.add_field(name="☠️ Deaths",      value=str(snapshot["total_deaths"]), inline=True)
        embed.add_field(name="✅ Wins",        value=str(snapshot["total_wins"]),   inline=True)
        embed.add_field(name="❌ Losses",      value=str(snapshot["total_losses"]), inline=True)
        embed.set_footer(text=f"Discord ID: {target.id}")

        await ctx.reply(embed=embed)

    @showsnapshot_cmd.error
    async def showsnapshot_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

async def setup(bot: commands.Bot) -> None:
    """Entry point called by bot.load_extension()."""
    await bot.add_cog(DailyCog(bot))
