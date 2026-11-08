"""清掉存量资产 format_check_json 里指定 code 的预检提示，并重算计数。

用途：预检规则下线（例如 2026-11-08 去掉 W010/W001/W002/W003/W012）后，库里
仍存着历史结论；详情页「模型检查」面板读的是这个字段，不清就会继续显示。

用法（容器内执行）：
  docker exec -w /app -e PYTHONPATH=/app -e CODES=W001,W002,W003 lp-api \
      python /app/scripts/purge_format_check_codes.py            # dry-run
  ... python /app/scripts/purge_format_check_codes.py --apply    # 真写库

注意：JSON 列读出来是同一个 dict 实例，原地改再赋回去 SQLAlchemy 判定"没变"、
不会发 UPDATE（第一次跑会出现"已更新 N 个"但数据没动）。所以这里 copy.deepcopy
造新 dict 赋值，再 flag_modified 兜底。
"""

from __future__ import annotations

import copy
import os
import sys
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.core.database import SessionLocal
from app.models.atp_asset import AtpAsset

CODES = {c.strip().upper() for c in os.environ.get("CODES", "").split(",") if c.strip()}
APPLY = "--apply" in sys.argv


def main() -> None:
    if not CODES:
        print("CODES 为空，示例：CODES=W001,W002 python purge_format_check_codes.py")
        raise SystemExit(2)

    with SessionLocal() as db:
        rows = db.execute(select(AtpAsset)).scalars().all()
        todo: list[tuple[AtpAsset, dict, list]] = []
        hit: Counter = Counter()
        for asset in rows:
            data = asset.format_check_json
            if not isinstance(data, dict):
                continue
            issues = data.get("issues") or []
            kept = [i for i in issues if (i or {}).get("code") not in CODES]
            if len(kept) == len(issues):
                continue
            for item in issues:
                code = (item or {}).get("code")
                if code in CODES:
                    hit[code] += 1
            todo.append((asset, data, kept))

        print("待处理资产：%d / %d   命中：%s" % (len(todo), len(rows), dict(hit)))
        for asset, data, kept in todo[:5]:
            print("   %-34s issues %d -> %d" % (asset.code, len(data.get("issues") or []), len(kept)))

        if not APPLY:
            print("(dry-run，未写库；加 --apply 执行)")
            return

        for asset, data, kept in todo:
            new = copy.deepcopy(data)
            new["issues"] = kept
            new["warning_count"] = sum(1 for i in kept if (i or {}).get("level") == "warning")
            new["error_count"] = sum(1 for i in kept if (i or {}).get("level") == "error")
            asset.format_check_json = new
            flag_modified(asset, "format_check_json")
        db.commit()
        print("已更新 %d 个资产" % len(todo))


if __name__ == "__main__":
    main()
