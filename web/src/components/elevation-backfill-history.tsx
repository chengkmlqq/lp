"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Button,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { SearchOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type {
  ElevationApplyJobListResponse,
  ElevationApplyJobSummary,
  ElevationApplyJobTowerAction,
  ElevationApplyJobTowerDetail,
  ElevationApplyJobTowerListResponse,
} from "@/types/auth";

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
    return <Tag color="green">{"成功"}</Tag>;
  }
  if (status === "running") {
    return <Tag color="blue">{"处理中"}</Tag>;
  }
  if (status === "pending") {
    return <Tag color="orange">{"待处理"}</Tag>;
  }
  if (status === "failed") {
    return <Tag color="red">{"失败"}</Tag>;
  }
  return <Tag>{status}</Tag>;
}

function renderMode(mode: string) {
  if (mode === "fill_null_only") {
    return <Tag color="default">{"仅填空"}</Tag>;
  }
  if (mode === "overwrite_all") {
    return <Tag color="purple">{"全部覆盖"}</Tag>;
  }
  return <Tag>{mode}</Tag>;
}

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

function renderTowerAction(action: ElevationApplyJobTowerAction) {
  if (action === "updated") {
    return <Tag color="green">{"已更新"}</Tag>;
  }
  if (action === "skipped") {
    return <Tag color="default">{"已跳过"}</Tag>;
  }
  if (action === "missing_geo") {
    return <Tag color="orange">{"缺坐标"}</Tag>;
  }
  if (action === "unmatched") {
    return <Tag color="red">{"未命中"}</Tag>;
  }
  return <Tag>{action}</Tag>;
}

