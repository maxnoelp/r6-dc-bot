"""
bot/memes/cog_meme.py — !meme command, !memeset, !memeschedule, !memescheduleclear.
"""

from __future__ import annotations

import logging
import random

import discord
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from discord.ext import commands

from db import models as db

log = logging.getLogger(__name__)

_SUBREDDITS = [
    "memes",
    "dankmemes",
    "me_irl",
    "AdviceAnimals",
    "HolUp",
]

_MEME_API = "https://meme-api.com/gimme"


class MemeCog(commands.Cog, name="Meme"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    @property
    def pool(self):
        return self.bot.db_pool

    # ------------------------------------------------------------------
    # Cog lifecycle
    # ------------------------------------------------------------------

    async def cog_load(self) -> None:
        self._scheduler.start()
        # Load all existing schedules from DB
        schedules = await db.get_all_meme_schedules(self.pool)
        for row in schedules:
            self._add_job(row["guild_id"], row["channel_id"], row["post_hour"], row["post_minute"])
        log.info("Meme scheduler started with %d active schedule(s).", len(schedules))

    async def cog_unload(self) -> None:
        self._scheduler.shutdown(wait=False)

    def _add_job(self, guild_id: int, channel_id: int, hour: int, minute: int) -> None:
        self._scheduler.add_job(
            self._auto_post_meme,
            trigger="cron",
            hour=hour,
            minute=minute,
            id=f"meme_{guild_id}",
            replace_existing=True,
            kwargs={"guild_id": guild_id, "channel_id": channel_id},
        )

    def _remove_job(self, guild_id: int) -> None:
        job_id = f"meme_{guild_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)

    async def _auto_post_meme(self, guild_id: int, channel_id: int) -> None:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        post = await self._fetch_meme()
        if post is None:
            log.warning("Auto-meme: no post fetched for guild %s", guild_id)
            return
        embed = discord.Embed(
            title=post["title"],
            url=post.get("postLink", ""),
            color=discord.Color.orange(),
        )
        embed.set_image(url=post["url"])
        embed.set_footer(
            text=f"r/{post['subreddit']}  •  👍 {post.get('ups', 0):,}"
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            log.exception("Auto-meme: failed to post in guild %s", guild_id)

    # ------------------------------------------------------------------
    # Channel guard
    # ------------------------------------------------------------------

    async def _in_meme_channel(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return True
        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None or config["meme_channel_id"] is None:
            return True
        if ctx.channel.id == config["meme_channel_id"]:
            return True
        channel = ctx.guild.get_channel(config["meme_channel_id"])
        hint = channel.mention if channel else "`#memes`"
        await ctx.reply(f"❌ `!meme` funktioniert nur in {hint}.", delete_after=8)
        return False

    # ------------------------------------------------------------------
    # !meme
    # ------------------------------------------------------------------

    @commands.command(name="meme")
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    async def meme(self, ctx: commands.Context) -> None:
        """Post a random meme from Reddit. Usage: !meme"""
        if not await self._in_meme_channel(ctx):
            return

        async with ctx.typing():
            post = await self._fetch_meme()

        if post is None:
            await ctx.reply("❌ Konnte kein Meme laden. Versuch's nochmal.")
            return

        embed = discord.Embed(
            title=post["title"],
            url=post.get("postLink", ""),
            color=discord.Color.orange(),
        )
        embed.set_image(url=post["url"])
        embed.set_footer(
            text=f"r/{post['subreddit']}  •  👍 {post.get('ups', 0):,}"
        )
        await ctx.send(embed=embed)

    async def _fetch_meme(self) -> dict | None:
        subreddit = random.choice(_SUBREDDITS)
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{_MEME_API}/{subreddit}", follow_redirects=True)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None

        # meme-api returns nsfw flag and post_link — skip nsfw
        if data.get("nsfw") or not data.get("url"):
            return None
        return data

    @meme.error
    async def meme_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ Noch {error.retry_after:.1f}s warten.", delete_after=5)

    # ------------------------------------------------------------------
    # !memeset
    # ------------------------------------------------------------------

    @commands.command(name="memeset")
    @commands.has_permissions(administrator=True)
    async def memeset(self, ctx: commands.Context, channel: discord.TextChannel) -> None:
        """Set the channel where !meme is allowed. Usage: !memeset #channel"""
        existing = await db.get_guild_config(self.pool, ctx.guild.id)
        if existing is None:
            await ctx.reply("❌ Bitte erst `!setup` ausführen.")
            return
        await db.set_meme_channel(self.pool, ctx.guild.id, channel.id)
        await ctx.reply(f"✅ Meme-Channel gesetzt: {channel.mention}")

    @memeset.error
    async def memeset_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    # ------------------------------------------------------------------
    # !memeschedule
    # ------------------------------------------------------------------

    @commands.command(name="memeschedule")
    @commands.has_permissions(administrator=True)
    async def memeschedule(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        time: str,
    ) -> None:
        """
        Schedule a daily automatic meme post.

        Usage: !memeschedule #channel 12:00
        Time is in 24h format (CET/CEST). Requires administrator permission.
        """
        try:
            hour, minute = (int(x) for x in time.split(":"))
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except ValueError:
            await ctx.reply("❌ Ungültige Uhrzeit. Format: `HH:MM` (z.B. `12:00`)")
            return

        await db.upsert_meme_schedule(self.pool, ctx.guild.id, channel.id, hour, minute)
        self._add_job(ctx.guild.id, channel.id, hour, minute)

        await ctx.reply(
            f"✅ Täglich um `{hour:02d}:{minute:02d}` wird ein Meme in {channel.mention} gepostet."
        )

    @memeschedule.error
    async def memeschedule_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.reply("❌ Usage: `!memeschedule #channel HH:MM`")

    # ------------------------------------------------------------------
    # !memescheduleclear
    # ------------------------------------------------------------------

    @commands.command(name="memescheduleclear")
    @commands.has_permissions(administrator=True)
    async def memescheduleclear(self, ctx: commands.Context) -> None:
        """Remove the daily meme auto-post schedule. Usage: !memescheduleclear"""
        await db.delete_meme_schedule(self.pool, ctx.guild.id)
        self._remove_job(ctx.guild.id)
        await ctx.reply("✅ Automatischer Meme-Post deaktiviert.")

    @memescheduleclear.error
    async def memescheduleclear_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemeCog(bot))
