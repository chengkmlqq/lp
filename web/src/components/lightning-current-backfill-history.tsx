"use client";

import { useQuery } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import {
  Button,
  DatePicker,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import dayjs from "dayjs";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { readApiError } from "@/lib/api";
import type {
  LineListResponse,
  LineSummary,
  LightningCurrentBackfillTaskDetail,
  LightningCurrentBackfillTaskListResponse,
  LightningCurrentBackfillTaskSummary,
  LightningCurrentBackfillTowerDetail,
} from "@/types/auth";

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

export function LightningCurrentBackfillHistoryTable() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();

  const [lineId, setLineId] = useState<string | null>(null);
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailTaskId, setDetailTaskId] = useState<string | null>(null);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");

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
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentBackfillTaskListResponse;
    },
  });

  const linesQuery = useQuery<LineListResponse>({
    queryKey: ["lines"],
    enabled: !!user && canRead,
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
    enabled: !!user && canRead && !!detailTaskId && detailOpen,
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

  const columns = useMemo<ColumnsType<LightningCurrentBackfillTaskSummary>>(
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

  const task = detailQuery.data?.task;

  const handleSearch = useCallback(() => {
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
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
              <Button type="primary" onClick={handleSearch}>
                查询
              </Button>
              <Button
                onClick={() => {
                  setLineId(null);
                  setDateRange(null);
                  setPagination((prev) => ({ ...prev, current: 1 }));
                }}
              >
                重置
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </div>

      <div className="flex-1 min-h-0">
        <Table<LightningCurrentBackfillTaskSummary>
          rowKey="id"
          columns={columns}
          dataSource={listQuery.data?.items ?? []}
          loading={listQuery.isFetching}
          tableLayout="fixed"
          scroll={{ x: 900 }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: listQuery.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50, 100],
            showTotal: () => `共 ${listQuery.data?.total ?? 0} 条`,
            hideOnSinglePage: false,
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="未找到回填记录。"
              />
            ),
          }}
        />
      </div>

      <Drawer
        title="回填任务详情"
        open={detailOpen}
        onClose={closeDetail}
        width={920}
        destroyOnClose
      >
        {detailQuery.isLoading && !task ? (
          <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[240px]" />
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
                dataSource={detailQuery.data?.towers ?? []}
                loading={detailQuery.isFetching}
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
