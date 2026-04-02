"""bot/r6/stats.py — !stats command (daily delta since midnight snapshot)."""

from __future__ import annotations

import datetime
from datetime import timezone

import discord
from discord.ext import commands

from bot.r6._base import R6BaseCog
from bot.r6._utils import delta_color, kd, rank_delta_str
from db import models as db


class StatsCog(R6BaseCog, name="Stats"):

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

        target      = member or ctx.author
        user_record = await db.get_user(self.pool, target.id)

        if user_record is None:
            await ctx.reply(f"❌ {target.display_name} ist nicht registriert. Nutze `!track <username>`.")
            return

        username: str = user_record["r6_username"]
        platform: str = user_record["platform"]

        snapshot = await db.get_latest_snapshot(self.pool, target.id)
        if snapshot is None:
            await ctx.reply(
                "📭 Noch kein Snapshot vorhanden. "
                "Der erste Snapshot wird heute Nacht um Mitternacht erstellt."
            )
            return

        try:
            live           = await self.r6.get_player_stats(username, platform)
            operator_stats = await self.r6.get_operator_stats(username, platform)
        except ValueError as exc:
            await ctx.reply(f"❌ Fehler beim Abrufen der Stats: {exc}")
            return

        kill_delta  = live.kills      - (snapshot["total_kills"]  or 0)
        death_delta = live.deaths     - (snapshot["total_deaths"] or 0)
        win_delta   = live.wins       - (snapshot["total_wins"]   or 0)
        loss_delta  = live.losses     - (snapshot["total_losses"] or 0)
        rp_delta    = live.rankPoints - (snapshot["rank_points"]  or 0)

        kd_val = kd(kill_delta, death_delta)

        embed = discord.Embed(
            title=f"📊 Tages-Stats: {username}",
            color=delta_color(rp_delta),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.set_footer(text=f"Plattform: {platform}")
        embed.add_field(name="Rang",      value=f"{live.rank} ({rank_delta_str(rp_delta)})",        inline=True)
        embed.add_field(name="K/D heute", value=f"{kill_delta}K / {death_delta}D (KD: {kd_val})",  inline=True)
        embed.add_field(name="W/L heute", value=f"{win_delta}W / {loss_delta}L",                   inline=True)

        if operator_stats:
            top_op = operator_stats[0]
            embed.add_field(
                name="Meistgespielter Operator",
                value=f"{top_op.name} ({top_op.roundsPlayed} Runden gespielt)",
                inline=False,
            )

        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
