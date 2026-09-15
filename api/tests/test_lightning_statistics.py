from __future__ import annotations

from app.services import lightning_statistics


def test_parse_distribution_line_valid() -> None:
    assert lightning_statistics.parse_distribution_line("30.5 120.2 12.3") == (30.5, 120.2, 12.3)
    assert lightning_statistics.parse_distribution_line("30.5,120.2,12.3") == (30.5, 120.2, 12.3)
    assert lightning_statistics.parse_distribution_line("30.5\t120.2\t-8.0") == (30.5, 120.2, -8.0)


def test_parse_distribution_line_invalid() -> None:
    assert lightning_statistics.parse_distribution_line("") is None
    assert lightning_statistics.parse_distribution_line("abc def") is None
    assert lightning_statistics.parse_distribution_line("30.5 120.2 abc") is None


def test_parse_distribution_content_skips_bad_rows() -> None:
    text = "\n".join(
        [
            "30.0 120.0 10",
            "31.0 121.0 -5",
            "invalid line here",
            "32.0 122.0 abc",
            "99.0 120.0 3",  # latitude out of range
        ]
    )
    warnings: list[str] = []
    strikes = lightning_statistics.parse_distribution_content(text, warnings=warnings)

    assert len(strikes) == 2
    assert strikes[0]["polarity"] == "positive"
    assert strikes[1]["polarity"] == "negative"
    assert len(warnings) == 3


def test_compute_statistics_counts_polarity_and_ng() -> None:
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
        {"lat": 30.02, "lon": 120.02, "current_ka": 0.0, "polarity": "unknown"},
    ]
    stats = lightning_statistics.compute_statistics(
        strikes, grid_size_km=1.0, data_years=1.0, include_grid_cells=True
    )

    assert stats["total_records"] == 3
    assert stats["positive_count"] == 1
    assert stats["negative_count"] == 1
    assert stats["unknown_count"] == 1
    assert stats["max_abs_current"] == 10.0
    assert stats["avg_abs_current"] == 5.0
    assert stats["area_km2"] > 0
    assert stats["overall_ng"] > 0
    assert len(stats["grid_cells"]) >= 1


def test_compute_statistics_persistent_stats_do_not_include_grid_cells() -> None:
    """stats_json 持久化字段不得包含 grid_cells（避免列表接口响应体过大）。"""
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
    ]
    stats = lightning_statistics.compute_statistics(strikes, grid_size_km=1.0, data_years=1.0)
    # 计算内部仍会产出 grid_cells（与内部重聚合解耦），但持久化 dict 必须剔除。
    stats_json = {k: v for k, v in stats.items() if k != "grid_cells"}
    assert "grid_cells" not in stats_json
    assert set(stats_json) == {
        "total_records",
        "area_km2",
        "data_years",
        "overall_ng",
        "max_abs_current",
        "avg_abs_current",
        "positive_count",
        "negative_count",
        "unknown_count",
        "bbox",
    }


def test_compute_statistics_bbox_reflects_strike_extents() -> None:
    """stats_json 新增的 bbox 反映落雷经纬度范围（含端点）。"""
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.05, "lon": 120.07, "current_ka": -5.0, "polarity": "negative"},
        {"lat": 29.98, "lon": 120.02, "current_ka": 0.0, "polarity": "unknown"},
    ]
    stats = lightning_statistics.compute_statistics(strikes, grid_size_km=1.0, data_years=1.0)

    assert stats["bbox"] == {
        "min_lat": 29.98,
        "max_lat": 30.05,
        "min_lon": 120.0,
        "max_lon": 120.07,
    }


def test_compute_statistics_bbox_none_when_empty() -> None:
    """空落雷集合 bbox 为 None，避免前端误用无效范围。"""
    stats = lightning_statistics.compute_statistics([], grid_size_km=1.0, data_years=1.0)
    assert stats["bbox"] is None


