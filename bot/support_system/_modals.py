"""
bot/support_system/_modals.py — Modal for opening a new support ticket.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .cog_ticket_actions import TicketActionsCog


class TicketOpenModal(discord.ui.Modal, title="Ticket erstellen"):
    ticket_title = discord.ui.TextInput(
        label="Titel",
        placeholder="Kurze Zusammenfassung deines Problems",
        max_length=100,
    )
    reason = discord.ui.TextInput(
        label="Beschreibung",
        placeholder="Beschreibe dein Problem so genau wie möglich",
        style=discord.TextStyle.paragraph,
        max_length=1000,
    )

    def __init__(self, cog: TicketActionsCog) -> None:
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.cog.create_ticket_channel(
            interaction,
            self.ticket_title.value,
            self.reason.value,
        )
