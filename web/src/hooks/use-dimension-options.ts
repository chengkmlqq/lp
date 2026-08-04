"use client";

import { useMemo } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { DimensionTypeTreeItem } from "@/types/auth";
import type { DimensionItemListResponse } from "@/types/dimension";

function flattenTypeNodes(types: DimensionTypeTreeItem[]): DimensionTypeTreeItem[] {
  return types.flatMap((t) => [t, ...flattenTypeNodes(t.children)]);
}

function findDimensionTypeByCode(types: DimensionTypeTreeItem[], code: string): DimensionTypeTreeItem | undefined {
  return flattenTypeNodes(types).find((t) => t.code === code);
}

export type DimensionOption = { label: string; value: string };

/**
 * 从维度管理 API 拉取指定维度类型的选项。
 * `fields` 为「本地字段名 → 维度类型 code」映射，例如
 * `{ job_type: "fl_analysis_job_type", current_waveform: "current_waveform" }`。
 * 返回每个字段的 optionMap（label/value，供下拉选）与 labelMap（code→name，供展示格式化）。
 * 维度管理不可用（查询失败 / 类型未 seed）时返回空集合，由调用方回退到静态硬编码选项。
 */
export function useDimensionOptions(fields: Record<string, string>) {
  const { user, fetchWithAuth } = useAuth();
  const ready = Boolean(user);
  const fieldsKey = JSON.stringify(fields);
  const fieldNames = useMemo(() => Object.keys(fields), [fieldsKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const dimensionTypesQuery = useQuery({
    queryKey: ["/api/v1/dimensions/types/tree"],
    enabled: ready,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/dimensions/types/tree");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as DimensionTypeTreeItem[];
    },
  });

  const dimensionTypeIds = useMemo(() => {
    const types = dimensionTypesQuery.data ?? [];
    const result: Record<string, string | undefined> = {};
    for (const field of fieldNames) {
      result[field] = findDimensionTypeByCode(types, fields[field])?.id;
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimensionTypesQuery.data, fieldsKey]);

  const dimensionItemsQueries = useQueries({
    queries: fieldNames.map((field) => {
      const typeId = dimensionTypeIds[field];
      return {
        queryKey: ["/api/v1/dimensions", { type_id: typeId, enabled: true }],
        enabled: ready && Boolean(typeId),
        queryFn: async () => {
          const params = new URLSearchParams();
          params.set("type_id", typeId!);
          params.set("enabled", "true");
          params.set("limit", "200");
          const response = await fetchWithAuth(`/api/v1/dimensions?${params.toString()}`);
          if (!response.ok) {
            throw new Error(await readApiError(response));
          }
          return (await response.json()) as DimensionItemListResponse;
        },
      };
    }),
  });

  const optionMap = useMemo(() => {
    const map: Record<string, DimensionOption[]> = {};
    for (const field of fieldNames) {
      map[field] = [];
    }
    dimensionItemsQueries.forEach((query, index) => {
      const field = fieldNames[index];
      map[field] = (query.data?.items ?? []).map((item) => ({ label: item.name, value: item.code }));
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimensionItemsQueries, fieldsKey]);

  const labelMap = useMemo(() => {
    const map: Record<string, Map<string, string>> = {};
    for (const field of fieldNames) {
      map[field] = new Map();
    }
    dimensionItemsQueries.forEach((query, index) => {
      const field = fieldNames[index];
      for (const item of query.data?.items ?? []) {
        map[field].set(item.code, item.name);
      }
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dimensionItemsQueries, fieldsKey]);

  return {
    optionMap,
    labelMap,
    isLoading: dimensionTypesQuery.isLoading || dimensionItemsQueries.some((query) => query.isLoading),
  };
}
