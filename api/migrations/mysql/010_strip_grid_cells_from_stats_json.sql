-- Migration: 清理 lightning_distribution.stats_json 中的 grid_cells 冗余键
-- Date: 2026-08-02
-- Description:
--   grid_cells（网格聚合明细，可达 20MB/条）仅用于内部计算，无 API 消费者。
--   任务端和序列化端已在代码层面剥离，本脚本一次性清理历史数据。
--   由 JSON 函数移除 stats_json -> 'grid_cells'，无需改表结构。

UPDATE lightning_distribution
SET stats_json = JSON_REMOVE(stats_json, '$.grid_cells')
WHERE JSON_CONTAINS_PATH(stats_json, 'one', '$.grid_cells');
