"use client";

import { Descriptions, Empty, Space, Spin, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { readApiError } from "@/lib/api";
import type {
  LineSummary,
  LineTowerListResponse,
  LineTowerSummary,
} from "@/types/auth";

const TOWER_TABLE_MIN_SCROLL_Y = 280;

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function formatCoordinate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(6);
}

function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "-";
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/**
 * LightningTowerView：雷电流幅值页「杆塔列表」动态 Tab 内容。
 * 绑定一条具体线路（lineId），顶部简略展示线路信息，表格精简展示杆塔基础信息并
 * 重点展示「雷电流幅值回填」数据（current_a/current_b/峰值/采样数/回填时间）；未回填塔显示「未回填」。
 */
export function LightningTowerView({
  lineId,
  fetchWithAuth,
}: {
  lineId: string;
  fetchWithAuth: (
    path: string,
    init?: RequestInit,
    retryOnUnauthorized?: boolean,
  ) => Promise<Response>;
}) {
  // 线路基本信息
  const lineQuery = useQuery<LineSummary>({
    queryKey: ["lines", lineId],
    enabled: !!lineId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineSummary;
    },
  });

  // 杆塔列表（复用线路杆塔接口，重点展示雷电流幅值回填字段）
  const towersQuery = useQuery<LineTowerListResponse>({
    queryKey: ["lines", lineId, "towers"],
    enabled: !!lineId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const columns: ColumnsType<LineTowerSummary> = [
    {
      title: "塔号",
      dataIndex: "tower_no",
      key: "tower_no",
      width: 110,
      render: (value: string | null) => value || "-",
    },
    {
      title: "杆塔型号",
      dataIndex: "tower_model",
      key: "tower_model",
      width: 120,
      ellipsis: true,
      render: (value: string | null) => value || "-",
    },
    {
      title: "经度",
      dataIndex: "longitude",
      key: "longitude",
      width: 110,
      render: (value: number | null) => formatCoordinate(value),
    },
    {
      title: "纬度",
      dataIndex: "latitude",
      key: "latitude",
      width: 110,
      render: (value: number | null) => formatCoordinate(value),
    },
    {
      title: "current_a",
      dataIndex: "current_a",
      key: "current_a",
      width: 90,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "current_b",
      dataIndex: "current_b",
      key: "current_b",
      width: 90,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "峰值max(kA)",
      dataIndex: ["lightning_current_preparation", "peak_max"],
      key: "peak_max",
      width: 110,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "峰值min(kA)",
      dataIndex: ["lightning_current_preparation", "peak_min"],
      key: "peak_min",
      width: 110,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "采样数",
      dataIndex: ["lightning_current_preparation", "sampled_event_count"],
      key: "sampled_event_count",
      width: 80,
      render: (value: number | null | undefined) =>
        value == null ? "-" : value,
    },
    {
      title: "回填时间",
      dataIndex: ["lightning_current_preparation", "prepared_at"],
      key: "prepared_at",
      width: 150,
      render: (value: string | null | undefined) => formatDateTime(value),
    },
    {
      title: "回填状态",
      key: "backfill_status",
      width: 110,
      fixed: "right",
      render: (_: unknown, row) => {
        const prep = row.lightning_current_preparation;
        const backfilled =
          row.current_type === "line_prepared" &&
          (row.current_a != null || row.current_b != null);
        if (backfilled || (prep && prep.sampled_event_count > 0)) {
          return <TagLightning color="blue">已回填</TagLightning>;
        }
        return <TagLightning color="default">未回填</TagLightning>;
      },
    },
  ];

  if (lineQuery.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "48px 0" }}>
        <Spin />
      </div>
    );
  }

  const line = lineQuery.data;

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      {line ? (
        <Descriptions size="small" column={4} bordered>
          <Descriptions.Item label="线路编号">{line.code || "-"}</Descriptions.Item>
          <Descriptions.Item label="线路名称">{line.name || "-"}</Descriptions.Item>
          <Descriptions.Item label="电压(kV)">
            {line.voltage_kv ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="杆塔数">{line.tower_count}</Descriptions.Item>
        </Descriptions>
      ) : (
        <Typography.Text type="secondary">线路信息加载失败</Typography.Text>
      )}
      <Table<LineTowerSummary>
        rowKey="id"
        columns={columns}
        dataSource={towersQuery.data?.items ?? []}
        loading={towersQuery.isFetching}
        size="small"
        tableLayout="fixed"
        pagination={false}
        scroll={{ x: 1300, y: TOWER_TABLE_MIN_SCROLL_Y }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="该线路暂无杆塔数据"
            />
          ),
        }}
      />
    </Space>
  );
}

function TagLightning({
  color,
  children,
}: {
  color: "blue" | "default";
  children: ReactNode;
}) {
  /* 轻量 Tag 渲染，避免额外模块依赖导致的类型/运行差异；色值跟随主题 token，亮/暗主题自适应 */
  const palette: Record<string, { background: string; color: string; border: string }> = {
    blue: { background: "var(--ant-color-primary-bg)", color: "var(--accent-11)", border: "var(--accent-6)" },
    default: { background: "var(--gray-2)", color: "var(--gray-10)", border: "var(--gray-6)" },
  };
  const style = palette[color];
  return (
    <span
      style={{
        display: "inline-block",
        padding: "0 7px",
        fontSize: 12,
        lineHeight: "20px",
        borderRadius: 6,
        ...style,
      }}
    >
      {children}
    </span>
  );
}
