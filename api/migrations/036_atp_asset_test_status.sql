-- Migration: atp_asset 增加「测试通过与否」标记（三档）
-- Date: 2026-11-07
-- 背景：ATP 模型管理页需要区分「这个模型是否真的能算、算出来是否可信」。
--   通过  passed  ：实跑成功，且结果落在合理区间（有结果塔、耐雷水平非 0 且未触上界）
--   未通过 failed  ：跑不起来（KILL=12 断链 / 缺变量 / 无结果），或结果为空
--   可疑  suspect ：能算，但数值异常（跳闸率越界被钳制、耐雷水平触顶、几何明显失真）
--   NULL          ：从未测过（存量行保持 NULL，不臆造结论）
--
-- 说明：与 analysis_status（上传期形态识别/槽位扫描）语义不同，二者互不覆盖；
--       test_status 只由实际仿真计算或人工复核写入。

ALTER TABLE atp_asset
    ADD COLUMN test_status VARCHAR(16) NULL COMMENT '测试结论：passed/failed/suspect，NULL=未测试',
    ADD COLUMN test_message VARCHAR(512) NULL COMMENT '测试结论说明（失败原因/可疑点）',
    ADD COLUMN test_date DATETIME NULL COMMENT '最近一次测试时间';

CREATE INDEX idx_atp_asset_test_status ON atp_asset (test_status);
