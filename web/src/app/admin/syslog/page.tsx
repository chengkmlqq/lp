"use client";

import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Col, Empty, Form, Input, Row, Select, Space, Spin, Table, Tabs, Tag, Typography, type CardProps } from "antd";
import { SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { CSSProperties, ComponentType, RefAttributes } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { ModoPagination, modoTablePagination } from "@/components/biz/modo-pagination";
import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { ApiError, readApiError } from "@/lib/api";
import { measureTableScrollY } from "@/lib/table-scroll-y";
import type { AuditLogItem, AuditLogListResponse } from "@/types/auth";

const PAGE_SIZE = 20;
const SYSLOG_TABLE_MIN_SCROLL_Y = 180;
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
  "fl_analysis.job.create": "创建防雷任务",
  "fl_analysis.job.start": "启动防雷任务",
  "fl_analysis.job.cancel": "取消防雷任务",
  "fl_analysis.job.delete": "删除防雷任务",
  "lightning.amplitude.import": "导入雷电流幅值",
  "lightning.amplitude.delete": "删除雷电流幅值",
  "lightning.distribution.import": "导入地闪密度",
  "lightning.distribution.delete": "删除地闪密度",
  "scheduled_task.run": "定时任务执行",
  "scheduled_task.run_failed": "定时任务执行失败",
};

