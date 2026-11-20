"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
} from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Steps,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TabsProps,
  type TableColumnsType,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { WindFarmCalcDetailView } from "@/components/wind-farm-calc-detail-view";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindFarmCalcCreateResponse,
  WindFarmCalcEngineInfo,
  WindFarmCalcJobListResponse,
  WindFarmCalcJobSummary,
  WindFarmCalcPrepBatchOptions,
} from "@/types/wind-farm-calc";
import { RISK_COLORS, RISK_LABELS } from "@/types/wind-farm-calc";

const { Text, Paragraph } = Typography;
const API_BASE = "/api/v1/wind-farm-calc";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

const RISK_COUNT_KEYS: Record<number, keyof WindFarmCalcJobSummary> = {
  1: "risk_I_count",
  2: "risk_II_count",
  3: "risk_III_count",
  4: "risk_IV_count",
};

type DetailTabData = {
  key: string;
  title: string;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function formatBytes(size: number | null | undefined): string {
  if (!size && size !== 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const WIND_TABLE_MIN_SCROLL_Y = 180;
const WIND_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const WIND_TABLE_BOTTOM_GAP = 8;

export default function WindFarmCalcListPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_farm_calc.read") || hasPermission("wind_farm_calc.manage");
  const canManage = hasPermission("wind_farm_calc.manage");

  const queryClient = useQueryClient();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");

  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [detailTabsData, setDetailTabsData] = useState<DetailTabData[]>([]);

  const [createOpen, setCreateOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [form] = Form.useForm<{ prep_batch_id: string; name: string }>();
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => setPage(1), [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-farm-calc", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    // 查询/翻页时保留上一份数据作占位，卡片/列表不清空，仅叠加 loading 遮罩，避免闪空。
    placeholderData: (previousData) => previousData,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (statusFilter) params.set("status", statusFilter);
      return getJson<WindFarmCalcJobListResponse>(`${API_BASE}?${params.toString()}`);
    },
    refetchInterval: (queryResult) => {
      const items = queryResult.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing") ? 4000 : false;
    },
  });

  const records = listQuery.data?.items ?? [];

  // 列表视图分页钉底（参考线路管理 pages/power-lines）：动态算表体高度，
  // 让分页条始终固定在页面右下角，表格体在剩余空间内滚动（不产生整页滚动条）。
  const [tableScrollY, setTableScrollY] = useState(WIND_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return WIND_TABLE_MIN_SCROLL_Y;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return WIND_TABLE_MIN_SCROLL_Y;
    }
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-lightning-distribution-list-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    // 分页器是卡片/列表共用的外置 ModoPagination，不在锚点内部；按面板取其实测高度，
    // 避免 anchor.querySelector(".ant-table-pagination") 落空后用 64px 回退而少算表体高度。
    const pagination = pane?.querySelector<HTMLElement>(".admin-list-view-pagination")
      ?? anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? WIND_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = pagination?.getBoundingClientRect().height ?? WIND_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available = containerRect.bottom - containerPadBottom - anchorTop - WIND_TABLE_BOTTOM_GAP;
    // 与故障分析页一致：分页钉在面板底部，预留 16px 上方间距 + 4px 余量（共 20px）。
    // available 已扣除面板底部 8px 余量，这里加回后再扣分页高度与 20px 间距，避免表格下方留白。
    const nextHeight = Math.floor(available - headerHeight - paginationHeight + WIND_TABLE_BOTTOM_GAP - 20);
    return Math.max(WIND_TABLE_MIN_SCROLL_Y, nextHeight);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => window.requestAnimationFrame(updateTableScrollHeight);
    window.addEventListener("resize", onViewportChange);
    return () => window.removeEventListener("resize", onViewportChange);
  }, [updateTableScrollHeight]);
  useEffect(() => {
    if (viewMode !== "list") {
      return;
    }
    setTableScrollY(updateTableScrollHeight());
    const raf = window.requestAnimationFrame(() => setTableScrollY(updateTableScrollHeight()));
    return () => window.cancelAnimationFrame(raf);
  }, [viewMode, records.length, updateTableScrollHeight]);


  // 引擎预检数据仍需保留：新建弹窗的「引擎预检」步骤是提交流程的一部分。
  const engineQuery = useQuery({
    queryKey: ["wind-farm-calc", "engine"],
    enabled: Boolean(user) && canRead,
    queryFn: () => getJson<WindFarmCalcEngineInfo>(`${API_BASE}/engine`),
  });

  const batchesQuery = useQuery({
    queryKey: ["wind-farm-calc", "prep-batches"],
    enabled: createOpen && Boolean(user) && canRead,
    queryFn: () => getJson<WindFarmCalcPrepBatchOptions>(`${API_BASE}/prep-batches`),
  });

  const refreshList = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-farm-calc"] });
  }, [queryClient]);

  const openDetail = useCallback((jobId: string, title: string) => {
    setDetailTabsData((previous) =>
      previous.some((tab) => tab.key === jobId) ? previous : [...previous, { key: jobId, title }],
    );
    setActiveTabKey(jobId);
  }, []);

  const closeDetailTab = useCallback(
    (key: string) => {
      const removedIndex = detailTabsData.findIndex((tab) => tab.key === key);
      const next = detailTabsData.filter((tab) => tab.key !== key);
      setDetailTabsData(next);
      if (activeTabKey === key) {
        const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
        setActiveTabKey(fallback);
      }
    },
    [activeTabKey, detailTabsData],
  );

  const handleTabsEdit = useCallback(
    (targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
      if (action !== "remove") {
        return;
      }
      closeDetailTab(String(targetKey));
    },
    [closeDetailTab],
  );

  const detailTabs = useMemo<NonNullable<TabsProps["items"]>>(
    () =>
      detailTabsData.map((tab) => ({
        key: tab.key,
        label: (
          <Tooltip title={tab.title}>
            <span>{tab.title.length > 14 ? `${tab.title.slice(0, 14)}...` : tab.title}</span>
          </Tooltip>
        ),
        closable: true,
        children: <WindFarmCalcDetailView jobId={tab.key} onClose={() => closeDetailTab(tab.key)} />,
      })),
    [closeDetailTab, detailTabsData],
  );

  const openCreate = useCallback(() => {
    setStep(0);
    setSelectedBatchId(undefined);
    form.resetFields();
    setCreateOpen(true);
  }, [form]);

  const selectedBatch = useMemo(
    () => batchesQuery.data?.items.find((item) => item.id === selectedBatchId),
    [batchesQuery.data, selectedBatchId],
  );

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    if (!values.prep_batch_id) {
      message.warning(t("请选择数据准备批次"));
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetchWithAuth(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prep_batch_id: values.prep_batch_id, name: values.name || "" }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindFarmCalcCreateResponse;
      message.success(t("已提交风电场计算任务"));
      setCreateOpen(false);
      refreshList();
      openDetail(result.job_id, (values.name || "").trim() || result.job_id);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [fetchWithAuth, form, message, openDetail, refreshList, t]);

  const handleCancel = useCallback(
    (record: WindFarmCalcJobSummary) => {
      modal.confirm({
        title: t("取消该计算任务？"),
        content: t("取消会终止正在运行的 Wine 进程组，已产生的结果不会保留。"),
        okText: t("取消任务"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}/cancel`, { method: "POST" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已发送取消请求"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const handleDelete = useCallback(
    (record: WindFarmCalcJobSummary) => {
      modal.confirm({
        title: t("删除该计算任务？"),
        content: t("仅删除任务记录与本地临时工作目录；对象存储中的原始输入输出仍可追溯。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("取消"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}`, { method: "DELETE" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已删除"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const columns = useMemo<TableColumnsType<WindFarmCalcJobSummary>>(
    () => [
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        width: 200,
        render: (_value, record) => (
          <Space direction="vertical" size={0}>
            <Button
              type="link"
              style={{ padding: 0, height: "auto" }}
              onClick={() => openDetail(record.id, record.name || record.id)}
            >
              {record.name || record.id}
            </Button>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("来源批次")}: {record.prep_batch_id.slice(0, 12)}…
            </Text>
          </Space>
        ),
      },
      { title: t("风机数"), dataIndex: "turbine_count", key: "turbine_count", width: 80 },
      {
        title: t("风险分布 I/II/III/IV"),
        key: "risk",
        width: 170,
        render: (_value, record) => (
          <Space size={2}>
            {[1, 2, 3, 4].map((level) => (
              <Tag key={level} color={RISK_COLORS[level]} style={{ marginInlineEnd: 0 }}>
                {RISK_LABELS[level]} {record[RISK_COUNT_KEYS[level]] as number}
              </Tag>
            ))}
          </Space>
        ),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        width: 170,
        render: (value: string, record) => {
          const meta = STATUS_META[value] ?? STATUS_META.pending;
          return (
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Tag color={meta.color}>{t(meta.label)}</Tag>
              {value === "processing" || value === "pending" ? (
                <Progress percent={record.progress} size="small" showInfo={false} />
              ) : null}
              {value === "failed" && record.error_message ? (
                <Text type="danger" style={{ fontSize: 12 }} ellipsis={{ tooltip: record.error_message }}>
                  {record.error_message}
                </Text>
              ) : null}
            </Space>
          );
        },
      },
      {
        title: t("耗时"),
        dataIndex: "duration_seconds",
        key: "duration_seconds",
        width: 90,
        render: (value: number | null) => formatDuration(value),
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        width: 150,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 160,
        fixed: "right",
        render: (_value, record) => (
          <ModoActionGroup
            actions={[
              {
                key: "detail",
                label: t("详情"),
                icon: <EyeOutlined />,
                onClick: () => openDetail(record.id, record.name || record.id),
              },
              {
                key: "export",
                label: t("导出 Excel"),
                icon: <DownloadOutlined />,
                visible: record.status === "completed",
                onClick: () =>
                  void downloadFileWithAuth(
                    `${API_BASE}/${record.id}/export`,
                    `${record.name || "wind-farm-calc"}-results.xlsx`,
                  ),
              },
              {
                key: "cancel",
                label: t("取消"),
                icon: <StopOutlined />,
                danger: true,
                visible: (record.status === "processing" || record.status === "pending") && canManage,
                onClick: () => handleCancel(record),
              },
              {
                key: "delete",
                label: t("删除"),
                icon: <DeleteOutlined />,
                danger: true,
                visible: canManage,
                onClick: () => handleDelete(record),
              },
            ]}
          />
        ),
      },
    ],
    [canManage, handleCancel, handleDelete, openDetail, t],
  );

  const paginationNode = (
    <ModoPagination
      current={page}
      pageSize={pageSize}
      total={listQuery.data?.total ?? 0}
      showSizeChanger
      pageSizeOptions={[10, 20, 50, 100]}
      onChange={(nextPage, nextSize) => {
        setPage(nextPage);
        if (nextSize && nextSize !== pageSize) {
          setPageSize(nextSize);
          setPage(1);
        }
      }}
      containerClassName="admin-list-view-pagination"
    />
  );

  const renderRecordCard = (record: WindFarmCalcJobSummary) => {
    const meta = STATUS_META[record.status] ?? STATUS_META.pending;
    return (
      <Card
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={() => openDetail(record.id, record.name || record.id)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Tooltip title={record.name || record.id}>
                <Text strong className="truncate min-w-0">
                  {record.name || record.id}
                </Text>
              </Tooltip>
              <Tag color={meta.color} style={{ marginInlineEnd: 0, flexShrink: 0 }}>
                {t(meta.label)}
              </Tag>
            </div>
          </div>

          <div className="flex flex-col gap-1 px-4 py-3">
            <Text type="secondary" className="text-xs truncate">
              {t("来源批次")}：{record.prep_batch_id.slice(0, 12)}…
            </Text>
            <Text type="secondary" className="text-xs">
              {t("风机数")}：{record.turbine_count}
            </Text>
            <Space size={2} wrap>
              {[1, 2, 3, 4].map((level) => (
                <Tag key={level} color={RISK_COLORS[level]} style={{ marginInlineEnd: 0 }}>
                  {RISK_LABELS[level]} {record[RISK_COUNT_KEYS[level]] as number}
                </Tag>
              ))}
            </Space>
            <Text type="secondary" className="text-xs">
              {t("耗时")}：{formatDuration(record.duration_seconds)} · {t("创建时间")}：{formatDateTime(record.create_date)}
            </Text>
            {record.status === "failed" && record.error_message ? (
              <Text type="danger" className="text-xs" ellipsis={{ tooltip: record.error_message }}>
                {record.error_message}
              </Text>
            ) : null}
          </div>

          <div className="admin-lightning-distribution-event-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {record.status === "processing" || record.status === "pending" ? (
              <Progress percent={record.progress} size="small" className="flex-1 max-w-40" />
            ) : (
              <div />
            )}
            <Space size="small" className="flex-wrap">
              <Tooltip title={t("详情")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openDetail(record.id, record.name || record.id);
                  }}
                />
              </Tooltip>
              {record.status === "completed" ? (
                <Tooltip title={t("导出 Excel")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<DownloadOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      void downloadFileWithAuth(`${API_BASE}/${record.id}/export`, `${record.name || "wind-farm-calc"}-results.xlsx`);
                    }}
                  />
                </Tooltip>
              ) : null}
              {(record.status === "processing" || record.status === "pending") && canManage ? (
                <Tooltip title={t("取消")}>
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<StopOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleCancel(record);
                    }}
                  />
                </Tooltip>
              ) : null}
              {canManage ? (
                <Tooltip title={t("删除")}>
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      handleDelete(record);
                    }}
                  />
                </Tooltip>
              ) : null}
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  const createContent = (
    <>
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 20 }}
        items={[{ title: t("选择数据准备批次") }, { title: t("引擎预检") }, { title: t("确认提交") }]}
      />
      <Form<{ prep_batch_id: string; name: string }> form={form} layout="vertical">
        {step === 0 ? (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("输入只来自已完成的「风电场数据准备」批次")}
              description={t("不开放直接上传 file_1~4 / P0.abc，以绕开数据校验。")}
            />
            <Form.Item label={t("数据准备批次")} name="prep_batch_id" rules={[{ required: true, message: t("请选择数据准备批次") }]}>
              <Select
                loading={batchesQuery.isLoading}
                placeholder={t("请选择已完成的批次")}
                onChange={(value) => setSelectedBatchId(value)}
                options={(batchesQuery.data?.items ?? []).map((item) => ({
                  value: item.id,
                  label: `${item.name || item.id}（${item.turbine_count} 台 · ${item.grid_nx}×${item.grid_ny}）`,
                }))}
              />
            </Form.Item>
            <Form.Item label={t("任务名称")} name="name">
              <Input maxLength={128} placeholder={t("留空时使用批次名称")} />
            </Form.Item>
          </>
        ) : null}

        {step === 1 ? (
          <>
            {selectedBatch ? (
              <Descriptions column={2} size="small" bordered style={{ marginBottom: 12 }}>
                <Descriptions.Item label={t("风机数")}>{selectedBatch.turbine_count}</Descriptions.Item>
                <Descriptions.Item label={t("网格")}>{selectedBatch.grid_nx} × {selectedBatch.grid_ny}</Descriptions.Item>
                <Descriptions.Item label={t("风险基准 S")}>{selectedBatch.risk_base_s}</Descriptions.Item>
                <Descriptions.Item label={t("五文件齐全度")}>{selectedBatch.files_ready}/5</Descriptions.Item>
              </Descriptions>
            ) : null}
            {engineQuery.data ? (
              <Alert
                type={engineQuery.data.exists && engineQuery.data.wine_available ? "success" : "error"}
                showIcon
                message={engineQuery.data.exists ? t("引擎已就绪") : t("引擎未部署")}
                description={
                  <div>
                    <div>{t("路径")}: {engineQuery.data.resolved || engineQuery.data.configured}</div>
                    <div>{t("大小")}: {formatBytes(engineQuery.data.size)} · MD5: {engineQuery.data.md5 || "-"}</div>
                    <div>
                      Wine: {engineQuery.data.wine_available ? engineQuery.data.wine_version : (engineQuery.data.wine_error || t("不可用"))}
                    </div>
                  </div>
                }
              />
            ) : (
              <Alert type="warning" showIcon message={t("无法获取引擎信息")} />
            )}
          </>
        ) : null}

        {step === 2 ? (
          <Paragraph>
            {t("将使用所选数据准备批次的五文件在 Wine 中调用核心程序，结果逐台落库。任务为小时级长任务，提交后可在详情页查看进度与日志。")}
          </Paragraph>
        ) : null}
      </Form>
    </>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="modo-page-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button icon={<PlusOutlined />} type="primary" onClick={openCreate}>{t("新建计算")}</Button>
          ) : null
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("风电场计算")}</>,
            closable: false,
            children: (
              <div className="modo-page-card admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("任务名称 / ID")}
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={() => setKeyword(keywordInput)}
                      />
                    </Form.Item>
                    <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={(value) => setStatusFilter(value)}
                        options={(Object.keys(STATUS_META)).map((value) => ({ label: t(STATUS_META[value].label), value }))}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Space>
                        <Button icon={<SearchOutlined />} onClick={() => setKeyword(keywordInput)}>{t("查询")}</Button>
                        <Button icon={<ReloadOutlined />} onClick={refreshList}>{t("刷新")}</Button>
                      </Space>
                    </Form.Item>
                  </Form>
                  <Segmented
                    value={viewMode}
                    onChange={(value) => setViewMode(value as "card" | "list")}
                    options={[
                      { label: t("卡片视图"), value: "card" },
                      { label: t("列表视图"), value: "list" },
                    ]}
                  />
                </div>

                <div className="relative flex min-h-0 flex-1 flex-col">
                {viewMode === "card" ? (
                    <div className="admin-lightning-distribution-card-scroll">
                      {listQuery.isLoading && records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Spin />
                        </div>
                      ) : records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("暂无计算任务，点击「新建计算」选择数据准备批次")}
                          />
                        </div>
                      ) : (
                        /* 查询/轮询刷新时不清空已有卡片，仅叠加 loading 遮罩 */
                        <Spin spinning={listQuery.isLoading || listQuery.isPlaceholderData} className="admin-card-view-spin">
                          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                            {records.map(renderRecordCard)}
                          </div>
                        </Spin>
                      )}
                    </div>
                ) : (
                  <div ref={tableScrollAnchorRef} className="admin-wind-table-view" style={{ "--admin-wind-table-body-min-height": `${tableScrollY}px` } as CSSProperties}>
                  <Table<WindFarmCalcJobSummary>
                    rowKey="id"
                    size="middle"
                    loading={listQuery.isLoading || listQuery.isPlaceholderData}
                    columns={columns}
                    dataSource={records}
                    pagination={false}
                    scroll={{ x: 1020, y: tableScrollY }}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无计算任务，点击「新建计算」选择数据准备批次")}
                        />
                      ),
                    }}
                  />
                  </div>
                )}
                  {paginationNode}
                </div>
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title={t("新建风电场计算")}
        width={640}
        open={createOpen}
        destroyOnHidden
        onCancel={() => setCreateOpen(false)}
        footer={
          <Space>
            <Button disabled={step === 0} onClick={() => setStep(step - 1)}>{t("上一步")}</Button>
            <Button disabled={step === 2} onClick={() => setStep(step + 1)}>{t("下一步")}</Button>
            <Button onClick={() => setCreateOpen(false)}>{t("取消")}</Button>
            <Button type="primary" loading={submitting} onClick={() => void handleSubmit()}>{t("提交计算")}</Button>
          </Space>
        }
      >
        {createContent}
      </Modal>
    </div>
  );
}
