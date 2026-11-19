"""风电场数据准备（LP-33）：公共内核、五文件产物、地形与校验、服务端到端。"""

from __future__ import annotations

import io
import math
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest

from app.services import wind_data_prep as prep
from app.services import wind_grid as wg
from app.services import wind_lightning_density as density_algo

FIXTURES = Path(__file__).parent / "fixtures" / "wind_lightning_density"
TURBINE_FILE = FIXTURES / "file_2.txt"
FUJIAN_CSV = FIXTURES / "lightning_fujian_in_range.csv"


def _params(**overrides) -> prep.PrepParams:  # type: ignore[no-untyped-def]
    values = dict(
        start_lon=119.34,
        start_lat=25.23,
        nx=100,
        ny=100,
        risk_base_s=1.0,
        terrain_mode="zero",
        wind_farm_name="福建B1",
    )
    values.update(overrides)
    return prep.PrepParams(**values)


def _lightning_bytes() -> bytes:
    return FUJIAN_CSV.read_bytes()


# ---------------------------------------------------------------------------
# 1) 公共内核：floor 编号 / 对齐 / 三种风机入口 / 雷电解析
# ---------------------------------------------------------------------------
def test_grid_cell_uses_floor_and_one_based_grid_id() -> None:
    # i=1,j=1 → grid_id=1*10+1+1=12
    assert wg.grid_cell(119.35, 25.24, 119.34, 25.23, 10, 10) == (1, 1, 12, True)
    # 西侧越界：floor 得 -1（不是 astype(int) 的 0），且标记越界
    i, j, grid_id, in_scope = wg.grid_cell(119.33, 25.24, 119.34, 25.23, 10, 10)
    assert (i, j, in_scope) == (-1, 1, False)
    assert grid_id == j * 10 + i + 1


def test_alignment_and_axis_limits() -> None:
    assert wg.is_aligned(119.34)
    assert not wg.is_aligned(119.345)
    with pytest.raises(wg.WindGridError, match="0.01"):
        wg.validate_grid(119.345, 25.23, 10, 10, wg.DEFAULT_DDEG)
    with pytest.raises(wg.WindGridError, match="NMAX"):
        wg.validate_grid(119.34, 25.23, 101, 10, wg.DEFAULT_DDEG)


def test_turbine_three_formats() -> None:
    txt = wg.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt")
    assert len(txt.points) == 58
    assert txt.points[0].lon_dms == (119.0, 26.0, 47.61)
    assert txt.points[0].height == 90 and txt.points[0].circuit == 3

    decimal = wg.parse_turbine_file(b"119.4466,25.3929,0,90,75,1,3\n", "x.csv")
    assert len(decimal.points) == 1
    assert decimal.points[0].lon == pytest.approx(119.4466)
    assert decimal.points[0].height == 90

    merged = wg.parse_turbine_file(
        "121°11'18.34\" 25°23'34.78\" 0 90 75 1 3\n".encode("utf-8"), "x.txt"
    )
    assert len(merged.points) == 1
    assert merged.points[0].lon == pytest.approx(121 + 11 / 60 + 18.34 / 3600)


def test_lightning_csv_gbk_and_type_distribution() -> None:
    header = "LONGITUDE,LATITUDE,DATETIME,TYPE\n"
    rows = "119.35,25.24,2021-03-01 10:00:00,CG\n119.36,25.25,2022-04-01 10:00:00,IC\n"
    gbk = (header + rows).encode("gbk")
    result = wg.parse_lightning_csv(gbk)
    assert result.valid_rows == 2
    assert result.detected_years == [2021, 2022]
    assert result.type_distribution == {"CG": 1, "IC": 1}
    assert result.time_span == "2021–2022"


def test_kernel_matches_legacy_density_module() -> None:
    """LP-32 复用同一内核后，逐格计数与 grid_id 完全一致。"""
    lightning = wg.parse_lightning_csv(_lightning_bytes())
    grid = {"start_lon": 119.0, "start_lat": 25.0, "x_count": 100, "y_count": 100, "step_deg": 0.01}
    legacy = density_algo.parse_lightning_csv(_lightning_bytes())
    legacy_counts = np.rint(density_algo.core_density_matrix(legacy.lon, legacy.lat, grid, 6.0) * 6).astype(int)
    counts, in_scope, out = wg.aggregate_flashes(lightning.lon, lightning.lat, 119.0, 25.0, 100, 100)
    assert np.array_equal(legacy_counts, counts)
    assert in_scope + out == lightning.valid_rows

    points = density_algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt")
    for point in points.points:
        legacy_id, _, _ = density_algo.core_grid_id(point.lon, point.lat, grid)
        _, _, new_id, _ = wg.grid_cell(point.lon, point.lat, 119.0, 25.0, 100, 100)
        assert legacy_id == new_id


