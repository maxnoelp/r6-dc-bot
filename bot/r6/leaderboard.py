"""bot/r6/leaderboard.py — !leaderboard command."""

from __future__ import annotations

import asyncio
import datetime
from datetime import timezone

import discord
from discord.ext import commands

from bot.r6._base import R6BaseCog
from bot.r6._utils import kd, tier_style
from db import models as db


class LeaderboardCog(R6BaseCog, name="Leaderboard"):

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
            entries.sort(key=lambda x: kd(x[1].kills, x[1].deaths), reverse=True)
            label = "K/D RATIO"
            def fmt(s): return f"{kd(s.kills, s.deaths)}  •  {s.kills:,}K / {s.deaths:,}D"
        else:
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
        color, _ = tier_style(top_stats.rank)

        embed = discord.Embed(
            title=f"🏆  LEADERBOARD  —  {label}",
            description="\n\n".join(lines),
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.set_footer(text=f"{len(entries)} Spieler  •  Season-Stats")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
