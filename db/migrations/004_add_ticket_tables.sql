-- 004_add_ticket_tables.sql
-- Adds tables for the support ticket system.

CREATE TABLE IF NOT EXISTS ticket_config (
    guild_id            BIGINT PRIMARY KEY,
    panel_channel_id    BIGINT,
    ticket_category_id  BIGINT,
    panel_message_id    BIGINT,
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ticket_support_roles (
    guild_id    BIGINT NOT NULL,
    role_id     BIGINT NOT NULL,
    PRIMARY KEY (guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS tickets (
    id              SERIAL PRIMARY KEY,
    guild_id        BIGINT NOT NULL,
    channel_id      BIGINT UNIQUE,
    author_id       BIGINT NOT NULL,
    claimer_id      BIGINT,
    title           VARCHAR(100) NOT NULL,
    reason          TEXT NOT NULL,
    status          VARCHAR(16) NOT NULL DEFAULT 'open',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    CONSTRAINT tickets_status_check CHECK (status IN ('open', 'claimed', 'closed'))
);

CREATE INDEX IF NOT EXISTS tickets_guild_status_idx ON tickets (guild_id, status);
