-- 022: 地闪密度回填任务异步化（对齐 LP-432 雷电流回填异步状态机）
-- Description:
--   在 lightning_density_backfill_task 增加异步任务状态机字段：
--   status / progress / task_id / error_message，以及每次回填各自一张
--   的「沿线圆」密度图对象键 circle_image_object_key（修复多线路回填
--   互相覆盖同一张图的问题）。
--   新部署由 ORM create_all 自动建列；本脚本显式兼容老库。
--   历史存量行均为同步回填已完成，status 默认置为 completed。

ALTER TABLE lightning_density_backfill_task
    ADD COLUMN status VARCHAR(32) NOT NULL DEFAULT 'completed';
ALTER TABLE lightning_density_backfill_task
    ADD COLUMN progress INTEGER NOT NULL DEFAULT 0;
ALTER TABLE lightning_density_backfill_task
    ADD COLUMN task_id VARCHAR(255);
ALTER TABLE lightning_density_backfill_task
    ADD COLUMN error_message TEXT;
ALTER TABLE lightning_density_backfill_task
    ADD COLUMN circle_image_object_key VARCHAR(512);

CREATE INDEX idx_lightning_density_backfill_task_status
    ON lightning_density_backfill_task(status);
