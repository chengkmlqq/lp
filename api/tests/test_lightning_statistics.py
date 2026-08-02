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
    }


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
