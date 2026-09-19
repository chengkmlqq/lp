-- Migration: 补回 ATP 资产运行记录的输出列（stderr_text / timed_out）
-- Date: 2026-09-19
--
-- 背景：0546d70（LP-473「移除 ATP 模型管理 release/版本概念」）把 atp_asset_run
--       的模型列删掉了，但序列化器 serialize_run() 仍读取 item.stderr_text，
--       执行侧 execute_asset_run_job() 也仍写 run.stderr_text / run.timed_out，
--       导致运行记录序列化抛 AttributeError（GET /atp/runs/{id} 及一切返回
--       AtpAssetRunDetail 的接口 500）。此处按序列化器/执行侧的实际字段补齐，
--       不新增语义（stderr 用于引擎报错排查，timed_out 标记超时）。

ALTER TABLE atp_asset_run
    ADD COLUMN IF NOT EXISTS stderr_text TEXT,
    ADD COLUMN IF NOT EXISTS timed_out BOOLEAN NOT NULL DEFAULT FALSE;
