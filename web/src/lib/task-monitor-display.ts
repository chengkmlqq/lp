type TagDisplay = {
  label: string;
  color: string;
};

const DEFAULT_TAG_DISPLAY: TagDisplay = {
  label: "-",
  color: "default",
};

const TASK_STATE_DISPLAYS: Record<string, TagDisplay> = {
  TODO: { label: "待处理", color: "default" },
  PENDING: { label: "待执行", color: "default" },
  RECEIVED: { label: "已接收", color: "blue" },
  STARTED: { label: "执行中", color: "processing" },
  RUNNING: { label: "执行中", color: "processing" },
  RETRY: { label: "重试中", color: "orange" },
  SCHEDULED: { label: "定时中", color: "purple" },
  SUCCESS: { label: "成功", color: "green" },
  DONE: { label: "成功", color: "green" },
  FAILURE: { label: "失败", color: "red" },
  FAILED: { label: "失败", color: "red" },
  REVOKED: { label: "已撤销", color: "default" },
  CANCELLED: { label: "已取消", color: "default" },
  TIMEOUT: { label: "超时", color: "volcano" },
  UNKNOWN: { label: "未知", color: "geekblue" },
};

const TASK_SOURCE_DISPLAYS: Record<string, TagDisplay> = {
  ACTIVE: { label: "活跃任务", color: "processing" },
  RESERVED: { label: "预留任务", color: "gold" },
  SCHEDULED: { label: "定时任务", color: "purple" },
  RECENT: { label: "最近记录", color: "default" },
};

function normalizeCode(value: string | null | undefined): string {
  return (value || "").trim().toUpperCase();
}

function containsChineseText(value: string): boolean {
  return /\p{Script=Han}/u.test(value);
}

export function getTaskStateDisplay(state: string | null | undefined): TagDisplay {
  const normalized = normalizeCode(state);
  if (!normalized) {
    return DEFAULT_TAG_DISPLAY;
  }
  return TASK_STATE_DISPLAYS[normalized] || { label: "未识别状态", color: "geekblue" };
}

export function getTaskSourceDisplay(source: string | null | undefined): TagDisplay {
  const normalized = normalizeCode(source);
  if (!normalized) {
    return DEFAULT_TAG_DISPLAY;
  }
  return TASK_SOURCE_DISPLAYS[normalized] || { label: "其他来源", color: "default" };
}

export function getQueueDisplayName(queueName: string | null | undefined): string {
  const normalized = (queueName || "").trim();
  if (!normalized) {
    return "-";
  }

  const lowered = normalized.toLowerCase();
  if (lowered === "celery" || lowered === "default") {
    return "默认队列";
  }

  return normalized;
}

export function normalizeQueueNames(queueNames: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];

  for (const queueName of queueNames) {
    const displayName = getQueueDisplayName(queueName);
    if (!seen.has(displayName)) {
      seen.add(displayName);
      result.push(queueName);
    }
  }

  return result;
}

export function formatTaskMonitorDuration(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "-";
  }

  if (value < 1) {
    return "< 1 秒";
  }

  const totalSeconds = Math.floor(value);

  if (totalSeconds < 60) {
    return `${totalSeconds} 秒`;
  }

  const minutes = Math.floor(totalSeconds / 60);
  const remainingSeconds = totalSeconds % 60;

  if (totalSeconds < 3600) {
    return `${minutes} 分 ${remainingSeconds} 秒`;
  }

  const hours = Math.floor(totalSeconds / 3600);
  const remainingMinutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;
  return `${hours} 时 ${remainingMinutes} 分 ${secs} 秒`;
}

export function formatTaskMonitorErrorMessage(message: string | null | undefined, fallback: string): string {
  const normalized = (message || "").trim();
  if (!normalized) {
    return fallback;
  }
  if (containsChineseText(normalized)) {
    return normalized;
  }

  const httpMatch = /^HTTP\s+(\d{3})$/i.exec(normalized);
  if (httpMatch) {
    return `${fallback}（HTTP ${httpMatch[1]}）`;
  }
  if (/worker is required/i.test(normalized)) {
    return "缺少执行节点参数。";
  }
  if (/flower request timeout/i.test(normalized)) {
    return "任务监控服务请求超时，请稍后重试。";
  }
  if (/flower returned non-json payload/i.test(normalized)) {
    return "任务监控服务返回了无法识别的数据。";
  }

  const flowerErrorMatch = /flower error\s+(\d{3})/i.exec(normalized);
  if (flowerErrorMatch) {
    return `任务监控服务返回异常（HTTP ${flowerErrorMatch[1]}）。`;
  }
  if (/flower request failed/i.test(normalized)) {
    return "任务监控服务请求失败，请检查后端服务状态。";
  }

  return fallback;
}
