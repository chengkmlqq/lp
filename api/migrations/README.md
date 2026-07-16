# 数据库迁移说明

本目录包含数据库迁移脚本，用于重构高程数据管理功能。

## 迁移文件

### 001_add_elevation_file_record.sql

**目的**: 将高程数据管理从数据集中心模式重构为文件中心模式

**主要变更**:

1. **创建新表 `elevation_file_record`**
   - 包含所有文件记录相关字段
   - 每个文件对应一条记录
   - 合并了原 `elevation_dataset` 的核心字段

2. **数据迁移**
   - 从 `elevation_dataset` 迁移数据到 `elevation_file_record`
   - 保留原有的 ID 以保持关联关系

3. **更新关联表**
   - `elevation_apply_job` 添加 `file_record_id` 字段
   - `elevation_data_import_job` 添加 `file_record_id` 字段
   - 将现有的 `dataset_id` 值复制到新字段

4. **向后兼容**
   - 保留旧表和旧字段用于过渡期
   - 创建兼容性视图 `elevation_dataset_compat`

## 执行迁移

```bash
# 使用 psql 执行迁移
psql -U your_user -d your_database -f 001_add_elevation_file_record.sql

# 或使用 Python 脚本执行
python -c "
from app.core.database import engine
with open('migrations/001_add_elevation_file_record.sql') as f:
    sql = f.read()
with engine.begin() as conn:
    conn.execute(sql)
"
```

## 回滚计划

如需回滚，执行以下操作：

1. 停止使用新的 `/records` API
2. 删除 `elevation_file_record` 表
3. 删除 `elevation_apply_job.file_record_id` 和 `elevation_data_import_job.file_record_id` 字段
4. 继续使用原有的 `/datasets` API

## 注意事项

- **迁移前务必备份数据库**
- 迁移过程中保留旧表，确保可以回滚
- 完全迁移完成并测试通过后，再考虑删除旧表
- 新旧 API 可以并存一段时间，逐步切换

## 后续清理

当确认新系统运行稳定后，可执行清理：

```sql
-- 删除旧表
DROP TABLE IF EXISTS elevation_dataset_file_meta;
DROP TABLE IF EXISTS elevation_dataset CASCADE;

-- 删除旧字段
ALTER TABLE elevation_apply_job DROP COLUMN IF EXISTS dataset_id;
ALTER TABLE elevation_data_import_job DROP COLUMN IF EXISTS dataset_id;

-- 删除兼容性视图
DROP VIEW IF EXISTS elevation_dataset_compat;
```
