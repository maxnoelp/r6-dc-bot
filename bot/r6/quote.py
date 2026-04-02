"""bot/r6/quote.py — !quote command (AI-generated R6 operator quote)."""

from __future__ import annotations

import discord
from discord.ext import commands

from agent.critic import QuoteOutput, quote_agent
from bot.r6._base import R6BaseCog
from config import settings
from db import models as db


class QuoteCog(R6BaseCog, name="Quote"):

    async def _in_quote_channel(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return True
        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None:
            return True
        quote_channel_id = config["quote_channel_id"]
        if quote_channel_id is None:
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(QuoteCog(bot))
