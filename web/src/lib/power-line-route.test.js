import assert from "node:assert/strict";
import test from "node:test";

import { buildRouteSegments, collectTowerGeoPoints } from "./power-line-route.ts";

test("buildRouteSegments keeps valid towers connected even when seq numbers jump", () => {
  const towers = [
    { id: "t-1", seq_no: 1, tower_no: "N001", longitude: 120.1, latitude: 30.1, altitude_m: 10, risk_level: null },
    { id: "t-2", seq_no: 3, tower_no: "N003", longitude: 120.2, latitude: 30.2, altitude_m: 11, risk_level: "1" },
    { id: "t-3", seq_no: 8, tower_no: "N008", longitude: 120.3, latitude: 30.3, altitude_m: 12, risk_level: "2" },
  ];

  const segments = buildRouteSegments(towers);

  assert.equal(segments.length, 1);
  assert.deepEqual(segments[0].points.map((point) => point.seqNo), [1, 3, 8]);
});

test("buildRouteSegments splits the route when a tower is missing valid coordinates", () => {
  const towers = [
    { id: "t-1", seq_no: 1, tower_no: "N001", longitude: 120.1, latitude: 30.1, altitude_m: 10, risk_level: null },
    { id: "t-2", seq_no: 2, tower_no: "N002", longitude: 120.2, latitude: 30.2, altitude_m: 11, risk_level: "1" },
    { id: "t-3", seq_no: 3, tower_no: "N003", longitude: null, latitude: 30.3, altitude_m: 12, risk_level: "2" },
    { id: "t-4", seq_no: 4, tower_no: "N004", longitude: 120.4, latitude: 30.4, altitude_m: 13, risk_level: "3" },
  ];

  const segments = buildRouteSegments(towers);

  assert.equal(segments.length, 2);
  assert.deepEqual(segments[0].points.map((point) => point.seqNo), [1, 2]);
  assert.deepEqual(segments[1].points.map((point) => point.seqNo), [4]);
});

test("collectTowerGeoPoints ignores towers without valid coordinates", () => {
  const towers = [
    { id: "t-1", seq_no: 1, tower_no: "N001", longitude: 120.1, latitude: 30.1, altitude_m: 10, risk_level: null },
    { id: "t-2", seq_no: 2, tower_no: "N002", longitude: 181, latitude: 30.2, altitude_m: 11, risk_level: "1" },
    { id: "t-3", seq_no: 3, tower_no: "N003", longitude: 120.3, latitude: 30.3, altitude_m: 12, risk_level: "2" },
  ];

  const points = collectTowerGeoPoints(towers);

  assert.deepEqual(points.map((point) => point.seqNo), [1, 3]);
});
