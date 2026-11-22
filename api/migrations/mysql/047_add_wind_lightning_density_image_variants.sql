-- LP-83：风电场地闪密度批次增加 4 张预生成图的 object key 字典（PG 版见 ../047_add_wind_lightning_density_image_variants.sql）。
-- 键为 bilinear-km2 / bilinear-cell / nearest-km2 / nearest-cell；旧批次 image_object_key 保留不变。

ALTER TABLE wind_lightning_density_batch
    ADD COLUMN image_variants_json JSON NULL;
