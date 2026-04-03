-- 006_add_meme_schedule.sql
-- Adds meme auto-post schedule configuration per guild.

CREATE TABLE IF NOT EXISTS meme_schedule (
    guild_id    BIGINT PRIMARY KEY,
    channel_id  BIGINT NOT NULL,
    post_hour   SMALLINT NOT NULL CHECK (post_hour BETWEEN 0 AND 23),
    post_minute SMALLINT NOT NULL DEFAULT 0 CHECK (post_minute BETWEEN 0 AND 59),
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
