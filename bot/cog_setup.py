"""
bot/cog_setup.py — Guild channel configuration commands.

Commands:
- !setup    — configure post, command, and quote channels
- !setupdate — set changelog update channel
"""

from __future__ import annotations

import discord
from discord.ext import commands

from db import models as db


class SetupCog(commands.Cog, name="Setup"):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

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
        Configure the post, command, and optional quote channels for this guild.

        Usage: !setup #post-channel #command-channel [#quote-channel]
        Requires administrator permission.
        """
        if quote_channel is None:
            existing         = await db.get_guild_config(self.pool, ctx.guild.id)
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

        quote_mention = f"<#{quote_channel_id}>" if quote_channel_id else "_(nicht gesetzt)_"
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))