def test_compute_statistics_empty() -> None:
    stats = lightning_statistics.compute_statistics([], grid_size_km=1.0, data_years=1.0)
    assert stats["total_records"] == 0
    assert stats["overall_ng"] == 0.0
    assert stats["grid_cells"] == []


def test_decode_text_bytes_utf8_and_gbk() -> None:
    utf8 = "纬度 经度 电流\n30 120 1".encode("utf-8")
    assert lightning_statistics.decode_text_bytes(utf8) == "纬度 经度 电流\n30 120 1"

    gbk = "30 120 1".encode("gbk")
    assert lightning_statistics.decode_text_bytes(gbk) == "30 120 1"


def test_render_density_image_graceful_without_matplotlib() -> None:
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
    ]
    # 环境未安装 matplotlib 时返回 b""，不抛异常（生产环境装有 matplotlib 会出图）
    png = lightning_statistics.render_density_image(strikes, grid_size_km=1.0)
    assert isinstance(png, bytes)


def test_build_density_matrix_hoists_min_out_of_loop() -> None:
    """O(n²) 修复：min 移出循环后，矩阵坐标映射结果与原实现在数值上完全一致。"""
    import numpy as np

    # 非原点网格，验证偏移基值（base_x/base_y）计算正确。
    cell_counts = {
        (3, 1): 2,
        (5, 4): 7,
        (3, 4): 1,
    }
    matrix = lightning_statistics.build_density_matrix(cell_counts)
    assert matrix is not None
    assert matrix.shape == (4, 3)  # width = 5-3+1, height = 4-1+1
    expected = np.zeros((4, 3), dtype=float)
    expected[1 - 1, 3 - 3] = 2
    expected[4 - 1, 5 - 3] = 7
    expected[4 - 1, 3 - 3] = 1
    assert matrix.tolist() == expected.tolist()


def test_build_density_matrix_performance_not_o_n_squared() -> None:
    """性能回归：2.8 万格矩阵填充须在 <1s 内完成（原 O(n²) 实现约 116s+）。"""
    try:
        import numpy as np
    except ImportError:
        np = None
    if np is None:
        return  # 环境无 numpy，性能回归无法执行，跳过

    import time
    import math

    # 构造 2.8 万个不重叠网格（与评审实测规模一致）。
    span = 168  # 168 * 168 ≈ 28224 格
    cell_counts: dict[tuple[int, int], int] = {}
    for x in range(span):
        for y in range(span):
            cell_counts[(x, y)] = 1

    start = time.monotonic()
    matrix = lightning_statistics.build_density_matrix(cell_counts)
    elapsed = time.monotonic() - start

    assert matrix is not None
    assert elapsed < 1.0, f"matrix build took {elapsed:.2f}s, performance regression"


def test_compute_statistics_default_skips_grid_cells() -> None:
    """默认 include_grid_cells=False：不构建 20 万格级别的巨型 grid_cells。"""
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
    ]
    stats = lightning_statistics.compute_statistics(strikes, grid_size_km=1.0, data_years=1.0)
    assert stats["grid_cells"] == []
    # 标量统计不受影响
    assert stats["total_records"] == 2
    assert stats["overall_ng"] > 0

    # 显式开启仍会构建明细（保持向后兼容）
    stats_full = lightning_statistics.compute_statistics(
        strikes, grid_size_km=1.0, data_years=1.0, include_grid_cells=True
    )
    assert len(stats_full["grid_cells"]) >= 1


def test_configure_chinese_font_no_error() -> None:
    """中文字体配置函数多次调用不抛异常，且 rcParams 正确设置。"""
    lightning_statistics._configure_chinese_font()
    import matplotlib

    assert "SimHei" in matplotlib.rcParams["font.sans-serif"]
    assert matplotlib.rcParams["axes.unicode_minus"] is False
    # 幂等：重复调用不会改变配置
    lightning_statistics._configure_chinese_font()
    assert matplotlib.rcParams["axes.unicode_minus"] is False


