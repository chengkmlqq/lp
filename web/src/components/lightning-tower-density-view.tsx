"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Empty,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";

import { readApiError } from "@/lib/api";
import type {
  LightningLinkedLinesResponse,
  LineTowerListResponse,
  LineTowerSummary,
} from "@/types/auth";

function formatDensity(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(6);
}

function formatGeo(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(6);
}

function formatAngle(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(2);
}

const RISK_COLOR: Record<string, string> = {
  高: "red",
  中: "orange",
  低: "green",
};

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

const TOWER_TABLE_SCROLL_X = 900;

export function TowerDensityView({
  distributionId,
  fetchWithAuth,
}: {
  distributionId: string;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
}) {
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);

  // 关联线路列表（数据源 = linked-lines 接口）
  const linkedLinesPath = `/api/v1/lightning-currents/distributions/${distributionId}/linked-lines`;
  const linkedLinesQuery = useQuery({
    queryKey: [linkedLinesPath],
    queryFn: async () => {
      const response = await fetchWithAuth(linkedLinesPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningLinkedLinesResponse;
    },
  });

  const linkedLines = useMemo(
    () => linkedLinesQuery.data?.items ?? [],
    [linkedLinesQuery.data],
  );

  // 无选中线路时回退到第一条线路（派生值，避免 effect 内 setState）
  const effectiveSelectedLineId = selectedLineId ?? linkedLines[0]?.line_id ?? null;

  const lineOptions = useMemo(
    () =>
      linkedLines.map((line) => ({
        label: `${line.line_code || line.line_name || line.line_id}${line.line_name ? ` - ${line.line_name}` : ""}`,
        value: line.line_id,
      })),
    [linkedLines],
  );

  // 当前选中线路的杆塔列表（复用线路杆塔列表接口）
  const towersPath = effectiveSelectedLineId
    ? `/api/v1/lines/${effectiveSelectedLineId}/towers?limit=1000&offset=0`
    : null;
  const towersQuery = useQuery({
    queryKey: [towersPath],
    enabled: !!towersPath,
    queryFn: async () => {
      if (!towersPath) {
        return { items: [], total: 0 } satisfies LineTowerListResponse;
      }
      const response = await fetchWithAuth(towersPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const towers: LineTowerSummary[] = useMemo(
    () => towersQuery.data?.items ?? [],
    [towersQuery.data],
  );

  const selectedLine = useMemo(
    () => linkedLines.find((line) => line.line_id === effectiveSelectedLineId) ?? null,
    [linkedLines, effectiveSelectedLineId],
  );

  // 精简列：重点展示地闪密度回填相关字段，线路无关字段不展示
  const columns = useMemo<ColumnsType<LineTowerSummary>>(
    () => [
      {
        title: t("杆塔编号"),
        dataIndex: "tower_no",
        width: 120,
        render: (value: string) => value || "-",
      },
      {
        title: t("序号"),
        dataIndex: "seq_no",
        width: 70,
        render: (value: number) => value,
      },
      {
        title: t("经度"),
        dataIndex: "longitude",
        width: 110,
        render: (value: number | null) => formatGeo(value),
      },
      {
        title: t("纬度"),
        dataIndex: "latitude",
        width: 110,
        render: (value: number | null) => formatGeo(value),
      },
      {
        title: t("海拔(m)"),
        dataIndex: "altitude_m",
        width: 90,
        render: (value: number | null) => (value === null || value === undefined ? "-" : value.toFixed(1)),
      },
      {
        title: t("地闪密度(次/km²·年)"),
        dataIndex: "lightning_density",
        width: 150,
        render: (value: number | null) => formatDensity(value),
      },
      {
        title: t("倾角1(°)"),
        dataIndex: "slope_1",
        width: 90,
        render: (value: number | null) => formatAngle(value),
      },
      {
        title: t("倾角2(°)"),
        dataIndex: "slope_2",
        width: 90,
        render: (value: number | null) => formatAngle(value),
      },
      {
        title: t("风险等级"),
        dataIndex: "risk_level",
        width: 100,
        render: (value: string | null) => {
          if (!value) {
            return "-";
          }
          return <Tag color={RISK_COLOR[value] ?? "default"}>{value}</Tag>;
        },
      },
    ],
    [],
  );

  if (linkedLinesQuery.isLoading && linkedLines.length === 0) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin />
      </div>
    );
  }

  if (linkedLinesQuery.isError && linkedLines.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={linkedLinesQuery.error instanceof Error ? linkedLinesQuery.error.message : t("关联线路加载失败")}
      />
    );
  }

  if (linkedLines.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("该分布尚未回填任何线路")}
      />
    );
  }

  return (
    <Space direction="vertical" size={16} className="w-full">
      <Space wrap size={8}>
        <Typography.Text type="secondary">{t("线路")}</Typography.Text>
        <Select
          style={{ minWidth: 240 }}
          value={effectiveSelectedLineId}
          options={lineOptions}
          onChange={setSelectedLineId}
          placeholder={t("选择线路")}
        />
        {selectedLine && (
          <Typography.Text type="secondary">
            {selectedLine.line_code || selectedLine.line_name || selectedLine.line_id}
            {selectedLine.voltage_kv ? ` (${selectedLine.voltage_kv}kV)` : ""}
            {" · "}引用杆塔 {selectedLine.tower_count} 座
            {" · "}最近回填 {formatDateTime(selectedLine.prepared_at)}
          </Typography.Text>
        )}
      </Space>

      <Table<LineTowerSummary>
        rowKey="id"
        size="small"
        columns={columns}
        dataSource={towers}
        loading={towersQuery.isFetching}
        pagination={{
          pageSize: 20,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
        }}
        scroll={{ x: TOWER_TABLE_SCROLL_X }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("该线路暂无杆塔数据")}
            />
          ),
        }}
      />
    </Space>
  );
}