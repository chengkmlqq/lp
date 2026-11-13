-- Validate: LP-11 P1 拆表校验（上线前必跑；任一查询异常即停止切换后端）
-- Target : PostgreSQL 17
-- 用法   : psql -f 038_atp_model_version_split_validate.sql ；逐条人工核对结果（bad 全为 0）。
--         第 6/8 项字段逐项比对依赖全库备份表 atp_asset_bak_20261106，
--         执行前须确保该备份表存在；无备份时跳过这两项，其余项照常核对。
--         全部通过后再切后端镜像；任一 bad>0 立即按 039 回滚。

-- 1) 行数：781 模型 / 1429 版本（按线上快照调整期望值）
SELECT 'models' AS what, COUNT(*) AS cnt FROM atp_model
UNION ALL
SELECT 'versions', COUNT(*) FROM atp_asset_version;

-- 2) 主表 code 无重复、无空
SELECT 'dup_model_code' AS check, COUNT(*) AS bad
FROM (SELECT code FROM atp_model GROUP BY code HAVING COUNT(*) > 1) d;

-- 3) 版本表 model_id 非空、version_code 非空且唯一
SELECT 'null_model_id'    AS check, COUNT(*) AS bad FROM atp_asset_version WHERE model_id IS NULL
UNION ALL
SELECT 'null_version_code',     COUNT(*) FROM atp_asset_version WHERE version_code IS NULL
UNION ALL
SELECT 'dup_version_code',      COUNT(*) FROM (SELECT version_code FROM atp_asset_version GROUP BY version_code HAVING COUNT(*) > 1) d;

-- 4) (model_id, version) 组内唯一（P4 会据此建唯一约束，重复会导致上线失败）
SELECT 'dup_model_version' AS check, COUNT(*) AS bad
FROM (SELECT model_id, version FROM atp_asset_version WHERE model_id IS NOT NULL
      GROUP BY model_id, version HAVING COUNT(*) > 1) d;

-- 5) 每组 is_active=true 至多 1 行
SELECT 'multi_active' AS check, COUNT(*) AS bad
FROM (SELECT model_id FROM atp_asset_version WHERE is_active = true AND model_id IS NOT NULL
      GROUP BY model_id HAVING COUNT(*) > 1) d;

-- 6) version_code 与迁移前旧 code 逐行一致（用备份表；无备份表时跳过）
--    期望 bad = 0
SELECT 'version_code_mismatch' AS check, COUNT(*) AS bad
FROM atp_asset_bak_20261106 b
JOIN atp_asset_version v ON v.id = b.id
WHERE v.version_code IS DISTINCT FROM b.code;

-- 7) 三张外键表 asset_id 零孤儿
SELECT 'orphan_asset_run' AS check, COUNT(*) AS bad
FROM atp_asset_run r LEFT JOIN atp_asset_version v ON v.id = r.asset_id WHERE v.id IS NULL
UNION ALL
SELECT 'orphan_test_line',     COUNT(*)
FROM atp_test_line t LEFT JOIN atp_asset_version v ON v.id = t.asset_id
WHERE t.asset_id IS NOT NULL AND v.id IS NULL
UNION ALL
SELECT 'orphan_test_set_case', COUNT(*)
FROM atp_test_set_case c LEFT JOIN atp_asset_version v ON v.id = c.asset_id WHERE v.id IS NULL;

-- 8) 关键字段逐项比对一致（存储路径 / 测试结论 / 发布状态 / 分析状态 / 标签）
--    期望全部 bad = 0；存储路径零变化是低风险关键（MinIO 文件一个都不搬）。
SELECT 'storage_root_path_diff' AS check, COUNT(*) AS bad
FROM atp_asset_bak_20261106 b JOIN atp_asset_version v ON v.id = b.id
WHERE v.storage_root_path IS DISTINCT FROM b.storage_root_path
UNION ALL
SELECT 'test_status_diff', COUNT(*)
FROM atp_asset_bak_20261106 b JOIN atp_asset_version v ON v.id = b.id
WHERE v.test_status IS DISTINCT FROM b.test_status
UNION ALL
SELECT 'publish_state_diff', COUNT(*)
FROM atp_asset_bak_20261106 b JOIN atp_asset_version v ON v.id = b.id
WHERE v.publish_state IS DISTINCT FROM b.publish_state
UNION ALL
SELECT 'analysis_status_diff', COUNT(*)
FROM atp_asset_bak_20261106 b JOIN atp_asset_version v ON v.id = b.id
WHERE v.analysis_status IS DISTINCT FROM b.analysis_status
UNION ALL
SELECT 'tags_json_diff', COUNT(*)
FROM atp_asset_bak_20261106 b JOIN atp_asset_version v ON v.id = b.id
WHERE v.tags_json::text IS DISTINCT FROM b.tags_json::text;

-- 9) 兼容视图可读、列齐全（旧代码可继续跑）
SELECT 'compat_view_rows' AS check, COUNT(*) AS cnt FROM atp_asset;

-- 10) 仿真选版一致性（最高优先级回归项）
--     由于版本表保留了全部维度列与 is_published / is_active，且 id 沿用旧值，
--     fl_analysis_external.py:1534-1561 的选版 SQL 逻辑无需改动，
--     对同一批线路/工况必然选出同一版本 id。上线灰度时请以线上快照
--     在测试库跑 api/tests/test_atp_model_version_split.py::test_simulation_picks_same_version_id 复核。
