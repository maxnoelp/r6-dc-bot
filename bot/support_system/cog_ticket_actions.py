"""
bot/support_system/cog_ticket_actions.py — Ticket lifecycle: open, claim, close.

Also handles:
- Registering persistent Views on cog_load so buttons survive bot restarts.
- on_ready: auto-posts the panel in each configured guild if not already present.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from datetime import timezone

import discord
from discord.ext import commands

from db import models as db
from ._permissions import build_overwrites
from ._views import TicketActionView, TicketOpenView

log = logging.getLogger(__name__)


def _panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🎫  SUPPORT TICKET",
        description=(
            "Hast du ein Problem oder eine Frage?\n"
            "Klicke auf den Button unten um ein privates Ticket zu öffnen.\n\n"
            "Ein Support-Mitglied wird sich so schnell wie möglich bei dir melden."
        ),
        color=discord.Color.from_str("#E8272E"),
        timestamp=datetime.datetime.now(tz=timezone.utc),
    )
    embed.set_footer(text="Support Ticket System")
    return embed


class TicketActionsCog(commands.Cog, name="TicketActions"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @property
    def pool(self):
        return self.bot.db_pool

    async def cog_load(self) -> None:
        self.bot.add_view(TicketOpenView(self))
        self.bot.add_view(TicketActionView(self))

    # ------------------------------------------------------------------
    # on_ready: ensure every configured guild has a panel message
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            try:
                await self._ensure_panel(guild)
            except Exception:
                log.exception("Failed to ensure ticket panel for guild %s", guild.id)

    async def _ensure_panel(self, guild: discord.Guild) -> None:
        config = await db.get_ticket_config(self.pool, guild.id)
        if config is None or config["panel_channel_id"] is None:
            return

        channel = guild.get_channel(config["panel_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return

        # Try to find the existing panel message
        if config["panel_message_id"] is not None:
            try:
                await channel.fetch_message(config["panel_message_id"])
                return  # still there, nothing to do
            except discord.NotFound:
                pass  # message was deleted — post a new one
            except discord.HTTPException:
                return  # unexpected error, skip

        # Post a fresh panel
        msg = await channel.send(embed=_panel_embed(), view=TicketOpenView(self))
        await db.update_panel_message_id(self.pool, guild.id, msg.id)
        log.info("Posted ticket panel in guild %s channel %s", guild.id, channel.id)

    # ------------------------------------------------------------------
    # !ticketpanel — manual panel post (admin command)
    # ------------------------------------------------------------------

    @commands.command(name="ticketpanel")
    @commands.has_permissions(administrator=True)
    async def ticketpanel(self, ctx: commands.Context) -> None:
        """Post the ticket panel in the configured panel channel. Usage: !ticketpanel"""
        config = await db.get_ticket_config(self.pool, ctx.guild.id)
        if config is None or config["panel_channel_id"] is None:
            await ctx.reply("❌ Bitte erst `!ticketsetup` ausführen.")
            return

        channel = ctx.guild.get_channel(config["panel_channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await ctx.reply("❌ Panel-Channel nicht gefunden.")
            return

        msg = await channel.send(embed=_panel_embed(), view=TicketOpenView(self))
        await db.update_panel_message_id(self.pool, ctx.guild.id, msg.id)
        await ctx.reply(f"✅ Panel gepostet in {channel.mention}")

    @ticketpanel.error
    async def ticketpanel_error(self, ctx: commands.Context, error: Exception) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.reply("❌ Du brauchst Administrator-Rechte für diesen Befehl.")

    # ------------------------------------------------------------------
    # Ticket creation (called from modal)
    # ------------------------------------------------------------------

    async def create_ticket_channel(
        self,
        interaction: discord.Interaction,
        title: str,
        reason: str,
    ) -> None:
        guild = interaction.guild
        config = await db.get_ticket_config(self.pool, guild.id)
        if config is None:
            await interaction.followup.send(
                "❌ Das Ticket-System ist nicht konfiguriert.", ephemeral=True
            )
            return

        support_role_ids = await db.get_ticket_support_roles(self.pool, guild.id)

        author = interaction.user
        if not isinstance(author, discord.Member):
            author = guild.get_member(interaction.user.id) or await guild.fetch_member(
                interaction.user.id
            )

        ticket = await db.create_ticket(self.pool, guild.id, author.id, title, reason)
        ticket_id = ticket["id"]
        channel_name = f"ticket-{ticket_id:04d}"

        category = (
            guild.get_channel(config["ticket_category_id"])
            if config["ticket_category_id"]
            else None
        )
        overwrites = build_overwrites(guild, author, support_role_ids)

        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            category=category,
            reason=f"Support Ticket #{ticket_id:04d} by {author}",
        )
        await db.update_ticket_channel_id(self.pool, ticket_id, channel.id)

        embed = discord.Embed(
            title=f"🎫  Ticket #{ticket_id:04d}  —  {title}",
            description=reason,
            color=discord.Color.from_str("#E8272E"),
            timestamp=datetime.datetime.now(tz=timezone.utc),
        )
        embed.add_field(name="Erstellt von", value=author.mention, inline=True)
        embed.add_field(name="Status", value="🟡  Offen", inline=True)
        embed.set_footer(text="Claime das Ticket um es zu übernehmen • Schließen löscht den Channel.")

        await channel.send(embed=embed, view=TicketActionView(self))
        await interaction.followup.send(
            f"✅ Dein Ticket wurde erstellt: {channel.mention}", ephemeral=True
        )

    # ------------------------------------------------------------------
    # Claim
    # ------------------------------------------------------------------

    async def handle_claim(self, interaction: discord.Interaction) -> None:
        ticket = await db.get_ticket_by_channel(self.pool, interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "❌ Ticket nicht gefunden.", ephemeral=True
            )
            return

        if ticket["status"] == "closed":
            await interaction.response.send_message(
                "❌ Dieses Ticket ist bereits geschlossen.", ephemeral=True
            )
            return

        if ticket["status"] == "claimed":
            await interaction.response.send_message(
                "❌ Dieses Ticket wurde bereits geclaimed.", ephemeral=True
            )
            return

        # Check permission: must be support role or admin
        member = interaction.user
        support_role_ids = await db.get_ticket_support_roles(
            self.pool, interaction.guild_id
        )
        is_support = any(r.id in support_role_ids for r in member.roles)
        is_admin = member.guild_permissions.administrator

        if not (is_support or is_admin):
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung, Tickets zu claimen.", ephemeral=True
            )
            return

        await db.claim_ticket(self.pool, ticket["id"], member.id)

        author = (
            interaction.guild.get_member(ticket["author_id"])
            or await interaction.guild.fetch_member(ticket["author_id"])
        )
        overwrites = build_overwrites(
            interaction.guild, author, support_role_ids, claimer=member
        )
        await interaction.channel.edit(overwrites=overwrites)

        await interaction.response.send_message(
            f"✅ {member.mention} hat das Ticket übernommen."
        )

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    async def handle_close(self, interaction: discord.Interaction) -> None:
        ticket = await db.get_ticket_by_channel(self.pool, interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message(
                "❌ Ticket nicht gefunden.", ephemeral=True
            )
            return

        if ticket["status"] == "closed":
            await interaction.response.send_message(
                "❌ Dieses Ticket ist bereits geschlossen.", ephemeral=True
            )
            return

        member = interaction.user
        support_role_ids = await db.get_ticket_support_roles(
            self.pool, interaction.guild_id
        )
        is_support = any(r.id in support_role_ids for r in member.roles)
        is_admin = member.guild_permissions.administrator
        is_author = member.id == ticket["author_id"]

        if not (is_support or is_admin or is_author):
            await interaction.response.send_message(
                "❌ Du hast keine Berechtigung, dieses Ticket zu schließen.", ephemeral=True
            )
            return

        await db.close_ticket(self.pool, ticket["id"])
        await interaction.response.send_message(
            f"🔒 Ticket wird in 5 Sekunden geschlossen..."
        )
        await asyncio.sleep(5)

        try:
            await interaction.channel.delete(reason=f"Ticket closed by {member}")
        except discord.NotFound:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketActionsCog(bot))
