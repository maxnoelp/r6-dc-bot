-- Add quote_channel_id to guild_config for the !quote command.
ALTER TABLE guild_config
    ADD COLUMN IF NOT EXISTS quote_channel_id BIGINT;
