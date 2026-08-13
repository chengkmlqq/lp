"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type {
  SystemParamListResponse,
  SystemParamRuntimeResponse,
  SystemParamSummary,
} from "@/types/auth";

/**
 * 天地图（Tianditu）底图配置。
 * 所有字段均来自系统参数管理页面（system_params 表，`tianditu.*` 前缀），
 * 参数缺失 / 为空 / 关闭时走禁用态，由调用方回退到现有深色背景，不抛错。
 */
export type TiandituConfig = {
  enabled: boolean;
  tk: string;
  baseLayer: string;
  annotationLayer: string;
  urlTemplate: string;
  subdomains: string[];
  maxLevel: number;
  coordTransform: boolean;
};

const EMPTY_CONFIG: TiandituConfig = {
  enabled: false,
  tk: "",
  baseLayer: "vec",
  annotationLayer: "",
  urlTemplate: "",
  subdomains: ["0", "1", "2", "3", "4", "5", "6", "7"],
  maxLevel: 18,
  coordTransform: false,
};

const TIANDITU_PREFIX = "tianditu.";

/** 天地图官方 WMTS 瓦片 URL 模板（{s}/{layer}/{z}/{y}/{x} 由 Cesium 占位符替换，{tk} 由 hook 替换）。 */
const DEFAULT_URL_TEMPLATE =
  "https://t{s}.tianditu.gov.cn/{layer}_w/wmts?SERVICE=WMTS"
  + "&REQUEST=GetTile&VERSION=1.0.0&LAYER={layer}&STYLE=default"
  + "&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk={tk}";

function firstParam(items: SystemParamSummary[], keyPrefix: string): string {
  const prefix = `${TIANDITU_PREFIX}${keyPrefix}`;
  const item = items.find((p) => p.param_key === prefix);
  if (!item || item.status !== "enabled") {
    return "";
  }
  return (item.param_value ?? "").trim();
}

function parseEnabled(raw: string): boolean {
  return raw === "" ? false : ["true", "1", "yes", "on"].includes(raw.toLowerCase());
}

function parseMaxLevel(raw: string): number {
  const parsed = Number.parseInt(raw, 10);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : 18;
}

/** 将 URL 模板占位符替换为具体图层与 Key（{s}/{z}/{y}/{x} 由 Cesium 运行时替换）。 */
export function resolveTiandituUrl(
  template: string,
  layer: string,
  tk: string,
): string {
  if (!template || !layer || !tk) return "";
  return template.replace(/\{layer\}/g, layer).replace(/\{tk\}/g, tk);
}

/**
 * 从系统参数接口读取天地图配置。
 *
 * - 查询失败（无权限 / 网络异常 / 单点失败）或 `tianditu.enabled` 关闭、`tianditu.tk` 为空时，
 *   返回 `enabled=false` 的禁用态，调用方维持现状深色背景，不报错。
 * - `url_template` 为空时回落到内置默认模板（仅作兜底参与拼接，实际 tk 仍来自系统参数，
 *   前端不硬编码业务 Key）。
 */
export function useTiandituConfig() {
  const { user, fetchWithAuth } = useAuth();
  const ready = Boolean(user);

  const paramsQuery = useQuery({
    queryKey: ["/api/v1/admin/system-params", { keyword: "tianditu", limit: 200 }],
    enabled: ready,
    queryFn: async () => {
      const params = new URLSearchParams({ limit: "200", offset: "0", keyword: TIANDITU_PREFIX });
      const response = await fetchWithAuth(`/api/v1/admin/system-params?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as SystemParamListResponse;
      if (!Array.isArray(data.items)) {
        throw new Error("系统参数数据格式异常");
      }
      return data.items;
    },
    staleTime: 30_000,
    retry: false,
  });

  // 加密参数（如 tianditu.tk）密文不下发，需通过运行时解密接口获取实际 Key（LP-310）
  const runtimeQuery = useQuery({
    queryKey: ["/api/v1/admin/system-params/runtime", { keys: ["tianditu.tk"] }],
    enabled: ready,
    queryFn: async () => {
      const params = new URLSearchParams({ keys: `${TIANDITU_PREFIX}tk` });
      const response = await fetchWithAuth(`/api/v1/admin/system-params/runtime?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as SystemParamRuntimeResponse;
      if (!Array.isArray(data.items)) {
        throw new Error("系统参数数据格式异常");
      }
      return data.items;
    },
    staleTime: 30_000,
    retry: false,
  });

  const config = useMemo<TiandituConfig>(() => {
    const items = paramsQuery.data ?? [];
    const enabledRaw = firstParam(items, "enabled");

    // tk 优先取运行时解密结果；未加密的存量参数从列表接口回退取明文。
    // 加密参数在列表中仅返回掩码（不返回明文），因此绝不作为 tk 使用。
    const tkItem = items.find((p) => p.param_key === `${TIANDITU_PREFIX}tk`);
    const tkFromList =
      tkItem && tkItem.status === "enabled" && !tkItem.is_encrypted
        ? (tkItem.param_value ?? "").trim()
        : "";
    const runtimeTk = runtimeQuery.data?.find((item) => item.param_key === `${TIANDITU_PREFIX}tk`)?.param_value?.trim() ?? "";
    const tk = runtimeTk || tkFromList;

    // 关闭 / 未配置 Key / 查询失败 → 禁用态（维持深色背景）
    if (!parseEnabled(enabledRaw) || !tk) {
      return EMPTY_CONFIG;
    }

    const urlTemplate = firstParam(items, "url_template") || DEFAULT_URL_TEMPLATE;
    const subdomainsRaw = firstParam(items, "subdomains");
    const subdomains = subdomainsRaw.split(",").map((s) => s.trim()).filter(Boolean);

    return {
      enabled: true,
      tk,
      baseLayer: firstParam(items, "base_layer") || "vec",
      annotationLayer: firstParam(items, "annotation_layer"),
      urlTemplate,
      subdomains: subdomains.length > 0 ? subdomains : EMPTY_CONFIG.subdomains,
      maxLevel: parseMaxLevel(firstParam(items, "max_level")),
      coordTransform: parseEnabled(firstParam(items, "coord_transform")),
    };
  }, [paramsQuery.data, runtimeQuery.data]);

  return {
    config,
    isLoading: paramsQuery.isLoading || runtimeQuery.isLoading,
  };
}