"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { Dayjs } from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  DatePicker,
  Descriptions,
  Input,
  Drawer,
  Empty,
  Form,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { readApiError } from "@/lib/api";
import type {
  LineListResponse,
  LineSummary,
  LightningAmplitudeBackfillLine,
  LightningAmplitudeBackfillLineListResponse,
  LightningCurrentBackfillTaskDetail,
  LightningCurrentBackfillTaskListResponse,
  LightningCurrentBackfillTaskSummary,
  LightningCurrentBackfillTowerDetail,
} from "@/types/auth";

const BACKFILL_HISTORY_MIN_SCROLL_Y = 180;
const BACKFILL_HISTORY_ESTIMATED_HEADER_HEIGHT = 56;
const BACKFILL_HISTORY_ESTIMATED_PAGINATION_HEIGHT = 64;
const BACKFILL_HISTORY_BOTTOM_GAP = 8;

type LightningCurrentBackfillHistoryTableProps = {
  amplitudeId?: string;
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
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function renderAction(action: string) {
  if (action === "created") {
    return <Tag color="blue">新建</Tag>;
  }
  return <Tag color="orange">更新</Tag>;
}

function renderDelta(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return <Typography.Text type="secondary">-</Typography.Text>;
  }
  if (value > 0) {
    return <Typography.Text style={{ color: "#52c41a" }}>+{value.toFixed(3)}</Typography.Text>;
  }
  if (value < 0) {
    return <Typography.Text type="danger">{value.toFixed(3)}</Typography.Text>;
  }
  return <Typography.Text type="secondary">0.000</Typography.Text>;
}