# ---------------------------------------------------------------------------
# 2) 五文件产物
# ---------------------------------------------------------------------------
def test_prepare_pipeline_and_five_files() -> None:
    result = prep.prepare_data(
        _params(),
        turbine_content=TURBINE_FILE.read_bytes(),
        turbine_filename="file_2.txt",
        lightning_content=_lightning_bytes(),
        lightning_filename="lightning.csv",
    )
    assert result.report["status"] == "pass"
    assert len(result.turbines) == 58
    assert result.stats["lightning_in_scope"] == 4252
    assert result.stats["data_years"] == 6

    file1 = result.files["file_1.txt"].decode("utf-8")
    assert file1.splitlines() == ["58", "1", "119.34", "25.23", "100", "100"]

    file2_lines = result.files["file_2.txt"].decode("utf-8").splitlines()
    assert len(file2_lines) == 58
    assert len(file2_lines[0].split("\t")) == 11

    file3_lines = result.files["file_3.txt"].decode("utf-8").splitlines()
    assert len(file3_lines) == 58
    assert file3_lines[0].endswith("\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1")
    assert int(file3_lines[0].split("\t")[0]) == result.turbines[0]["grid_id"]

    file4_lines = result.files["file_4.txt"].decode("utf-8").splitlines()
    assert len(file4_lines) == 58
    first = result.turbines[0]
    assert float(file4_lines[0]) == pytest.approx(first["flash_count"] / 6)

    p0 = result.files["P0.abc"]
    assert len(p0) == 12 + 100 * 100 * 2
    header = prep.validate_p0abc(p0, nx=100, ny=100)
    assert (header["left"], header["right"], header["bottom"], header["top"]) == (11934, 12034, 2523, 2623)
    assert (header["width"], header["height"], header["row_order"]) == (100, 100, "north_to_south")
    for name in prep.FILE_NAMES:
        assert not result.files[name].startswith(b"\xef\xbb\xbf")
    assert b"\r" not in result.files["file_3.txt"]


def test_east_neighbor_difference_documented() -> None:
    """修正编号后，样例 58 台中 56 台本格与东邻格不同（错位缺陷的预期结果）。"""
    result = prep.prepare_data(
        _params(),
        turbine_content=TURBINE_FILE.read_bytes(),
        turbine_filename="file_2.txt",
        lightning_content=_lightning_bytes(),
        lightning_filename="lightning.csv",
    )
    differing = sum(1 for t in result.turbines if t["flash_count"] != t["flash_count_east"])
    assert differing == 56


def test_validation_blocks_half_baked_records() -> None:
    good = dict(
        turbine_content=TURBINE_FILE.read_bytes(),
        turbine_filename="file_2.txt",
        lightning_content=_lightning_bytes(),
        lightning_filename="lightning.csv",
    )
    with pytest.raises(wg.WindGridError, match="0.01"):
        prep.prepare_data(_params(start_lon=119.345), **good)
    with pytest.raises(wg.WindGridError, match="NMAX"):
        prep.prepare_data(_params(nx=101), **good)
    with pytest.raises(wg.WindGridError, match="风险基准"):
        prep.prepare_data(_params(risk_base_s=-1.0), **good)
    with pytest.raises(wg.WindGridError, match="研究区域外"):
        prep.prepare_data(_params(start_lon=120.0), **good)


# ---------------------------------------------------------------------------
# 3) 地形两条路径
# ---------------------------------------------------------------------------
def test_tif_terrain_p0abc(tmp_path: Path) -> None:
    import rasterio
    from rasterio.transform import from_origin

    nx = ny = 20
    start_lon, start_lat, step = 119.34, 25.23, 0.01
    top = start_lat + ny * step
    path = tmp_path / "terrain.tif"
    data = np.arange(nx * ny, dtype=np.uint16).reshape(ny, nx) % 1000
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype="uint16",
        crs="EPSG:4326",
        transform=from_origin(start_lon, top, step, step),
    ) as dst:
        dst.write(data, 1)

    result = prep.prepare_data(
        _params(nx=nx, ny=ny, terrain_mode="tif"),
        turbine_content=(
            b"119\t26\t47.61\t25\t23\t34.78\t0\t90\t75\t1\t3\n"
            b"119\t27\t11.52\t25\t23\t8.44\t0\t85\t75\t1\t3\n"
        ),
        turbine_filename="file_2.txt",
        lightning_content=_lightning_bytes(),
        lightning_filename="lightning.csv",
        tif_content=path.read_bytes(),
    )
    assert result.report["status"] == "pass"
    p0 = result.files["P0.abc"]
    assert len(p0) == 12 + nx * ny * 2
    header = prep.validate_p0abc(p0, nx=nx, ny=ny)
    assert header["width"] == nx and header["height"] == ny
    pixels = np.frombuffer(p0[12:], dtype=">u2").reshape(ny, nx)
    # GTiff 行序北→南；采样后按北→南写出，输出行序与 GTiff 原始数组一致
    np.testing.assert_array_equal(pixels, data)

    # 负高程阻断
    bad = data.copy()
    bad[0, 0] = 65535
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=ny,
        width=nx,
        count=1,
        dtype="int16",
        crs="EPSG:4326",
        transform=from_origin(start_lon, top, step, step),
    ) as dst:
        dst.write(bad.astype("int16"), 1)
    with pytest.raises(wg.WindGridError):
        prep.build_p0abc(_params(nx=nx, ny=ny, terrain_mode="tif"), tif_content=path.read_bytes())


