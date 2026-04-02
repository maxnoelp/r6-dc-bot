"""
bot/support_system/_views.py — Persistent Views for the ticket system.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from ._modals import TicketOpenModal

if TYPE_CHECKING:
    from .cog_ticket_actions import TicketActionsCog


class TicketOpenView(discord.ui.View):
    """Persistent View posted in the panel channel. Opens a ticket on click."""

    def __init__(self, cog: TicketActionsCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Ticket öffnen",
        emoji="🎫",
        style=discord.ButtonStyle.primary,
        custom_id="ticket:open",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(TicketOpenModal(self.cog))


class TicketActionView(discord.ui.View):
    """Persistent View posted inside every ticket channel."""

    def __init__(self, cog: TicketActionsCog) -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Claimen",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="ticket:claim",
    )
    async def claim(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.handle_claim(interaction)

    @discord.ui.button(
        label="Schließen",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="ticket:close",
    )
    async def close(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.handle_close(interaction)
