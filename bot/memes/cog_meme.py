"""
bot/memes/cog_meme.py — !meme command + !memeset setup.
"""

from __future__ import annotations

import random

import discord
import httpx
from discord.ext import commands

from db import models as db

_SUBREDDITS = [
    "memes",
    "dankmemes",
    "me_irl",
    "AdviceAnimals",
    "HolUp",
]

_HEADERS = {"User-Agent": "r6-dc-bot/1.0"}
_IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp")


class MemeCog(commands.Cog, name="Meme"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    async def _in_meme_channel(self, ctx: commands.Context) -> bool:
        if ctx.guild is None:
            return True
        config = await db.get_guild_config(self.pool, ctx.guild.id)
        if config is None or config["meme_channel_id"] is None:
            return True
        return ctx.channel.id == config["meme_channel_id"]

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
            url=f"https://reddit.com{post['permalink']}",
            color=discord.Color.orange(),
        )
        embed.set_image(url=post["url"])
        embed.set_footer(
            text=f"r/{post['subreddit']}  •  👍 {post['ups']:,}  •  💬 {post['num_comments']:,}"
        )
        await ctx.send(embed=embed)

    async def _fetch_meme(self) -> dict | None:
        subreddit = random.choice(_SUBREDDITS)
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=50"

        try:
            async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as client:
                resp = await client.get(url, follow_redirects=True)
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            return None

        posts = [
            p["data"]
            for p in data["data"]["children"]
            if not p["data"].get("stickied")
            and not p["data"].get("is_video")
            and p["data"].get("url", "").lower().endswith(_IMAGE_EXTS)
        ]

        return random.choice(posts) if posts else None

    @meme.error
    async def meme_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.reply(f"⏳ Noch {error.retry_after:.1f}s warten.", delete_after=5)

    # ------------------------------------------------------------------
    # !memeset
    # ------------------------------------------------------------------

    @commands.command(name="memeset")
    @commands.has_permissions(administrator=True)
    async def memeset(
        self, ctx: commands.Context, channel: discord.TextChannel
    ) -> None:
        """
        Set the channel where !meme is allowed.

        Usage: !memeset #memes
        Requires administrator permission.
        """
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemeCog(bot))
