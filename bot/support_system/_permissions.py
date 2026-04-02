"""
bot/support_system/_permissions.py — Channel permission overwrite builder.
"""

from __future__ import annotations

import discord


def build_overwrites(
    guild: discord.Guild,
    author: discord.Member,
    support_role_ids: list[int],
    claimer: discord.Member | None = None,
) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    """
    Build the permission overwrite dict for a ticket channel.

    Rules:
    - @everyone: no access
    - author: view + send
    - support roles: view + send (without claimer) / view only (after claim)
    - claimer: view + send
    """
    view_send = discord.PermissionOverwrite(view_channel=True, send_messages=True)
    view_only = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    no_access = discord.PermissionOverwrite(view_channel=False)

    overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: no_access,
        author: view_send,
    }

    for role_id in support_role_ids:
        role = guild.get_role(role_id)
        if role is None:
            continue
        overwrites[role] = view_only if claimer else view_send

    if claimer:
        overwrites[claimer] = view_send

    return overwrites