export function ElevationBackfillHistoryTable({
  recordId,
}: ElevationBackfillHistoryTableProps) {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(ELEVATION_HISTORY_MIN_SCROLL_Y);

  // 回填任务 → 杆塔回填数据明细（抽屉）
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailJob, setDetailJob] = useState<ElevationApplyJobSummary | null>(null);
  const [towerPagination, setTowerPagination] = useState({ current: 1, pageSize: 20 });

  // 线路名称过滤（表单草稿值 + 已应用值，点击「查询」后走后端过滤）
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");

  const canRead = hasPermission("elevation.read") || hasPermission("elevation.manage");

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    // 与线路管理-列表页同一套算法：用「面板(.admin-elevation-backfill-pane)的 padding-box 底边」
    // 推导表体高度；面板底边若低于视口底边取其较小值，避免撑出整页纵向滚动条。2026-09-12 对齐
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-elevation-backfill-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? ELEVATION_HISTORY_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? ELEVATION_HISTORY_ESTIMATED_PAGINATION_HEIGHT;
    const containerBottom = Math.min(containerRect.bottom, document.documentElement.clientHeight);
    // 面板自身若已有纵向溢出（内容比面板高），把溢出量一并扣掉，避免面板内出现多余滚动条
    const paneOverflow = Math.max(0, (pane ? pane.scrollHeight - pane.clientHeight : 0));
    const available = containerBottom - containerPadBottom - anchorTop - ELEVATION_HISTORY_BOTTOM_GAP - paneOverflow;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
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
    const trimmedKeyword = keyword.trim();
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return `/api/v1/elevation/records/${recordId}/jobs?${params.toString()}`;
  }, [keyword, pagination.current, pagination.pageSize, recordId]);

  const handleSearch = useCallback(() => {
    setKeyword(keywordDraft.trim());
    setPagination((previous) => ({ ...previous, current: 1 }));
  }, [keywordDraft]);

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

  const detailTowersPath = useMemo(() => {
    if (!detailJob || !detailOpen) {
      return null;
    }
    const params = new URLSearchParams();
    params.set("limit", String(towerPagination.pageSize));
    params.set("offset", String((towerPagination.current - 1) * towerPagination.pageSize));
    return `/api/v1/elevation/jobs/${detailJob.id}/towers?${params.toString()}`;
  }, [detailJob, detailOpen, towerPagination.current, towerPagination.pageSize]);

  const detailTowersQuery = useQuery<ElevationApplyJobTowerListResponse>({
    queryKey: ["elevation", "job-towers", detailJob?.id ?? "", towerPagination.current, towerPagination.pageSize],
    enabled: !!user && canRead && !!detailJob && !!detailOpen && !!detailTowersPath,
    queryFn: async () => {
      const response = await fetchWithAuth(detailTowersPath!);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ElevationApplyJobTowerListResponse;
    },
  });

  const openDetail = useCallback((job: ElevationApplyJobSummary) => {
    setTowerPagination({ current: 1, pageSize: 20 });
    setDetailJob(job);
    setDetailOpen(true);
  }, []);

  const closeDetail = useCallback(() => {
    setDetailOpen(false);
    setDetailJob(null);
  }, []);

  const towerColumns = useMemo<ColumnsType<ElevationApplyJobTowerDetail>>(
    () => [
      {
        title: t("序号"),
        dataIndex: "seq_no",
        key: "seq_no",
        width: 60,
        render: (value: number | null) => value ?? "-",
      },
      {
        title: t("杆塔编号"),
        dataIndex: "tower_no",
        key: "tower_no",
        width: 120,
        render: (value: string | null, row) => value || row.tower_id || "-",
      },
      {
        title: t("经度"),
        dataIndex: "longitude",
        key: "longitude",
        width: 110,
        render: (value: number | null) => formatCoordinate(value),
      },
      {
        title: t("纬度"),
        dataIndex: "latitude",
        key: "latitude",
        width: 110,
        render: (value: number | null) => formatCoordinate(value),
      },
      {
        title: t("回填结果"),
        dataIndex: "action",
        key: "action",
        width: 90,
        render: (value: ElevationApplyJobTowerAction) => renderTowerAction(value),
      },
      {
        title: t("回填前海拔(m)"),
        dataIndex: "altitude_before_m",
        key: "altitude_before_m",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填后海拔(m)"),
        dataIndex: "altitude_after_m",
        key: "altitude_after_m",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填前倾角1(°)"),
        dataIndex: "slope_1_before",
        key: "slope_1_before",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填后倾角1(°)"),
        dataIndex: "slope_1_after",
        key: "slope_1_after",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填前倾角2(°)"),
        dataIndex: "slope_2_before",
        key: "slope_2_before",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
      {
        title: t("回填后倾角2(°)"),
        dataIndex: "slope_2_after",
        key: "slope_2_after",
        width: 110,
        render: (value: number | null) => formatNumber(value, 3),
      },
    ],
    [],
  );

  const columns = useMemo<ColumnsType<ElevationApplyJobSummary>>(
    () => [
      {
        title: t("线路名称"),
        dataIndex: "line_name",
        width: 180,
        ellipsis: { showTitle: true },
        render: (value: string | null) => value || "-",
      },
      {
        title: t("状态"),
        dataIndex: "status",
        width: 100,
        render: (value: string) => renderStatus(value),
      },
      {
        title: t("回填时间"),
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: t("总杆塔"),
        dataIndex: "total_tower_count",
        width: 90,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("更新杆塔"),
        dataIndex: "updated_tower_count",
        width: 100,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("跳过"),
        dataIndex: "skipped_tower_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("缺坐标"),
        dataIndex: "missing_geo_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("未命中"),
        dataIndex: "unmatched_count",
        width: 80,
        render: (value: number) => value ?? 0,
      },
      {
        title: t("操作人"),
        dataIndex: "create_user",
        width: 140,
        ellipsis: true,
        render: (value: string | null, row: ElevationApplyJobSummary) => row.create_user_name || value || "-",
      },
      {
        title: t("操作"),
        key: "actions",
        width: 90,
        render: (_: unknown, row) => (
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => openDetail(row)}
          >
            查看明细
          </Button>
        ),
      },
    ],
    [openDetail],
  );

  if (initializing) {
    return null;
  }

  if (!user) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("请先登录后再访问回填记录。")}
      />
    );
  }

  if (!canRead) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("暂无权限查看回填记录。")}
      />
    );
  }

  return (
    <div className="admin-elevation-backfill-pane">
      {/* 线路名称过滤 + 查询（点击查询后走后端 keyword 过滤） */}
      <div className="admin-filter-bar">
        <Form layout="inline" onFinish={handleSearch}>
          <Form.Item label={t("线路名称")} style={{ marginBottom: 0 }}>
            <Input
              allowClear
              placeholder={t("输入线路名称/编号")}
              style={{ width: 280 }}
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
        </Form>
      </div>

      {/* 表格自适应高度区域：动态计算 body 滚动高度，分页固定表格右下角 */}
      <div
        ref={tableScrollAnchorRef}
        className="admin-elevation-backfill-table-view flex-1 min-h-0"
        style={{ "--admin-elevation-backfill-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
      >
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
            position: ["bottomRight"],
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={t("暂无回填记录。")}
              />
            ),
          }}
        />
      </div>

      {/* 回填任务 → 杆塔回填数据明细 */}
      <Drawer
        title={detailJob
          ? `回填任务明细 - ${[detailJob.line_code, detailJob.line_name].filter(Boolean).join(" ")}`
          : "回填任务明细"}
        open={detailOpen}
        onClose={closeDetail}
        width={1120}
        destroyOnHidden
      >
        {detailJob && (
          <Space direction="vertical" size={16} style={{ width: "100%" }}>
            <Descriptions bordered size="small" column={3}>
              <Descriptions.Item label={t("线路")}>
                {[detailJob.line_code, detailJob.line_name].filter(Boolean).join(" ") || "-"}
              </Descriptions.Item>
              <Descriptions.Item label={t("回填时间")}>
                {formatDateTime(detailJob.create_date)}
              </Descriptions.Item>
              <Descriptions.Item label={t("完成时间")}>
                {formatDateTime(detailJob.finished_at)}
              </Descriptions.Item>
              <Descriptions.Item label={t("模式")}>
                {renderMode(detailJob.mode)}
              </Descriptions.Item>
              <Descriptions.Item label={t("状态")}>
                {renderStatus(detailJob.status)}
              </Descriptions.Item>
              <Descriptions.Item label={t("操作人")}>
                {detailJob.create_user_name || detailJob.create_user || "-"}
              </Descriptions.Item>
              <Descriptions.Item label={t("总杆塔")}>
                {detailJob.total_tower_count ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label={t("更新杆塔")}>
                {detailJob.updated_tower_count ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label={t("跳过")}>
                {detailJob.skipped_tower_count ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label={t("缺坐标")}>
                {detailJob.missing_geo_count ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label={t("未命中")}>
                {detailJob.unmatched_count ?? 0}
              </Descriptions.Item>
              <Descriptions.Item label={t("任务ID")}>
                {detailJob.task_id || "-"}
              </Descriptions.Item>
              {detailJob.error_message && (
                <Descriptions.Item label={t("错误/警告")} span={3}>
                  <Typography.Text type={detailJob.status === "failed" ? "danger" : "warning"}>
                    {detailJob.error_message}
                  </Typography.Text>
                </Descriptions.Item>
              )}
            </Descriptions>

            <div>
              <Typography.Title level={5} style={{ marginTop: 0 }}>
                杆塔回填数据明细
              </Typography.Title>
              <Table<ElevationApplyJobTowerDetail>
                rowKey="id"
                columns={towerColumns}
                dataSource={detailTowersQuery.data?.items ?? []}
                loading={detailTowersQuery.isFetching}
                size="small"
                tableLayout="fixed"
                scroll={{ x: 1160 }}
                pagination={{
                  current: towerPagination.current,
                  pageSize: towerPagination.pageSize,
                  total: detailTowersQuery.data?.total ?? 0,
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  showTotal: (total) => `共 ${total} 条`,
                  onChange: (page, pageSize) => {
                    setTowerPagination({ current: page, pageSize });
                  },
                }}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        detailJob.status === "success"
                          ? "该任务暂无杆塔明细（历史任务未保存逐塔快照，重新回填后即可查看）。"
                          : "任务尚未生成杆塔明细，处理完成后可查看。"
                      }
                    />
                  ),
                }}
              />
            </div>
          </Space>
        )}
      </Drawer>
    </div>
  );
}
