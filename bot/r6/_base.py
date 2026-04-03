"""bot/r6/_base.py — Base cog with shared properties and channel guard."""

from __future__ import annotations

import discord
from discord.ext import commands

from db import models as db
from r6api.client import R6DataClient


class R6BaseCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    @property
    def r6(self) -> R6DataClient:
        return self.bot.r6_client

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
