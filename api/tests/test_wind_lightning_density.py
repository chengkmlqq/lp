"""风电场地闪密度统计：算法 golden case、解析入口与核心程序文件导出。

golden case 说明
----------------
``lightning_fujian_in_range.csv`` 取自核心程序随包的 ``福建B1.csv``（只保留统计范围
内的 4252 条记录，矩阵只依赖这些行，结果与整份文件完全一致），配合
``file_2.txt``（11 列风机格式）复现 ``地闪密度/density.py`` 的逐格结果。

⚠️ 任务描述里提到的 ``江苏A3.csv`` 与 ``file_2.txt`` 地理上不重叠（江苏数据 + 福建风机），
范围内 0 条落雷、矩阵全 0，无法用于「逐格一致」的有效校验；这里用真正产出
``file_3.txt``/``file_4.txt`` 的福建数据集做 golden，江苏 CSV 用于解析/年限推断测试。
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import numpy as np
import pytest

from app.services import wind_lightning_density as algo
from app.services.wind_lightning_density_service import analyze_inputs

FIXTURES = Path(__file__).parent / "fixtures" / "wind_lightning_density"
TURBINE_FILE = FIXTURES / "file_2.txt"
FUJIAN_CSV = FIXTURES / "lightning_fujian_in_range.csv"
JIANGSU_CSV = FIXTURES / "lightning_jiangsu_sample.csv"
GOLDEN = json.loads((FIXTURES / "golden_density.json").read_text(encoding="utf-8"))


def _analyze(lightning_path: Path, **kwargs):
    return analyze_inputs(
        turbine_content=TURBINE_FILE.read_bytes(),
        turbine_filename="file_2.txt",
        lightning_content=lightning_path.read_bytes(),
        lightning_filename=lightning_path.name,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1) golden case：与 density.py 逐格一致（1e-9）
# ---------------------------------------------------------------------------
def test_golden_density_matrix_matches_density_py() -> None:
    analysis = _analyze(FUJIAN_CSV)

    lon_bins, lat_bins = algo.build_bins(analysis.bbox, 0.01)
    np.testing.assert_allclose(lon_bins, GOLDEN["lon_bins"], rtol=0, atol=1e-12)
    np.testing.assert_allclose(lat_bins, GOLDEN["lat_bins"], rtol=0, atol=1e-12)

    expected = np.asarray(GOLDEN["density"], dtype=float)
    assert analysis.per_km2.shape == expected.shape
    np.testing.assert_allclose(analysis.per_km2, expected, rtol=0, atol=1e-9)
    assert int(analysis.counts.sum()) == GOLDEN["strike_count_total"]


def test_years_inferred_from_time_column() -> None:
    analysis = _analyze(FUJIAN_CSV)
    # 时间列覆盖 2020–2025 → 自动推断 6 年，与 density.py 的 /6 完全一致
    assert analysis.years == 6.0
    assert analysis.years_source == "auto"
    assert analysis.years_inferred is True
    assert analysis.detected_years[0] == 2020
    assert analysis.detected_years[-1] == 2025


def test_fixed_years_always_six() -> None:
    analysis = _analyze(FUJIAN_CSV, years_source="fixed")
    assert analysis.years == 6.0
    assert analysis.years_source == "fixed"
    assert analysis.years_inferred is False


def test_jiangsu_csv_parses_utf8_and_years() -> None:
    result = algo.parse_lightning_csv(JIANGSU_CSV.read_bytes())
    assert result.total_rows == 240
    assert result.valid_rows == 240
    assert result.inferred_years == 6
    assert result.detected_years == [2020, 2021, 2022, 2023, 2024, 2025]


# ---------------------------------------------------------------------------
# 2) 两种风机入口：11 列 txt / Excel 列名映射 / DMS 合并格式
# ---------------------------------------------------------------------------
def test_turbine_txt_11_columns() -> None:
    result = algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt")
    assert len(result.points) == 58
    first = result.points[0]
    assert first.lon == pytest.approx(algo.dms_to_decimal(119, 26, 47.61))
    assert first.lat == pytest.approx(algo.dms_to_decimal(25, 23, 34.78))


def test_turbine_excel_with_dms_columns() -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["风机编号", "经度度", "经度分", "经度秒", "纬度度", "纬度分", "纬度秒"])
    rows = [line.split() for line in TURBINE_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    for index, row in enumerate(rows, start=1):
        sheet.append([f"WT{index:03d}"] + [float(value) for value in row[:6]])
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = algo.parse_turbine_file(buffer.getvalue(), "turbines.xlsx")
    txt_result = algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt")
    assert len(result.points) == len(txt_result.points) == 58
    assert result.points[0].turbine_no == "WT001"
    for expected, actual in zip(txt_result.points, result.points):
        assert actual.lon == pytest.approx(expected.lon, abs=1e-12)
        assert actual.lat == pytest.approx(expected.lat, abs=1e-12)


def test_turbine_excel_with_decimal_and_compact_dms() -> None:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["编号", "经度", "纬度"])
    sheet.append(["A1", 119.44656, 25.39299])
    sheet.append(["A2", "119°27'11.52\"", "25°23'8.44\""])
    buffer = io.BytesIO()
    workbook.save(buffer)

    result = algo.parse_turbine_file(buffer.getvalue(), "turbines.xlsx")
    assert [point.turbine_no for point in result.points] == ["A1", "A2"]
    assert result.points[1].lon == pytest.approx(algo.dms_to_decimal(119, 27, 11.52))
    assert result.points[1].lat == pytest.approx(algo.dms_to_decimal(25, 23, 8.44))


def test_dms_compact_parsing() -> None:
    assert algo.parse_dms_compact("121°11'18.34\"") == (121.0, 11.0, 18.34)
    assert algo.parse_dms_compact("121 11 18.339516") == (121.0, 11.0, 18.339516)
    assert algo.parse_dms_compact("121′11′18.34″") == (121.0, 11.0, 18.34)
    assert algo.parse_dms_compact("abc") is None


# ---------------------------------------------------------------------------
# 3) 异常输入：明确报错、不产生半成品
# ---------------------------------------------------------------------------
def test_missing_coordinate_columns_rejected() -> None:
    content = "A,B\n1,2\n3,4\n".encode("utf-8")
    with pytest.raises(algo.WindLightningDensityError) as excinfo:
        algo.parse_lightning_csv(content)
    assert "LONGITUDE" in str(excinfo.value)


def test_empty_lightning_rejected() -> None:
    content = "LONGITUDE,LATITUDE\n,\n".encode("utf-8")
    with pytest.raises(algo.WindLightningDensityError):
        algo.parse_lightning_csv(content)


def test_grid_limit_rejected() -> None:
    analysis_points = algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt")
    bbox = algo.compute_bbox(analysis_points.points, 0.01)
    with pytest.raises(algo.WindLightningDensityError) as excinfo:
        algo.validate_grid(bbox, 0.0001)  # 0.14° / 0.0001° = 1400 列，超 500 上限
    assert "500" in str(excinfo.value)


def test_out_of_range_lightning_warns_instead_of_failing() -> None:
    """江苏 CSV + 福建风机：范围内 0 条 → 明确告警，但批次仍可完成（矩阵全 0）。"""
    analysis = _analyze(JIANGSU_CSV)
    assert analysis.in_range_records == 0
    assert int(analysis.counts.sum()) == 0
    assert any("没有落雷记录" in warning for warning in analysis.warnings)


def test_invalid_year_source_rejected() -> None:
    with pytest.raises(algo.WindLightningDensityError):
        _analyze(FUJIAN_CSV, years_source="manual")


# ---------------------------------------------------------------------------
# 4) file_3 / file_4：编号规则与 fengji_bianhao.py 一致
# ---------------------------------------------------------------------------
def test_file_3_grid_ids_match_reference() -> None:
    analysis = _analyze(FUJIAN_CSV)
    turbines = [{"lon": point.lon, "lat": point.lat} for point in
                algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt").points]
    file3, file4 = algo.build_core_files(turbines, analysis.core_grid, analysis.core_density)

    expected_ids = [
        line.split()[0]
        for line in (FIXTURES / "file_3_expected.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual_ids = [line.split("\t")[0] for line in file3]
    assert actual_ids == expected_ids
    assert len(file4) == len(file3) == len(turbines) == 58
    for line in file3:
        assert line.endswith("\t0\t0.2\t0.2\t0.2\t0.2\t0.1\t0.1\n")
    for line in file4:
        assert line.endswith("\n")


def test_core_grid_matches_file_1_parameters() -> None:
    """样例 file_1.txt 为 119 / 25 / 100 / 100，研究区域网格必须一致。"""
    analysis = _analyze(FUJIAN_CSV)
    assert analysis.core_grid["start_lon"] == 119.0
    assert analysis.core_grid["start_lat"] == 25.0
    assert analysis.core_grid["x_count"] == 100
    assert analysis.core_grid["y_count"] == 100


def test_file_4_uses_grid_cell_density() -> None:
    """file_4 的数值必须是 file_3 中该 grid_id 对应网格的密度（次/(km²·年)）。"""
    analysis = _analyze(FUJIAN_CSV)
    turbines = [{"lon": point.lon, "lat": point.lat} for point in
                algo.parse_turbine_file(TURBINE_FILE.read_bytes(), "file_2.txt").points]
    file3, file4 = algo.build_core_files(turbines, analysis.core_grid, analysis.core_density)
    grid = analysis.core_grid
    for turbine, line3, line4 in zip(turbines, file3, file4):
        grid_id = int(line3.split("\t")[0])
        i = int(round(turbine["lon"], 6) * 100) - int(grid["start_lon"] * 100)
        j = int(round(turbine["lat"], 6) * 100) - int(grid["start_lat"] * 100)
        assert grid_id == j * int(grid["x_count"]) + i + 1
        assert float(line4) == pytest.approx(float(analysis.core_density[j, i]), abs=1e-12)


# ---------------------------------------------------------------------------
# 5) 矩阵重建与出图
# ---------------------------------------------------------------------------
def test_matrix_rebuild_roundtrip() -> None:
    analysis = _analyze(FUJIAN_CSV)
    rebuilt = algo.matrix_from_cells(
        [{"cell_i": cell["cell_i"], "cell_j": cell["cell_j"], "strike_count": cell["strike_count"]}
         for cell in analysis.cells],
        analysis.x_count,
        analysis.y_count,
    )
    assert rebuilt.shape == analysis.counts.shape
    np.testing.assert_array_equal(rebuilt, analysis.counts)


def test_render_density_png() -> None:
    analysis = _analyze(FUJIAN_CSV)
    png = algo.render_batch_png(
        counts=analysis.counts,
        lon_bins=analysis.lon_bins,
        lat_bins=analysis.lat_bins,
        data_years=analysis.years,
        step_deg=0.01,
        title="Wind Farm",
        unit="km2",
        interpolation="bilinear",
    )
    assert png.startswith(b"\x89PNG")
    assert len(png) > 5000


# ---------------------------------------------------------------------------
# 6) 导出：Excel（中文不乱码）+ file_3/file_4 zip
# ---------------------------------------------------------------------------
def _seed_batch(db, analysis):  # type: ignore[no-untyped-def]
    from app.models.wind_lightning_density import (
        WindLightningDensityBatch,
        WindLightningDensityCell,
        WindLightningDensityTurbine,
    )

    batch = WindLightningDensityBatch(
        id="batch-test",
        batch_name="福建B1测试场",
        wind_farm_name="福建B1",
        grid_step_deg=0.01,
        margin_deg=0.01,
        data_years=analysis.years,
        years_source=analysis.years_source,
        turbine_source_file_name="file_2.txt",
        turbine_object_key="wind-lightning-density/batch-test/turbines.txt",
        lightning_source_file_name="lightning.csv",
        lightning_object_key="wind-lightning-density/batch-test/lightning.csv",
        turbine_count=analysis.turbine_count,
        total_records=analysis.total_records,
        valid_records=analysis.valid_records,
        skipped_records=analysis.skipped_records,
        bbox_min_lon=analysis.bbox.min_lon,
        bbox_max_lon=analysis.bbox.max_lon,
        bbox_min_lat=analysis.bbox.min_lat,
        bbox_max_lat=analysis.bbox.max_lat,
        grid_x_count=analysis.x_count,
        grid_y_count=analysis.y_count,
        area_km2=analysis.stats["area_km2"],
        overall_density=analysis.stats["overall_density"],
        peak_density=analysis.stats["peak_density"],
        status="completed",
        stage="done",
        progress=100,
        stats_json={"core_grid": analysis.core_grid},
    )
    db.add(batch)
    db.add_all(
        [
            WindLightningDensityCell(batch_id=batch.id, **cell)
            for cell in analysis.cells
        ]
    )
    db.add_all(
        [
            WindLightningDensityTurbine(batch_id=batch.id, **turbine)
            for turbine in analysis.turbines
        ]
    )
    db.commit()
    return batch


def test_export_core_files_and_excel(monkeypatch) -> None:
    import zipfile

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.database import Base
    from app.services import wind_lightning_density_service as service

    analysis = _analyze(FUJIAN_CSV)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        batch = _seed_batch(db, analysis)
        monkeypatch.setattr(
            service.minio_storage, "get_object", lambda key: FUJIAN_CSV.read_bytes()
        )

        zip_bytes, zip_name = service.export_core_files(db, batch.id)
        assert zip_name.endswith(".zip")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
            assert archive.namelist() == ["file_3.txt", "file_4.txt"]
            file3 = archive.read("file_3.txt").decode("utf-8")
            file4 = archive.read("file_4.txt").decode("utf-8")
        assert not file3.startswith("\ufeff") and not file4.startswith("\ufeff")
        assert len(file3.splitlines()) == len(file4.splitlines()) == 58
        assert "\r" not in file3 and "\r" not in file4
        assert file3.splitlines()[0].startswith("3945\t")

        excel_bytes, excel_name = service.export_excel(db, batch.id, export_type="all")
        assert excel_name.endswith(".xlsx")
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(excel_bytes))
        assert workbook.sheetnames == ["概览", "网格", "风机"]
        assert workbook["风机"].max_row == 59  # 表头 + 58 台风机
        assert workbook["风机"].cell(row=2, column=2).value  # 风机编号不为空
        assert workbook["网格"].max_row == len(analysis.cells) + 1
    finally:
        db.close()
