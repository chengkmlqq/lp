"use client";

/**
 * 批量测试历史记录(页内动态选项卡)。
 *
 * 形态参考「回填记录查看」页(admin-elevation-backfill-pane):
 * 工具条(搜索 + 批量测试按钮 + 刷新) + 历史批次表格 + 行操作(查看 / 下载报告)。
 * 点「批量测试」→ 打开发起抽屉(模型选择 + 参数配置);点行「查看」→ 打开该批次
 * 进度/报告抽屉;点「下载报告」→ 下载报告包 zip(report.xlsx + detail.csv + report.json)。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  Progress,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DownloadOutlined,
  ExperimentOutlined,
  RedoOutlined,
  SearchOutlined,
  EyeOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type { AtpBatchTestRunListResponse, AtpBatchTestRunSummary } from "@/types/auth";
import { AtpBatchTestDrawer } from "@/components/atp-models/atp-batch-test-drawer";

const BATCH_TABLE_MIN_SCROLL_Y = 280;

const BATCH_STATUS_TAG: Record<string, { color: string; text: string }> = {
  running: { color: "processing", text: "运行中" },
  success: { color: "green", text: "全部完成" },
  failed: { color: "red", text: "有失败" },
};

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

export function AtpBatchHistoryTab() {
  const { t } = useI18n();
  const { user } = useAuth();
  const { hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(BATCH_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  // 发起抽屉(空 batchId=发起模式;非空=查看历史批次)
  const [launchOpen, setLaunchOpen] = useState(false);
  const [viewBatchId, setViewBatchId] = useState<string | null>(null);

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canTest = hasPermission("atp.run") || hasPermission("atp.manage");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const measure = () => {
      const anchor = tableScrollAnchorRef.current;
      if (!anchor) {
        return;
      }
      const rect = anchor.getBoundingClientRect();
      const available = window.innerHeight - rect.top - 190;
      setTableScrollY(Math.max(BATCH_TABLE_MIN_SCROLL_Y, Math.floor(available)));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [pagination.current, pagination.pageSize]);

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(pagination.pageSize));
    params.set("offset", String((pagination.current - 1) * pagination.pageSize));
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    return `/api/v1/atp/batch-test-runs?${params.toString()}`;
  }, [keyword, pagination.current, pagination.pageSize]);

  const listQuery = useQuery<AtpBatchTestRunListResponse>({
    queryKey: ["atp-batch-history", listPath],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpBatchTestRunListResponse;
    },
  });

  const handleSearch = useCallback(() => {
    setKeyword(keywordDraft.trim());
    setPagination((previous) => ({ ...previous, current: 1 }));
  }, [keywordDraft]);

  const handleRefresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["atp-batch-history"] });
  }, [queryClient]);

  const downloadReport = useCallback(async (batchId: string) => {
    try {
      const response = await fetchWithAuth(`/api/v1/atp/batch-test-runs/${batchId}/report`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atp-batch-report-${batchId.replace(/[/\\]/g, "_")}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "报告下载失败");
    }
  }, []);

  const openView = useCallback((batchId: string) => {
    setViewBatchId(batchId);
    setLaunchOpen(true);
  }, []);

  const openLaunch = useCallback(() => {
    setViewBatchId(null);
    setLaunchOpen(true);
  }, []);

  const columns = useMemo<ColumnsType<AtpBatchTestRunSummary>>(
    () => [
      {
        title: t("批次号"),
        dataIndex: "batch_id",
        width: 230,
        ellipsis: { showTitle: true },
        render: (value: string) => (
          <Typography.Text code ellipsis={{ tooltip: value }}>
            {value}
          </Typography.Text>
        ),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        width: 110,
        render: (value: string | null, row) => {
          if (row.status === "running") {
            const done = row.done ?? 0;
            const percent = row.total > 0 ? Math.round((done / row.total) * 100) : 0;
            return (
              <Space direction="vertical" size={0} style={{ width: 140 }}>
                <Tag color="processing">{t("运行中")}</Tag>
                <Progress percent={percent} size="small" strokeColor="#1677ff" />
              </Space>
            );
          }
          const meta = BATCH_STATUS_TAG[value ?? ""] ?? { color: "default", text: value ?? "-" };
          return <Tag color={meta.color}>{meta.text}</Tag>;
        },
      },
      {
        title: t("发起时间"),
        dataIndex: "create_date",
        width: 165,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: t("发起人"),
        dataIndex: "create_user",
        width: 120,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      { title: t("总数"), dataIndex: "total", width: 70, render: (v: number) => v ?? 0 },
      {
        title: t("成功"),
        dataIndex: "success",
        width: 70,
        render: (v: number) => <Typography.Text style={{ color: "#3f8600" }}>{v ?? 0}</Typography.Text>,
      },
      {
        title: t("失败"),
        dataIndex: "failed",
        width: 70,
        render: (v: number) =>
          (v ?? 0) > 0 ? <Typography.Text style={{ color: "#cf1322" }}>{v ?? 0}</Typography.Text> : (v ?? 0),
      },
      {
        title: t("通过率"),
        dataIndex: "pass_rate",
        width: 90,
        render: (v: number | null) => (
          <Typography.Text strong>{v != null ? `${v}%` : "-"}</Typography.Text>
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 160,
        fixed: "right" as const,
        render: (_: unknown, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<EyeOutlined />}
              onClick={() => openView(row.batch_id)}
            >
              查看
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<DownloadOutlined />}
              onClick={() => void downloadReport(row.batch_id)}
            >
              下载报告
            </Button>
          </Space>
        ),
      },
    ],
    [downloadReport, openView],
  );

  if (!user) {
    return <Empty description={t("请先登录后再访问批量测试记录。")} />;
  }
  if (!canRead) {
    return <Empty description={t("暂无权限查看批量测试记录。")} />;
  }

  return (
    <div className="admin-atp-batch-history-pane">
      {/* 工具条:搜索 + 批量测试 + 刷新 */}
      <div className="admin-filter-bar">
        <Form layout="inline" onFinish={handleSearch}>
          <Form.Item label={t("批次号/发起人")} style={{ marginBottom: 0 }}>
            <Input
              allowClear
              placeholder={t("输入批次号/发起人")}
              style={{ width: 260 }}
              value={keywordDraft}
              onChange={(event) => setKeywordDraft(event.target.value)}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              查询
            </Button>
          </Form.Item>
          {canTest ? (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" icon={<ExperimentOutlined />} onClick={openLaunch}>
                批量测试
              </Button>
            </Form.Item>
          ) : null}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button icon={<RedoOutlined />} onClick={handleRefresh}>
              刷新
            </Button>
          </Form.Item>
        </Form>
      </div>

      {/* 表格 */}
      <div ref={tableScrollAnchorRef} className="admin-atp-batch-history-table-view flex-1 min-h-0">
        <Table<AtpBatchTestRunSummary>
          rowKey="batch_id"
          size="small"
          loading={listQuery.isFetching}
          dataSource={listQuery.data?.items ?? []}
          columns={columns}
          tableLayout="fixed"
          scroll={{ y: tableScrollY, x: 1080 }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: listQuery.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (total) => `共 ${total} 条`,
            position: ["bottomRight"],
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无批量测试记录。")} />
            ),
          }}
        />
      </div>

      {/* 发起 / 查看抽屉 */}
      <AtpBatchTestDrawer
        open={launchOpen}
        initialBatchId={viewBatchId}
        onClose={() => {
          setLaunchOpen(false);
          setViewBatchId(null);
        }}
      />
    </div>
  );
}