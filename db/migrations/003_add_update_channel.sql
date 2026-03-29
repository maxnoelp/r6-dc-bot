-- Add update_channel_id and last_changelog_hash to guild_config.
-- update_channel_id: where changelog posts go (falls back to command_channel_id if NULL)
-- last_changelog_hash: MD5 of the last posted changelog section, to avoid re-posting
ALTER TABLE guild_config
    ADD COLUMN IF NOT EXISTS update_channel_id   BIGINT,
    ADD COLUMN IF NOT EXISTS last_changelog_hash VARCHAR(32);
