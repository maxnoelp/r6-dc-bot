"""
bot/support_system/cog_ticket_setup.py — !ticketsetup command.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from db import models as db


class TicketSetupCog(commands.Cog, name="TicketSetup"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    @commands.command(name="ticketsetup")
    @commands.has_permissions(administrator=True)
    async def ticketsetup(
        self,
        ctx: commands.Context,
        panel_channel: discord.TextChannel,
        *roles: discord.Role,
    ) -> None:
        """
        Configure the ticket system for this server.

        Usage: !ticketsetup #panel-channel @SupportRole [@AnotherRole ...]
        The ticket category is taken from the panel channel's category automatically.
        Requires administrator permission.
        """
        if not roles:
            await ctx.reply("❌ Mindestens eine Support-Rolle angeben.")
            return

        category_id = panel_channel.category_id
        await db.upsert_ticket_config(self.pool, ctx.guild.id, panel_channel.id, category_id)
        await db.set_ticket_support_roles(self.pool, ctx.guild.id, [r.id for r in roles])

        roles_fmt = " ".join(r.mention for r in roles)
        category_fmt = panel_channel.category.name if panel_channel.category else "*(keine Kategorie)*"

        embed = discord.Embed(
            title="✅  Ticket-System konfiguriert",
            color=discord.Color.green(),
        )
        embed.add_field(name="Panel-Channel", value=panel_channel.mention, inline=True)
        embed.add_field(name="Kategorie", value=category_fmt, inline=True)
        embed.add_field(name="Support-Rollen", value=roles_fmt, inline=False)
        embed.set_footer(text="Nutze !ticketpanel um das Panel zu posten.")
        await ctx.reply(embed=embed)

    @ticketsetup.error
    async def ticketsetup_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketSetupCog(bot))
