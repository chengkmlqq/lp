#!/usr/bin/env python3
"""
迁移脚本：将 lightning_current_event 表中已有的地闪分布数据
（feature_json->source = "distribution-import" 或 sample_count < 2 的记录）
迁移到新的 lightning_distribution_point 表。

用法：
  python3 migrate_distribution_data.py

该脚本会在迁移前自动创建目标表（通过 SQLAlchemy model），
然后将符合条件的记录从旧表复制到新表，最后从旧表中删除已迁移的记录。
"""

import sys
import os

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from api.app.core.database import Base
from api.app.models.lightning_distribution import LightningDistributionPoint


def migrate(db_url: str, dry_run: bool = True) -> dict[str, int]:
    """
    执行迁移。
    
    Args:
        db_url: SQLAlchemy 数据库 URL
        dry_run: 如果为 True，只统计不执行写入
    
    Returns:
        迁移统计
    """
    engine = create_engine(db_url)
    
    # 创建新表（如果不存在）
    LightningDistributionPoint.__table__.create(engine, checkfirst=True)
    print(f"[{'DRY-RUN' if dry_run else 'MIGRATE'}] 表 lightning_distribution_point 已就绪")
    
    with Session(engine) as db:
        # 查找所有分布数据（feature_json->source = "distribution-import" 的记录）
        rows = db.execute(
            select(text("*")).select_from(text("lightning_current_event"))
            .where(
                text("feature_json ->> 'source' = 'distribution-import'")
            )
        ).all()
        
        print(f"\n找到 {len(rows)} 条地闪分布记录（feature_json.source = 'distribution-import'）")
        
        if not rows:
            print("没有需要迁移的数据。")
            return {"found": 0, "migrated": 0, "errors": 0}
        
        migrated = 0
        errors = 0
        
        for row in rows:
            try:
                row_dict = dict(row._mapping)
                
                # 只复制 lightning_distribution_point 有的字段
                point = LightningDistributionPoint(
                    id=row_dict.get("id"),
                    event_id=row_dict.get("event_id"),
                    source_file_name=row_dict.get("source_file_name"),
                    event_time=row_dict.get("event_time"),
                    peak_current_ka=row_dict.get("peak_current_ka"),
                    peak_abs_current_ka=row_dict.get("peak_abs_current_ka"),
                    polarity=row_dict.get("polarity") or "unknown",
                    region_id=row_dict.get("region_id"),
                    location_tag=row_dict.get("location_tag"),
                    city=row_dict.get("city"),
                    longitude=row_dict.get("longitude"),
                    latitude=row_dict.get("latitude"),
                    is_synthetic=bool(row_dict.get("is_synthetic", False)),
                    feature_json=row_dict.get("feature_json") or {},
                    notes=row_dict.get("notes"),
                    create_date=row_dict.get("create_date") or datetime.utcnow(),
                    create_user=row_dict.get("create_user"),
                    update_date=row_dict.get("update_date") or datetime.utcnow(),
                    update_user=row_dict.get("update_user"),
                )
                
                if not dry_run:
                    db.add(point)
                
                migrated += 1
                
            except Exception as exc:
                print(f"  错误: 记录 {row_dict.get('event_id', '?')}: {exc}")
                errors += 1
        
        if not dry_run and migrated > 0:
            db.flush()
            
            # 从旧表删除已迁移的记录
            deleted = db.execute(
                text("DELETE FROM lightning_current_event WHERE feature_json ->> 'source' = 'distribution-import'")
            )
            db.commit()
            print(f"\n从 lightning_current_event 删除了 {deleted.rowcount} 条记录")
        
        return {"found": len(rows), "migrated": migrated, "errors": errors}


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="迁移地闪分布数据到独立表")
    parser.add_argument("--db-url", help="数据库 URL（默认从环境变量 DATABASE_URL 读取）")
    parser.add_argument("--execute", action="store_true", help="实际执行迁移（默认仅 dry-run）")
    
    args = parser.parse_args()
    
    db_url = args.db_url or os.environ.get("DATABASE_URL")
    if not db_url:
        print("错误: 请通过 --db-url 参数或 DATABASE_URL 环境变量提供数据库连接")
        sys.exit(1)
    
    print(f"数据库 URL: {db_url}")
    print(f"模式: {'DRY-RUN（仅预览）' if not args.execute else 'ACTUAL（实际执行）'}")
    
    result = migrate(db_url, dry_run=not args.execute)
    
    print(f"\n结果:")
    print(f"  找到: {result['found']} 条")
    print(f"  迁移: {result['migrated']} 条")
    print(f"  错误: {result['errors']} 条")
    
    if result["found"] > 0 and not args.execute:
        print("\n⚠️  这是 dry-run 模式。确认无误后请使用 --execute 实际执行迁移。")