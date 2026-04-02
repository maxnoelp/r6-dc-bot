"""
bot/cog_admin.py — !info command and changelog on_ready listener.
"""

from __future__ import annotations

import asyncio
import datetime
import hashlib
from datetime import timezone
from pathlib import Path

import discord
import httpx
from discord.ext import commands

from config import settings
from db import models as db

_CHANGELOG_PATH = Path(__file__).parent.parent / "CHANGELOG.md"


def _parse_latest_changelog() -> tuple[str, str, dict[str, list[str]]]:
    if not _CHANGELOG_PATH.exists():
        return "", "", {}

    text = _CHANGELOG_PATH.read_text(encoding="utf-8")
    parts = text.split("\n## ")
    raw = parts[1] if len(parts) > 1 else ""
    if not raw:
        return "", "", {}

    lines = raw.strip().splitlines()
    title = lines[0].strip()
    section_hash = hashlib.md5(raw.encode()).hexdigest()

    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines[1:]:
        if line.startswith("### "):
            current = line[4:].strip()
            sections[current] = []
        elif current and line.startswith("- "):
            sections[current].append(line[2:].strip())

    return section_hash, title, sections


class AdminCog(commands.Cog, name="Admin"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    async def _in_command_channel(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return True
        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None:
            return True
        return ctx.channel.id == config["command_channel_id"]

    async def _health_checks(self) -> tuple[bool, bool, bool]:
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
            check_db(),
            check_r6(),
            check_ai(),
            return_exceptions=True,
        )
        return tuple(not isinstance(r, Exception) for r in results)

    @commands.command(name="info")
    async def info(self, ctx: commands.Context) -> None:
        """Post a styled help embed with live health checks. Usage: !info"""
        if not await self._in_command_channel(ctx):
            return

        async with ctx.typing():
            db_ok, r6_ok, ai_ok = await self._health_checks()

        all_ok = db_ok and r6_ok and ai_ok
        any_ok = db_ok or r6_ok or ai_ok

        def status_line(label: str, ok: bool) -> str:
            return f"+ {label:<14} ONLINE" if ok else f"- {label:<14} OFFLINE"

        if all_ok:
            overall = "+ OVERALL        ONLINE"
        elif any_ok:
            overall = "! OVERALL        DEGRADED"
        else:
            overall = "- OVERALL        OFFLINE"

        status_block = "\n".join(
            [
                status_line("DATABASE", db_ok),
                status_line("R6DATA API", r6_ok),
                status_line("KI (CLAUDE)", ai_ok),
                "─" * 26,
                overall,
            ]
        )

        embed = discord.Embed(
            title="RAINBOW SIX SIEGE  //  TRACKER",
            description=(
                f"```diff\n{status_block}\n```"
                f"```fix\n"
                "Bot-Version: 0.0.2\n"
                "Entwickelt von MaxNoelp\n"
            ),
            color=discord.Color.from_str("#E8272E"),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        if settings.r6_enabled and settings.quote_enabled:
            embed.add_field(
                name="▸  OPERATOR RANDOM QUOTES",
                value=(
                    "```yaml\n!quote  # KI-generiertes Zitat eines R6-Operators\n```"
                ),
                inline=False,
            )

        if settings.r6_enabled:
            embed.add_field(
                name="▸  ACCOUNT",
                value=(
                    "```yaml\n"
                    "!track <username> [platform]  # Account verknüpfen\n"
                    "!untrack                       # Tracking beenden\n"
                    "```"
                    "`platform` → `uplay` *(Standard)*, `psn`, `xbl`"
                    f"```fix\n"
                    f"REPORT: {settings.daily_hour:02d}:{settings.daily_minute:02d} CET\n"
                    f"```"
                    "Ich tracke eure Stats, analysiere euer Versagen und präsentiere\n"
                    "es jeden Abend mit KI-generierter Kritik. Kein Mitleid. Nur Daten."
                ),
                inline=False,
            )

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

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        section_hash, title, sections = _parse_latest_changelog()
        if not title:
            return

        _SECTION_ICONS = {
            "Added": "🟢  ADDED",
            "Changed": "🟡  CHANGED",
            "Fixed": "🔧  FIXED",
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
                if len(value) > 1020:
                    value = value[:1020] + "\n…"
                embed.add_field(name=icon, value=value, inline=False)

            embed.set_footer(text="R6 Tracker Bot  •  Changelog")

            try:
                await channel.send(embed=embed)
                await db.set_changelog_hash(self.pool, guild.id, section_hash)
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
