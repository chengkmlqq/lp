-- ============================================================
-- ⚠️ DEPRECATED：已被 api/app/services/dimension_seed.py 取代（代码化 ORM 种子，
--    兼容 PG/MySQL/SQLite，启动自动播种），此 SQL 仅保留作历史参考，勿再手动执行。
-- ============================================================
-- 禁用 FL分析「风险评估」任务类型选项
-- 背景：新建防雷计算任务表单不再提供「风险评估」入口（web/src/components/fl-analysis/create-job-form.tsx
--       已同时过滤枚举来源 + 静态兜底；seed_fl_analysis_dimensions.sql 已将 risk 置为 is_enabled = FALSE）。
-- 本迁移用于已初始化数据库：把 fl_analysis_job_type 维度下已存在的 risk 项置为禁用。
-- 幂等：可重复执行（AND is_enabled = TRUE 保证重复执行为空更新），不删除记录，历史 risk 任务的展示与详情操作不受影响。

UPDATE dimension_item
SET is_enabled = FALSE,
    update_date = NOW() AT TIME ZONE 'UTC',
    update_user = 'system'
WHERE dimension_type = 'fl_analysis_job_type'
  AND code = 'risk'
  AND is_enabled = TRUE;