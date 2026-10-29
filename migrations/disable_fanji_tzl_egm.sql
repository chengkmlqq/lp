-- ============================================================
-- ⚠️ DEPRECATED：已被 api/app/services/dimension_seed.py 取代（代码化 ORM 种子，
--    兼容 PG/MySQL/SQLite，启动自动播种），此 SQL 仅保留作历史参考，勿再手动执行。
-- ============================================================
-- 反击跳闸率计算方法：去掉 EGM 选项（2026-09-12）
-- 说明：仅停用（is_enabled=false），保留数据便于回溯；前端维度下拉只取 enabled=true。
-- 恢复方式：UPDATE dimension_item SET is_enabled = TRUE WHERE dimension_type='fanji_tzl_method' AND code='egm';

UPDATE dimension_item
SET is_enabled = FALSE,
    update_date = NOW() AT TIME ZONE 'UTC',
    update_user = 'system'
WHERE dimension_type = 'fanji_tzl_method'
  AND code = 'egm';
