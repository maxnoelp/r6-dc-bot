"""bot/r6/track.py — !track and !untrack commands."""

from __future__ import annotations

from discord.ext import commands

from bot.r6._base import R6BaseCog
from db import models as db


class TrackCog(R6BaseCog, name="Track"):

    @commands.command(name="track")
    async def track(
        self,
        ctx: commands.Context,
        username: str,
        platform: str = "uplay",
    ) -> None:
        """
        Register a Rainbow Six Siege account for daily tracking.

        Usage: !track <username> [platform=uplay]
        """
        if not await self._in_command_channel(ctx):
            return

        async with ctx.typing():
            try:
                account = await self.r6.get_account_info(username, platform)
                stats   = await self.r6.get_player_stats(username, platform)
            except ValueError as exc:
                await ctx.reply(f"❌ Spieler nicht gefunden. ({exc})")
                return

            await db.upsert_user(
                self.pool,
                ctx.author.id,
                account.nameOnPlatform,
                account.profileId,
                account.platformType,
            )

        has_snapshot = await db.get_latest_snapshot(self.pool, ctx.author.id) is not None
        daily_hint = (
            "" if has_snapshot
            else "\n📅 Dein erster Snapshot wird heute Nacht um Mitternacht erstellt — ab morgen bist du im Daily Report dabei."
        )
        await ctx.reply(
            f"✅ **{account.nameOnPlatform}** ({stats.rank}) wird ab jetzt getrackt!{daily_hint}"
        )

    @commands.command(name="untrack")
    async def untrack(self, ctx: commands.Context) -> None:
        """
        Stop tracking the calling user's R6 account.

        Usage: !untrack
        """
        if not await self._in_command_channel(ctx):
            return

        deleted = await db.delete_user(self.pool, ctx.author.id)
        if deleted:
            await ctx.reply("✅ Du wirst nicht mehr getrackt.")
        else:
            await ctx.reply("❌ Du bist gar nicht registriert.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrackCog(bot))
