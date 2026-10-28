import type { ContextOptions, Viewer } from "cesium";

type CesiumNamespace = typeof import("cesium");
type ViewerOptions = import("cesium").Viewer.ConstructorOptions;

/**
 * WebGL 上下文渐进降级配置。
 *
 * 在 GPU 受限环境（虚拟机、远程桌面、浏览器关闭硬件加速、软件渲染）中，
 * Cesium 默认请求的 WebGL2 上下文可能创建失败，抛出
 * "The browser supports WebGL, but initialization failed."。
 * 依次尝试更宽松的配置，尽可能让地图可用：
 *   1. Cesium 默认（antialias + high-performance，画质最好）
 *   2. 关闭抗锯齿 + low-power + 允许软件渲染（弱 GPU/虚拟显卡更易成功）
 *   3. 进一步退化为 WebGL1
 */
const WEBGL_CONTEXT_TRIES: Array<ContextOptions | undefined> = [
  undefined,
  {
    webgl: {
      antialias: false,
      powerPreference: "low-power",
      failIfMajorPerformanceCaveat: false,
    },
  },
  {
    requestWebgl1: true,
    webgl: {
      antialias: false,
      powerPreference: "low-power",
      failIfMajorPerformanceCaveat: false,
    },
  },
];

/**
 * 创建 Cesium Viewer，并在 WebGL 上下文创建失败时自动降级重试。
 * 所有配置都失败时抛出最后一次的原始错误，便于上层展示诊断信息。
 */
export function createCesiumViewer(
  Cesium: CesiumNamespace,
  container: HTMLElement,
  options: ViewerOptions,
): Viewer {
  let lastError: unknown = null;

  for (const contextOptions of WEBGL_CONTEXT_TRIES) {
    try {
      return new Cesium.Viewer(container, { ...options, contextOptions });
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError ?? new Error("Cesium Viewer 初始化失败");
}

/**
 * 格式化 Cesium 初始化错误，遇到 WebGL 相关失败时附加浏览器侧排查提示。
 */
export function formatCesiumInitError(candidate: unknown, t: (s: string) => string = (s) => s): string {
  const message = candidate instanceof Error && candidate.message
    ? candidate.message
    : t("Cesium 初始化失败，请检查依赖与静态资源是否已同步。");

  if (/webgl/i.test(message)) {
    return `${message}。${t("当前浏览器未能创建 WebGL 上下文，可尝试：开启浏览器硬件加速、更换 Chrome/Edge 浏览器、或更新显卡驱动。")}`;
  }

  return message;
}
