"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Empty, Space, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { ElevationApplyJobListResponse, ElevationApplyJobSummary } from "@/types/auth";

const ELEVATION_HISTORY_MIN_SCROLL_Y = 180;
const ELEVATION_HISTORY_ESTIMATED_HEADER_HEIGHT = 56;
const ELEVATION_HISTORY_ESTIMATED_PAGINATION_HEIGHT = 64;
const ELEVATION_HISTORY_BOTTOM_GAP = 8;

type ElevationBackfillHistoryTableProps = {
  recordId: string;
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

function renderStatus(status: string) {
  if (status === "success") {
    return <Tag color="green">成功</Tag>;
  }
  if (status === "running") {
    return <Tag color="blue">处理中</Tag>;
  }
  if (status === "pending") {
    return <Tag color="orange">待处理</Tag>;
  }
  if (status === "failed") {
    return <Tag color="red">失败</Tag>;
  }
  return <Tag>{status}</Tag>;
}

function renderMode(mode: string) {
  if (mode === "fill_null_only") {
    return <Tag color="default">仅填空</Tag>;
  }
  if (mode === "overwrite_all") {
    return <Tag color="purple">全部覆盖</Tag>;
  }
  return <Tag>{mode}</Tag>;
}

export function ElevationBackfillHistoryTable({
  recordId,
}: ElevationBackfillHistoryTableProps) {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(ELEVATION_HISTORY_MIN_SCROLL_Y);

  const canRead = hasPermission("elevation.read") || hasPermission("elevation.manage");

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const anchorHeight = anchor.getBoundingClientRect().height;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? ELEVATION_HISTORY_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? ELEVATION_HISTORY_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - ELEVATION_HISTORY_BOTTOM_GAP);
    const clampedHeight = Math.max(ELEVATION_HISTORY_MIN_SCROLL_Y, nextHeight);
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
  }, [updateTableScrollHeight, pagination.current, pagination.pageSize]);

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
    params.set("limit", String(pagination.pageSize));
    params.set("offset", String((pagination.current - 1) * pagination.pageSize));
    return `/api/v1/elevation/records/${recordId}/jobs?${params.toString()}`;
  }, [recordId, pagination.current, pagination.pageSize]);

  const listQuery = useQuery<ElevationApplyJobListResponse>({
    queryKey: [listPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationApplyJobListResponse;
    },
  });

  const columns = useMemo<ColumnsType<ElevationApplyJobSummary>>(
    () => [
      {
        title: "回填时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
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
        title: "模式",
        dataIndex: "mode",
        width: 100,
        render: (value: string) => renderMode(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 100,
        render: (value: string) => renderStatus(value),
      },
      {
        title: "总杆塔",
        dataIndex: "total_tower_count",
        width: 90,
        render: (value: number) => value ?? 0,
      },
      {
        title: "更新杆塔",
        dataIndex: "updated_tower_count",
        width: 100,
        render: (value: number) => value ?? 0,
      },
      {
        title: "跳过",
        dataIndex: "skipped_tower_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: "缺坐标",
        dataIndex: "missing_geo_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: "未命中",
        dataIndex: "unmatched_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: "操作人",
        dataIndex: "create_user",
        width: 100,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      {
        title: "错误信息",
        dataIndex: "error_message",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string | null) => {
          if (!value) {
            return <Typography.Text type="secondary">-</Typography.Text>;
          }
          return <Typography.Text type="danger">{value}</Typography.Text>;
        },
      },
    ],
    [],
  );

  if (initializing) {
    return null;
  }

  if (!user) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="请先登录后再访问回填记录。"
      />
    );
  }

  if (!canRead) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无权限查看回填记录。"
      />
    );
  }

  return (
    <div
      ref={tableScrollAnchorRef}
      className="flex min-h-0 flex-1 flex-col"
      style={{ minHeight: ELEVATION_HISTORY_MIN_SCROLL_Y }}
    >
      <Space style={{ marginBottom: 8 }}>
        <Typography.Text type="secondary">
          共 {listQuery.data?.total ?? 0} 条回填记录
        </Typography.Text>
      </Space>
      <Table<ElevationApplyJobSummary>
        rowKey="id"
        size="small"
        loading={listQuery.isFetching}
        dataSource={listQuery.data?.items ?? []}
        columns={columns}
        tableLayout="fixed"
        scroll={{ y: tableScrollY }}
        pagination={{
          current: pagination.current,
          pageSize: pagination.pageSize,
          total: listQuery.data?.total ?? 0,
          showSizeChanger: true,
          pageSizeOptions: [10, 20, 50],
          showTotal: (total) => `共 ${total} 条`,
          onChange: (page, pageSize) => {
            setPagination({ current: page, pageSize });
          },
        }}
        locale={{
          emptyText: (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无回填记录。"
            />
          ),
        }}
      />
    </div>
  );
}
