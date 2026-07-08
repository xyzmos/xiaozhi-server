-- liquibase formatted sql

-- changeset codex:202607081230
ALTER TABLE `ai_agent_snapshot`
    ALTER COLUMN `snapshot_data` SET DEFAULT (JSON_OBJECT());
