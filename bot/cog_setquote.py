"""
bot/cog_setquote.py — !setquote command (standalone, future paid feature).
"""

from __future__ import annotations

import discord
from discord.ext import commands

from db import models as db


class SetQuoteCog(commands.Cog, name="SetQuote"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    @commands.command(name="setquote")
    @commands.has_permissions(administrator=True)
    async def setquote(
        self,
        ctx: commands.Context,
        quote_channel: discord.TextChannel,
    ) -> None:
        """
        Set (or update) the quote channel without re-running !setup.

        Usage: !setquote #channel
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
            existing["update_channel_id"],
        )
        await ctx.reply(f"✅ Quote-Channel gesetzt: {quote_channel.mention}")

    @setquote.error
    async def setquote_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetQuoteCog(bot))