def test_render_density_image_with_data_years() -> None:
    """传入 data_years 后，图片为有效 PNG 且不再产生 CJK 缺字警告。"""
    import warnings

    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
        {"lat": 30.02, "lon": 120.02, "current_ka": 3.0, "polarity": "positive"},
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        png = lightning_statistics.render_density_image(
            strikes, grid_size_km=1.0, data_years=2.0
        )
    assert isinstance(png, bytes)
    assert len(png) > 100
    # PNG 签名校验
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_density_image_backward_compatible_without_data_years() -> None:
    """旧调用方式（不传 data_years）向后兼容，正常出图。"""
    strikes = [
        {"lat": 30.0, "lon": 120.0, "current_ka": 10.0, "polarity": "positive"},
        {"lat": 30.01, "lon": 120.01, "current_ka": -5.0, "polarity": "negative"},
    ]
    png = lightning_statistics.render_density_image(strikes, grid_size_km=1.0)
    assert isinstance(png, bytes)
    assert len(png) > 100


# ------------------------- GB/T 40621-2021 分级 / 观测年数 / 网格样本量 -------------------------

def test_density_grade_thresholds() -> None:
    """GB/T 40621-2021 第 4 章：Ng 五等级八级别阈值映射。"""
    grade = lightning_statistics.density_grade
    # 边界取值：低含高不含（Ng < max 属于该级）
    assert grade(0.0) == "A"
    assert grade(0.79) == "A"
    assert grade(0.8) == "B1"
    assert grade(1.9) == "B1"
    assert grade(2.0) == "B2"
    assert grade(2.79) == "B2"
    assert grade(2.8) == "C1"
    assert grade(4.9) == "C1"
    assert grade(5.0) == "C2"
    assert grade(7.9) == "C2"
    assert grade(8.0) == "D1"
    assert grade(10.9) == "D1"
    assert grade(11.0) == "D2"
    assert grade(15.4) == "D2"
    # E 级：>=15.5（英文版误写为 Ng<15.5，按其上下文应为 >=15.5）
    assert grade(15.5) == "E"
    assert grade(30.0) == "E"


def test_density_grade_invalid() -> None:
    grade = lightning_statistics.density_grade
    assert grade(None) is None
    assert grade(-1) is None
    assert grade("abc") is None


def test_grade_rgb_matches_standard() -> None:
    """图例 RGB 与 GB/T 40621-2021 表 1 一致。"""
    expect = {
        "A": (204, 204, 204), "B1": (60, 130, 255), "B2": (0, 255, 255),
        "C1": (255, 255, 0), "C2": (255, 170, 0), "D1": (255, 0, 255),
        "D2": (170, 0, 0), "E": (100, 0, 0),
    }
    for g, rgb in expect.items():
        assert lightning_statistics.grade_rgb(g) == rgb


def test_infer_observation_years_from_timestamp_lines() -> None:
    """带时间戳/年份列的文件可正确推断观测期年数。"""
    text = "\n".join([
        "2015-05-01 12:00:00 30.5 120.2 12.3",
        "2018-08-15 03:22:11 30.6 120.3 -8.0",
        "2020-11-30 19:45:00 30.4 120.1 5.0",
    ])
    assert lightning_statistics.infer_observation_years(text) == 6.0  # 2020-2015+1


def test_infer_observation_years_no_year_returns_none() -> None:
    assert lightning_statistics.infer_observation_years("30.5 120.2 12.3\n30.6 120.3 -8.0") is None


def test_grid_sufficiency_ok() -> None:
    ok = lightning_statistics.grid_sufficiency_ok
    # Ng×A×T >= 80 达标
    assert ok(1.0, 100.0, 1.0) is True   # 100 >= 80
    assert ok(1.0, 1.0, 80.0) is True    # 80 == 80
    assert ok(0.5, 1.0, 10.0) is False   # 5 < 80
    assert ok(None, 1.0, 10.0) is False
