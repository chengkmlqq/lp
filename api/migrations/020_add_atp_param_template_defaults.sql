-- Migration: ATP 参数模板补「测试默认参数集」列
-- Date: 2026-09-19
--
-- 背景：C# 引擎只吃「一串参数」（_javaParams），不需要杆塔实例；Web 端做模型测试
--       也应如此 —— 用「ATP 模型 + 参数模板（含默认值）」直接测，不引入杆塔概念。
--       故给模板行加 defaults_json：该模板对应的默认上下文变量（如
--       {"h_u": 65.5, "shield_h": 73.5, "insul_m": 5.945}），仅在测试路径
--       （resolve_params(allow_defaults=True)）生效，只补上下文里为 None 的键；
--       生产计算路径不读该列 → 对既有结果零影响。
--
-- 全局默认值也可写在 api/app/services/atp_param_mappings/_common.json 的顶层 defaults
-- （DB 无模板行时回落到 JSON）。

ALTER TABLE atp_param_template
    ADD COLUMN IF NOT EXISTS defaults_json JSONB NOT NULL DEFAULT '{}'::jsonb;
