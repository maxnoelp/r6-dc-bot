"""bot/r6/compare.py — !compare command (side-by-side season stat comparison)."""

from __future__ import annotations

import asyncio
import datetime
from datetime import timezone

import discord
from discord.ext import commands

from bot.r6._base import R6BaseCog
from bot.r6._utils import kd, tier_style
from db import models as db


class CompareCog(R6BaseCog, name="Compare"):

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
            member    = await commands.MemberConverter().convert(ctx, arg)
            user_rec  = await db.get_user(self.pool, member.id)
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

        kd1  = kd(stats1.kills, stats1.deaths)
        kd2  = kd(stats2.kills, stats2.deaths)
        tot1 = stats1.wins + stats1.losses
        tot2 = stats2.wins + stats2.losses
        wr1  = round(stats1.wins / tot1 * 100, 1) if tot1 > 0 else 0.0
        wr2  = round(stats2.wins / tot2 * 100, 1) if tot2 > 0 else 0.0
        op1  = ops1[0].name if ops1 else "—"
        op2  = ops2[0].name if ops2 else "—"

        scored = [
            stats1.rankPoints > stats2.rankPoints,
            kd1 > kd2,
            wr1 > wr2,
            stats1.kills > stats2.kills,
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
            if v1 > v2:
                return f"**{s1}**", s2
            if v2 > v1:
                return s1, f"**{s2}**"
            return s1, s2

        r_rp1, r_rp2 = _w(stats1.rankPoints, stats2.rankPoints,
                           f"{stats1.rank}\n{stats1.rankPoints:,} RP",
                           f"{stats2.rank}\n{stats2.rankPoints:,} RP")
        r_kd1, r_kd2 = _w(kd1, kd2, str(kd1), str(kd2))
        r_wr1, r_wr2 = _w(wr1, wr2, f"{wr1}%", f"{wr2}%")
        r_k1,  r_k2  = _w(stats1.kills, stats2.kills,
                           f"{stats1.kills:,}K / {stats1.deaths:,}D",
                           f"{stats2.kills:,}K / {stats2.deaths:,}D")
        r_w1,  r_w2  = _w(stats1.wins, stats2.wins,
                           f"{stats1.wins}W / {stats1.losses}L",
                           f"{stats2.wins}W / {stats2.losses}L")

        Z = "\u200b"

        embed = discord.Embed(
            description=f"## ⚔️  {name1}  vs  {name2}\n{winner_line}",
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        embed.add_field(name=f"🔵  {name1}", value=Z, inline=True)
        embed.add_field(name=Z,              value=Z, inline=True)
        embed.add_field(name=f"🔴  {name2}", value=Z, inline=True)

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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompareCog(bot))
