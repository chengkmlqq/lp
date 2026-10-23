#!/usr/bin/env python3
"""PG → MySQL 迁移 SQL 转换器。
读取 api/migrations/*.sql，输出 MySQL 兼容版到 api/migrations/mysql/。
适用场景：全新库顺序执行（幂等性假设：表/列/索引均不存在）。
"""
import pathlib
import re

SRC = pathlib.Path(__file__).parent / "api" / "migrations"
DST = SRC / "mysql"

# ───────── 通用逐行/逐块正则规则 ─────────
GENERIC_RULES = [
    # 类型映射（顺序敏感：TIMESTAMPTZ 先于 TIME ZONE）
    (re.compile(r"(?i)\bTIMESTAMPTZ\b"), "DATETIME"),
    (re.compile(r"(?i)\bTIMESTAMP WITH TIME ZONE\b"), "DATETIME"),
    (re.compile(r"(?i)\bDOUBLE PRECISION\b"), "DOUBLE"),
    (re.compile(r"(?i)\bJSONB\b"), "JSON"),
    # SERIAL → AUTO_INCREMENT
    (re.compile(r"(?i)\bSERIAL PRIMARY KEY\b"), "INT NOT NULL AUTO_INCREMENT PRIMARY KEY"),
    # IF NOT EXISTS 系列
    (re.compile(r"(?i)\bCREATE INDEX IF NOT EXISTS\b"), "CREATE INDEX"),
    (re.compile(r"(?i)\bADD COLUMN IF NOT EXISTS\b"), "ADD COLUMN"),
    (re.compile(r"(?i)\bDROP TABLE IF EXISTS\s+(\w+)\s+CASCADE\b"), r"DROP TABLE IF EXISTS \1"),
    (re.compile(r"(?i)\bDROP CONSTRAINT\s+(\w+_fkey)\b"), r"DROP FOREIGN KEY \1"),
    # ::cast 默认值 → MySQL 表达式默认值
    (re.compile(r"(?i)DEFAULT\s+'(\{\}|\{\}|\[\])'\s*::\s*jsonb?"), r"DEFAULT ('\1')"),
    (re.compile(r"(?i)DEFAULT\s+'(\{\}|\{\}|\[\])'\s*::\s*json"), r"DEFAULT ('\1')"),
    # 剩余 ::cast 直接剥离（'<lit>'::type → '<lit>'）
    (re.compile(r"(?i)'('[^']')'\s*::\s*[a-z_]+"), r"\1"),
    # TEXT/JSON 字面量默认值 → 表达式默认值（MySQL 8.0.13+）
    (re.compile(r"(?i)(TEXT|JSON)\b([^,()]*?)\bDEFAULT\s+'([^']*)'"), lambda m: f"{m.group(1)}{m.group(2)}DEFAULT ('{m.group(3)}')"),
    # SUBSTRING(x FROM a FOR b) → SUBSTRING(x, a, b)
    (re.compile(r"(?i)SUBSTRING\(([^()]*?)\s+FROM\s+(\d+)\s+FOR\s+(\d+)\)"), r"SUBSTRING(\1, \2, \3)"),
    # AT TIME ZONE 'UTC' → UTC_TIMESTAMP()
    (re.compile(r"(?i)\(NOW\(\)\s+AT\s+TIME\s+ZONE\s+'UTC'\)"), "(UTC_TIMESTAMP())"),
    (re.compile(r"(?i)\(CURRENT_TIMESTAMP\s+AT\s+TIME\s+ZONE\s+'UTC'\)"), "(UTC_TIMESTAMP())"),
]

