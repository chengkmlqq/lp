type StatusDisplay = {
  label: string;
  color: string;
};

const ASSET_STATUS_DISPLAYS: Record<string, StatusDisplay> = {
  draft: { label: "草稿", color: "gold" },
  enabled: { label: "启用", color: "green" },
  disabled: { label: "停用", color: "default" },
  archived: { label: "归档", color: "red" },
};

const RELEASE_STATUS_DISPLAYS: Record<string, StatusDisplay> = {
  draft: { label: "草稿", color: "gold" },
  released: { label: "已发布", color: "green" },
  archived: { label: "归档", color: "red" },
};

const RUN_STATUS_DISPLAYS: Record<string, StatusDisplay> = {
  pending: { label: "排队中", color: "blue" },
  running: { label: "执行中", color: "gold" },
  success: { label: "成功", color: "green" },
  failed: { label: "失败", color: "red" },
};

const RUNNER_KIND_LABELS: Record<string, string> = {
  atp: "ATP",
  egm: "EGM",
  hybrid: "混合",
};

function getStatusDisplay(mapping: Record<string, StatusDisplay>, value: string): StatusDisplay {
  return mapping[value] ?? { label: value || "未知", color: "blue" };
}

export function getAtpAssetStatusDisplay(value: string): StatusDisplay {
  return getStatusDisplay(ASSET_STATUS_DISPLAYS, value);
}

export function getAtpReleaseStatusDisplay(value: string): StatusDisplay {
  return getStatusDisplay(RELEASE_STATUS_DISPLAYS, value);
}

export function getAtpRunStatusDisplay(value: string): StatusDisplay {
  return getStatusDisplay(RUN_STATUS_DISPLAYS, value);
}

export function getAtpRunnerKindLabel(value: string): string {
  return RUNNER_KIND_LABELS[value] ?? (value || "未知");
}
