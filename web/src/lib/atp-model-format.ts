import type { AtpAssetModelFormat } from "@/types/auth";

/**
 * ATPDraw 模型形态的展示元数据。
 *
 * 形态由后端在上传时按 work.atp 的几何引用形态判定（services/atp_model_format.py），
 * 决定仿真走哪条链路，所以卡片上必须能一眼看出来 —— 同一份模型用两条链路算出的
 * 几何来源完全不同，出错时的排查方向也不同。
 */
export type ModelFormatMeta = {
  /** 完整标签，列表/卡片用 */
  label: string;
  /** 极短标签，表格列用 */
  short: string;
  /** 标记色（受控色值，深浅主题都够对比度） */
  color: string;
  /** 背景色 */
  background: string;
  /** 一句话说明仿真链路，放 Tooltip */
  hint: string;
  tone: "legacy" | "insert" | "other";
};

const META: Record<AtpAssetModelFormat | "unknown", ModelFormatMeta> = {
  legacy: {
    label: "旧版 · $INCLUDE + .lib",
    short: "旧版",
    color: "#1d4ed8",
    background: "#eff6ff",
    tone: "legacy",
    hint:
      "ATPDraw 6.x/7.0/7.1（DBM 形态）。几何写在 long/short/dahao/xiaohao 四个 .dat 里，" +
      "每轮仿真由 LP 重算：dat → LCC → pch → lib。节点名在 work.atp 的 $INCLUDE 参数位。",
  },
  insert: {
    label: "新版 · $INSERT + .pch",
    short: "新版",
    color: "#b45309",
    background: "#fffbeb",
    tone: "insert",
    hint:
      "ATPDraw 7.2+ 形态。几何由 ATPDraw 内置 LCC 生成到序号 pch，随包上传、LP 不再重算；" +
      "节点名的唯一载体是 pch 脚卡。仿真前会把 $PARAMETER 段规范化（去 $$、整数补小数点、内联中间变量）。",
  },
  embed: {
    label: "内嵌 · 几何已烧死",
    short: "内嵌",
    color: "#b91c1c",
    background: "#fef2f2",
    tone: "other",
    hint:
      "ATPDraw 7.x 的 Enbed 形态：punch 数据直接内嵌进 work.atp，节点名与几何都已固定，无法按塔参数重算。" +
      "上传口会拒收，此处仅可能出现在改造前的存量记录上。",
  },
  plain: {
    label: "无线路模型",
    short: "无线路",
    color: "#4b5563",
    background: "#f3f4f6",
    tone: "other",
    hint: "work.atp 里没有 $INCLUDE/$INSERT，也没有 7.x 指纹：纯 RLC 工程或手写文件，没有几何需要重算。",
  },
  unknown: {
    label: "待检测 · 尚未判定",
    short: "待检测",
    color: "#6b7280",
    background: "#f9fafb",
    tone: "other",
    hint:
      "这条资产还没有形态预检报告：可能是刚创建还没上传模型文件，或存量数据在形态列上线前入库。" +
      "上传模型文件会自动判定；已有文件的话重新上传可再次触发检测。",
  },
};

export function describeModelFormat(
  format?: AtpAssetModelFormat | null,
  /** 是否已有预检报告。false = 从未判定过，不能显示成「老版」 */
  checked = true,
): ModelFormatMeta {
  // 后端对存量行会回落 legacy（列默认值），但「列默认值」不等于「判定结果」：
  // 2026-11-03 生产事故就是 7.2+ 的 $INSERT 模型因默认值显示成「老版」。
  // 没有预检报告的资产一律显示「待检测」，避免把默认值伪装成结论。
  if (!checked) return META.unknown;
  return META[format ?? "legacy"] ?? META.legacy;
}

/**
 * 异步分析进行中（analysis_status = pending / running）。
 *
 * 2026-11-03：形态识别 + 槽位扫描改成上传后自动触发的后台任务（读 OSS 要 1~3 秒），
 * 这期间库里还是上一次的形态值，直接展示等于拿旧结论冒充新结果，统一显示「检测中」。
 */
export const MODEL_ANALYZING_META: ModelFormatMeta = {
  label: "检测中 · 后台分析",
  short: "检测中",
  color: "#0369a1",
  background: "#f0f9ff",
  tone: "other",
  hint:
    "上传模型后自动触发的后台任务：按存储里的真实 work.atp 重判形态并扫描槽位。" +
    "走的是对象存储（每次 list/get 一次网络往返），单资产约 1~3 秒，列表会自动刷新。",
};

/** 预检报告里有几条需要人工看的提示（warning）。error 级已在后端 400，不会入库。 */
export function checkWarningCount(check?: { warning_count?: number; issues?: unknown[] } | null): number {
  if (!check) return 0;
  if (typeof check.warning_count === "number") return check.warning_count;
  return Array.isArray(check.issues) ? check.issues.length : 0;
}
