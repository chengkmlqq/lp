import type { LineSummary } from "@/types/auth";

export type LinePreparationComponentKey = "lightning_current" | "lightning_density" | "ground_slope";

export type LinePreparationComponent = {
  key: LinePreparationComponentKey;
  label: string;
  ready: boolean;
  status: string;
  tower_total_count: number;
  tower_ready_count: number;
  missing_tower_count: number;
  line_ready: boolean;
  values: Record<string, unknown>;
  source: Record<string, unknown>;
};

export type LinePreparationSummary = {
  all_ready: boolean;
  missing_items: string[];
  lightning_current: LinePreparationComponent;
  lightning_density: LinePreparationComponent;
  ground_slope: LinePreparationComponent;
};

const LABELS: Record<LinePreparationComponentKey, string> = {
  lightning_current: "雷电流幅值",
  lightning_density: "地闪密度",
  ground_slope: "地面倾角",
};

function readObject(value: unknown): Record<string, unknown> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function readBoolean(value: unknown): boolean {
  return value === true;
}

function readNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is string => typeof item === "string" && item.trim().length > 0);
}

function emptyComponent(key: LinePreparationComponentKey): LinePreparationComponent {
  return {
    key,
    label: LABELS[key],
    ready: false,
    status: "missing",
    tower_total_count: 0,
    tower_ready_count: 0,
    missing_tower_count: 0,
    line_ready: false,
    values: {},
    source: {},
  };
}

function readComponent(value: unknown, key: LinePreparationComponentKey): LinePreparationComponent {
  const record = readObject(value);
  const fallback = emptyComponent(key);
  return {
    key,
    label: typeof record.label === "string" ? record.label : fallback.label,
    ready: readBoolean(record.ready),
    status: typeof record.status === "string" ? record.status : fallback.status,
    tower_total_count: readNumber(record.tower_total_count),
    tower_ready_count: readNumber(record.tower_ready_count),
    missing_tower_count: readNumber(record.missing_tower_count),
    line_ready: typeof record.line_ready === "boolean" ? record.line_ready : fallback.line_ready,
    values: readObject(record.values),
    source: readObject(record.source),
  };
}

export function readLinePreparation(line: Pick<LineSummary, "preparation_json"> | null | undefined): LinePreparationSummary {
  const record = readObject(line?.preparation_json);
  return {
    all_ready: readBoolean(record.all_ready),
    missing_items: readStringArray(record.missing_items),
    lightning_current: readComponent(record.lightning_current, "lightning_current"),
    lightning_density: readComponent(record.lightning_density, "lightning_density"),
    ground_slope: readComponent(record.ground_slope, "ground_slope"),
  };
}
