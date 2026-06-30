-- Add language configuration for local FunASR ASR.
UPDATE `ai_model_provider`
SET `fields` = '[{"key":"model_dir","label":"模型目录","type":"string"},{"key":"output_dir","label":"输出目录","type":"string"},{"key":"language","label":"识别语言","type":"string","default":"auto"}]'
WHERE `id` = 'SYSTEM_ASR_FunASR';

UPDATE `ai_model_config`
SET `config_json` = JSON_SET(`config_json`, '$.language', 'auto')
WHERE `id` = 'ASR_FunASR'
AND JSON_EXTRACT(`config_json`, '$.language') IS NULL;
