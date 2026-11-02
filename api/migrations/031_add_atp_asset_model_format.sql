-- Migration: ATP 模型形态识别与上传预检报告
-- Date: 2026-11-02
-- 背景：ATPDraw 7.2+ 改用 $INSERT + 序号 .pch 引用几何（无参位、无节点名），
--       与 6.x/7.0/7.1 的 $INCLUDE + .lib（DBM）是两条完全不同的链路。
--       上传时必须判定形态并打标记，仿真时按形态分流。
-- 依据：D:\ATP 全量 1101 个模型实测（618 个 legacy / 483 个 insert，其中 204 个 insert 跑不起来）

-- model_format: legacy | insert | embed | plain
--   legacy: $INCLUDE + .lib，每轮 dat→LCC→pch→pch_to_lib 重算几何
--   insert: $INSERT + <name><序号>.pch，几何随包上传、不再重算，参数段需规范化
--   embed : 7.2+ Enbed，几何内嵌进 work.atp，上传口已拒收（存量可能残留）
--   plain : 无 LCC 的纯 RLC 工程
-- 存量默认 legacy：改造前入口只放行 $INCLUDE 形态。
ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS model_format VARCHAR(16) NOT NULL DEFAULT 'legacy';

-- format_check_json: 上传预检报告（error 级已在上传口 400，本字段存放行时的 warning + 统计）
ALTER TABLE atp_asset
    ADD COLUMN IF NOT EXISTS format_check_json JSON DEFAULT '{}'::json;

COMMENT ON COLUMN atp_asset.model_format IS 'ATPDraw 形态：legacy/insert/embed/plain，决定仿真走 lib 还是 pch 链路';
COMMENT ON COLUMN atp_asset.format_check_json IS '上传期预检报告（atp_model_format.PackageInspection.as_dict）';
