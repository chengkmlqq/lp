-- LP-83：风电场地闪密度批次增加 4 张预生成图的 object key 字典。
-- image_variants_json 的键为 bilinear-km2 / bilinear-cell / nearest-km2 / nearest-cell；
-- 旧批次的 image_object_key（默认 bilinear-km2 图）保留不变，缺 variant 时由 API 一次性 lazy 生成。
-- 幂等：列已存在时不重复添加。MySQL 版见 mysql/047_add_wind_lightning_density_image_variants.sql

ALTER TABLE wind_lightning_density_batch
    ADD COLUMN IF NOT EXISTS image_variants_json JSONB;
