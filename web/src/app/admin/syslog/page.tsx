"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, Empty, Form, Input, Row, Select, Space, Spin, Table, Tag, Typography, type CardProps } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { CSSProperties, ComponentType, RefAttributes } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type { AuditLogItem, AuditLogListResponse } from "@/types/auth";

const PAGE_SIZE = 50;
const SYSLOG_TABLE_MIN_SCROLL_Y = 180;
const SYSLOG_TABLE_VIEWPORT_GAP = 40;
const SYSLOG_TABLE_FALLBACK_RESERVE = 220;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

/** 动作编码 → 中文显示名映射 */
const ACTION_LABEL_MAP: Record<string, string> = {
  "auth.login": "登录",
  "auth.login_failed": "登录失败",
  "auth.logout": "登出",
  "user.create": "创建用户",
  "user.update": "更新用户",
  "user.delete": "删除用户",
  "user.password.reset": "重置密码",
  "user.roles.replace": "替换用户角色",
  "role.create": "创建角色",
  "role.update": "更新角色",
  "role.delete": "删除角色",
  "role.menus.replace": "替换角色菜单",
  "menu.create": "创建菜单",
  "menu.update": "更新菜单",
  "menu.delete": "删除菜单",
  "menu.seed_defaults": "初始化默认菜单",
  "system_param.create": "创建系统参数",
  "system_param.update": "更新系统参数",
  "system_param.delete": "删除系统参数",
  "file.mkdir": "创建目录",
  "file.upload": "上传文件",
  "file.rename": "重命名文件",
  "file.move": "移动文件",
  "file.download": "下载文件",
  "file.download_zip": "下载目录压缩包",
  "file.delete": "删除文件",
};

function getActionLabel(action: string): string {
  return ACTION_LABEL_MAP[action] || action;
}

type Filters = {
  action: string;
  user_id: string;
};

const EMPTY_FILTERS: Filters = {
  action: "",
  user_id: "",
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "-";
  }
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hour = String(date.getHours()).padStart(2, "0");
  const minute = String(date.getMinutes()).padStart(2, "0");
  const second = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
}