# ───────── 特殊文件整体替换 ─────────
SPECIAL_FILES = {
    "001_add_elevation_file_record.sql": [
        # 跳过 CREATE OR REPLACE VIEW（MySQL 严格校验列存在性，全新库残缺列会失败）
        (re.compile(r"(?is)CREATE OR REPLACE VIEW[^;]*?FROM elevation_file_record;"),
         "-- [mysql] SKIPPED: CREATE OR REPLACE VIEW elevation_dataset_compat（MySQL 严格校验列，全新库列不全；兼容视图不需要）"),
    ],
    "010_strip_grid_cells_from_stats_json.sql": [
        # JSONB 运算符 → MySQL JSON 函数
        (re.compile(r"(?is)SET\s+stats_json\s*=\s*stats_json\s*-\s*'grid_cells'\s*WHERE\s+stats_json\s*\?\s*'grid_cells';"),
         "SET stats_json = JSON_REMOVE(stats_json, '$.grid_cells')\nWHERE JSON_CONTAINS_PATH(stats_json, 'one', '$.grid_cells');"),
    ],
    "008_drop_power_line_tower_shape.sql": [
        # 全新库无此列：整体跳过
        (re.compile(r"(?is)ALTER TABLE power_line\s+DROP COLUMN IF EXISTS tower_shape;"),
         "-- [mysql] SKIPPED: ALTER TABLE power_line DROP COLUMN IF EXISTS tower_shape（MySQL 不支持 IF EXISTS，全新库无此列）"),
    ],
    "018_remove_atp_release_mechanism.sql": [
        # 全新库无版本字段：整段 ALTER 跳过
        (re.compile(r"(?is)ALTER TABLE atp_asset\s*(?:DROP COLUMN IF EXISTS[^,;]*,?\s*)*;"),
         "-- [mysql] SKIPPED: ALTER TABLE atp_asset 移除版本字段（全新库无此列）"),
        (re.compile(r"(?is)ALTER TABLE atp_asset_run\s*(?:DROP COLUMN IF EXISTS[^,;]*,?\s*)*;"),
         "-- [mysql] SKIPPED: ALTER TABLE atp_asset_run 移除版本字段（全新库无此列）"),
    ],
}

# DO $$ 匿名块文件 → 直接展开（CREATE TABLE IF NOT EXISTS + 去 IF NOT EXISTS 索引）
DO_BLOCK_FILES = {
    "021_add_lightning_density_backfill_task.sql": {
        "table_name": "lightning_density_backfill_task",
        "create_table": """CREATE TABLE IF NOT EXISTS lightning_density_backfill_task (
            id                  VARCHAR(32) PRIMARY KEY,
            line_id             VARCHAR(32) NOT NULL REFERENCES power_line(id) ON DELETE CASCADE,
            distribution_id     VARCHAR(32),
            prepared_at         DATETIME DEFAULT now(),
            prepared_by_user_id VARCHAR(64),
            radius_km           DOUBLE,
            data_years          DOUBLE,
            updated_tower_count INTEGER      DEFAULT 0,
            missing_geo_count   INTEGER      DEFAULT 0,
            avg_density         DOUBLE,
            min_density         DOUBLE,
            max_density         DOUBLE,
            strike_count        INTEGER,
            warnings            JSON         DEFAULT ('[]'),
            create_date         DATETIME DEFAULT now()
        );""",
        "indexes": [
            "CREATE INDEX idx_ldbf_task_line ON lightning_density_backfill_task(line_id);",
            "CREATE INDEX idx_ldbf_task_dist ON lightning_density_backfill_task(distribution_id);",
            "CREATE INDEX idx_ldbf_task_prepared ON lightning_density_backfill_task(prepared_at);",
        ],
    },
    "023_add_elevation_apply_job_tower.sql": {
        "table_name": "elevation_apply_job_tower",
        "create_table": """CREATE TABLE IF NOT EXISTS elevation_apply_job_tower (
            id               VARCHAR(32) PRIMARY KEY,
            job_id           VARCHAR(32) NOT NULL REFERENCES elevation_apply_job(id) ON DELETE CASCADE,
            tower_id         VARCHAR(32) NOT NULL REFERENCES power_line_tower(id) ON DELETE CASCADE,
            tower_no         VARCHAR(64),
            seq_no           INTEGER,
            longitude        DOUBLE,
            latitude         DOUBLE,
            action           VARCHAR(32) NOT NULL DEFAULT 'updated',
            altitude_before_m DOUBLE,
            altitude_after_m  DOUBLE,
            slope_1_before   DOUBLE,
            slope_1_after    DOUBLE,
            slope_2_before   DOUBLE,
            slope_2_after    DOUBLE,
            create_date      DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP())
        );""",
        "indexes": [
            "CREATE INDEX idx_elevation_apply_job_tower_job ON elevation_apply_job_tower(job_id);",
            "CREATE INDEX idx_elevation_apply_job_tower_tower ON elevation_apply_job_tower(tower_id);",
        ],
    },
}


