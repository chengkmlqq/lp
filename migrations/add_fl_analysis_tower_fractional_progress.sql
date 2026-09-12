-- 防雷计算任务：塔内进度细分字段（方案C · 单塔内部子步骤实时进度）
-- 用于进度条展示「已完成塔数 + 当前塔内部完成比例」，并显示当前子步骤文字。
ALTER TABLE fl_analysis_job
    ADD COLUMN IF NOT EXISTS fractional_progress DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    ADD COLUMN IF NOT EXISTS current_step_text VARCHAR(255);