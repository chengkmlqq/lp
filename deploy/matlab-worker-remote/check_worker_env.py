"""MATLAB Worker 分离部署自检（在 worker 容器内执行）。

    docker compose run --rm matlab-worker python /app/check_worker_env.py

逐项验证远程 worker 与 33.2 的连通性：
  1) 配置回显（脱敏）——确认吃的是隧道地址而不是容器名
  2) PostgreSQL（隧道 -> lp-pg）
  3) Redis（隧道 -> lp-redis，broker 与结果后端）
  4) 对象存储（隧道 -> MinIO）：列 bucket、读写删探针、引擎包可访问性
  5) 引擎目录：可写、已部署哪些可执行文件
  6) 引擎模块配置：模块 slug / worker 部署路径 / 已发布包大小

任一硬性检查失败退出码为 1。
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

OK = "[ OK ]"
WARN = "[WARN]"
FAIL = "[FAIL]"

failures: list[str] = []


def section(title: str) -> None:
    print(f"\n=== {title} ===")


def report(status: str, msg: str) -> None:
    print(f"{status} {msg}")
    if status == FAIL:
        failures.append(msg)


def main() -> int:
    from app.core.config import get_settings

    s = get_settings()

    section("配置")
    print(f"  DB            : {s.db_dialect} {s.db_host}:{s.db_port}/{s.db_name} schema={s.db_schema}")
    broker = s.resolved_celery_broker_url
    print(f"  Celery broker : {_mask_url(broker)}")
    print(f"  Celery result : {_mask_url(s.resolved_celery_result_backend)}")
    print(f"  Object backend: {s.object_storage_backend}")
    print(f"  Object store  : {s.object_store_endpoint or s.minio_endpoint} bucket="
          f"{s.object_store_bucket or s.minio_bucket} style={s.object_store_addressing_style}")
    print(f"  Engine dir    : {s.fault_diag_matlab_compiled_dir or '(empty)'}")

    if s.object_storage_backend != "s3":
        report(FAIL, "OBJECT_STORAGE_BACKEND 不是 s3，worker 会去找本地磁盘对象而不是 MinIO")
    if s.db_host not in ("127.0.0.1", "localhost"):
        report(WARN, f"DB_HOST={s.db_host} 不是回环地址，确认隧道拓扑是否被绕过")
    endpoint = (s.object_store_endpoint or s.minio_endpoint or "")
    if "127.0.0.1" not in endpoint and "localhost" not in endpoint:
        report(WARN, f"对象存储 endpoint={endpoint} 不是隧道地址，远端机器上大概率连不通")
    if s.object_store_addressing_style != "path":
        report(FAIL, "OBJECT_STORE_ADDRESSING_STYLE 必须是 path（MinIO 不支持 virtual 风格）")

    # ---- PostgreSQL -------------------------------------------------------
    section("PostgreSQL")
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(s.resolved_database_url, pool_pre_ping=True, connect_args={"connect_timeout": 8})
        with engine.connect() as conn:
            row = conn.execute(text("select current_database(), current_user, version()")).one()
            print(f"{OK} connected: db={row[0]} user={row[1]}")
            print(f"       {str(row[2]).split(',')[0]}")
            cnt = conn.execute(text(
                "select count(*) from information_schema.tables where table_schema = :sch"
            ), {"sch": s.db_schema or "public"}).scalar()
            print(f"       tables in {s.db_schema or 'public'}: {cnt}")
        engine.dispose()
    except Exception as exc:  # noqa: BLE001
        report(FAIL, f"数据库连接失败: {exc}")

    # ---- Redis ------------------------------------------------------------
    section("Redis")
    try:
        import redis as redis_lib

        for label, url in (("broker", broker), ("result", s.resolved_celery_result_backend)):
            client = redis_lib.from_url(url, socket_connect_timeout=8, socket_timeout=8)
            print(f"{OK} {label} PING -> {client.ping()}")
            client.close()
    except Exception as exc:  # noqa: BLE001
        report(FAIL, f"Redis 连接失败: {exc}")

    # ---- 对象存储 ---------------------------------------------------------
    section("对象存储（MinIO）")
    try:
        from app.services import minio_storage as ms

        conf = ms.store_conf()
        print(f"{OK} 配置: {conf['endpoint']} bucket={conf['bucket']} style={conf['addressing_style']}")

        keys = ms.list_objects("")
        print(f"{OK} bucket 可列举，共 {len(keys)} 个对象")

        probe_key = f"_healthcheck/worker-{uuid.uuid4().hex}.txt"
        payload = f"probe {uuid.uuid4().hex}".encode()
        ms.put_object(probe_key, payload)
        back = ms.get_object(probe_key)
        if back != payload:
            report(FAIL, "对象存储读写探针内容不一致")
        else:
            print(f"{OK} 写/读探针通过: {probe_key}")
        ms.delete_object(probe_key)
        print(f"{OK} 删除探针通过")

        engine_keys = [k for k in keys if k.startswith("matlab-engine/")]
        print(f"       matlab-engine 对象: {len(engine_keys)} 个")
    except Exception as exc:  # noqa: BLE001
        report(FAIL, f"对象存储不可用（引擎同步会直接失败）: {exc}")
        engine_keys = []

    # ---- 引擎目录 ---------------------------------------------------------
    section("引擎目录")
    engine_dir = Path(s.fault_diag_matlab_compiled_dir or "")
    if not str(engine_dir) or str(engine_dir) in ("", "."):
        report(FAIL, "FAULT_DIAG_MATLAB_COMPILED_DIR 为空，引擎同步无处解压")
    else:
        try:
            engine_dir.mkdir(parents=True, exist_ok=True)
            touch = engine_dir / f".probe_{uuid.uuid4().hex}"
            touch.write_text("ok", encoding="utf-8")
            touch.unlink()
            print(f"{OK} 目录可写: {engine_dir}")
            exe_names = ("RunWaveAnalysisModule", "run_RunWaveAnalysisModule.sh",
                         "waveform_engine_v2.exe", "waveform_engine.exe")
            found = [n for n in exe_names if (engine_dir / n).is_file()]
            if found:
                print(f"{OK} 已部署可执行文件: {', '.join(found)}")
            else:
                report(WARN, f"{engine_dir} 还没有可执行文件——需要在引擎管理页上传并同步一次")
        except Exception as exc:  # noqa: BLE001
            report(FAIL, f"引擎目录不可写: {exc}")

    # ---- 引擎模块配置 -----------------------------------------------------
    # 模块清单与版本记录存在 system_param（数据库），不在对象存储里；
    # 这里借用服务的私有读取函数拿到和接口一致的视图，仅用于诊断。
    section("引擎模块配置")
    try:
        from app.core.database import SessionLocal
        from app.services.fault_matlab_engine_service import list_modules, _load_versions

        db = SessionLocal()
        try:
            modules = list_modules(db)
            if not modules:
                report(WARN, "数据库里没有引擎模块——需要先在引擎管理页新建/上传")
            for module in modules:
                slug = module.get("slug") or ""
                deploy_path = module.get("worker_deploy_path") or ""
                print(f"  slug={slug} name={module.get('name', '')}")
                print(f"    worker_deploy_path={deploy_path or '(空，用 FAULT_DIAG_MATLAB_COMPILED_DIR)'}")
                versions = _load_versions(db, slug)
                releases = versions.get("releases") or []
                if not releases:
                    report(WARN, f"{slug} 没有已发布版本，同步任务无包可下")
                for release in releases[-3:]:
                    vh = release.get("version_hash", "")
                    zip_key = f"matlab-engine/release/{slug}/{vh}/engine.zip"
                    try:
                        size = ms.head_object_size(zip_key)
                        flag = "已标记部署" if release.get("deployed_at") else "未部署"
                        active = "当前生效" if release.get("is_active") else ""
                        print(f"    release {vh[:12]} {size / 1048576:.1f}MB {flag} {active}".rstrip())
                    except Exception as exc:  # noqa: BLE001
                        report(FAIL, f"{slug}/{vh[:12]} 缺 engine.zip（同步会失败）: {exc}")
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        report(FAIL, f"读取引擎模块配置失败: {exc}")

    print()
    if failures:
        print(f"结果：{len(failures)} 项失败")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("结果：全部通过")
    return 0


def _mask_url(url: str) -> str:
    if "@" not in url:
        return url
    head, tail = url.rsplit("@", 1)
    if ":" not in head:
        return url
    scheme, rest = head.split("://", 1)
    user = rest.split(":", 1)[0]
    return f"{scheme}://{user}:***@{tail}"


if __name__ == "__main__":
    sys.exit(main())
