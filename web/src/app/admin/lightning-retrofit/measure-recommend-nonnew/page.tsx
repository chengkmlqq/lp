"use client";

import { useMemo, useState } from "react";
import {
  Alert,
  Button,
  Empty,
  Input,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { PlusOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import type {
  FlAnalysisJobDetail,
  FlAnalysisJobListResponse,
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
  FlAnalysisTowerResultListResponse,
} from "@/types/auth";
import { readApiError } from "@/lib/api";
import {
  formatDateTime,
  formatJobType,
  mitigationMode,
  riskColor,
  statusColor,
} from "@/components/fl-analysis/types";

const TABLE_MIN_SCROLL_Y = 180;

type TowerSelectionRow = {
  id: string;
  tower_id: string;
  tower_no: string;
  risk_level: string | null;
  status: string;
  include: boolean;
};

export default function AdminLightningMeasureRecommendNonnewPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [baseJobs, setBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [selectedBaseJobId, setSelectedBaseJobId] = useState<string>("");
  const [towerRows, setTowerRows] = useState<TowerSelectionRow[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [loadingTowers, setLoadingTowers] = useState(false);
  const [creating, setCreating] = useState(false);
  const [jobName, setJobName] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage") || hasPermission("tower.manage");

  const selectedBaseJob = useMemo(
    () => baseJobs.find((job) => job.id === selectedBaseJobId) ?? null,
    [baseJobs, selectedBaseJobId],
  );

  const loadBaseJobs = async () => {
    setLoadingJobs(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as FlAnalysisJobListResponse;
      const matched = data.items.filter((item) => item.job_type === "normal" || item.job_type === "tongtiao");
      setBaseJobs(matched);
    } catch (error) {
      setBaseJobs([]);
    } finally {
      setLoadingJobs(false);
    }
  };

  const loadTowerRows = async (baseJobId: string) => {
    if (!baseJobId) {
      setTowerRows([]);
      return;
    }
    setLoadingTowers(true);
    try {
      const detailResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${baseJobId}`);
      if (!detailResponse.ok) {
        throw new Error(await readApiError(detailResponse));
      }
      const detail = (await detailResponse.json()) as { job: FlAnalysisJobDetail };
      const resultsResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${baseJobId}/results?limit=500`);
      if (!resultsResponse.ok) {
        throw new Error(await readApiError(resultsResponse));
      }
      const results = (await resultsResponse.json()) as FlAnalysisTowerResultListResponse;
      const rows: TowerSelectionRow[] = results.items.map((row) => ({
        id: row.id,
        tower_id: row.tower_id,
        tower_no: row.tower_no,
        risk_level: row.risk_level,
        status: row.status,
        include: row.risk_level === "high" || (row.risk_level && parseInt(row.risk_level, 10) > 2),
      }));
      setTowerRows(rows);
      if (rows.some((row) => row.include)) {
        setJobName(
          `${detail.job.job_name || detail.job.line_name || detail.job.line_code || "防雷任务"}-措施推荐(非建线)`,
        );
      }
    } catch (error) {
      setTowerRows([]);
    } finally {
      setLoadingTowers(false);
    }
  };

  const handleBaseJobChange = async (nextJobId: string) => {
    setSelectedBaseJobId(nextJobId);
    setErrorMessage("");
    setSuccessMessage("");
    await loadTowerRows(nextJobId);
  };

  const toggleTowerInclude = (rowId: string) => {
    setTowerRows((previous) =>
      previous.map((row) => (row.id === rowId ? { ...row, include: !row.include } : row)),
    );
  };

  const handleCreateJob = async () => {
    if (!selectedBaseJob) {
      setErrorMessage("请先选择前置任务");
      return;
    }
    const selectedTowers = towerRows.filter((row) => row.include);
    if (selectedTowers.length === 0) {
      setErrorMessage("请至少包含一个杆塔");
      return;
    }
    setCreating(true);
    setErrorMessage("");
    setSuccessMessage("");
    try {
      const payload = {
        line_id: selectedBaseJob.line_id,
        job_name: jobName.trim() || `${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "防雷任务"}-措施推荐(非建线)`,
        job_type: "mitigation",
        execution_options_json: {
          non_construction: true,
          base_job_id: selectedBaseJob.id,
          selected_tower_ids: selectedTowers.map((row) => row.tower_id),
        },
      };
      const createResponse = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!createResponse.ok) {
        throw new Error(await readApiError(createResponse));
      }
      const created = (await createResponse.json()) as { job: FlAnalysisJobDetail };
      const startResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${created.job.id}/start`, {
        method: "POST",
      });
      if (!startResponse.ok) {
        throw new Error(await readApiError(startResponse));
      }
      setSuccessMessage(`非建线措施推荐任务已创建并启动：${created.job.job_name || created.job.id}`);
      setJobName("");
      setSelectedBaseJobId("");
      setTowerRows([]);
      await loadBaseJobs();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "非建线措施推荐任务创建失败");
    } finally {
      setCreating(false);
    }
  };

  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再查看改造措施推荐。</Typography.Text>
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
        改造措施推荐（非建线）
      </Typography.Title>

      <div className="admin-filter-bar">
        <Space.Compact style={{ display: "inline-flex" }}>
          <Select
            value={selectedBaseJobId}
            onChange={handleBaseJobChange}
            loading={loadingJobs}
            placeholder="选择前置任务"
            style={{ width: 320 }}
            options={baseJobs.map((job) => ({
              value: job.id,
              label: `${job.job_name || job.line_name || job.line_code || "-"}（${formatJobType(job.job_type, mitigationMode(job))}）`,
            }))}
          />
          <Button icon={<PlusOutlined />} onClick={loadBaseJobs}>
            刷新
          </Button>
        </Space.Compact>
      </div>

      {selectedBaseJob ? (
        <Alert
          type="info"
          showIcon
          message="已选择前置任务"
          description={`${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "-"} / 杆塔总数：${selectedBaseJob.total_tower_count}`}
        />
      ) : null}

      {loadingTowers ? (
        <Progress percent={0} size="small" />
      ) : towerRows.length === 0 && selectedBaseJobId ? (
        <Empty description="暂无杆塔结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : selectedBaseJobId ? (
        <div style={{ "--admin-fl-analysis-table-body-min-height": `${TABLE_MIN_SCROLL_Y}px` } as React.CSSProperties}>
          <Table<TowerSelectionRow>
            rowKey="id"
            className="admin-fl-analysis-job-table"
            columns={[
              {
                title: "包含",
                key: "include",
                width: 80,
                align: "center" as const,
                render: (_value, row) => (
                  <input
                    type="checkbox"
                    checked={row.include}
                    onChange={() => toggleTowerInclude(row.id)}
                  />
                ),
              },
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
                title: "状态",
                dataIndex: "status",
                key: "status",
                width: 120,
                render: (value) => <span style={{ color: statusColor(value) }}>{value}</span>,
              },
            ]}
            dataSource={towerRows}
            pagination={{
              pageSize: 20,
              showSizeChanger: true,
              pageSizeOptions: [10, 20, 50, 100],
              showTotal: (total) => `共 ${total} 条`,
              hideOnSinglePage: false,
            }}
            scroll={{ x: 800, y: TABLE_MIN_SCROLL_Y }}
          />
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        <Input
          value={jobName}
          onChange={(event) => setJobName(event.target.value)}
          placeholder="任务名称"
        />
        <div className="flex flex-wrap gap-3">
          <Button type="primary" onClick={handleCreateJob} loading={creating} disabled={!selectedBaseJobId || towerRows.length === 0}>
            生成措施推荐
          </Button>
        </div>
        {successMessage ? <Alert type="success" showIcon message={successMessage} /> : null}
        {errorMessage ? <Alert type="error" showIcon message={errorMessage} /> : null}
      </div>
    </div>
  );
}
