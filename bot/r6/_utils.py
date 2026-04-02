"""bot/r6/_utils.py — Shared helper functions for R6 cogs."""

from __future__ import annotations

import discord


_TIER_STYLES: dict[str, tuple[discord.Color, str]] = {
    "Unranked":  (discord.Color.from_str("#808080"), "⬜"),
    "Copper":    (discord.Color.from_str("#A05C3B"), "🟫"),
    "Bronze":    (discord.Color.from_str("#CD7F32"), "🪙"),
    "Silver":    (discord.Color.from_str("#C0C0C0"), "🩶"),
    "Gold":      (discord.Color.from_str("#FFD700"), "🥇"),
    "Platinum":  (discord.Color.from_str("#00D4B4"), "🩵"),
    "Emerald":   (discord.Color.from_str("#50C878"), "💚"),
    "Diamond":   (discord.Color.from_str("#0099FF"), "💎"),
    "Champion":  (discord.Color.from_str("#FF6600"), "👑"),
}


def tier_style(rank: str) -> tuple[discord.Color, str]:
    for tier, style in _TIER_STYLES.items():
        if rank.startswith(tier):
            return style
    return _TIER_STYLES["Unranked"]


def rank_icon_url(rank: str) -> str:
    slug = rank.lower().replace(" ", "-")
    return f"https://r6data.eu/assets/img/r6_ranks_img/{slug}.webp"


def kd(kills: int, deaths: int) -> float:
    return round(kills / deaths, 2) if deaths > 0 else float(kills)


def wl(wins: int, losses: int) -> str:
    total = wins + losses
    if total == 0:
        return "—"
    return f"{round(wins / total * 100, 1)}%"


def rank_delta_str(delta: int) -> str:
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta} RP"


def delta_color(delta: int) -> discord.Color:
    if delta > 0:
        return discord.Color.green()
    if delta < 0:
        return discord.Color.red()
    return discord.Color.greyple()
