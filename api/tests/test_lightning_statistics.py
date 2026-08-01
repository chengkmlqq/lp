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
    stats = lightning_statistics.compute_statistics(strikes, grid_size_km=1.0, data_years=1.0)

    assert stats["total_records"] == 3
    assert stats["positive_count"] == 1
    assert stats["negative_count"] == 1
    assert stats["unknown_count"] == 1
    assert stats["max_abs_current"] == 10.0
    assert stats["avg_abs_current"] == 5.0
    assert stats["area_km2"] > 0
    assert stats["overall_ng"] > 0
    assert len(stats["grid_cells"]) >= 1


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
