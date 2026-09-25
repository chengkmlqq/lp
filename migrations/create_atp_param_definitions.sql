-- ATP 模型计算参数注册表（atp_param_definition）
-- 目标：独立页面定义「参数模板使用的那些参数」：
--   · line_binding : 从线路导入的杆塔属性绑定（建立 杆塔属性路径 ↔ 参数名 关联）
--   · script       : Python 计算脚本（沙箱求值，纯数学函数）
--   · constant     : 字面量
-- 消费方：atp_param_template.slots_json 的 {"param": "<code>"} 引用形态。
-- 幂等：CREATE TABLE IF NOT EXISTS + UNIQUE(code)，可重复执行。
-- 注意：种子数据由 api/app/services/atp_param_definition_seed.py 生成
--       （SOURCE_VARS → line_binding 翻译器，随代码版本演进），本文件只建表。

CREATE TABLE IF NOT EXISTS atp_param_definition (
    id           varchar(36)  PRIMARY KEY,
    code         varchar(64)  NOT NULL,
    name         varchar(128) NOT NULL,
    unit         varchar(32),
    data_type    varchar(16)  NOT NULL DEFAULT 'number',   -- number | string | bool
    source_type  varchar(16)  NOT NULL,                    -- line_binding | script | constant
    binding_json jsonb        NOT NULL DEFAULT '{}'::jsonb, -- line_binding 绑定描述（见 seed 翻译器）
    script_code  text,                                      -- script 的函数体（纯数学表达式/语句）
    deps_json    jsonb        NOT NULL DEFAULT '[]'::jsonb, -- script 依赖的参数 code 列表
    enabled      boolean      NOT NULL DEFAULT true,
    sort_order   integer      NOT NULL DEFAULT 0,
    description  text,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now(),
    updated_by   varchar(64)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_atp_param_definition_code ON atp_param_definition (code);
CREATE INDEX IF NOT EXISTS ix_atp_param_definition_source ON atp_param_definition (source_type, enabled);
CREATE INDEX IF NOT EXISTS ix_atp_param_definition_enabled ON atp_param_definition (enabled);
