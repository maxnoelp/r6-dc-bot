"""
bot/cog_stats.py — Discord cog for player tracking commands.

Commands:
- !track <username> [platform=uplay]
    Looks up the R6 profile, saves it to the DB, replies with rank info.
- !untrack
    Removes the calling user from tracking.
- !stats [member]
    Shows the current-day delta between the midnight snapshot and live stats.
- !setup <post_channel> <command_channel>
    (Admin only) Configure which channels the bot uses in this guild.

All commands silently ignore invocations outside the configured command channel
(if a guild config exists). If no config is set, commands are allowed everywhere.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
from datetime import date, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import discord
from discord.ext import commands

_BERLIN = ZoneInfo("Europe/Berlin")


def _today_berlin() -> date:
    return datetime.datetime.now(tz=_BERLIN).date()

from agent.critic import QuoteOutput, quote_agent
from config import settings
from db import models as db
from r6api.client import R6DataClient

# ---------------------------------------------------------------------------
# Rank tier → accent colour + emoji
# ---------------------------------------------------------------------------
_TIER_STYLES: dict[str, tuple[discord.Color, str]] = {
    "Unranked":  (discord.Color.from_str("#808080"), "⬜"),
    "Copper":    (discord.Color.from_str("#A05C3B"), "🟫"),
    "Bronze":    (discord.Color.from_str("#CD7F32"), "🪙"),
    "Silver":    (discord.Color.from_str("#C0C0C0"), "🩶"),
    "Gold":      (discord.Color.from_str("#FFD700"), "🥇"),
    "Platinum":  (discord.Color.from_str("#00D4B4"), "🩵"),
    "Emerald":   (discord.Color.from_str("#50C878"), "💚"),
    "Diamond":   (discord.Color.from_str("#0099FF"), "💎"),
    "Champion":  (discord.Color.from_str("#FF6600"), "👑"),
}


def _tier_style(rank: str) -> tuple[discord.Color, str]:
    """Return (color, emoji) for the given rank string."""
    for tier, style in _TIER_STYLES.items():
        if rank.startswith(tier):
            return style
    return _TIER_STYLES["Unranked"]


def _rank_icon_url(rank: str) -> str:
    """Return the r6data.eu WebP rank badge URL for the given rank string."""
    slug = rank.lower().replace(" ", "-")
    return f"https://r6data.eu/assets/img/r6_ranks_img/{slug}.webp"


def _wl(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "—"
    return f"{round(wins / total * 100, 1)}%"


def _kd(kills: int, deaths: int) -> float:
    """Safe kill/death ratio calculation (avoids ZeroDivisionError)."""
    return round(kills / deaths, 2) if deaths > 0 else float(kills)


def _rank_delta_str(delta: int) -> str:
    """Format a rank-point delta as '+12 RP' or '-8 RP' with sign."""
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} RP"


def _delta_color(delta: int) -> discord.Color:
    """Return green for positive delta, red for negative, grey for zero."""
    if delta > 0:
        return discord.Color.green()
    if delta < 0:
        return discord.Color.red()
    return discord.Color.greyple()


class StatsCog(commands.Cog, name="Stats"):
    """Cog handling all player-facing tracking and stats commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        """Convenience accessor for the asyncpg pool stored on the bot."""
        return self.bot.db_pool

    @property
    def r6(self) -> R6DataClient:
        """Convenience accessor for the R6DataClient stored on the bot."""
        return self.bot.r6_client

    # ------------------------------------------------------------------
    # Channel guard helper
    # ------------------------------------------------------------------

    async def _in_command_channel(self, ctx: commands.Context) -> bool:
        """
        Return True if the command was sent in the configured command channel.

        If no guild config exists yet, all channels are considered valid so the
        bot is usable before !setup has been run.
        """
        if ctx.guild is None:
            # DMs are always allowed
            return True

        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None:
            # No config set → allow anywhere
            return True

        return ctx.channel.id == config["command_channel_id"]

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    @commands.command(name="track")
    async def track(
        self,
        ctx: commands.Context,
        username: str,
        platform: str = "uplay",
    ) -> None:
        """
        Register a Rainbow Six Siege account for daily tracking.

        Usage: !track <username> [platform=uplay]
        """
        # Silently ignore if not in the correct channel
        if not await self._in_command_channel(ctx):
            return

        async with ctx.typing():
            try:
                account = await self.r6.get_account_info(username, platform)
                stats = await self.r6.get_player_stats(username, platform)
            except ValueError as exc:
                await ctx.reply(f"❌ Spieler nicht gefunden. ({exc})")
                return

            await db.upsert_user(
                self.pool,
                ctx.author.id,
                account.nameOnPlatform,
                account.profileId,
                account.platformType,
            )

        has_snapshot = await db.get_latest_snapshot(self.pool, ctx.author.id) is not None
        daily_hint = (
            "" if has_snapshot
            else "\n📅 Dein erster Snapshot wird heute Nacht um Mitternacht erstellt — ab morgen bist du im Daily Report dabei."
        )
        await ctx.reply(
            f"✅ **{account.nameOnPlatform}** ({stats.rank}) wird ab jetzt getrackt!{daily_hint}"
        )

    @commands.command(name="untrack")
    async def untrack(self, ctx: commands.Context) -> None:
        """
        Stop tracking the calling user's R6 account.

        Usage: !untrack
        """
        if not await self._in_command_channel(ctx):
            return

        deleted = await db.delete_user(self.pool, ctx.author.id)
        if deleted:
            await ctx.reply("✅ Du wirst nicht mehr getrackt.")
        else:
            await ctx.reply("❌ Du bist gar nicht registriert.")

    @commands.command(name="stats")
    async def stats(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        """
        Show today's stat delta for yourself or another member.

        Usage: !stats          — show your own stats
               !stats @member  — show another member's stats
        """
        if not await self._in_command_channel(ctx):
            return

        target = member or ctx.author
        user_record = await db.get_user(self.pool, target.id)

        if user_record is None:
            name = target.display_name
            await ctx.reply(f"❌ {name} ist nicht registriert. Nutze `!track <username>`.")
            return

        username: str = user_record["r6_username"]
        platform: str = user_record["platform"]

        # Fetch the most recent baseline snapshot
        snapshot = await db.get_latest_snapshot(self.pool, target.id)

        if snapshot is None:
            await ctx.reply(
                "📭 Noch kein Snapshot vorhanden. "
                "Der erste Snapshot wird heute Nacht um Mitternacht erstellt."
            )
            return

        # Fetch live stats from the API
        try:
            live = await self.r6.get_player_stats(username, platform)
            operator_stats = await self.r6.get_operator_stats(username, platform)
        except ValueError as exc:
            await ctx.reply(f"❌ Fehler beim Abrufen der Stats: {exc}")
            return

        # Calculate deltas against today's baseline snapshot
        kill_delta  = live.kills  - (snapshot["total_kills"]  or 0)
        death_delta = live.deaths - (snapshot["total_deaths"] or 0)
        win_delta   = live.wins   - (snapshot["total_wins"]   or 0)
        loss_delta  = live.losses - (snapshot["total_losses"] or 0)
        rp_delta    = live.rankPoints - (snapshot["rank_points"] or 0)

        kd = _kd(kill_delta, death_delta)

        # Build the embed
        embed = discord.Embed(
            title=f"📊 Tages-Stats: {username}",
            color=_delta_color(rp_delta),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.set_footer(text=f"Plattform: {platform}")
        embed.add_field(name="Rang", value=f"{live.rank} ({_rank_delta_str(rp_delta)})", inline=True)
        embed.add_field(name="K/D heute", value=f"{kill_delta}K / {death_delta}D (KD: {kd})", inline=True)
        embed.add_field(name="W/L heute", value=f"{win_delta}W / {loss_delta}L", inline=True)

        # Show the most-played operator by kill increase today
        if operator_stats:
            top_op = operator_stats[0]
            embed.add_field(
                name="Meistgespielter Operator",
                value=f"{top_op.name} ({top_op.roundsPlayed} Runden gespielt)",
                inline=False,
            )

        await ctx.reply(embed=embed)

    @commands.command(name="season")
    async def season(
        self,
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        """
        Show full season stats for yourself or another member.

        Usage: !season          — your own season stats
               !season @member  — another member's season stats
        """
        if not await self._in_command_channel(ctx):
            return

        target = member or ctx.author
        user_record = await db.get_user(self.pool, target.id)

        if user_record is None:
            await ctx.reply(f"❌ {target.display_name} ist nicht registriert. Nutze `!track <username>`.")
            return

        username: str = user_record["r6_username"]
        platform: str = user_record["platform"]

        async with ctx.typing():
            try:
                account   = await self.r6.get_account_info(username, platform)
                stats     = await self.r6.get_player_stats(username, platform)
                operators = await self.r6.get_operator_stats(username, platform)
            except ValueError as exc:
                await ctx.reply(f"❌ Fehler beim Abrufen der Stats: {exc}")
                return

        color, rank_emoji = _tier_style(stats.rank)
        kd    = _kd(stats.kills, stats.deaths)
        wl    = _wl(stats.wins, stats.losses)
        total = stats.wins + stats.losses

        embed = discord.Embed(
            description=f"### {rank_emoji}  {stats.rank}  •  {stats.rankPoints:,} RP",
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        # Avatar as thumbnail (bigger than author icon), rank badge as author icon
        if account.profilePicture:
            embed.set_thumbnail(url=account.profilePicture)

        embed.set_author(
            name=f"{username}  •  {platform.upper()}",
            icon_url=_rank_icon_url(stats.rank),
        )

        # ── Combat ──────────────────────────────────────────────────
        embed.add_field(name="💀  Kills",    value=f"**{stats.kills:,}**",  inline=True)
        embed.add_field(name="☠️  Deaths",   value=f"**{stats.deaths:,}**", inline=True)
        embed.add_field(name="🎯  K/D",      value=f"**{kd}**",             inline=True)

        embed.add_field(name="\u200b", value="", inline=False)

        # ── Matches ─────────────────────────────────────────────────
        embed.add_field(name="✅  Wins",     value=f"**{stats.wins}**",  inline=True)
        embed.add_field(name="❌  Losses",   value=f"**{stats.losses}**", inline=True)
        embed.add_field(name="📊  Win Rate", value=f"**{wl}**",          inline=True)

        # ── Top Operators ────────────────────────────────────────────
        if operators:
            top3 = operators[:3]
            op_lines = "\n".join(
                f"**{i+1}. {op.name}** — {op.roundsPlayed} Runden "
                f"({op.roundsWon}W / {op.roundsPlayed - op.roundsWon}L)"
                for i, op in enumerate(top3)
            )
            embed.add_field(name="\u200b", value="", inline=False)
            embed.add_field(name="🎭  Top Operators", value=op_lines, inline=False)
            # Show most played operator's icon as embed image
            icon = top3[0].iconUrl
            if icon and icon.startswith(('http://', 'https://')):
                embed.set_image(url=icon)

        embed.set_footer(text=f"{total} Matches diese Season")

        await ctx.reply(embed=embed)

    @commands.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def setup(
        self,
        ctx: commands.Context,
        post_channel: discord.TextChannel,
        command_channel: discord.TextChannel,
        quote_channel: discord.TextChannel | None = None,
    ) -> None:
        """
        Configure the post, command, and quote channels for this guild.

        Usage: !setup #post-channel #command-channel [#quote-channel]
        Requires administrator permission.
        """
        # If no quote channel provided, preserve the existing one
        if quote_channel is None:
            existing = await db.get_guild_config(self.pool, ctx.guild.id)
            quote_channel_id = existing["quote_channel_id"] if existing else None
        else:
            quote_channel_id = quote_channel.id

        await db.upsert_guild_config(
            self.pool,
            ctx.guild.id,
            post_channel.id,
            command_channel.id,
            quote_channel_id,
        )

        if quote_channel_id:
            quote_mention = f"<#{quote_channel_id}>"
        else:
            quote_mention = "_(nicht gesetzt)_"

        await ctx.reply(
            f"✅ Setup gespeichert!\n"
            f"  • Post-Channel: {post_channel.mention}\n"
            f"  • Command-Channel: {command_channel.mention}\n"
            f"  • Quote-Channel: {quote_mention}"
        )

    @setup.error
    async def setup_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    @commands.command(name="setquote")
    @commands.has_permissions(administrator=True)
    async def setquote(
        self,
        ctx: commands.Context,
        quote_channel: discord.TextChannel,
    ) -> None:
        """
        Set (or update) the quote channel without touching the other channel settings.

        Usage: !setquote #quote-channel
        Requires administrator permission.
        """
        existing = await db.get_guild_config(self.pool, ctx.guild.id)
        if existing is None:
            await ctx.reply("❌ Bitte erst `!setup` ausführen.")
            return

        await db.upsert_guild_config(
            self.pool,
            ctx.guild.id,
            existing["post_channel_id"],
            existing["command_channel_id"],
            quote_channel.id,
        )
        await ctx.reply(f"✅ Quote-Channel gesetzt: {quote_channel.mention}")

    @setquote.error
    async def setquote_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    async def _in_quote_channel(self, ctx: commands.Context) -> bool:
        """
        Return True if the command was sent in the configured quote channel.

        Falls back to the command channel check if no quote channel is set.
        """
        if ctx.guild is None:
            return True

        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None:
            return True

        quote_channel_id = config["quote_channel_id"]
        if quote_channel_id is None:
            # No quote channel configured — fall back to command channel
            return ctx.channel.id == config["command_channel_id"]

        return ctx.channel.id == quote_channel_id

    @commands.command(name="quote")
    async def quote(self, ctx: commands.Context) -> None:
        """
        Generate a random R6 operator quote via AI.

        Usage: !quote
        """
        if not settings.quote_enabled:
            return
        if not await self._in_quote_channel(ctx):
            return

        async with ctx.typing():
            try:
                result = await quote_agent.run("Generiere ein Zitat.")
                output: QuoteOutput = result.output
            except Exception as exc:
                await ctx.reply(f"❌ Fehler beim Generieren des Zitats: {exc}")
                return

        embed = discord.Embed(
            description=f'*"{output.quote}"*',
            color=discord.Color.dark_gold(),
        )
        embed.set_footer(text=f"— {output.operator}")
        await ctx.reply(embed=embed)

    async def _health_checks(self) -> tuple[bool, bool, bool]:
        """Run DB, R6Data API, and Claude API checks concurrently."""

        async def check_db() -> None:
            await self.pool.fetchval("SELECT 1")

        async def check_r6() -> None:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("https://api.r6data.eu")
                if resp.status_code >= 500:
                    raise ConnectionError(resp.status_code)

        async def check_ai() -> None:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.anthropic.com/v1/models",
                    headers={
                        "x-api-key": settings.anthropic_api_key,
                        "anthropic-version": "2023-06-01",
                    },
                )
                if resp.status_code != 200:
                    raise ConnectionError(resp.status_code)

        results = await asyncio.gather(
            check_db(), check_r6(), check_ai(),
            return_exceptions=True,
        )
        return tuple(not isinstance(r, Exception) for r in results)

    @commands.command(name="leaderboard", aliases=["lb"])
    async def leaderboard(
        self,
        ctx: commands.Context,
        metric: str = "rp",
    ) -> None:
        """
        Show a ranked leaderboard of all tracked players.

        Usage: !leaderboard [metric]
        Metrics: rp (default), kd, wins
        """
        if not await self._in_command_channel(ctx):
            return

        _METRIC_ALIASES = {
            "rp": "rp", "rank": "rp", "ranked": "rp",
            "kd": "kd", "k/d": "kd",
            "wins": "wins", "win": "wins",
        }
        metric = _METRIC_ALIASES.get(metric.lower())
        if metric is None:
            await ctx.reply("❌ Ungültige Metrik. Nutze: `rp`, `kd` oder `wins`")
            return

        users = await db.get_all_users(self.pool)
        if not users:
            await ctx.reply("❌ Keine Spieler registriert.")
            return

        async with ctx.typing():
            async def fetch(user):
                try:
                    stats = await self.r6.get_player_stats(
                        user["r6_username"], user["platform"]
                    )
                    return user["r6_username"], stats
                except Exception:
                    return None

            results = await asyncio.gather(*[fetch(u) for u in users])

        entries = [(name, s) for r in results if r and (name := r[0]) and (s := r[1])]

        if not entries:
            await ctx.reply("❌ Konnte keine Stats abrufen.")
            return

        if metric == "rp":
            entries.sort(key=lambda x: x[1].rankPoints, reverse=True)
            label = "RANK POINTS"
            def fmt(s): return f"{s.rank}  •  {s.rankPoints:,} RP"
        elif metric == "kd":
            entries.sort(key=lambda x: _kd(x[1].kills, x[1].deaths), reverse=True)
            label = "K/D RATIO"
            def fmt(s): return f"{_kd(s.kills, s.deaths)}  •  {s.kills:,}K / {s.deaths:,}D"
        else:  # wins
            entries.sort(key=lambda x: x[1].wins, reverse=True)
            label = "WINS"
            def fmt(s):
                total = s.wins + s.losses
                wr = round(s.wins / total * 100, 1) if total > 0 else 0.0
                return f"{s.wins}W / {s.losses}L  •  {wr}%"

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (name, stats) in enumerate(entries):
            pos = medals[i] if i < 3 else f"`{i + 1}.`"
            lines.append(f"{pos}  **{name}**\n{' ' * 5}{fmt(stats)}")

        _, top_stats = entries[0]
        color, _ = _tier_style(top_stats.rank)

        embed = discord.Embed(
            title=f"🏆  LEADERBOARD  —  {label}",
            description="\n\n".join(lines),
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.set_footer(text=f"{len(entries)} Spieler  •  Season-Stats")
        await ctx.reply(embed=embed)

    async def _resolve_player(
        self,
        ctx: commands.Context,
        arg: str,
        default_platform: str = "uplay",
    ) -> tuple[str, str]:
        """
        Resolve a command argument to (r6_username, platform).

        Tries to parse arg as a Discord member first (mention or ID).
        If the member is tracked, returns their stored R6 username + platform.
        If not a valid member, treats arg as a raw R6 username.
        """
        try:
            member = await commands.MemberConverter().convert(ctx, arg)
            user_rec = await db.get_user(self.pool, member.id)
            if user_rec is None:
                raise ValueError(
                    f"**{member.display_name}** ist nicht registriert. "
                    f"Nutze `!track` oder gib den R6-Usernamen direkt an."
                )
            return user_rec["r6_username"], user_rec["platform"]
        except commands.MemberNotFound:
            return arg, default_platform

    @commands.command(name="compare")
    async def compare(
        self,
        ctx: commands.Context,
        arg1: str,
        arg2: str,
        platform: str = "uplay",
    ) -> None:
        """
        Compare season stats between any two R6 players.

        Accepts @mention (tracked players) or raw R6 username (anyone).
        Usage: !compare <@user|username> <@user|username> [platform=uplay]
        """
        if not await self._in_command_channel(ctx):
            return

        try:
            (name1, plat1), (name2, plat2) = await asyncio.gather(
                self._resolve_player(ctx, arg1, platform),
                self._resolve_player(ctx, arg2, platform),
            )
        except ValueError as exc:
            await ctx.reply(f"❌ {exc}")
            return

        if name1.lower() == name2.lower():
            await ctx.reply("❌ Kannst du nicht mit dir selbst vergleichen.")
            return

        async with ctx.typing():
            try:
                (stats1, ops1), (stats2, ops2) = await asyncio.gather(
                    asyncio.gather(
                        self.r6.get_player_stats(name1, plat1),
                        self.r6.get_operator_stats(name1, plat1),
                    ),
                    asyncio.gather(
                        self.r6.get_player_stats(name2, plat2),
                        self.r6.get_operator_stats(name2, plat2),
                    ),
                )
            except ValueError as exc:
                await ctx.reply(f"❌ Spieler nicht gefunden: {exc}")
                return

        kd1  = _kd(stats1.kills, stats1.deaths)
        kd2  = _kd(stats2.kills, stats2.deaths)
        tot1 = stats1.wins + stats1.losses
        tot2 = stats2.wins + stats2.losses
        wr1  = round(stats1.wins / tot1 * 100, 1) if tot1 > 0 else 0.0
        wr2  = round(stats2.wins / tot2 * 100, 1) if tot2 > 0 else 0.0
        op1  = ops1[0].name if ops1 else "—"
        op2  = ops2[0].name if ops2 else "—"

        # Score: count how many categories each player wins
        scored = [
            stats1.rankPoints > stats2.rankPoints,  # rank
            kd1 > kd2,                               # K/D
            wr1 > wr2,                               # win rate
            stats1.kills > stats2.kills,             # kills
        ]
        p1_score = sum(scored)
        p2_score = sum(not s for s in scored)

        if p1_score > p2_score:
            color, winner_line = discord.Color.green(), f"**{name1}** gewinnt  {p1_score} — {p2_score}"
        elif p2_score > p1_score:
            color, winner_line = discord.Color.red(),   f"**{name2}** gewinnt  {p2_score} — {p1_score}"
        else:
            color, winner_line = discord.Color.greyple(), f"Unentschieden  {p1_score} — {p2_score}"

        def _w(v1, v2, s1: str, s2: str) -> tuple[str, str]:
            """Return (val1_str, val2_str) with the winner bolded."""
            if v1 > v2:
                return f"**{s1}**", s2
            if v2 > v1:
                return s1, f"**{s2}**"
            return s1, s2

        r_rp1, r_rp2   = _w(stats1.rankPoints, stats2.rankPoints,
                              f"{stats1.rank}\n{stats1.rankPoints:,} RP",
                              f"{stats2.rank}\n{stats2.rankPoints:,} RP")
        r_kd1, r_kd2   = _w(kd1,  kd2,  str(kd1),  str(kd2))
        r_wr1, r_wr2   = _w(wr1,  wr2,  f"{wr1}%",  f"{wr2}%")
        r_k1,  r_k2    = _w(stats1.kills, stats2.kills,
                              f"{stats1.kills:,}K / {stats1.deaths:,}D",
                              f"{stats2.kills:,}K / {stats2.deaths:,}D")
        r_w1,  r_w2    = _w(stats1.wins,  stats2.wins,
                              f"{stats1.wins}W / {stats1.losses}L",
                              f"{stats2.wins}W / {stats2.losses}L")

        Z = "\u200b"  # zero-width space for empty field names

        embed = discord.Embed(
            description=f"## ⚔️  {name1}  vs  {name2}\n{winner_line}",
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        # ── Column headers ──────────────────────────────────────────
        embed.add_field(name=f"🔵  {name1}", value=Z, inline=True)
        embed.add_field(name=Z,              value=Z, inline=True)
        embed.add_field(name=f"🔴  {name2}", value=Z, inline=True)

        # ── Stat rows ───────────────────────────────────────────────
        for v1, label, v2 in [
            (r_rp1,  "🏆\nRANG",     r_rp2),
            (r_kd1,  "🎯\nK / D",    r_kd2),
            (r_wr1,  "📊\nWIN RATE", r_wr2),
            (r_k1,   "💀\nKILLS",    r_k2),
            (r_w1,   "✅\nW / L",    r_w2),
            (op1,    "🎭\nMAIN",     op2),
        ]:
            embed.add_field(name=Z, value=v1,    inline=True)
            embed.add_field(name=Z, value=label, inline=True)
            embed.add_field(name=Z, value=v2,    inline=True)

        embed.set_footer(text=f"Season-Stats  •  {name1} vs {name2}")
        await ctx.reply(embed=embed)

    @commands.command(name="setupdate")
    @commands.has_permissions(administrator=True)
    async def setupdate(
        self,
        ctx: commands.Context,
        update_channel: discord.TextChannel,
    ) -> None:
        """
        Set the channel where changelog updates are posted.

        Usage: !setupdate #channel
        Requires administrator permission.
        """
        existing = await db.get_guild_config(self.pool, ctx.guild.id)
        if existing is None:
            await ctx.reply("❌ Bitte erst `!setup` ausführen.")
            return

        await db.upsert_guild_config(
            self.pool,
            ctx.guild.id,
            existing["post_channel_id"],
            existing["command_channel_id"],
            existing["quote_channel_id"],
            update_channel.id,
        )
        await ctx.reply(f"✅ Update-Channel gesetzt: {update_channel.mention}")

    @setupdate.error
    async def setupdate_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Post the latest changelog section to each guild's update channel if it changed."""
        section_hash, title, sections = _parse_latest_changelog()
        if not title:
            return

        _SECTION_ICONS = {
            "Added":   "🟢  ADDED",
            "Changed": "🟡  CHANGED",
            "Fixed":   "🔧  FIXED",
            "Removed": "🔴  REMOVED",
        }

        for guild in self.bot.guilds:
            config = await db.get_guild_config(self.pool, guild.id)
            if config is None:
                continue

            if config["last_changelog_hash"] == section_hash:
                continue

            channel_id = config["update_channel_id"] or config["command_channel_id"]
            channel = guild.get_channel(channel_id)
            if not isinstance(channel, discord.TextChannel):
                continue

            embed = discord.Embed(
                title=f"📋  {title}",
                color=discord.Color.from_str("#E8272E"),
                timestamp=datetime.datetime.now(tz=timezone.utc),
            )

            for section_name, entries in sections.items():
                if not entries:
                    continue
                icon = _SECTION_ICONS.get(section_name, f"▸  {section_name.upper()}")
                value = "\n".join(f"• {e}" for e in entries)
                # Truncate field to Discord's 1024 char limit
                if len(value) > 1020:
                    value = value[:1020] + "\n…"
                embed.add_field(name=icon, value=value, inline=False)

            embed.set_footer(text="R6 Tracker Bot  •  Changelog")

            try:
                await channel.send(embed=embed)
                await db.set_changelog_hash(self.pool, guild.id, section_hash)
            except discord.HTTPException:
                pass

    @commands.command(name="info")
    async def info(self, ctx: commands.Context) -> None:
        """
        Post a styled embed explaining all available commands.

        Usage: !info
        """
        if not await self._in_command_channel(ctx):
            return

        async with ctx.typing():
            db_ok, r6_ok, ai_ok = await self._health_checks()

        all_ok  = db_ok and r6_ok and ai_ok
        any_ok  = db_ok or r6_ok or ai_ok

        def status_line(label: str, ok: bool) -> str:
            return f"+ {label:<14} ONLINE" if ok else f"- {label:<14} OFFLINE"

        if all_ok:
            overall = "+ OVERALL        ONLINE"
        elif any_ok:
            overall = "! OVERALL        DEGRADED"
        else:
            overall = "- OVERALL        OFFLINE"

        status_block = "\n".join([
            status_line("DATABASE", db_ok),
            status_line("R6DATA API", r6_ok),
            status_line("KI (CLAUDE)", ai_ok),
            "─" * 26,
            overall,
        ])

        embed = discord.Embed(
            title="RAINBOW SIX SIEGE  //  TRACKER",
            description=(
                f"```diff\n{status_block}\n```"
                f"```fix\n"
                f"SNAPSHOT: {settings.snapshot_hour:02d}:{settings.snapshot_minute:02d}  |  "
                f"REPORT: {settings.daily_hour:02d}:{settings.daily_minute:02d} CET\n"
                f"```"
                "Ich tracke eure Stats, analysiere euer Versagen und präsentiere\n"
                "es jeden Abend mit KI-generierter Kritik. Kein Mitleid. Nur Daten."
            ),
            color=discord.Color.from_str("#E8272E"),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        # ── Account ────────────────────────────────────────────────────
        embed.add_field(
            name="▸  ACCOUNT",
            value=(
                "```yaml\n"
                "!track <username> [platform]  # Account verknüpfen\n"
                "!untrack                       # Tracking beenden\n"
                "```"
                "`platform` → `uplay` *(Standard)*, `psn`, `xbl`"
            ),
            inline=False,
        )

        # ── Stats ──────────────────────────────────────────────────────
        embed.add_field(
            name="▸  STATISTIKEN",
            value=(
                "```yaml\n"
                "!stats              # Heutiger Delta seit Mitternacht\n"
                "!stats @user        # Delta eines anderen Spielers\n"
                "!season             # Vollständige Season-Übersicht\n"
                "!season @user       # Season-Stats eines anderen\n"
                "!compare p1 p2      # Season-Vergleich zweier Spieler\n"
                "!leaderboard [rp|kd|wins]  # Server-Rangliste\n"
                "```"
                "`p1`/`p2` → `@mention` oder R6-Username  •  Alias: `!lb`"
            ),
            inline=False,
        )

        # ── Daily Report ───────────────────────────────────────────────
        embed.add_field(
            name="▸  TÄGLICHER REPORT  //  22:00 UHR",
            value=(
                "```yaml\n"
                "Kills  Deaths  W/L  Rang-Delta  Top-Operator\n"
                "```"
                "Automatisch für jeden aktiven Spieler — "
                "generiert von einer KI die kein Erbarmen kennt."
            ),
            inline=False,
        )

        # ── Quote (optional) ───────────────────────────────────────────
        if settings.quote_enabled:
            embed.add_field(
                name="▸  OPERATOR INTEL",
                value=(
                    "```yaml\n"
                    "!quote  # KI-generiertes Zitat eines R6-Operators\n"
                    "```"
                ),
                inline=False,
            )

        embed.set_footer(
            text="Nur registrierte Spieler erscheinen im Daily Report  •  !track um mitzumachen"
        )

        await ctx.send(embed=embed)


_CHANGELOG_PATH = Path(__file__).parent.parent / "CHANGELOG.md"


def _parse_latest_changelog() -> tuple[str, str, dict[str, list[str]]]:
    """
    Parse CHANGELOG.md and return (hash, title, sections) of the first ## block.

    sections is a dict like {"Added": [...], "Changed": [...], "Fixed": [...]}
    Returns empty values if the file is missing or unparseable.
    """
    if not _CHANGELOG_PATH.exists():
        return "", "", {}

    text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    parts = text.split("\n## ")
    raw = parts[1] if len(parts) > 1 else ""
    if not raw:
        return "", "", {}

    lines = raw.strip().splitlines()
    title = lines[0].strip()  # e.g. "[Unreleased] — 2026-03-29"
    section_hash = hashlib.md5(raw.encode()).hexdigest()

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.startswith("### "):
            current = line[4:].strip()
            sections[current] = []
        elif current and line.startswith("- "):
            # Only top-level bullet points, strip markdown bold/code for readability
            entry = line[2:].strip()
            sections[current].append(entry)

    return section_hash, title, sections


async def setup(bot: commands.Bot) -> None:
    """Entry point called by bot.load_extension()."""
    await bot.add_cog(StatsCog(bot))
