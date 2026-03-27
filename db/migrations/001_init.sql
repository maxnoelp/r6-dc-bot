-- Initial database schema for the R6 tracking bot.
-- Creates the users, guild_config, and snapshots tables.

CREATE TABLE IF NOT EXISTS users (
    discord_id      BIGINT PRIMARY KEY,
    r6_username     VARCHAR(64) NOT NULL,
    r6_profile_id   VARCHAR(64) NOT NULL,
    platform        VARCHAR(16) NOT NULL DEFAULT 'uplay',
    registered_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS guild_config (
    guild_id            BIGINT PRIMARY KEY,
    post_channel_id     BIGINT NOT NULL,
    command_channel_id  BIGINT NOT NULL,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS snapshots (
    id              SERIAL PRIMARY KEY,
    discord_id      BIGINT REFERENCES users(discord_id) ON DELETE CASCADE,
    snapshot_date   DATE NOT NULL,
    rank            VARCHAR(32),
    rank_points     INT,
    total_kills     INT,
    total_deaths    INT,
    total_wins      INT,
    total_losses    INT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (discord_id, snapshot_date)
);
