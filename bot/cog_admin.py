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
        if ctx.channel.id == config["command_channel_id"]:
            return True
        channel = ctx.guild.get_channel(config["command_channel_id"])
        hint = channel.mention if channel else "`#bot-commands`"
        await ctx.reply(
            f"❌ Dieser Command funktioniert nur in {hint}.",
            delete_after=8,
        )
        return False

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

        # Load guild config + ticket config for channel hints
        guild_config = await db.get_guild_config(self.pool, ctx.guild.id) if ctx.guild else None
        ticket_config = await db.get_ticket_config(self.pool, ctx.guild.id) if ctx.guild else None

        def ch(channel_id: int | None) -> str:
            if channel_id is None or ctx.guild is None:
                return "*(nicht gesetzt)*"
            c = ctx.guild.get_channel(channel_id)
            return c.mention if c else "*(nicht gefunden)*"

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

        status_lines = [status_line("DATABASE", db_ok)]
        if settings.r6_enabled:
            status_lines.append(status_line("R6DATA API", r6_ok))
        status_lines.append(status_line("KI (CLAUDE)", ai_ok))
        status_lines += ["─" * 26, overall]

        status_block = "\n".join(status_lines)

        embed = discord.Embed(
            title="BOT  //  ÜBERSICHT",
            description=(
                f"```diff\n{status_block}\n```"
                "```fix\n"
                "Bot-Version: 0.0.2\n"
                "Entwickelt von MaxNoelp\n"
                "```"
            ),
            color=discord.Color.from_str("#E8272E"),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        cmd_ch  = ch(guild_config["command_channel_id"] if guild_config else None)
        post_ch = ch(guild_config["post_channel_id"] if guild_config else None)

        if settings.r6_enabled:
            embed.add_field(
                name="▸  ACCOUNT",
                value=(
                    "```yaml\n"
                    "!track <username> [platform]  # Account verknüpfen\n"
                    "!untrack                       # Tracking beenden\n"
                    "```"
                    f"`platform` → `uplay` *(Standard)*, `psn`, `xbl`\n"
                    f"Channel: {cmd_ch}\n"
                    f"```fix\n"
                    f"REPORT: {settings.daily_hour:02d}:{settings.daily_minute:02d} CET → {post_ch}\n"
                    "```"
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
                    f"`p1`/`p2` → `@mention` oder R6-Username  •  Alias: `!lb`\n"
                    f"Channel: {cmd_ch}"
                ),
                inline=False,
            )

            if settings.quote_enabled:
                quote_ch = ch(
                    (guild_config["quote_channel_id"] or guild_config["command_channel_id"])
                    if guild_config else None
                )
                embed.add_field(
                    name="▸  OPERATOR INTEL",
                    value=(
                        "```yaml\n"
                        "!quote  # KI-generiertes Zitat eines R6-Operators\n"
                        "```"
                        f"Channel: {quote_ch}"
                    ),
                    inline=False,
                )

        if settings.memes_enabled:
            meme_ch = ch(
                (guild_config["meme_channel_id"] or guild_config["command_channel_id"])
                if guild_config else None
            )
            embed.add_field(
                name="▸  MEMES",
                value=(
                    "```yaml\n"
                    "!meme  # Zufälliges Meme von Reddit\n"
                    "```"
                    f"Channel: {meme_ch}"
                ),
                inline=False,
            )

        if settings.tickets_enabled:
            panel_ch = ch(ticket_config["panel_channel_id"] if ticket_config else None)
            embed.add_field(
                name="▸  SUPPORT",
                value=(
                    "```yaml\n"
                    "🎫 Ticket öffnen  # Button im Panel-Channel klicken\n"
                    "```"
                    f"Panel: {panel_ch}"
                ),
                inline=False,
            )

        footer = "!info — Live-Statuscheck aller Dienste"
        if settings.r6_enabled:
            footer = "Nur registrierte Spieler erscheinen im Daily Report  •  !track um mitzumachen"
        embed.set_footer(text=footer)
        await ctx.send(embed=embed)

    # ------------------------------------------------------------------
    # !listallcommands
    # ------------------------------------------------------------------

    @commands.command(name="listallcommands", aliases=["lac"])
    @commands.has_permissions(administrator=True)
    async def listallcommands(self, ctx: commands.Context) -> None:
        """List all active commands grouped by feature. Admin only. Usage: !listallcommands"""
        if not await self._in_command_channel(ctx):
            return

        embed = discord.Embed(
            title="📋  ALLE COMMANDS",
            color=discord.Color.from_str("#E8272E"),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        # Always available
        embed.add_field(
            name="⚙️  SETUP  (Admin)",
            value=(
                "`!setup #post #commands [#quotes]`\n"
                "`!setupdate #channel`\n"
                "`!setquote #channel`\n"
                "`!info`\n"
                "`!listallcommands` · `!lac`"
            ),
            inline=False,
        )

        if settings.r6_enabled:
            embed.add_field(
                name="🎮  R6 — ACCOUNT",
                value=(
                    "`!track <username> [platform]`\n"
                    "`!untrack`"
                ),
                inline=True,
            )
            embed.add_field(
                name="📊  R6 — STATISTIKEN",
                value=(
                    "`!stats [@user]`\n"
                    "`!season [@user]`\n"
                    "`!compare <p1> <p2>`\n"
                    "`!leaderboard [rp|kd|wins]` · `!lb`"
                ),
                inline=True,
            )
            embed.add_field(
                name="🗓️  R6 — REPORT  (Admin)",
                value=(
                    "`!snapshot`\n"
                    "`!report [offset]`\n"
                    "`!showsnapshot [@user] [offset]`"
                ),
                inline=True,
            )
            if settings.quote_enabled:
                embed.add_field(
                    name="💬  OPERATOR INTEL",
                    value="`!quote`",
                    inline=True,
                )

        if settings.memes_enabled:
            embed.add_field(
                name="😂  MEMES",
                value=(
                    "`!meme`\n"
                    "`!memeset #channel`  *(Admin)*\n"
                    "`!memeschedule #channel HH:MM`  *(Admin)*\n"
                    "`!memescheduleclear`  *(Admin)*"
                ),
                inline=True,
            )

        if settings.tickets_enabled:
            embed.add_field(
                name="🎫  SUPPORT  (Admin)",
                value=(
                    "`!ticketsetup #channel @role ...`\n"
                    "`!ticketpanel`"
                ),
                inline=True,
            )

        embed.set_footer(text="Nur für Admins sichtbar  •  Zeigt nur aktive Features")
        await ctx.send(embed=embed, ephemeral=False)
        # Delete invoking message so it stays clean
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    @listallcommands.error
    async def listallcommands_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.", delete_after=5)

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
