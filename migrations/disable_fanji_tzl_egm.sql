-- 反击跳闸率计算方法：去掉 EGM 选项（2026-09-12）
-- 说明：仅停用（is_enabled=false），保留数据便于回溯；前端维度下拉只取 enabled=true。
-- 恢复方式：UPDATE dimension_item SET is_enabled = TRUE WHERE dimension_type='fanji_tzl_method' AND code='egm';

UPDATE dimension_item
SET is_enabled = FALSE,
    update_date = NOW() AT TIME ZONE 'UTC',
    update_user = 'system'
WHERE dimension_type = 'fanji_tzl_method'
  AND code = 'egm';