def convert_do_block(src_text: str, name: str) -> str:
    """将 DO $$ ... $$ 匿名块展开为普通 DDL（全新库语义等价）。"""
    spec = DO_BLOCK_FILES[name]
    header = "-- [mysql] 由 PG 匿名块(DO $$)展开：全新库直接建表/索引（幂等由 CREATE TABLE IF NOT EXISTS 保证）\n"
    body = spec["create_table"] + "\n" + "\n".join(spec["indexes"]) + "\n"
    return header + body


def convert_file(name: str) -> str:
    src_path = SRC / name
    text = src_path.read_text(encoding="utf-8")

    if name in DO_BLOCK_FILES:
        text = convert_do_block(text, name)

    # 通用规则
    for pattern, repl in GENERIC_RULES:
        if callable(repl):
            text = pattern.sub(repl, text)
        else:
            text = pattern.sub(repl, text)

    # 文件级特例
    for pattern, repl in SPECIAL_FILES.get(name, []):
        text = pattern.sub(repl, text)

    # ON CONFLICT DO NOTHING → INSERT IGNORE（003_add_ai_chat_params.sql）
    if "ON CONFLICT" in text.upper():
        text = re.sub(r"(?is)^(\s*INSERT\b)((?:(?!ON CONFLICT).)*?)\s+ON CONFLICT[^;]*?(;)",
                      lambda m: "INSERT IGNORE" + m.group(2) + m.group(3) if "INSERT IGNORE" not in m.group(0).upper() else m.group(0),
                      text, flags=re.M | re.S)

    # DROP COLUMN / DROP INDEX IF EXISTS → 注释（MySQL 8 不支持）
    text = re.sub(r"(?im)^(\s*)DROP (COLUMN|INDEX) IF EXISTS\b.*$", lambda m: f"{m.group(1)}-- [mysql] SKIPPED: DROP {m.group(2)} IF EXISTS（MySQL 不支持，全新库无此对象）", text)
    # 多行 DROP COLUMN IF EXISTS 子句（逗号连接）
    text = re.sub(r"(?is)(ADD COLUMN|ALTER COLUMN)[^;]*?DROP COLUMN IF EXISTS[^,;]*", lambda m: m.group(0).replace("DROP COLUMN IF EXISTS", "-- [mysql] SKIPPED DROP COLUMN IF EXISTS"), text)

    # 触发器等 plpgsql 特殊文件
    if "002_add_document_management.sql" == name:
        text = convert_triggers_mysql_002(text)

    # COMMENT ON TABLE → ALTER TABLE ... COMMENT；COMMENT ON COLUMN → 注释跳过
    text = re.sub(
        r"(?is)COMMENT ON TABLE\s+(\w+)\s+IS\s+'([^']*)';",
        lambda m: f"ALTER TABLE {m.group(1)} COMMENT = '{m.group(2)}';",
        text,
    )
    text = re.sub(r"(?is)COMMENT ON COLUMN\s+\w+\.\w+\s+IS\s+'[^']*';",
                  lambda m: "-- [mysql] SKIPPED: COMMENT ON COLUMN（MySQL 需 MODIFY 全列定义，省略）", text)

    return text


def convert_triggers_mysql_002(text: str) -> str:
    """002 的 PG 触发器函数 → MySQL 触发器。"""
    repl_chapters = """-- [mysql] PG plpgsql 触发器 → MySQL 触发器
CREATE TRIGGER trigger_update_document_chapters_updated_at
    BEFORE UPDATE ON document_chapters
    FOR EACH ROW
    SET NEW.updated_at = CURRENT_TIMESTAMP;
"""
    repl_documents = """CREATE TRIGGER trigger_update_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    SET NEW.updated_at = CURRENT_TIMESTAMP;
"""
    text = re.sub(r"(?is)CREATE OR REPLACE FUNCTION update_document_chapters_updated_at.*?EXECUTE FUNCTION update_document_chapters_updated_at\(\);",
                  repl_chapters, text)
    text = re.sub(r"(?is)CREATE OR REPLACE FUNCTION update_documents_updated_at.*?EXECUTE FUNCTION update_documents_updated_at\(\);",
                  repl_documents, text)
    return text


def main() -> None:
    DST.mkdir(exist_ok=True)
    sql_files = sorted(SRC.glob("*.sql"))
    for f in sql_files:
        out = convert_file(f.name)
        (DST / f.name).write_text(out, encoding="utf-8")
        print(f"{f.name} -> mysql/{f.name} ({len(out.splitlines())} lines)")


if __name__ == "__main__":
    main()