def test_tif_wrong_resolution_and_crsBlocked(tmp_path: Path) -> None:
    import rasterio
    from rasterio.transform import from_origin

    path = tmp_path / "wrong.tif"
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=10,
        width=10,
        count=1,
        dtype="uint16",
        crs="EPSG:3857",
        transform=from_origin(119.34, 25.5, 0.02, 0.02),
    ) as dst:
        dst.write(np.zeros((10, 10), dtype=np.uint16), 1)
    with pytest.raises(wg.WindGridError, match="EPSG:4326"):
        prep.build_p0abc(_params(nx=10, ny=10, terrain_mode="tif"), tif_content=path.read_bytes())


# ---------------------------------------------------------------------------
# 4) 服务端到端（SQLite + 内存对象存储）
# ---------------------------------------------------------------------------
def test_service_run_batch_package_and_report(monkeypatch) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.models.wind_data_prep import WindDataPrepBatch
    from app.services import wind_data_prep_service as service

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    store: dict[str, bytes] = {}
    monkeypatch.setattr(service.minio_storage, "put_object", lambda key, data, **kwargs: (store.__setitem__(key, data), key)[1])
    monkeypatch.setattr(service.minio_storage, "get_object", lambda key: store[key])
    monkeypatch.setattr(service, "_dispatch_batch_task", lambda batch_id, actor_user_id: "fake-task-id")
    try:
        params = _params()
        response = service.create_batch(
            db,
            turbine_file=_Upload(TURBINE_FILE.read_bytes(), "file_2.txt"),
            lightning_file=_Upload(_lightning_bytes(), "lightning.csv"),
            terrain_file=None,
            params=params,
            name="端到端测试",
            actor_user_id="tester",
        )
        batch = db.query(WindDataPrepBatch).filter_by(id=response.batch_id).one()
        assert batch.status == "processing"
        # 任务尚未执行：不落风机明细节（校验失败则连批次记录都不建）
        assert service.list_turbines(db, batch.id, limit=10).total == 0

        result = service.run_batch(db, batch.id, actor_user_id="tester")
        assert result["status"] == "completed" and result["files_ready"] == 5
        assert batch.turbine_count == 58
        assert len(service.list_turbines(db, batch.id, limit=100).items) == 58

        package, filename = service.get_package(db, batch.id)
        assert filename.endswith(".zip")
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            assert set(archive.namelist()) == set(prep.FILE_NAMES)

        p0_content, media_type, _ = service.get_file(db, batch.id, "p0abc", preview=True)
        assert media_type == "application/json"
        assert b'"width": 100' in p0_content

        report, media_type, _ = service.get_report(db, batch.id, format="json")
        assert media_type == "application/json"
        assert b'"status": "pass"' in report
    finally:
        db.close()


class _Upload:
    """最小 UploadFile 替身（只需 filename 与 file.read）。"""

    def __init__(self, content: bytes, filename: str) -> None:
        self.content = content
        self.filename = filename
        self.file = io.BytesIO(content)


# ---------------------------------------------------------------------------
# 5) 性能：10 万条雷电记录端到端 ≤ 30 秒
# ---------------------------------------------------------------------------
def test_100k_lightning_records_under_30s() -> None:
    rng = np.random.default_rng(42)
    lon = 119.34 + rng.random(100_000) * 0.5
    lat = 25.23 + rng.random(100_000) * 0.5
    started = time.perf_counter()
    counts, in_scope, _ = wg.aggregate_flashes(lon, lat, 119.34, 25.23, 100, 100)
    elapsed = time.perf_counter() - started
    assert int(counts.sum()) == in_scope == 100_000
    assert elapsed < 30.0
