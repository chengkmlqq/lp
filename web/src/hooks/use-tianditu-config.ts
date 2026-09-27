"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { SystemParamRuntimeResponse } from "@/types/auth";

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

/**
 * 需要向运行时接口拉取的天地图参数键。
 *
 * 统一走 `/admin/system-params/runtime` 而非列表接口，原因有二：
 * 1. 运行时接口服务端解密，加密参数（`tianditu.tk`）能拿到明文；列表接口只回掩码。
 * 2. 运行时接口仅返回 `status=enabled` 的参数，天然承担了「关闭即失效」的过滤。
 */
const TIANDITU_RUNTIME_KEYS = [
  "enabled",
  "tk",
  "url_template",
  "base_layer",
  "annotation_layer",
  "subdomains",
  "max_level",
  "coord_transform",
] as const;

function readParam(items: { param_key: string; param_value: string }[], keySuffix: string): string {
  const key = `${TIANDITU_PREFIX}${keySuffix}`;
  const item = items.find((p) => p.param_key === key);
  return (item?.param_value ?? "").trim();
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
 * 从系统参数运行时接口读取天地图配置。
 *
 * - 参数缺失（含 `tianditu.enabled` 关闭或 `tianditu.tk` 为空）、无查询权限、网络异常时，
 *   返回 `enabled=false` 的禁用态，调用方维持现状深色背景，不报错。
 * - `url_template` 为空时回落到内置默认模板（仅作兜底参与拼接，实际 tk 仍来自系统参数，
 *   前端不硬编码业务 Key）。
 */
export function useTiandituConfig() {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const ready = Boolean(user);

  // 与后端 /admin/system-params/runtime 的准入码集合保持一致
  // （见 api/app/api/v1/system_params.py）。前端先判权限再发请求，
  // 避免无权限用户打出必然 403 的请求（权限审计项 D）。
  const canReadRuntime =
    hasPermission("system_param.runtime")
    || hasPermission("system_param.read")
    || hasPermission("system_param.manage")
    || hasPermission("line.read")
    || hasPermission("line.manage")
    || hasPermission("tower.read")
    || hasPermission("tower.manage");

  const runtimeQuery = useQuery({
    queryKey: ["/api/v1/admin/system-params/runtime", { keys: TIANDITU_RUNTIME_KEYS }],
    enabled: ready && canReadRuntime,
    queryFn: async () => {
      const params = new URLSearchParams({
        keys: TIANDITU_RUNTIME_KEYS.map((key) => `${TIANDITU_PREFIX}${key}`).join(","),
      });
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
    const items = runtimeQuery.data ?? [];

    // 运行时接口仅返回 status=enabled 的参数，缺失即未配置 / 已关闭。
    const tk = readParam(items, "tk");
    // 关闭 / 未配置 Key / 查询失败 → 禁用态（维持深色背景）
    if (!parseEnabled(readParam(items, "enabled")) || !tk) {
      return EMPTY_CONFIG;
    }

    const urlTemplate = readParam(items, "url_template") || DEFAULT_URL_TEMPLATE;
    const subdomainsRaw = readParam(items, "subdomains");
    const subdomains = subdomainsRaw.split(",").map((s) => s.trim()).filter(Boolean);

    return {
      enabled: true,
      tk,
      baseLayer: readParam(items, "base_layer") || "vec",
      annotationLayer: readParam(items, "annotation_layer"),
      urlTemplate,
      subdomains: subdomains.length > 0 ? subdomains : EMPTY_CONFIG.subdomains,
      maxLevel: parseMaxLevel(readParam(items, "max_level")),
      coordTransform: parseEnabled(readParam(items, "coord_transform")),
    };
  }, [runtimeQuery.data]);

  return {
    config,
    isLoading: runtimeQuery.isLoading,
  };
}
