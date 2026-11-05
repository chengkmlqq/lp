"use client";

import { Alert, Empty, Spin, Typography } from "antd";
import { Card as ThemeCard } from "@/components/ui-antd";
import type { EChartsOption } from "echarts";
import ReactECharts from "echarts-for-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

// 后端 overview-tree 节点结构（见 atp_asset_service.get_asset_overview_tree）
interface OverviewTreeNode {
  label: string;
  key: string;
  value: number;
  is_published?: boolean;
  asset_id?: string;
  asset_name?: string;
  status?: string;
  children?: OverviewTreeNode[];
}

// 每个维度层级的节点配色（voltage → tower → scene → arrester → shield_wire → version/leaf）
const LEVEL_COLORS = ["#1677ff", "#52c41a", "#faad14", "#722ed1", "#13c2c2", "#eb2f96"];
const PUBLISHED_LEAF_COLOR = "#52c41a";
const UNPUBLISHED_LEAF_COLOR = "#bfbfbf";

function toEChartsTree(node: OverviewTreeNode, depth: number): Record<string, unknown> {
  const isLeaf = !node.children || node.children.length === 0;
  const itemStyle = node.is_published
    ? { color: PUBLISHED_LEAF_COLOR }
    : { color: levelColor(depth) };
  return {
    name: node.label,
    value: node.value,
    ...(isLeaf && node.is_published !== undefined
      ? { itemStyle: { color: node.is_published ? PUBLISHED_LEAF_COLOR : UNPUBLISHED_LEAF_COLOR } }
      : { itemStyle }),
    children: node.children?.map((child) => toEChartsTree(child, depth + 1)),
  };
}

function levelColor(depth: number): string {
  return LEVEL_COLORS[depth % LEVEL_COLORS.length];
}

export function AtpModelOverviewTab() {
  const { t } = useI18n();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  const overviewQuery = useQuery({
    queryKey: ["atp-assets-overview-tree"],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/atp/assets/overview-tree");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as OverviewTreeNode;
    },
  });

  const option = useMemo<EChartsOption>(() => {
    const data = overviewQuery.data;
    if (!data) {
      return {};
    }
    return {
      tooltip: {
        trigger: "item",
        triggerOn: "mousemove",
        formatter: (params: unknown) => {
          const p = params as { name?: string; value?: unknown };
          const name = p?.name ?? "";
          if (name.includes("已发布") || name.includes("未发布")) {
            return name;
          }
          return `${name}（${p?.value ?? ""}）`;
        },
      },
      series: [
        {
          type: "tree",
          data: [toEChartsTree(data, 0)],
          top: "5%",
          left: "8%",
          bottom: "5%",
          right: "32%",
          symbolSize: 9,
          orient: "LR",
          label: {
            position: "left",
            verticalAlign: "middle",
            align: "right",
            fontSize: 12,
          },
          leaves: {
            label: {
              position: "right",
              verticalAlign: "middle",
              align: "left",
            },
          },
          expandAndCollapse: true,
          initialTreeDepth: 3,
          animationDuration: 550,
          animationDurationUpdate: 750,
        },
      ],
    };
  }, [overviewQuery.data]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Typography.Text type="secondary" className="mb-3">
        {t("按 电压等级 → 塔型 → 场景 → 避雷器组合 → 避雷线 → 版本 分层；绿色叶子为已发布版本，灰色为已下线版本。")}
      </Typography.Text>
      {overviewQuery.isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Spin />
        </div>
      ) : overviewQuery.isError ? (
        <Alert type="error" showIcon message={t("总览数据加载失败")} description={String(overviewQuery.error instanceof Error ? overviewQuery.error.message : overviewQuery.error)} />
      ) : !overviewQuery.data ? (
        <Empty description={t("暂无模型数据")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <ThemeCard size="small" className="flex-1">
          <ReactECharts option={option} style={{ height: 560, width: "100%" }} notMerge={false} lazyUpdate />
        </ThemeCard>
      )}
    </div>
  );
}