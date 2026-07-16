import assert from "node:assert/strict";
import test from "node:test";

import {
  countLineTowersOutsideTerrainBounds,
  getElevationTerrainRenderState,
  shouldUseElevationTerrainTiles,
} from "./elevation-terrain.ts";

test("getElevationTerrainRenderState reports ready only when terrain url is available", () => {
  assert.equal(
    getElevationTerrainRenderState({ terrain_status: "ready", terrain_url_template: "/api/v1/elevation/ds/terrain/{z}/{x}/{y}.terrain" }),
    "ready",
  );
  assert.equal(
    getElevationTerrainRenderState({ terrain_status: "ready", terrain_url_template: null }),
    "fallback",
  );
});

test("getElevationTerrainRenderState covers processing failed and fallback states", () => {
  assert.equal(getElevationTerrainRenderState({ terrain_status: "pending", terrain_url_template: null }), "processing");
  assert.equal(getElevationTerrainRenderState({ terrain_status: "processing", terrain_url_template: null }), "processing");
  assert.equal(getElevationTerrainRenderState({ terrain_status: "failed", terrain_url_template: null }), "failed");
  assert.equal(getElevationTerrainRenderState({ terrain_status: "not_supported", terrain_url_template: null }), "fallback");
});

test("countLineTowersOutsideTerrainBounds ignores towers without coordinates and counts out-of-range towers", () => {
  const towers = [
    { longitude: 120.1, latitude: 30.1 },
    { longitude: 121.8, latitude: 30.2 },
    { longitude: null, latitude: 30.3 },
    { longitude: 120.3, latitude: 31.6 },
  ];
  const bounds = { west: 120.0, south: 30.0, east: 121.0, north: 31.0 };

  assert.equal(countLineTowersOutsideTerrainBounds(towers, bounds), 2);
  assert.equal(countLineTowersOutsideTerrainBounds(towers, null), 0);
});

test("shouldUseElevationTerrainTiles returns true only when terrain is ready", () => {
  assert.equal(shouldUseElevationTerrainTiles("ready"), true);
  assert.equal(shouldUseElevationTerrainTiles("processing"), false);
  assert.equal(shouldUseElevationTerrainTiles("failed"), false);
  assert.equal(shouldUseElevationTerrainTiles("fallback"), false);
});
