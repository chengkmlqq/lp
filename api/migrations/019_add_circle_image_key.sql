-- 019: LightningDistribution 新增沿线圆密度图 object_key（对齐 C# banjin 分组圆）
-- 在回填地闪密度时同步生成「沿线圆」图并存 MinIO，key 存此列。

ALTER TABLE lightning_distribution
    ADD COLUMN IF NOT EXISTS circle_image_object_key VARCHAR(512) NULL;
