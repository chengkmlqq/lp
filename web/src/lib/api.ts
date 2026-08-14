const LOOPBACK_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

export function getApiBaseUrl(): string {
  const configured =
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ?? "http://127.0.0.1:8000";

  if (typeof window === "undefined") {
    return trimTrailingSlash(configured);
  }

  let parsed: URL;
  try {
    parsed = new URL(configured);
  } catch {
    return trimTrailingSlash(configured);
  }

  const browserHost = window.location.hostname;
  const browserOrigin = window.location.origin;

  const configuredPort = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
  const browserPort = window.location.port || (parsed.protocol === "https:" ? "443" : "80");

  // Same-site cookies need same hostname (localhost vs 127.0.0.1 breaks it).
  // When both are loopback, rewrite the API hostname to match the browser
  // hostname so SameSite cookies work (they share the same site).
  const shouldRewriteLoopback =
    isLoopbackHost(parsed.hostname)
    && isLoopbackHost(browserHost)
    && parsed.hostname.toLowerCase() !== browserHost.toLowerCase();

  if (shouldRewriteLoopback) {
    // Keep the original port, just swap the hostname (e.g. 127.0.0.1:8000 → localhost:8000)
    return trimTrailingSlash(`${parsed.protocol}//${browserHost}:${configuredPort}`);
  }

  // Port mismatch: keep the configured URL (has the correct port)
  if (configuredPort !== browserPort) {
    return trimTrailingSlash(configured);
  }

  return trimTrailingSlash(browserOrigin);
}

export const API_BASE_URL = getApiBaseUrl();

/**
 * API 错误响应结构
 *
 * 后端在异常时返回的完整错误响应包含：
 * - detail: 错误描述信息（面向用户，应展示此字段）
 * - type: 异常类型名称（供开发参考）
 * - stacktrace: 调用栈信息（仅在debug模式下返回，仅供开发人员调试，不应展示给用户）
 */
interface ApiErrorResponse {
  detail?: string;
  type?: string;
  stacktrace?: string; // 仅供开发调试，不展示给用户
}

/**
 * 从 API 错误响应中提取用户友好的错误信息
 *
 * 注意：此函数仅提取 detail 字段展示给用户，
 * stacktrace 字段（如果存在）不会暴露到用户界面
 */
export async function readApiError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as ApiErrorResponse;
    return data.detail ?? `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

/**
 * 结构化 API 错误类型
 *
 * 相比原生 Error，额外携带 HTTP 状态码与业务错误码，
 * 便于前端结构性消费（如区分 4xx / 5xx、按 code 分流）。
 */
export class ApiError extends Error {
  status?: number;
  code?: string;

  constructor(message: string, options?: { status?: number; code?: string }) {
    super(message);
    this.name = "ApiError";
    this.status = options?.status;
    this.code = options?.code;
  }
}

/**
 * 统一错误消息渲染 helper
 *
 * 兼容 ApiError、纯字符串与 null，返回可用于界面展示的字符串。
 */
export function formatErrorMessage(err: ApiError | string | null | undefined): string {
  if (err == null) return "";
  return typeof err === "string" ? err : err.message;
}
