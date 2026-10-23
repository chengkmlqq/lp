-- Migration: ATP 测试集管理（atp_test_set / atp_test_set_case / atp_test_set_run）
-- Date: 2026-10-20
--
-- 测试集 = 一组测试用例（atp_test_set_case），每个用例绑定一个 ATP 资产
-- （atp_asset）与一种计算类型（普通计算 normal / 同跳计算 tongtiao），
-- 携带测试参数快照（params_json，与 AtpAssetTestRunRequest 同语义）与
-- 预期结果（expected_json，回归断言可选）。
--
-- 执行测试集：逐用例走现有「单模型测试」管线（atp_asset_test_service.
-- create_test_run），用例级结果落在 atp_asset_run（result_summary_json 带
-- batch_id=<batch_marker> 与 test_set_* 元数据）；atp_test_set_run 只承担
-- 集合级发起记录与聚合入口。
--
-- 表由 SQLAlchemy 模型（app/models/atp_test_set.py）在应用启动时
-- create_all 自动创建；此脚本为生产/手动库保持一致性的正式 DDL。

CREATE TABLE IF NOT EXISTS atp_test_set (
    id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NOT NULL DEFAULT (''),
    status VARCHAR(20) NOT NULL DEFAULT 'enabled',
    tags_json JSON NOT NULL DEFAULT ('[]'),
    create_date DATETIME NOT NULL DEFAULT now(),
    create_user VARCHAR(64),
    update_date DATETIME NOT NULL DEFAULT now(),
    update_user VARCHAR(64)
);

CREATE INDEX idx_atp_test_set_status ON atp_test_set (status);
CREATE INDEX idx_atp_test_set_update_date ON atp_test_set (update_date);
CREATE INDEX idx_atp_test_set_create_user ON atp_test_set (create_user);
CREATE INDEX idx_atp_test_set_update_user ON atp_test_set (update_user);

CREATE TABLE IF NOT EXISTS atp_test_set_case (
    id VARCHAR(32) PRIMARY KEY,
    set_id VARCHAR(32) NOT NULL REFERENCES atp_test_set (id) ON DELETE CASCADE,
    asset_id VARCHAR(32) NOT NULL REFERENCES atp_asset (id) ON DELETE CASCADE,
    job_kind VARCHAR(20) NOT NULL DEFAULT 'normal',
    name VARCHAR(255) NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT (''),
    params_json JSON NOT NULL DEFAULT ('{}'),
    expected_json JSON NOT NULL DEFAULT ('{}'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    create_date DATETIME NOT NULL DEFAULT now(),
    create_user VARCHAR(64),
    update_date DATETIME NOT NULL DEFAULT now(),
    update_user VARCHAR(64)
);

CREATE INDEX idx_atp_test_set_case_set ON atp_test_set_case (set_id, sort_order);
CREATE INDEX idx_atp_test_set_case_asset ON atp_test_set_case (asset_id);
CREATE INDEX idx_atp_test_set_case_enabled ON atp_test_set_case (set_id, enabled);
CREATE INDEX idx_atp_test_set_case_job_kind ON atp_test_set_case (job_kind);
CREATE INDEX idx_atp_test_set_case_create_user ON atp_test_set_case (create_user);
CREATE INDEX idx_atp_test_set_case_update_user ON atp_test_set_case (update_user);

CREATE TABLE IF NOT EXISTS atp_test_set_run (
    id VARCHAR(32) PRIMARY KEY,
    set_id VARCHAR(32) NOT NULL REFERENCES atp_test_set (id) ON DELETE CASCADE,
    status VARCHAR(20) NOT NULL DEFAULT 'running',
    batch_marker VARCHAR(64),
    total_cases INTEGER NOT NULL DEFAULT 0,
    started_at DATETIME,
    finished_at DATETIME,
    duration_ms INTEGER,
    error_message TEXT,
    result_summary_json JSON NOT NULL DEFAULT ('{}'),
    create_user VARCHAR(64),
    create_date DATETIME NOT NULL DEFAULT now(),
    update_date DATETIME NOT NULL DEFAULT now()
);

CREATE INDEX idx_atp_test_set_run_set ON atp_test_set_run (set_id, create_date);
CREATE INDEX idx_atp_test_set_run_status ON atp_test_set_run (status);
CREATE INDEX idx_atp_test_set_run_marker ON atp_test_set_run (batch_marker);
CREATE INDEX idx_atp_test_set_run_create_user ON atp_test_set_run (create_user);
