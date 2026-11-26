-- Rollback: LP-133 机组型号 / 叶片型号映射表（MySQL 版）。
-- 仅删除本次新建的两张表；不影响既有业务表。
-- PG 版见 ../048_add_wind_model_mapping_rollback.sql

DROP TABLE IF EXISTS wind_blade_model;
DROP TABLE IF EXISTS wind_turbine_model;
