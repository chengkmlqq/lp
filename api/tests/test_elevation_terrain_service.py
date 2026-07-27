from __future__ import annotations

from ..services import elevation_service


def test_generate_blank_heightmap_tile_has_expected_binary_layout() -> None:
    tile_bytes = elevation_service._generate_heightmap_tile_bytes(
        rasterio=None,
        src=None,
        tile_bounds={"west": -180.0, "south": -90.0, "east": 0.0, "north": 90.0},
        child_mask=5,
        is_blank_root=True,
    )

    expected_height_bytes = elevation_service.TERRAIN_TILE_SIZE * elevation_service.TERRAIN_TILE_SIZE * 2
    assert len(tile_bytes) == expected_height_bytes + 1 + 1
    assert tile_bytes[expected_height_bytes] == 5
    assert tile_bytes[-1] == 0


def test_build_terrain_available_ranges_and_child_mask() -> None:
    bounds = {"west": 110.0, "south": 20.0, "east": 122.0, "north": 32.0}
    availability = elevation_service._build_terrain_available_ranges(bounds=bounds, max_zoom=2)

    assert availability[0] == [{"startX": 0, "endX": 1, "startY": 0, "endY": 0}]
    assert 1 in availability
    assert 2 in availability

    tile_range = availability[1][0]
    child_mask = elevation_service._build_terrain_child_mask(
        availability=availability,
        level=1,
        x=tile_range["startX"],
        y=tile_range["startY"],
        max_zoom=2,
    )
    assert child_mask > 0
