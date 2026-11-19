"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Progress,
  Row,
  Space,
  Statistic,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  ArrowLeftOutlined,
  DownloadOutlined,
  ReloadOutlined,
  StopOutlined,
  DeleteOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcJobDetail,
  WindTurbineCalcResultListResponse,
  WindTurbineCalcResultRow,
} from "@/types/wind-turbine-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0 ? `${h}h ${m}m ${s}s` : `${m}m ${s}s`;
}

function formatRate(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toExponential(9);
}

export default function WindTurbineCalcDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = params.id;
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const canManage = hasPermission("wind_turbine_calc.manage");

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [chartUrl, setChartUrl] = useState<string | null>(null);

  const detailQuery = useQuery({
    queryKey: ["wind-turbine-calc", "detail", jobId],
    enabled: Boolean(user) && Boolean(jobId),
    queryFn: () => getJson<WindTurbineCalcJobDetail>(`${API_BASE}/${jobId}`),
    refetchInterval: (queryResult) => {
      const status = queryResult.state.data?.status;
      return status === "processing" || status === "pending" ? 4000 : false;
    },
  });

  const resultsQuery = useQuery({
    queryKey: ["wind-turbine-calc", "results", jobId, page, pageSize],
    enabled: Boolean(user) && Boolean(jobId) && detailQuery.data?.status === "completed",
    queryFn: async () => {
      const q = new URLSearchParams();
      q.set("limit", String(pageSize));
      q.set("offset", String((page - 1) * pageSize));
      return getJson<WindTurbineCalcResultListResponse>(`${API_BASE}/${jobId}/results?${q.toString()}`);
    },
  });

  const detail = detailQuery.data;
  const statusMeta = STATUS_META[detail?.status ?? "pending"] ?? STATUS_META.pending;

  // 曲线图带鉴权拉取，转成 blob URL 展示
  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;
    if (!user || !jobId || detail?.status !== "completed") {
      setChartUrl(null);
      return;
    }
    (async () => {
      try {
        const response = await fetchWithAuth(`${API_BASE}/${jobId}/chart`);
        if (!response.ok) return;
        const blob = await response.blob();
        objectUrl = URL.createObjectURL(blob);
        if (!cancelled) setChartUrl(objectUrl);
      } catch {
        // 曲线缺失不阻断详情页
      }
    })();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [user, jobId, detail?.status, fetchWithAuth]);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-turbine-calc"] });
  }, [queryClient]);

  const handleExport = useCallback(
    async (type: "csv" | "all") => {
      try {
        await downloadFileWithAuth(`${API_BASE}/${jobId}/export?type=${type}`, `wind-turbine-${jobId}.${type === "csv" ? "csv" : "zip"}`);
      } catch (error) {
        message.error((error as Error).message);
      }
    },
    [jobId, message],
  );

  const handleCancel = useCallback(() => {
    modal.confirm({
      title: t("取消该计算任务？"),
      content: t("取消会真正终止 MATLAB Runtime 进程组。"),
      okText: t("取消任务"),
      okButtonProps: { danger: true },
      cancelText: t("返回"),
      onOk: async () => {
        const response = await fetchWithAuth(`${API_BASE}/${jobId}/cancel`, { method: "POST" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已发送取消请求"));
        refresh();
      },
    });
  }, [fetchWithAuth, jobId, message, modal, refresh, t]);

  const handleDelete = useCallback(() => {
    modal.confirm({
      title: t("删除该计算任务？"),
      okText: t("删除"),
      okButtonProps: { danger: true },
      cancelText: t("返回"),
      onOk: async () => {
        const response = await fetchWithAuth(`${API_BASE}/${jobId}`, { method: "DELETE" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已删除"));
        refresh();
      },
    });
  }, [fetchWithAuth, jobId, message, modal, refresh, t]);

  const columns = useMemo<TableColumnsType<WindTurbineCalcResultRow>>(
    () => [
      { title: t("旋转角 θ (deg)"), dataIndex: "theta_deg", key: "theta_deg", width: 160, render: (v: number) => v.toFixed(2) },
      { title: t("屏蔽失效率"), dataIndex: "failure_rate", key: "failure_rate", render: (v: number) => v.toExponential(12) },
      {
        title: t("失效率 (%)"),
        dataIndex: "failure_rate_pct",
        key: "failure_rate_pct",
        render: (v: number) => `${v.toFixed(9)}%`,
      },
    ],
    [t],
  );

  const completedAngles = detail
    ? Math.round((detail.progress / 100) * detail.angle_count)
    : 0;

  return (
    <div style={{ padding: 24 }}>
      <Space style={{ marginBottom: 16 }}>
        <Link href="/admin/wind-turbine-calc">
          <Button icon={<ArrowLeftOutlined />}>{t("返回列表")}</Button>
        </Link>
        <Button icon={<ReloadOutlined />} onClick={refresh}>
          {t("刷新")}
        </Button>
        <Button icon={<DownloadOutlined />} onClick={() => handleExport("csv")} disabled={detail?.status !== "completed"}>
          {t("导出 CSV")}
        </Button>
        <Button icon={<DownloadOutlined />} onClick={() => handleExport("all")} disabled={detail?.status !== "completed"}>
          {t("导出结果包")}
        </Button>
        {canManage && (detail?.status === "processing" || detail?.status === "pending") && (
          <Button danger icon={<StopOutlined />} onClick={handleCancel}>
            {t("取消任务")}
          </Button>
        )}
        {canManage && detail && detail.status !== "processing" && detail.status !== "pending" && (
          <Button danger icon={<DeleteOutlined />} onClick={handleDelete}>
            {t("删除")}
          </Button>
        )}
      </Space>

      <Alert
        type="warning"
        showIcon
        style={{ marginBottom: 16 }}
        message={t("角度公式外推提示")}
        description={t("角度击距公式只在 0–90° 范围内拟合，超过 90° 的旋转角按外推计算，结果仅供参考。")}
      />

      <Card title={detail?.name || t("单风机计算详情")} style={{ marginBottom: 16 }}>
        <Descriptions column={2} size="small" bordered>
          <Descriptions.Item label={t("状态")}>
            <Tag color={statusMeta.color}>{statusMeta.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label={t("阶段")}>{detail?.stage ?? "-"}</Descriptions.Item>
          <Descriptions.Item label={t("进度（已完成角度）")}>
            <Progress
              percent={detail?.progress ?? 0}
              format={() => `${completedAngles}/${detail?.angle_count ?? 0}`}
              style={{ width: 200 }}
            />
          </Descriptions.Item>
          <Descriptions.Item label={t("耗时")}>{formatDuration(detail?.duration_seconds)}</Descriptions.Item>
          <Descriptions.Item label={t("轮毂高度 h")}>{detail?.hub_height ?? "-"} m</Descriptions.Item>
          <Descriptions.Item label={t("叶片长度 R")}>{detail?.blade_length ?? "-"} m</Descriptions.Item>
          <Descriptions.Item label={t("起始雷电流 Ic")}>{detail?.start_current ?? "-"} kA</Descriptions.Item>
          <Descriptions.Item label={t("接闪器径向位置")}>{detail?.receptor_radii?.join(", ") || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("旋转角列表")}>{detail?.angle_list?.join(", ") || "-"}</Descriptions.Item>
          <Descriptions.Item label={t("引擎版本")}>
            {detail?.engine_version_tag || detail?.engine_version_hash?.slice(0, 12) || "-"}
            {detail?.runtime_version ? ` (${detail.runtime_version})` : ""}
          </Descriptions.Item>
          <Descriptions.Item label={t("开始时间")}>{formatDateTime(detail?.started_at)}</Descriptions.Item>
          <Descriptions.Item label={t("结束时间")}>{formatDateTime(detail?.finished_at)}</Descriptions.Item>
          {detail?.error_message && (
            <Descriptions.Item label={t("错误信息")} span={2}>
              <Text type="danger">{detail.error_message}</Text>
            </Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card>
            <Statistic title={t("平均失效率")} value={formatRate(detail?.mean_failure_rate)} />
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title={t("最小失效率")} value={formatRate(detail?.min_failure_rate)} />
            <Text type="secondary">{t("对应角度")}: {detail?.min_failure_rate_theta ?? "-"}°</Text>
          </Card>
        </Col>
        <Col span={8}>
          <Card>
            <Statistic title={t("最大失效率")} value={formatRate(detail?.max_failure_rate)} />
            <Text type="secondary">{t("对应角度")}: {detail?.max_failure_rate_theta ?? "-"}°</Text>
          </Card>
        </Col>
      </Row>

      {chartUrl && (
        <Card title={t("失效率曲线")} style={{ marginBottom: 16 }}>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={chartUrl} alt="failure rate chart" style={{ maxWidth: "100%", width: 900 }} />
        </Card>
      )}

      <Card title={t("逐角度结果")}>
        <Table<WindTurbineCalcResultRow>
          rowKey="theta_deg"
          columns={columns}
          dataSource={resultsQuery.data?.items ?? []}
          loading={resultsQuery.isLoading}
          pagination={false}
          locale={{ emptyText: <Empty description={t("暂无结果")} /> }}
        />
        <ModoPagination
          current={page}
          pageSize={pageSize}
          total={resultsQuery.data?.total ?? 0}
          showSizeChanger
          pageSizeOptions={[20, 50, 100]}
          onChange={(nextPage, nextSize) => {
            setPage(nextPage);
            if (nextSize && nextSize !== pageSize) {
              setPageSize(nextSize);
              setPage(1);
            }
          }}
        />
      </Card>
    </div>
  );
}