function getActionLabel(action: string, t: (s: string) => string): string {
  const label = ACTION_LABEL_MAP[action];
  return label ? t(label) : action;
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
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const isMobile = useMobileDetection();

  const [offset, setOffset] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const [draftFilters, setDraftFilters] = useState<Filters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  // 手动刷新计数：每次点击「查询」都自增并作为 queryKey 的一部分，强制走一次接口，
  // 即使筛选条件/分页均未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [tableScrollY, setTableScrollY] = useState(SYSLOG_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
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
    // 每次点击「查询」都强制触发一次接口请求：searchNonce 作为 queryKey 的一部分自增，
    // 即便筛选条件/分页均未变化（旧实现仅 refetchQueries，目标 key 已被 react-query 缓存时
    // 会短路不发请求）也会产生新 key 重新拉取；筛选条件照常提交并回到第 1 页。
    // 卡片视图的累积列表不再在查询开始时清空，刷新期间旧卡片保持可见（叠加 loading
    // 遮罩），待接口返回后再整体替换，避免列表闪空。
    setFilters({
      action: draftFilters.action.trim(),
      user_id: draftFilters.user_id.trim(),
    });
    setOffset(0);
    setSearchNonce((n) => n + 1);
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
    queryKey: [logsPath, searchNonce],
    queryFn: loadLogs,
    enabled: !!user && canRead,
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询/翻页时列表闪空
    placeholderData: (previousData) => previousData,
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
      label: getActionLabel(action, t),
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
  const queryError = useMemo<ApiError | null>(() => logsQuery.error instanceof Error ? new ApiError(logsQuery.error.message) : null, [logsQuery.error]);
  const apiError = error || queryError;
  const currentPage = Math.floor(offset / pageSize) + 1;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

  const columns = useMemo<ColumnsType<AuditLogItem>>(
    () => [
      {
        title: t("时间"),
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
        title: t("用户"),
        key: "user",
        width: 260,
        render: (_value, record) => (
          <span>{record.username ?? record.user_id ?? "-"}</span>
        ),
      },
      {
        title: t("动作"),
        dataIndex: "action",
        key: "action",
        width: 220,
        render: (value: string) => <Tag>{getActionLabel(value, t)}</Tag>,
      },
      {
        title: t("入参"),
        dataIndex: "detail",
        key: "detail",
        render: (value: string | null) => (
          <Typography.Text type="secondary">{value || "-"}</Typography.Text>
        ),
      },
      {
        title: t("出参"),
        dataIndex: "output",
        key: "output",
        render: (value: string | null) => (
          <Typography.Text type="secondary">{value || "-"}</Typography.Text>
        ),
      },
    ],
    [t],
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
    let nextHeight = Math.floor(window.innerHeight - anchorTop - SYSLOG_TABLE_FALLBACK_RESERVE);
    // 站点级样式（globals.css）把表格锚点拉伸为撑满白卡的 flex 列，旧公式
    // wrapper.height - body.height 会把拉伸空白误算成外围高度，导致表体被钳在
    // 最小值、未占满剩余空间就出现纵向滚动条；改用统一测量工具按实际
    // chrome（表头+分页+边框）与滚动容器底边计算，两种布局都稳定收敛
    const measuredHeight = measureTableScrollY(anchor);
    if (measuredHeight !== null) {
      nextHeight = measuredHeight;
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
        <div className="flex items-center gap-2 min-w-0">
          <Typography.Text strong ellipsis={{ tooltip: log.username ?? log.user_id ?? "-" }} className="flex-1 min-w-0">
            {log.username ?? log.user_id ?? "-"}
          </Typography.Text>
          <div className="flex flex-shrink-0 items-center gap-2">
            <Tag>{getActionLabel(log.action, t)}</Tag>
          </div>
        </div>
      }
    >
      <Space direction="vertical" size={10} style={{ width: "100%" }}>
        <div className="admin-syslog-log-card-field">
          <Typography.Text type="secondary">{t("时间")}</Typography.Text>
          <Typography.Text className="text-xs">
            {formatDate(log.created_at)}
          </Typography.Text>
        </div>
        <div className="admin-syslog-log-card-field">
          <Typography.Text type="secondary">{t("用户 ID")}</Typography.Text>
          <Typography.Text code type="secondary" ellipsis={{ tooltip: log.user_id ?? "-" }}>
            {log.user_id ?? "-"}
          </Typography.Text>
        </div>
        {log.detail && (
          <div className="admin-syslog-log-card-field">
            <Typography.Text type="secondary">{t("入参")}</Typography.Text>
            <Typography.Text type="secondary" ellipsis={{ tooltip: log.detail }}>
              {log.detail}
            </Typography.Text>
          </div>
        )}
        {log.output && (
          <div className="admin-syslog-log-card-field">
            <Typography.Text type="secondary">{t("出参")}</Typography.Text>
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
        <Spin />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问系统日志页面。")}</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          {t("返回首页")}
        </Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `menu.read`）。")}</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          {t("返回首页")}
        </Link>
      </main>
    );
  }

  const filterBar = (
    <div className="admin-filter-bar">
      <Form layout="inline">
        <Form.Item label={t("动作")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
          <Select
            allowClear
            showSearch
            placeholder={t("选择动作筛选")}
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
        <Form.Item label={t("用户")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
          <Input
            allowClear
            placeholder={t("按用户ID或用户名搜索")}
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
            className="admin-search-btn" loading={logsQuery.isFetching}
          >
            {t("查询")}
          </Button>
        </Form.Item>
      </Form>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="modo-page-tabs"
        items={[
          {
            key: "list",
            label: <>{t("系统日志")}</>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="modo-page-card admin_syslog_list_pane">
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
                      loading={logsQuery.isFetching}
                      tableLayout="fixed"
                      pagination={modoTablePagination({
                        current: currentPage,
                        pageSize,
                        total: Math.max(total, 1),
                        onChange: (page, nextPageSize) => {
                          setPageSize(nextPageSize);
                          setOffset((page - 1) * nextPageSize);
                        },
                      })}
                      locale={{
                        emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("未找到符合筛选条件的日志记录。")} />,
                      }}
                      scroll={{ y: tableScrollY }}
                    />
                  </div>
                ) : (
                  <div className="admin-syslog-card-view">
                    {(logsQuery.isLoading || logsQuery.isFetching) && logs.length === 0 ? (
                      <div className="admin-syslog-card-view-state">
                        <Spin />
                      </div>
                    ) : logs.length === 0 ? (
                      <div className="admin-syslog-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("未找到符合筛选条件的日志记录。")}
                        />
                      </div>
                    ) : (
                      // 查询/加载期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据
                      <Spin spinning={logsQuery.isFetching}>
                        <div className="admin-syslog-card-view-content">
                          <Row gutter={[12, 12]}>
                            {logs.map((log) => (
                              <Col key={log.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                                {renderLogCard(log)}
                              </Col>
                            ))}
                          </Row>
                        </div>
                      </Spin>
                    )}
                    <ModoPagination
                      current={currentPage}
                      pageSize={pageSize}
                      total={Math.max(total, 1)}
                      onChange={(page, nextPageSize) => {
                        setPageSize(nextPageSize);
                        setOffset((page - 1) * nextPageSize);
                      }}
                      style={{ flexShrink: 0, marginTop: "auto" }}
                    />
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}
