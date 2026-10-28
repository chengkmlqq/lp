"use client";

import { Empty, Select, Space, Spin, Table, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  ElevationLinkedLineListResponse,
  ElevationLinkedLineSummary,
  LineTowerListResponse,
  LineTowerSummary,
} from "@/types/auth";

/** ElevationTowerView 仅需读取文件记录 id 来拉取关联线路与杆塔，使用结构化最小类型与页面解耦。 */
export type ElevationTowerRecord = {
  id: string;
};

const LINKED_LINES_TABLE_MIN_SCROLL_Y = 280;

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

export function ElevationTowerView({
  record,
  fetchWithAuth,
}: {
  record: ElevationTowerRecord;
  fetchWithAuth: (
    path: string,
    init?: RequestInit,
    retryOnUnauthorized?: boolean,
  ) => Promise<Response>;
}) {
  const { t } = useI18n();
  const [selectedLineId, setSelectedLineId] = useState<string | null>(null);

  // 关联线路列表（作为下拉数据源，同时决定是否显示空状态）
  const linkedLinesQuery = useQuery<ElevationLinkedLineListResponse>({
    queryKey: ["elevation-records", record.id, "linked-lines"],
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/elevation/records/${record.id}/linked-lines`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationLinkedLineListResponse;
    },
  });

  const linkedLines = useMemo(
    () => linkedLinesQuery.data?.items ?? [],
    [linkedLinesQuery.data?.items],
  );
  const activeLineId = selectedLineId ?? linkedLines[0]?.line_id ?? null;

  // 杆塔列表（复用线路杆塔接口，仅展示高程回填重点字段）
  const towersQuery = useQuery<LineTowerListResponse>({
    queryKey: ["lines", activeLineId, "towers"],
    enabled: !!activeLineId,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lines/${activeLineId}/towers?limit=1000`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const lineOptions = useMemo(
    () =>
      linkedLines.map((line: ElevationLinkedLineSummary) => ({
        label: `${line.line_code ?? "-"} - ${line.line_name ?? "-"}${
          line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""
        }`,
        value: line.line_id,
      })),
    [linkedLines],
  );

  const columns: ColumnsType<LineTowerSummary> = [
    {
      title: "杆塔编号",
      dataIndex: "tower_no",
      key: "tower_no",
      width: 120,
      render: (value: string) => value || "-",
    },
    {
      title: "序号",
      dataIndex: "seq_no",
      key: "seq_no",
      width: 70,
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
      title: "海拔(m)",
      dataIndex: "altitude_m",
      key: "altitude_m",
      width: 90,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "倾角1(°)",
      dataIndex: "slope_1",
      key: "slope_1",
      width: 90,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "倾角2(°)",
      dataIndex: "slope_2",
      key: "slope_2",
      width: 90,
      render: (value: number | null) => formatNumber(value, 3),
    },
    {
      title: "风险等级",
      dataIndex: "risk_level",
      key: "risk_level",
      width: 110,
      render: (value: string | null) =>
        value ? (
          <Typography.Text>{value}</Typography.Text>
        ) : (
          "-"
        ),
    },
  ];

  if (linkedLinesQuery.isLoading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", padding: "48px 0" }}>
        <Spin />
      </div>
    );
  }

  if (linkedLines.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("该高程文件尚未回填任何线路")}
        style={{ padding: "48px 0" }}
      />
    );
  }

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <Typography.Text strong>{t("线路：")}</Typography.Text>
        <Select
          style={{ width: 320 }}
          showSearch
          optionFilterProp="label"
          value={activeLineId}
          onChange={(value) => setSelectedLineId(value)}
          options={lineOptions}
        />
      </div>
      <Table<LineTowerSummary>
        rowKey="id"
        columns={columns}
        dataSource={towersQuery.data?.items ?? []}
        loading={towersQuery.isFetching}
        size="small"
        tableLayout="fixed"
        pagination={false}
        scroll={{ y: LINKED_LINES_TABLE_MIN_SCROLL_Y }}
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
