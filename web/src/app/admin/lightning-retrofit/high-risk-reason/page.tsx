"use client";

import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  InputNumber,
  Modal,
  Pagination,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { ArrowUpOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
  FlAnalysisTowerResultListResponse,
  LineListResponse,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import {
  formatDateTime,
  formatJobType,
  readMitigationMode,
  riskColor,
  statusColor,
} from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_HEADER_HEIGHT = 56;
const TABLE_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

export default function AdminLightningHighRiskReasonPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [lineId, setLineId] = useState<string>("");
  const [lines, setLines] = useState<FlAnalysisJobSummary[]>([]);
  const [loadingLines, setLoadingLines] = useState(false);
  const [riskRows, setRiskRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [loadingRisk, setLoadingRisk] = useState(false);
  const [detailVisible, setDetailVisible] = useState(false);
  const [selectedRow, setSelectedRow] = useState<FlAnalysisTowerResultSummary | null>(null);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

  const loadLines = async (nextLineId: string) => {
    if (!nextLineId) {
      setLines([]);
      setRiskRows([]);
      return;
    }
    setLoadingLines(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as FlAnalysisJobListResponse;
      const matched = data.items.filter((item) => item.line_id === nextLineId);
      setLines(matched);
    } catch (error) {
      setLines([]);
    } finally {
      setLoadingLines(false);
    }
  };

  const loadRiskRows = async (nextLineId: string) => {
    if (!nextLineId) {
      setRiskRows([]);
      return;
    }
    setLoadingRisk(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as FlAnalysisJobListResponse;
      const matched = data.items.filter((item) => item.line_id === nextLineId);
      const ids = matched.map((item) => item.id);
      const rows: FlAnalysisTowerResultSummary[] = [];
      await Promise.all(
        ids.map(async (jobId) => {
          const resultResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/results?limit=200`);
          if (!resultResponse.ok) return;
          const resultData = (await resultResponse.json()) as FlAnalysisTowerResultListResponse;
          rows.push(...resultData.items);
        }),
      );
      const highRiskRows = rows.filter((row) => (row.risk_level === "high" || (row.risk_level && parseInt(row.risk_level, 10) > 2)));
      setRiskRows(highRiskRows);
    } catch (error) {
      setRiskRows([]);
    } finally {
      setLoadingRisk(false);
    }
  };

  const handleLineChange = async (nextLineId: string) => {
    setLineId(nextLineId);
    await Promise.all([loadLines(nextLineId), loadRiskRows(nextLineId)]);
  };

  const handleExport = () => {
    const headers = "塔号,风险等级,原因类型,状态\n";
    const rows = riskRows
      .map((row) => `${row.tower_no},${row.risk_level ?? "-"},${readReasonType(row)},${row.status}`)
      .join("\n");
    const blob = new Blob([headers + rows], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "高风险原因分析.csv";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleViewDetail = (row: FlAnalysisTowerResultSummary) => {
    setSelectedRow(row);
    setDetailVisible(true);
  };

  const columns: ColumnsType<FlAnalysisTowerResultSummary> = useMemo(
    () => [
      {
        title: "塔号",
        dataIndex: "tower_no",
        key: "tower_no",
        width: 120,
        render: (value) => value || "-",
      },
      {
        title: "风险等级",
        dataIndex: "risk_level",
        key: "risk_level",
        width: 120,
        render: (value) => <Tag color={riskColor(value)}>{value ?? "-"}</Tag>,
      },
      {
        title: "原因类型",
        key: "reason_type",
        width: 180,
        render: (_value, row) => readReasonType(row),
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (value) => <span style={{ color: statusColor(value) }}>{value}</span>,
      },
      {
        title: "操作",
        key: "operation",
        width: 140,
        align: "center" as const,
        render: (_value, row) => (
          <Button type="link" size="small" onClick={() => handleViewDetail(row)}>
            查看详情
          </Button>
        ),
      },
    ],
    [],
  );

  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再查看高风险原因分析。</Typography.Text>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `line.manage`）。</Typography.Text>
        </Space>
      </Card>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      <Typography.Title level={4} style={{ margin: 0 }}>
        高风险原因分析
      </Typography.Title>

      <div className="admin-filter-bar">
        <Select
          value={lineId}
          onChange={handleLineChange}
          loading={loadingLines}
          placeholder="选择线路"
          style={{ width: 320 }}
          options={[]}
          showSearch
          optionFilterProp="label"
        />
      </div>

      {loadingRisk ? (
        <Progress percent={0} size="small" />
      ) : riskRows.length === 0 ? (
        <Empty description="暂无高风险杆塔" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <div style={{ "--admin-fl-analysis-table-body-min-height": `${TABLE_MIN_SCROLL_Y}px` } as React.CSSProperties}>
          <Table
            rowKey="id"
            className="admin-fl-analysis-job-table"
            columns={columns}
            dataSource={riskRows}
            pagination={{
              pageSize: 20,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (total) => `共 ${total} 条`,
              hideOnSinglePage: false,
            }}
            scroll={{ x: 1000, y: TABLE_MIN_SCROLL_Y }}
            locale={{
              emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无高风险杆塔" />,
            }}
          />
        </div>
      )}

      <div className="flex justify-end">
        <Button onClick={handleExport} disabled={riskRows.length === 0}>
          导出报告
        </Button>
      </div>

      <Modal
        title="杆塔详情"
        open={detailVisible}
        onCancel={() => setDetailVisible(false)}
        footer={<Button onClick={() => setDetailVisible(false)}>关闭</Button>}
        width={720}
      >
        {selectedRow ? (
          <Space direction="vertical" size={12} className="flex w-full">
            <Alert
              type="warning"
              showIcon
              message={`高风险杆塔：${selectedRow.tower_no || selectedRow.tower_id}`}
              description={`风险等级：${selectedRow.risk_level ?? "-"}；状态：${selectedRow.status}`}
            />
            <Typography.Text>原因详情：</Typography.Text>
            <Typography.Text type="secondary">
              {typeof selectedRow.result_json?.cause_analysis === "string"
                ? selectedRow.result_json.cause_analysis
                : JSON.stringify(selectedRow.result_json ?? {}, null, 2)}
            </Typography.Text>
          </Space>
        ) : null}
      </Modal>
    </div>
  );
}

function readReasonType(row: FlAnalysisTowerResultSummary): string {
  const value = row.result_json?.reason_type;
  if (typeof value === "string") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.join("、");
  }
  const summary = row.summary_text;
  return typeof summary === "string" && summary.trim().length > 0 ? summary : "-";
}
