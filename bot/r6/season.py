"""bot/r6/season.py — !season command (full season stats embed)."""

from __future__ import annotations

import datetime
from datetime import timezone

import discord
from discord.ext import commands

from bot.r6._base import R6BaseCog
from bot.r6._utils import kd, rank_icon_url, tier_style, wl
from db import models as db


class SeasonCog(R6BaseCog, name="Season"):

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

        target      = member or ctx.author
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

        color, rank_emoji = tier_style(stats.rank)
        kd_val = kd(stats.kills, stats.deaths)
        wl_val = wl(stats.wins, stats.losses)
        total  = stats.wins + stats.losses

        embed = discord.Embed(
            description=f"### {rank_emoji}  {stats.rank}  •  {stats.rankPoints:,} RP",
            color=color,
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )

        if account.profilePicture:
            embed.set_thumbnail(url=account.profilePicture)

        embed.set_author(
            name=f"{username}  •  {platform.upper()}",
            icon_url=rank_icon_url(stats.rank),
        )

        embed.add_field(name="💀  Kills",    value=f"**{stats.kills:,}**",  inline=True)
        embed.add_field(name="☠️  Deaths",   value=f"**{stats.deaths:,}**", inline=True)
        embed.add_field(name="🎯  K/D",      value=f"**{kd_val}**",         inline=True)

        embed.add_field(name="\u200b", value="", inline=False)

        embed.add_field(name="✅  Wins",     value=f"**{stats.wins}**",   inline=True)
        embed.add_field(name="❌  Losses",   value=f"**{stats.losses}**", inline=True)
        embed.add_field(name="📊  Win Rate", value=f"**{wl_val}**",       inline=True)

        if operators:
            top3 = operators[:3]
            op_lines = "\n".join(
                f"**{i+1}. {op.name}** — {op.roundsPlayed} Runden "
                f"({op.roundsWon}W / {op.roundsPlayed - op.roundsWon}L)"
                for i, op in enumerate(top3)
            )
            embed.add_field(name="\u200b", value="", inline=False)
            embed.add_field(name="🎭  Top Operators", value=op_lines, inline=False)
            icon = top3[0].iconUrl
            if icon and icon.startswith(("http://", "https://")):
                embed.set_image(url=icon)

        embed.set_footer(text=f"{total} Matches diese Season")
        await ctx.reply(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SeasonCog(bot))
