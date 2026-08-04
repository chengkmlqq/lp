import io

import pytest
from PIL import Image

from app.services import lightning_statistics


def _sample_strikes(n=20):
    return [{"lat": 28.0 + i * 0.001, "lon": 113.0 + i * 0.001, "current_ka": 20.0} for i in range(n)]


def test_voronoi_cells_all_finite():
    groups = [
        {"group_id": 0, "center_lat": 28.00, "center_lon": 113.00},
        {"group_id": 1, "center_lat": 28.01, "center_lon": 113.01},
        {"group_id": 2, "center_lat": 28.00, "center_lon": 113.02},
    ]
    cells = lightning_statistics.compute_lp_voronoi_cells(groups, radius_km=3)
    assert len(cells) == 3
    for c in cells:
        assert len(c["polygon"]) >= 3
        assert c["area_km2"] > 0


def test_render_lp_density_image_returns_png():
    groups = [
        {"group_id": 0, "center_lat": 28.00, "center_lon": 113.00},
        {"group_id": 1, "center_lat": 28.01, "center_lon": 113.01},
    ]
    cells = lightning_statistics.compute_lp_voronoi_cells(groups, radius_km=3)
    png = lightning_statistics.render_lp_density_image(
        _sample_strikes(), cells, data_years=1.0, radius_km=3, title="测试")
    assert isinstance(png, bytes) and png
    img = Image.open(io.BytesIO(png))
    assert img.format == "PNG"
