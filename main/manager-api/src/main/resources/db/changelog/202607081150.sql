-- liquibase formatted sql

-- changeset codex:202607081150
ALTER TABLE `ai_agent_snapshot`
    ADD COLUMN `restore_from_snapshot_id` VARCHAR(32) DEFAULT NULL COMMENT '恢复来源快照ID' AFTER `source`,
    ADD COLUMN `restore_from_version_no` INT UNSIGNED DEFAULT NULL COMMENT '恢复来源版本号' AFTER `restore_from_snapshot_id`,
    ADD INDEX `idx_snapshot_user_created_at` (`user_id`, `created_at`);
