"use client";

/**
 * 测试集执行结果抽屉：轮询执行批次详情，展示
 * ①集合级摘要(状态/计数/通过率/回归统计) ②用例级结果表(闪络/与上次对比) ③下载报告包。
 * 数据来自 GET /atp/test-sets/runs/{run_id}。
 */
import { useCallback, useEffect, useMemo, useRef } from "react";
import { useI18n } from "@/lib/i18n";
import {
  Alert,
  Button,
  Descriptions,
  Drawer,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { DownloadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type { AtpTestSetRunSummary } from "@/types/auth";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: "default", text: "待执行" },
  running: { color: "processing", text: "运行中" },
  success: { color: "green", text: "成功" },
  failed: { color: "red", text: "失败" },
};

export function AtpTestSetRunDrawer({
  runId,
  open,
  onClose,
}: {
  runId: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const { user, hasPermission } = useAuth();
  const { t } = useI18n();
  const canRead =
    hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  const runQuery = useQuery<AtpTestSetRunSummary>({
    queryKey: ["atp-test-set-run", runId],
    enabled: Boolean(user && canRead && open && runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "running" || status === "pending" ? 3000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/runs/${runId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpTestSetRunSummary;
    },
  });

  // 执行中自动滚动到最新完成的用例（首个仍 running 的行）
  const tableWrapRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!runQuery.data) return;
    if (runQuery.data.status !== "running" && runQuery.data.status !== "pending") return;
    const rows = tableWrapRef.current?.querySelectorAll<HTMLElement>(
      ".ant-table-tbody > tr.ant-table-row",
    );
    if (!rows) return;
    for (const row of rows) {
      const text = row.textContent ?? "";
      if (text.includes("运行中") || text.includes("待执行")) {
        row.scrollIntoView({ block: "nearest", behavior: "smooth" });
        return;
      }
    }
  }, [runQuery.data]);

  const downloadReport = useCallback(async () => {
    if (!runId) return;
    try {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/runs/${runId}/report`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atp-test-set-${runId}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("报告下载失败"));
    }
  }, [runId]);

  const data = runQuery.data;
  const done = data
    ? data.counts.success + data.counts.failed
    : 0;
  const percent = data && data.total_cases > 0 ? Math.round((done / data.total_cases) * 100) : 0;
  const regressionCounts = data?.report?.regression?.counts;

  const columns = useMemo<ColumnsType<AtpTestSetRunSummary["items"][number]>>(
    () => [
      {
        title: t("用例"),
        dataIndex: "case_name",
        width: 150,
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text ellipsis={{ tooltip: value }} style={{ maxWidth: 170 }}>
              {value || row.case_id}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {row.asset_code}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: t("计算类型"),
        dataIndex: "job_kind",
        width: 90,
        render: (value: string) =>
          value === "tongtiao" ? (
            <Tag color="purple">{t("同跳计算")}</Tag>
          ) : (
            <Tag color="blue">{t("普通计算")}</Tag>
          ),
      },
      {
        title: t("电压/塔型/场景"),
        key: "dims",
        width: 170,
        render: (_, row) =>
          [row.voltage_level, row.tower_type, row.scene_type].filter(Boolean).join(" / ") || "-",
      },
      {
        title: t("状态"),
        dataIndex: "status",
        width: 90,
        render: (value: string, row) => {
          const meta = STATUS_TAG[value] ?? { color: "default", text: value ?? "-" };
          const metaText = t(meta.text);
          return (
            <Space direction="vertical" size={0}>
              <Tag color={meta.color}>{t(meta.text)}</Tag>
              {(value === "running" || value === "pending") && row.run_id && (
                <Progress
                  type="circle"
                  percent={50}
                  size={18}
                  strokeColor="#1677ff"
                  format={() => ""}
                />
              )}
            </Space>
          );
        },
      },
      {
        title: t("雷电流(kA)"),
        dataIndex: "current_ka",
        width: 100,
        render: (value: number | null) => (value != null ? value : "-"),
      },
      {
        title: t("闪络相数"),
        dataIndex: "flashover_count",
        width: 120,
        render: (value: number | null, row) => {
          if (value == null) return "-";
          const phases = row.flashover_phases?.length ? `（${row.flashover_phases.join(",")}）` : "";
          return (
            <Typography.Text strong={value > 0} style={value > 0 ? { color: "#cf1322" } : {}}>
              {value} 相{phases}
            </Typography.Text>
          );
        },
      },
      {
        title: t("与上次对比"),
        key: "prev",
        width: 130,
        render: (_, row) => {
          const prev = row.previous;
          if (!prev) return <Typography.Text type="secondary">-</Typography.Text>;
          const statusChanged = prev.status !== row.status;
          const flashoverChanged = prev.flashover_count !== row.flashover_count;
          if (!statusChanged && !flashoverChanged) {
            return <Tag color="green">{t("无变化")}</Tag>;
          }
          if (prev.status === "success" && row.status !== "success") {
            return <Tag color="red">{t("回归失败")}</Tag>;
          }
          if (flashoverChanged) {
            return (
              <Tag color="orange">
                闪络 {prev.flashover_count ?? "-"}→{row.flashover_count ?? "-"}
              </Tag>
            );
          }
          if (prev.status !== "success" && row.status === "success") {
            return <Tag color="green">{t("修复通过")}</Tag>;
          }
          return <Tag color="orange">{t("结果有变")}</Tag>;
        },
      },
      {
        title: t("耗时"),
        dataIndex: "duration_ms",
        width: 90,
        render: (value: number | null) =>
          value != null ? `${(value / 1000).toFixed(1)}s` : "-",
      },
      {
        title: t("错误信息"),
        dataIndex: "error_message",
        ellipsis: { showTitle: true },
        render: (value: string | null) =>
          value ? <Typography.Text type="danger">{value}</Typography.Text> : "-",
      },
    ],
    [],
  );

  return (
    <Drawer
      title={
        <Space>
          <span>{t("执行结果")}</span>
          {data ? (
            <Tag color={STATUS_TAG[data.status]?.color ?? "default"}>
              {t(STATUS_TAG[data.status]?.text ?? data.status)}
            </Tag>
          ) : null}
        </Space>
      }
      open={open}
      onClose={onClose}
      width={1100}
      destroyOnHidden
      extra={
        <Space>
          <Button icon={<DownloadOutlined />} onClick={() => void downloadReport()}>
            {t("下载报告")}
          </Button>
        </Space>
      }
    >
      {runQuery.isError ? (
        <Alert
          type="error"
          showIcon
          message={t("加载执行结果失败")}
          description={runQuery.error instanceof Error ? runQuery.error.message : ""}
        />
      ) : !data ? (
        <div style={{ padding: 40, textAlign: "center" }}>{t("加载中…")}</div>
      ) : (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {/* 集合级摘要 */}
          <div
            style={{
              display: "flex",
              gap: 24,
              alignItems: "center",
              padding: 16,
              border: "1px solid var(--ant-color-border-secondary)",
              borderRadius: 8,
              flexWrap: "wrap",
            }}
          >
            <div style={{ minWidth: 120 }}>
              <Progress
                type="dashboard"
                size={88}
                percent={percent}
                status={data.counts.failed > 0 ? "exception" : "active"}
                format={(p) => `${p ?? 0}%`}
              />
            </div>
            <Descriptions
              column={2}
              size="small"
              items={[
                { key: "total", label: t("用例总数"), children: data.total_cases },
                {
                  key: "success",
                  label: t("成功"),
                  children: (
                    <Typography.Text style={{ color: "#3f8600" }}>{data.counts.success}</Typography.Text>
                  ),
                },
                {
                  key: "failed",
                  label: t("失败"),
                  children: (
                    <Typography.Text style={{ color: "#cf1322" }}>{data.counts.failed}</Typography.Text>
                  ),
                },
                {
                  key: "pass",
                  label: t("通过率"),
                  children: (
                    <Typography.Text strong>{data.report?.overall_pass_rate ?? 0}%</Typography.Text>
                  ),
                },
                {
                  key: "duration",
                  label: t("耗时"),
                  children:
                    data.duration_ms != null ? `${(data.duration_ms / 1000).toFixed(1)}s` : "-",
                },
                {
                  key: "time",
                  label: t("发起时间"),
                  children: formatDateTime(data.create_date),
                },
              ]}
            />
            {regressionCounts ? (
              <div
                style={{
                  marginLeft: "auto",
                  display: "flex",
                  gap: 10,
                  flexWrap: "wrap",
                  alignItems: "center",
                }}
              >
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  与上次执行对比：
                </Typography.Text>
                <Tag color="green">无变化 {regressionCounts.unchanged ?? 0}</Tag>
                <Tag color="orange">有变更 {regressionCounts.changed ?? 0}</Tag>
                {regressionCounts.regressed ? (
                  <Tag color="red">回归失败 {regressionCounts.regressed}</Tag>
                ) : null}
                {regressionCounts.improved ? (
                  <Tag color="green">修复通过 {regressionCounts.improved}</Tag>
                ) : null}
                {regressionCounts.flashover_changed ? (
                  <Tag color="orange">闪络变化 {regressionCounts.flashover_changed}</Tag>
                ) : null}
              </div>
            ) : null}
          </div>

          {data.error_message ? (
            <Alert type="error" showIcon message={data.error_message} />
          ) : null}

          {/* 用例级结果 */}
          <div ref={tableWrapRef} style={{ border: "1px solid var(--ant-color-border-secondary)", borderRadius: 8 }}>
            <Table<AtpTestSetRunSummary["items"][number]>
              rowKey={(row) => row.case_id}
              size="small"
              loading={runQuery.isFetching}
              dataSource={data.items}
              columns={columns}
              tableLayout="fixed"
              scroll={{ x: 1000, y: 420 }}
              pagination={false}
              locale={{
                emptyText: (
                  <Typography.Text type="secondary">{t("暂无用例结果（可能全部派发失败）。")}</Typography.Text>
                ),
              }}
            />
          </div>
        </Space>
      )}
    </Drawer>
  );
}