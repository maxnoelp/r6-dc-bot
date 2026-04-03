-- 005_add_meme_channel.sql
-- Adds meme_channel_id to guild_config.

ALTER TABLE guild_config
    ADD COLUMN IF NOT EXISTS meme_channel_id BIGINT;
