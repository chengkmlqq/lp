from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.elevation import ElevationDataset
from app.services import elevation_service


def _build_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(bind=engine, tables=[ElevationDataset.__table__])
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    return testing_session()


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


def test_get_dataset_terrain_task_status_reports_ready_detail() -> None:
    session = _build_session()
    try:
        dataset = ElevationDataset(
            code="ELEV-READY-001",
            name="已就绪地形",
            file_format="tif",
            mount_code="default",
            dataset_dir="/elevation/datasets/ELEV-READY-001",
            file_path="/elevation/datasets/ELEV-READY-001/data.tif",
            status="active",
            usage_status="idle",
            terrain_status="ready",
            terrain_task_id="terrain-task-1",
            terrain_url_template="/api/v1/elevation/datasets/ds/terrain/{z}/{x}/{y}.terrain",
            terrain_min_zoom=0,
            terrain_max_zoom=4,
        )
        session.add(dataset)
        session.commit()

        payload = elevation_service.get_dataset_terrain_task_status(session, dataset_id=dataset.id)
        assert payload.status == "success"
        assert payload.detail == "地形瓦片已就绪。"
        assert payload.terrain_url_template == dataset.terrain_url_template
        assert payload.terrain_max_zoom == 4
    finally:
        session.close()


def test_get_dataset_terrain_layer_reads_driver_payload(monkeypatch) -> None:
    session = _build_session()
    try:
        dataset = ElevationDataset(
            code="ELEV-LAYER-001",
            name="地形图层",
            file_format="tif",
            mount_code="default",
            dataset_dir="/elevation/datasets/ELEV-LAYER-001",
            file_path="/elevation/datasets/ELEV-LAYER-001/data.tif",
            status="active",
            usage_status="idle",
            terrain_status="ready",
            terrain_root_path="/elevation/datasets/ELEV-LAYER-001/terrain",
        )
        session.add(dataset)
        session.commit()

        layer_json = {
            "tilejson": "2.1.0",
            "format": "heightmap-1.0",
            "version": "1.0.0",
            "scheme": "tms",
            "projection": "EPSG:4326",
            "tiles": ["{z}/{x}/{y}.terrain?v=1.0.0"],
            "maxzoom": 4,
            "bounds": [110.0, 20.0, 122.0, 32.0],
            "available": [[{"startX": 0, "endX": 1, "startY": 0, "endY": 0}]],
        }

        monkeypatch.setattr(elevation_service, "_require_mount", lambda *_args, **_kwargs: SimpleNamespace())
        monkeypatch.setattr(
            elevation_service,
            "_build_driver_or_400",
            lambda *_args, **_kwargs: SimpleNamespace(
                read_file=lambda path: SimpleNamespace(path=path, content=json.dumps(layer_json).encode("utf-8")),
            ),
        )

        payload = elevation_service.get_dataset_terrain_layer(session, dataset_id=dataset.id)
        assert payload.format == "heightmap-1.0"
        assert payload.maxzoom == 4
        assert payload.bounds == [110.0, 20.0, 122.0, 32.0]
    finally:
        session.close()
