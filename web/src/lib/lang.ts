/**
 * 界面语言的纯逻辑（不依赖 React / 浏览器全局，便于单测）。
 *
 * 默认语言优先级（LP-34）：用户手动选择（localStorage） > 后端启动配置
 * （``GET /api/v1/system/bootstrap``，取自 ``APP_LANGUAGE``）> ``zh``。
 * 不再按浏览器语言兜底——否则「默认值由配置提供」就没有意义。
 */

export type AppLang = "zh" | "en";

export const DEFAULT_APP_LANG: AppLang = "zh";

function asAppLang(value: unknown): AppLang | null {
  return value === "zh" || value === "en" ? value : null;
}

/** 纯函数：解析首次访问应使用的界面语言。 */
export function resolveInitialLang(
  stored: string | null | undefined,
  bootstrap: string | null | undefined,
): AppLang {
  return asAppLang(stored) ?? asAppLang(bootstrap) ?? DEFAULT_APP_LANG;
}
