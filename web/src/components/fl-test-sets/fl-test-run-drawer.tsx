"use client";

/**
 * 防雷测试执行详情抽屉（测试任务的查看入口）。
 *
 * 展示一次批量执行（run）内逐用例的任务状态与评估结论；支持：
 * - 用例级重跑 / 人工判定（manual_pass / manual_fail）；
 * - 展开查看该用例任务的杆塔结果简表（GET /fl-analysis/jobs/{job_id}/results）；
 * - run 级取消。任务本体不出现在防雷计算页面（test_run_case_id 标记隔离）。
 */
import { useMemo, useState } from "react";
import type { Key } from "react";
import {
  App,
  Button,
  Descriptions,
  Drawer,
  Dropdown,
  Empty,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { CheckOutlined, CloseOutlined, RedoOutlined, StopOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type { FlTestRunCaseSummary, FlTestRunSummary } from "@/types/fl-test-set";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";
import { FlTestJobStatusTag, FlTestRunStatusTag, FlTestVerdictTag } from "@/components/fl-test-sets/fl-test-set-tab";

interface TowerResultRow {
  id: string;
  tower_no: string;
  tower_model: string | null;
  status: string;
  risk_level: string | null;
  summary_text: string | null;
  result_json: Record<string, unknown>;
}

function formatDuration(ms: number | null): string {
  if (ms == null) return "-";
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m${seconds % 60}s`;
}

export function FlTestRunDrawer({
  runId,
  open,
  onClose,
}: {
  runId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { hasPermission } = useAuth();
  const { modal: modalApi, message: messageApi } = App.useApp();
  const queryClient = useQueryClient();
  const [expandedRowKey, setExpandedRowKey] = useState<string | null>(null);

  const canRun = hasPermission("fl.start") || hasPermission("fl.create") || hasPermission("line.manage") || hasPermission("atp.manage");
  const canJudge = hasPermission("fl.create") || hasPermission("line.manage") || hasPermission("atp.manage");

  const runQuery = useQuery({
    queryKey: ["/api/v1/fl-test-sets/runs", runId],
    enabled: open && !!runId,
    refetchInterval: (query) => {
      const status = (query.state.data as FlTestRunSummary | undefined)?.status;
      return status === "running" || status === "pending" ? 8000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/runs/${runId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as FlTestRunSummary;
    },
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/fl-test-sets/runs", runId] });
  };

  const rerunMutation = useMutation({
    mutationFn: async (runCaseId: string) => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/run-cases/${runCaseId}/rerun`, { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      messageApi.success(t("已重新发起该用例任务"));
      invalidate();
    },
    onError: (error: Error) => modalApi.error({ title: t("重跑失败"), content: error.message }),
  });

  const verdictMutation = useMutation({
    mutationFn: async ({ runCaseId, verdict }: { runCaseId: string; verdict: string }) => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/run-cases/${runCaseId}/verdict`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ verdict }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      messageApi.success(t("已记录人工判定"));
      invalidate();
    },
    onError: (error: Error) => modalApi.error({ title: t("人工判定失败"), content: error.message }),
  });

  const cancelRunMutation = useMutation({
    mutationFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/runs/${runId}/cancel`, { method: "POST" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      messageApi.success(t("已请求取消，状态更新中"));
      invalidate();
    },
    onError: (error: Error) => modalApi.error({ title: t("取消失败"), content: error.message }),
  });

  const run = runQuery.data;
  const cases = run?.cases ?? [];

  const columns = useMemo<ColumnsType<FlTestRunCaseSummary>>(
    () => [
      {
        title: t("用例"),
        dataIndex: "case_name",
        ellipsis: { showTitle: true },
      },
      {
        title: t("任务状态"),
        width: 120,
        render: (_: unknown, row) => <FlTestJobStatusTag status={row.job_status} />,
      },
      {
        title: t("评估结论"),
        width: 130,
        render: (_: unknown, row) => <FlTestVerdictTag verdict={row.verdict} />,
      },
      {
        title: t("耗时 / 时间"),
        width: 170,
        render: (_: unknown, row) => (
          <Typography.Text type="secondary">{formatDateTime(row.update_date)}</Typography.Text>
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 190,
        render: (_: unknown, row) => (
          <Space size={0}>
            {row.job_id ? (
              <Button
                size="small"
                type="link"
                onClick={() => setExpandedRowKey((prev) => (prev === row.id ? null : row.id))}
              >
                {expandedRowKey === row.id ? t("收起结果") : t("查看结果")}
              </Button>
            ) : null}
            {canRun ? (
              <Button size="small" type="link" icon={<RedoOutlined />} onClick={() => rerunMutation.mutateAsync(row.id)}>
                {t("重跑")}
              </Button>
            ) : null}
            {canJudge ? (
              <Dropdown
                menu={{
                  items: [
                    { key: "pass", icon: <CheckOutlined />, label: t("判定通过") },
                    { key: "fail", icon: <CloseOutlined />, label: t("判定不通过") },
                  ],
                  onClick: ({ key }) =>
                    verdictMutation.mutateAsync({ runCaseId: row.id, verdict: key === "pass" ? "manual_pass" : "manual_fail" }),
                }}
              >
                <Button size="small" type="link">
                  {t("人工判定")}
                </Button>
              </Dropdown>
            ) : null}
          </Space>
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, canRun, canJudge, expandedRowKey],
  );

  return (
    <Drawer
      title={t("执行详情")}
      open={open}
      onClose={onClose}
      width={960}
      destroyOnClose
      extra={
        run && (run.status === "running" || run.status === "pending") && canRun ? (
          <Button danger icon={<StopOutlined />} loading={cancelRunMutation.isPending} onClick={() => cancelRunMutation.mutateAsync()}>
            {t("取消整批执行")}
          </Button>
        ) : null
      }
    >
      {!run ? (
        <Spin />
      ) : (
        <>
          <Descriptions size="small" column={4} style={{ marginBottom: 12 }}>
            <Descriptions.Item label={t("状态")}>
              <FlTestRunStatusTag status={run.status} />
            </Descriptions.Item>
            <Descriptions.Item label={t("进度")}>
              {run.finished_cases}/{run.total_cases}
            </Descriptions.Item>
            <Descriptions.Item label={t("通过")}>{run.passed_cases}</Descriptions.Item>
            <Descriptions.Item label={t("失败")}>{run.failed_cases}</Descriptions.Item>
            <Descriptions.Item label={t("待人工")}>{run.pending_manual_cases}</Descriptions.Item>
            <Descriptions.Item label={t("发起时间")}>{formatDateTime(run.create_date)}</Descriptions.Item>
            <Descriptions.Item label={t("耗时")}>{formatDuration(run.duration_ms)}</Descriptions.Item>
          </Descriptions>
          <Table<FlTestRunCaseSummary>
            rowKey="id"
            size="small"
            columns={columns}
            dataSource={cases}
            loading={runQuery.isLoading}
            pagination={false}
            expandable={{
              expandedRowKeys: expandedRowKey ? [expandedRowKey] : [],
              onExpandedRowsChange: (keys: readonly Key[]) =>
                setExpandedRowKey(keys.length ? String(keys[keys.length - 1]) : null),
              expandedRowRender: (row) => (row.job_id ? <CaseJobResults jobId={row.job_id} /> : null),
              rowExpandable: (row) => !!row.job_id,
            }}
            locale={{ emptyText: <Empty description={t("没有用例执行记录")} /> }}
          />
        </>
      )}
    </Drawer>
  );
}

function CaseJobResults({ jobId }: { jobId: string }) {
  const { t } = useI18n();
  const resultsQuery = useQuery({
    queryKey: ["/api/v1/fl-analysis/jobs/results", jobId],
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/results?limit=200`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as { items: TowerResultRow[]; total: number };
    },
  });

  const riskColor = (level: string | null): string => {
    if (level === "high") return "error";
    if (level === "medium") return "warning";
    if (level === "low") return "success";
    return "default";
  };

  return (
    <Table<TowerResultRow>
      rowKey="id"
      size="small"
      loading={resultsQuery.isLoading}
      dataSource={resultsQuery.data?.items ?? []}
      pagination={false}
      columns={[
        { title: t("塔号"), dataIndex: "tower_no", width: 110 },
        {
          title: t("风险等级"),
          dataIndex: "risk_level",
          width: 110,
          render: (value: string | null) =>
            value ? <Tag color={riskColor(value)}>{value}</Tag> : <Typography.Text type="secondary">-</Typography.Text>,
        },
        {
          title: t("耐雷水平 / 跳闸率"),
          render: (_: unknown, row) => {
            const withHim = row.result_json?.counterstrike_withstand_ka;
            const shield = row.result_json?.shielding_withstand_ka;
            const trip = row.result_json?.counterstrike_trip_rate ?? row.result_json?.shielding_trip_rate;
            return (
              <Typography.Text type="secondary">
                {withHim != null ? `反击 ${withHim}kA ` : ""}
                {shield != null ? `绕击 ${shield}kA ` : ""}
                {trip != null ? `跳闸率 ${trip}` : ""}
                {!withHim && shield == null && trip == null ? "-" : ""}
              </Typography.Text>
            );
          },
        },
        {
          title: t("摘要"),
          dataIndex: "summary_text",
          ellipsis: { showTitle: true },
          render: (value: string | null) => (
            <Typography.Text type="secondary">{value || "-"}</Typography.Text>
          ),
        },
      ]}
      locale={{ emptyText: <Empty description={t("暂无杆塔结果（任务可能仍在计算）")} /> }}
    />
  );
}