export function LightningCurrentBackfillHistoryTable({
  amplitudeId,
}: LightningCurrentBackfillHistoryTableProps) {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [lineId, setLineId] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<[Dayjs, Dayjs] | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(BACKFILL_HISTORY_MIN_SCROLL_Y);
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);
  // 幅值模式：筛选关键词 + 点击某线路查看该次回填具体填了什么值
  const [keyword, setKeyword] = useState("");
  const [amplitudeLineTarget, setAmplitudeLineTarget] = useState<{ lineId: string; lineName: string | null } | null>(null);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const isAmplitudeMode = !!amplitudeId;

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    // 与线路管理-列表页同一套算法：用「可滚动面板(.admin-lightning-backfill-pane)的
    // padding-box 底边」推导表体高度。2026-09-12 对齐
    //   ① 不用 anchor 自身高度反推（会被表体 min-height 撑大 → 正反馈、越翻越高）
    //   ② 不用 window.innerHeight（漏掉面板底部内边距与页面底边距 → 溢出 12px、多出纵向滚动条）
    //   ③ 分页器上方 margin 16px + 4px 余量，保证容器内不产生滚动条
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-lightning-backfill-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? BACKFILL_HISTORY_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? BACKFILL_HISTORY_ESTIMATED_PAGINATION_HEIGHT;
    // 面板底边常低于视口底边（页面上方还有页签栏等），取较小值；并将面板自身已有的纵向溢出扣掉，
    // 避免表体算高撑出页面滚动条或面板内滚动条。2026-09-12
    const containerBottom = Math.min(containerRect.bottom, document.documentElement.clientHeight);
    const paneOverflow = Math.max(0, container.scrollHeight - container.clientHeight);
    const available = containerBottom - containerPadBottom - anchorTop - BACKFILL_HISTORY_BOTTOM_GAP - paneOverflow;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
    const clampedHeight = Math.max(BACKFILL_HISTORY_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const frameId = window.requestAnimationFrame(updateTableScrollHeight);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollHeight, isAmplitudeMode, pagination.current, pagination.pageSize, lineId, dateRange]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollHeight);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollHeight]);

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("page", String(pagination.current));
    params.set("page_size", String(pagination.pageSize));
    if (lineId) {
      params.set("line_id", lineId);
    }
    if (dateRange?.[0]) {
      params.set("start_date", dateRange[0].format("YYYY-MM-DD"));
    }
    if (dateRange?.[1]) {
      params.set("end_date", dateRange[1].format("YYYY-MM-DD"));
    }
    return `/api/v1/lightning-currents/backfill-tasks?${params.toString()}`;
  }, [dateRange, lineId, pagination.current, pagination.pageSize]);

  const listQuery = useQuery<LightningCurrentBackfillTaskListResponse>({
    queryKey: [listPath],
    enabled: !!user && canRead && !isAmplitudeMode,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskListResponse;
    },
  });

  const amplitudeLinesQuery = useQuery<LightningAmplitudeBackfillLineListResponse>({
    queryKey: ["lightning-currents", amplitudeId, "backfill-lines", keyword, pagination.current, pagination.pageSize],
    enabled: !!user && canRead && isAmplitudeMode,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("offset", String((pagination.current - 1) * pagination.pageSize));
      params.set("limit", String(pagination.pageSize));
      if (keyword.trim()) {
        params.set("keyword", keyword.trim());
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${amplitudeId}/backfill-lines?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeBackfillLineListResponse;
    },
  });

  // 幅值模式：某线路使用该幅值那一次回填的明细（含每塔回填前/后幅值）
  const amplitudeTaskQuery = useQuery<LightningCurrentBackfillTaskDetail>({
    queryKey: ["lightning-currents", amplitudeId, "line-task", amplitudeLineTarget?.lineId],
    enabled: !!user && canRead && isAmplitudeMode && !!amplitudeId && !!amplitudeLineTarget,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/amplitudes/${amplitudeId}/backfill-lines/${amplitudeLineTarget?.lineId}/task`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskDetail;
    },
  });

  const linesQuery = useQuery<LineListResponse>({
    queryKey: ["lines"],
    enabled: !!user && canRead && !isAmplitudeMode,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  const detailQuery = useQuery<LightningCurrentBackfillTaskDetail>({
    queryKey: ["lightning-currents", "backfill-tasks", detailTaskId],
    enabled: !!user && canRead && !!detailTaskId && detailOpen && !isAmplitudeMode,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/backfill-tasks/${detailTaskId}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskDetail;
    },
  });

  const openDetail = useCallback((record: LightningCurrentBackfillTaskSummary) => {
    setDetailTaskId(record.id);
    setDetailOpen(true);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailOpen(false);
    setDetailTaskId(null);
  }, []);

  const amplitudeColumns = useMemo<ColumnsType<LightningAmplitudeBackfillLine>>(
    () => [
      {
        title: "线路编号",
        dataIndex: "line_code",
        width: 120,
        render: (value: string | null) => value || "-",
      },
      {
        title: "线路名称",
        dataIndex: "line_name",
        width: 180,
        ellipsis: { showTitle: true },
        render: (value: string | null) => value || "-",
      },
      {
        title: "电压(kV)",
        dataIndex: "voltage_kv",
        width: 110,
        render: (value: number | null) => (value == null ? "-" : value),
      },
      {
        title: "回填时间",
        dataIndex: "prepared_at",
        width: 170,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: "操作",
        key: "actions",
        width: 110,
        fixed: "right",
        render: (_: unknown, row) => (
          <Button
            size="small"
            onClick={() => setAmplitudeLineTarget({ lineId: row.line_id, lineName: row.line_name ?? null })}
          >
            查看详情
          </Button>
        ),
      },
    ],
    [],
  );

  const taskColumns = useMemo<ColumnsType<LightningCurrentBackfillTaskSummary>>(
    () => [
      {
        title: "回填时间",
        dataIndex: "prepared_at",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "线路名称",
        dataIndex: "line_name",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string | null) => value || "-",
      },
      {
        title: "幅值a (kA)",
        dataIndex: "current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "幅值b (kA)",
        dataIndex: "current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "更新杆塔数",
        dataIndex: "updated_tower_count",
        width: 110,
        render: (value: number) => value ?? 0,
      },
      {
        title: "操作人",
        dataIndex: "prepared_by",
        width: 120,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      {
        title: "操作",
        key: "actions",
        width: 100,
        fixed: "right",
        render: (_: unknown, row) => (
          <Button size="small" onClick={() => openDetail(row)}>
            查看详情
          </Button>
        ),
      },
    ],
    [openDetail],
  );

  const towerColumns = useMemo<ColumnsType<LightningCurrentBackfillTowerDetail>>(
    () => [
      {
        title: "塔号",
        dataIndex: "tower_no",
        width: 120,
        render: (value: string | null, row) => value || row.tower_id || "-",
      },
      {
        title: "操作",
        dataIndex: "action",
        width: 80,
        render: (value: string) => renderAction(value),
      },
      {
        title: "回填前幅值a",
        dataIndex: "previous_current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "回填后幅值a",
        dataIndex: "current_a",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "变化量a",
        dataIndex: "delta_a",
        width: 100,
        render: (value: number | null) => renderDelta(value),
      },
      {
        title: "回填前幅值b",
        dataIndex: "previous_current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "回填后幅值b",
        dataIndex: "current_b",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: "变化量b",
        dataIndex: "delta_b",
        width: 100,
        render: (value: number | null) => renderDelta(value),
      },
    ],
    [],
  );

  // 抽屉数据源：任务模式用任务详情，幅值模式用「幅值+线路」明细
  const detailData = isAmplitudeMode ? amplitudeTaskQuery.data : detailQuery.data;
  const detailLoading = isAmplitudeMode ? amplitudeTaskQuery.isLoading : detailQuery.isLoading;
  const detailFetching = isAmplitudeMode ? amplitudeTaskQuery.isFetching : detailQuery.isFetching;
  const task = detailData?.task;

  const handleSearch = useCallback(() => {
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const tableDataSource = isAmplitudeMode
    ? amplitudeLinesQuery.data?.items ?? []
    : listQuery.data?.items ?? [];
  const tableTotal = isAmplitudeMode ? amplitudeLinesQuery.data?.total ?? 0 : listQuery.data?.total ?? 0;
  const tableLoading = isAmplitudeMode ? amplitudeLinesQuery.isFetching : listQuery.isFetching;

  return (
    <div className="admin-lightning-backfill-pane">
      {isAmplitudeMode && (
        <div className="admin-filter-bar">
          <Form layout="inline" onFinish={handleSearch}>
            <Form.Item label="线路" style={{ marginBottom: 0 }}>
              <Input
                allowClear
                placeholder="按线路编号/名称筛选"
                style={{ width: 240 }}
                value={keyword}
                onChange={(event) => setKeyword(event.target.value)}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" htmlType="submit">
                查询
              </Button>
            </Form.Item>
          </Form>
        </div>
      )}

      {!isAmplitudeMode && (
        <div className="admin-filter-bar">
          <Form layout="inline" onFinish={handleSearch}>
            <Form.Item label="线路">
              <Select
                allowClear
                showSearch
                optionFilterProp="label"
                placeholder="选择线路"
                style={{ width: 240 }}
                value={lineId ?? undefined}
                onChange={(value: string | undefined) => {
                  setLineId(value ?? null);
                  handleSearch();
                }}
                options={(linesQuery.data?.items ?? []).map((line: LineSummary) => ({
                  label: `${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`,
                  value: line.id,
                }))}
              />
            </Form.Item>
            <Form.Item label="回填时间">
              <DatePicker.RangePicker
                allowClear
                value={dateRange ?? undefined}
                onChange={(dates) => {
                  setDateRange(dates && dates[0] && dates[1] ? [dates[0], dates[1]] : null);
                  handleSearch();
                }}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Space size={4}>
                <Button type="primary" htmlType="submit">
                  查询
                </Button>
              </Space>
            </Form.Item>
          </Form>
        </div>
      )}

      <div
        ref={tableScrollAnchorRef}
        className="admin-lightning-backfill-table-view flex-1 min-h-0"
        style={{ "--admin-lightning-backfill-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
      >
        <Table<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>
          rowKey={(row) => {
            if (isAmplitudeMode && "line_id" in row) {
              return row.line_id;
            }
            return (row as LightningCurrentBackfillTaskSummary).id;
          }}
          columns={isAmplitudeMode ? (amplitudeColumns as ColumnsType<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>) : (taskColumns as ColumnsType<LightningCurrentBackfillTaskSummary | LightningAmplitudeBackfillLine>)}
          dataSource={tableDataSource}
          loading={tableLoading}
          tableLayout="fixed"
          scroll={{ x: 900, y: tableScrollY }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: tableTotal,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: () => `共 ${tableTotal} 条`,
            hideOnSinglePage: false,
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={isAmplitudeMode ? "该幅值尚未被任何线路回填使用。" : "未找到回填记录。"}
              />
            ),
          }}
        />
      </div>

      <Drawer
        title={
          isAmplitudeMode
            ? (amplitudeLineTarget?.lineName ? `回填明细 - ${amplitudeLineTarget.lineName}` : "回填明细")
            : "回填任务详情"
        }
        open={isAmplitudeMode ? !!amplitudeLineTarget : detailOpen}
        onClose={isAmplitudeMode ? () => setAmplitudeLineTarget(null) : closeDetail}
        width={920}
        destroyOnHidden
      >
          {(detailLoading && !task) ? (
            <AdminPageLoading minHeightClassName="min-h-[240px]" />
          ) : task ? (
            <Space direction="vertical" size={16} className="w-full">
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="线路">
                  {task.line_name || "-"}
                </Descriptions.Item>
                <Descriptions.Item label="回填时间">
                  {formatDateTime(task.prepared_at)}
                </Descriptions.Item>
                <Descriptions.Item label="操作人">
                  {task.prepared_by || "-"}
                </Descriptions.Item>
                <Descriptions.Item label="采样数">
                  {task.sampled_event_count}
                </Descriptions.Item>
                <Descriptions.Item label="幅值a (kA)">
                  {formatNumber(task.current_a, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="幅值b (kA)">
                  {formatNumber(task.current_b, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="峰值max (kA)">
                  {formatNumber(task.peak_max, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="峰值min (kA)">
                  {formatNumber(task.peak_min, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="更新杆塔数">
                  {task.updated_tower_count}
                </Descriptions.Item>
                <Descriptions.Item label="新建杆塔数">
                  {task.created_profile_count}
                </Descriptions.Item>
                {task.warnings.length > 0 && (
                  <Descriptions.Item label="警告" span={2}>
                    <Space direction="vertical" size={2}>
                      {task.warnings.map((warn, index) => (
                        <Typography.Text key={index} type="warning">
                          {warn}
                        </Typography.Text>
                      ))}
                    </Space>
                  </Descriptions.Item>
                )}
              </Descriptions>

              <div>
                <Typography.Title level={5}>杆塔回填明细</Typography.Title>
                <Table<LightningCurrentBackfillTowerDetail>
                  rowKey="tower_id"
                  columns={towerColumns}
                  dataSource={detailData?.towers ?? []}
                  loading={detailFetching}
                  size="small"
                  tableLayout="fixed"
                  scroll={{ x: 860 }}
                  pagination={false}
                  locale={{
                    emptyText: (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description="暂无杆塔明细。"
                      />
                    ),
                  }}
                />
              </div>
            </Space>
          ) : (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="加载失败或任务不存在"
            />
          )}
      </Drawer>
    </div>
  );
}