export default function AdminSyslogPage() {
  const queryClient = useQueryClient();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();

  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [draftFilters, setDraftFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [tableScrollY, setTableScrollY] = useState(SYSLOG_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedLogs, setAllLoadedLogs] = useState<AuditLogItem[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [actionOptions, setActionOptions] = useState<{ label: string; value: string }[]>([]);

  const canRead = hasPermission("menu.read") || hasPermission("menu.manage");

  const handleActionChange = (value: string) => {
    setDraftFilters((prev) => ({ ...prev, action: value }));
  };

  const handleUserIdChange = (value: string) => {
    setDraftFilters((prev) => ({ ...prev, user_id: value }));
  };

  const handleSearch = () => {
    setFilters({
      action: draftFilters.action.trim(),
      user_id: draftFilters.user_id.trim(),
    });
    setOffset(0);
    setCardViewPage(1);
    setAllLoadedLogs([]);
    void queryClient.refetchQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/admin/audit-logs"),
    });
  };

  const logsPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(pageSize));
    params.set("offset", String(offset));
    if (filters.action.trim()) {
      params.set("action", filters.action.trim());
    }
    if (filters.user_id.trim()) {
      params.set("user_id", filters.user_id.trim());
    }
    return `/api/v1/admin/audit-logs?${params.toString()}`;
  }, [filters.action, filters.user_id, offset, pageSize]);

  const loadLogs = useCallback(async () => {
    const response = await fetchWithAuth(logsPath);
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    return (await response.json()) as AuditLogListResponse;
  }, [fetchWithAuth, logsPath]);

  const logsQuery = useQuery({
    queryKey: [logsPath],
    queryFn: loadLogs,
    enabled: !!user && canRead,
  });

  // Fetch action options for the Select dropdown
  const actionsPath = "/api/v1/admin/audit-logs/actions";
  const loadActions = useCallback(async () => {
    const response = await fetchWithAuth(actionsPath);
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }
    return (await response.json()) as { items: string[] };
  }, [fetchWithAuth]);

  const actionsQuery = useQuery({
    queryKey: [actionsPath],
    queryFn: loadActions,
    enabled: !!user && canRead,
  });

  // Build action options when actions data loads
  useEffect(() => {
    if (!actionsQuery.data) return;
    const items = actionsQuery.data.items.map((action: string) => ({
      label: getActionLabel(action),
      value: action,
    }));
    setActionOptions(items);
  }, [actionsQuery.data]);

  useTopicSubscription(
    "admin.audit_logs",
    useCallback(() => {
      void queryClient.invalidateQueries({ queryKey: [logsPath] });
    }, [logsPath, queryClient]),
  );

  const logs = useMemo(() => logsQuery.data?.items ?? [], [logsQuery.data?.items]);
  const total = logsQuery.data?.total ?? 0;
  const queryError = logsQuery.error instanceof Error ? logsQuery.error.message : "";
  const anyError = error || queryError;
  const currentPage = Math.floor(offset / pageSize) + 1;

  useToastFeedback({
    errorMessage: anyError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  // Update allLoadedLogs when logs data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || logsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedLogs(() => logs);
      } else {
        setAllLoadedLogs((prev) => {
          if (logs.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(l => l.id));
          const newLogs = logs.filter(l => !existingIds.has(l.id));
          return [...prev, ...newLogs];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [logs, logsQuery.isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || logsQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const loadedCount = allLoadedLogs.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setOffset((prev) => prev + pageSize);
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, logsQuery.isLoading, total, allLoadedLogs.length, pageSize]);

  // Reset card view state when filters change
  useEffect(() => {
    const frameId = window.requestAnimationFrame(() => {
      setCardViewPage(1);
      setAllLoadedLogs([]);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [filters.action, filters.user_id]);

  const columns = useMemo<ColumnsType<AuditLogItem>>(
    () => [
      {
        title: "时间",
        dataIndex: "created_at",
        key: "created_at",
        width: 220,
        render: (value: string) => (
          <Typography.Text type="secondary" className="text-xs">
            {formatDate(value)}
          </Typography.Text>
        ),
      },
      {
        title: "用户",
        key: "user",
        width: 260,
        render: (_value, record) => (
          <span>{record.username ?? record.user_id ?? "-"}</span>
        ),
      },
      {
        title: "动作",
        dataIndex: "action",
        key: "action",
        width: 220,
        render: (value: string) => <Tag>{getActionLabel(value)}</Tag>,
      },
      {
        title: "入参",
        dataIndex: "detail",
        key: "detail",
        render: (value: string | null) => (
          <Typography.Text type="secondary">{value || "-"}</Typography.Text>
        ),
      },
      {
        title: "出参",
        dataIndex: "output",
        key: "output",
        render: (value: string | null) => (
          <Typography.Text type="secondary">{value || "-"}</Typography.Text>
        ),
      },
    ],
    [],
  );

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const anchorTop = anchor.getBoundingClientRect().top;
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - SYSLOG_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? SYSLOG_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - SYSLOG_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(SYSLOG_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    const frameId = window.requestAnimationFrame(updateTableScrollY);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [logs.length, logsQuery.isFetching, total, updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }

    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollY]);

  const renderLogCard = (log: AuditLogItem) => (
    <AntCard
      key={log.id}
      className="admin-syslog-log-card"
      size="small"
      title={
        <Space className="min-w-0" size={8}>
          <Typography.Text strong>{log.username ?? log.user_id ?? "-"}</Typography.Text>
          <Tag>{getActionLabel(log.action)}</Tag>
        </Space>
      }
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <div className="admin-syslog-log-card-field">
          <Typography.Text type="secondary">时间</Typography.Text>
          <Typography.Text className="text-xs">
            {formatDate(log.created_at)}
          </Typography.Text>
        </div>
        <div className="admin-syslog-log-card-field">
          <Typography.Text type="secondary">用户 ID</Typography.Text>
          <Typography.Text code type="secondary" ellipsis={{ tooltip: log.user_id ?? "-" }}>
            {log.user_id ?? "-"}
          </Typography.Text>
        </div>
        {log.detail && (
          <div className="admin-syslog-log-card-field">
            <Typography.Text type="secondary">入参</Typography.Text>
            <Typography.Text type="secondary" ellipsis={{ tooltip: log.detail }}>
              {log.detail}
            </Typography.Text>
          </div>
        )}
        {log.output && (
          <div className="admin-syslog-log-card-field">
            <Typography.Text type="secondary">出参</Typography.Text>
            <Typography.Text type="secondary" ellipsis={{ tooltip: log.output }}>
              {log.output}
            </Typography.Text>
          </div>
        )}
      </Space>
    </AntCard>
  );

  if (initializing) {
    return (
      <div className="flex min-h-[240px] items-center justify-center">
        <Spin tip="初始化中..." />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问系统日志页面。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `menu.read`）。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  const filterBar = (
    <div className="admin-filter-bar">
      <Form layout="inline">
        <Form.Item label="动作" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
          <Select
            allowClear
            showSearch
            placeholder="选择动作筛选"
            value={draftFilters.action || undefined}
            onChange={handleActionChange}
            onClear={() => handleActionChange("")}
            options={actionOptions}
            style={{ minWidth: 200 }}
            filterOption={(input, option) =>
              (option?.label ?? "").toLowerCase().includes(input.toLowerCase()) ||
              (option?.value ?? "").toLowerCase().includes(input.toLowerCase())
            }
          />
        </Form.Item>
        <Form.Item label="用户" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
          <Input
            allowClear
            placeholder="按用户ID或用户名搜索"
            value={draftFilters.user_id}
            onChange={(event) => handleUserIdChange(event.target.value)}
            onPressEnter={handleSearch}
          />
        </Form.Item>
        <Form.Item style={{ marginBottom: 0 }}>
          <Button
            htmlType="button"
            icon={<SearchOutlined />}
            onClick={handleSearch}
            className="admin-search-btn"
          >
            查询
          </Button>
        </Form.Item>
      </Form>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-syslog-page-card"
        title="系统日志"
      >
        {filterBar}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-syslog-table-anchor"
            style={{ "--admin-syslog-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<AuditLogItem>
              rowKey={(record) => String(record.id)}
              columns={columns}
              dataSource={logs}
              loading={logsQuery.isLoading}
              tableLayout="fixed"
              pagination={{
                current: currentPage,
                pageSize,
                total: Math.max(total, 1),
                onChange: (page, nextPageSize) => {
                  setPageSize(nextPageSize);
                  setOffset((page - 1) * nextPageSize);
                },
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${total} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
              }}
              locale={{
                emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到符合筛选条件的日志记录。" />,
              }}
              scroll={{ y: tableScrollY }}
            />
          </div>
        ) : (
          <div className="admin-syslog-card-view">
            {logsQuery.isLoading && allLoadedLogs.length === 0 ? (
              <div className="admin-syslog-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedLogs.length === 0 ? (
              <div className="admin-syslog-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的日志记录。"
                />
              </div>
            ) : (
              <div className="admin-syslog-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedLogs.map((log) => (
                    <Col key={log.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderLogCard(log)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedLogs.length >= total && allLoadedLogs.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedLogs.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>
    </div>
  );
}
