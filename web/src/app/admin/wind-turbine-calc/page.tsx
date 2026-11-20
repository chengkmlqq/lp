"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
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
  InputNumber,
  Modal,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
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
import { ModoPagination } from "@/components/biz/modo-pagination";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { WindTurbineCalcDetailView } from "@/components/wind-turbine-calc-detail-view";
import { getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcCreateResponse,
  WindTurbineCalcJobListResponse,
  WindTurbineCalcJobSummary,
} from "@/types/wind-turbine-calc";
import { DEFAULT_ANGLES, DEFAULT_RADII } from "@/types/wind-turbine-calc";

const { Text } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

type DetailTabData = {
  key: string;
  title: string;
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function parseNumberList(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((v) => v.trim())
    .filter(Boolean)
    .map(Number);
}

export default function WindTurbineCalcListPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_turbine_calc.read") || hasPermission("wind_turbine_calc.manage");
  const canManage = hasPermission("wind_turbine_calc.manage");

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
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => setPage(1), [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-turbine-calc", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    // 查询/翻页时保留上一份数据作占位，卡片/列表不清空，仅叠加 loading 遮罩，避免闪空。
    // 后台同 key 轮询属于静默刷新，不触发占位态。
    placeholderData: (previousData) => previousData,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (statusFilter) params.set("status", statusFilter);
      return getJson<WindTurbineCalcJobListResponse>(`${API_BASE}?${params.toString()}`);
    },
    refetchInterval: (queryResult) => {
      const items = queryResult.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing") ? 4000 : false;
    },
  });

  const records = listQuery.data?.items ?? [];

  const refreshList = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-turbine-calc"] });
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
      if (action !== "remove") return;
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
        children: <WindTurbineCalcDetailView jobId={tab.key} onClose={() => closeDetailTab(tab.key)} />,
      })),
    [closeDetailTab, detailTabsData],
  );

  const openCreate = useCallback(() => {
    form.resetFields();
    form.setFieldsValue({
      name: "",
      hub_height: 105.5,
      receptor_radii: DEFAULT_RADII.join(", "),
      blade_length: undefined,
      start_current: 1,
      angle_list: DEFAULT_ANGLES.join(", "),
    });
    setCreateOpen(true);
  }, [form]);

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    const radii = parseNumberList(values.receptor_radii);
    const angles = parseNumberList(values.angle_list);
    if (radii.length === 0) {
      message.error(t("接闪器径向位置不能为空"));
      return;
    }
    if (angles.length === 0 || angles.length > 36) {
      message.error(t("旋转角数量须在 1~36 之间"));
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        name: values.name || "",
        hub_height: Number(values.hub_height),
        receptor_radii: radii,
        blade_length: values.blade_length === undefined || values.blade_length === null ? null : Number(values.blade_length),
        start_current: Number(values.start_current),
        angle_list: angles,
      };
      const response = await fetchWithAuth(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindTurbineCalcCreateResponse;
      message.success(t("已提交单风机计算任务"));
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
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("取消该计算任务？"),
        content: t("取消会真正终止 MATLAB Runtime 进程组，已产生的结果不会保留。"),
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
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("删除该计算任务？"),
        content: t("删除后不可恢复。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}`, { method: "DELETE" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已删除"));
          closeDetailTab(record.id);
          refreshList();
        },
      });
    },
    [closeDetailTab, fetchWithAuth, message, modal, refreshList, t],
  );

  const handleExportCsv = useCallback((record: WindTurbineCalcJobSummary) => {
    window.location.href = `${API_BASE}/${record.id}/export?type=csv`;
  }, []);

  const columns = useMemo<TableColumnsType<WindTurbineCalcJobSummary>>(
    () => [
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        width: 200,
        render: (_value, record) => (
          <Button
            type="link"
            style={{ padding: 0, height: "auto" }}
            onClick={() => openDetail(record.id, record.name || record.id)}
          >
            {record.name || record.id}
          </Button>
        ),
      },
      {
        title: t("参数摘要"),
        key: "params",
        render: (_: unknown, record) => (
          <div style={{ fontSize: 12, lineHeight: 1.5 }}>
            <div>h={record.hub_height} · R={record.blade_length} · Ic={record.start_current}</div>
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              r=[{record.receptor_radii?.join(", ")}]
            </Text>
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              θ=[{record.angle_list?.join(", ")}]
            </Text>
          </div>
        ),
      },
      {
        title: t("引擎版本"),
        key: "engine",
        render: (_: unknown, record) => record.engine_version_tag || record.engine_version_hash?.slice(0, 8) || "-",
      },
      {
        title: t("平均失效率"),
        dataIndex: "mean_failure_rate",
        key: "mean_failure_rate",
        render: (v: number | null) => (v === null ? "-" : v.toExponential(9)),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        render: (status: string, record) => (
          <Space direction="vertical" size={0}>
            <Tag color={STATUS_META[status]?.color ?? "default"}>{STATUS_META[status]?.label ?? status}</Tag>
            {(record.status === "processing" || record.status === "pending") && (
              <Progress percent={record.progress} size="small" style={{ width: 90 }} showInfo={false} />
            )}
          </Space>
        ),
      },
      {
        title: t("耗时"),
        dataIndex: "duration_seconds",
        key: "duration_seconds",
        render: (v: number | null) => formatDuration(v),
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        render: (v: string | null) => formatDateTime(v),
      },
      {
        title: t("操作"),
        key: "actions",
        fixed: "right",
        render: (_: unknown, record) => {
          const active = record.status === "processing" || record.status === "pending";
          return (
            <Space size={4}>
              <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => openDetail(record.id, record.name || record.id)} />
              <Button
                type="link"
                size="small"
                icon={<DownloadOutlined />}
                title={t("导出 CSV")}
                onClick={() => handleExportCsv(record)}
              />
              {active && canManage && (
                <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => handleCancel(record)} />
              )}
              {!active && canManage && (
                <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record)} />
              )}
            </Space>
          );
        },
      },
    ],
    [canManage, handleCancel, handleDelete, handleExportCsv, openDetail, t],
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
      style={{ marginTop: 0 }}
    />
  );

  const renderRecordCard = (record: WindTurbineCalcJobSummary) => {
    const meta = STATUS_META[record.status] ?? STATUS_META.pending;
    const active = record.status === "processing" || record.status === "pending";
    const title = record.name || record.id;
    return (
      <Card
        key={record.id}
        className="admin-lightning-distribution-event-card"
        size="small"
        hoverable
        onClick={() => openDetail(record.id, title)}
      >
        <div className="flex flex-col">
          <div className="admin-lightning-distribution-event-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <ThunderboltOutlined className="text-base text-gray-500" />
            <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
              <Tooltip title={title}>
                <Text strong className="truncate min-w-0">
                  {title}
                </Text>
              </Tooltip>
              <Tag color={meta.color} style={{ marginInlineEnd: 0, flexShrink: 0 }}>
                {t(meta.label)}
              </Tag>
            </div>
          </div>

          <div className="flex flex-col gap-1 px-4 py-3">
            <Text type="secondary" className="text-xs truncate">
              ID：{record.id}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("阶段")}：{record.stage || "-"} · {t("进度")}：{record.progress}%
            </Text>
            {record.status === "failed" && record.error_message ? (
              <Text type="danger" className="text-xs" ellipsis={{ tooltip: record.error_message }}>
                {record.error_message}
              </Text>
            ) : null}
            <Text type="secondary" className="text-xs">
              h={record.hub_height} · R={record.blade_length} · Ic={record.start_current}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("角度数")}：{record.angle_count} · r=[{record.receptor_radii?.join(", ")}]
            </Text>
            <Text type="secondary" className="text-xs">
              {t("引擎版本")}：{record.engine_version_tag || record.engine_version_hash?.slice(0, 8) || "-"}
            </Text>
            <Text type="secondary" className="text-xs">
              {t("耗时")}：{formatDuration(record.duration_seconds)} · {t("创建时间")}：{formatDateTime(record.create_date)}
            </Text>
          </div>

          <div className="admin-lightning-distribution-event-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {active ? <Progress percent={record.progress} size="small" className="flex-1 max-w-40" /> : <div />}
            <Space size="small" className="flex-wrap">
              <Tooltip title={t("详情")}>
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openDetail(record.id, title);
                  }}
                />
              </Tooltip>
              <Tooltip title={t("导出 CSV")}>
                <Button
                  type="text"
                  size="small"
                  icon={<DownloadOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    handleExportCsv(record);
                  }}
                />
              </Tooltip>
              {active && canManage ? (
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
              {!active && canManage ? (
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

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="modo-page-tabs"
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("单风机计算")}</>,
            closable: false,
            children: (
              <div className="modo-page-card admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("搜索任务名称 / ID")}
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={() => setKeyword(keywordInput.trim())}
                      />
                    </Form.Item>
                    <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={(value) => setStatusFilter(value)}
                        options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: t(meta.label) }))}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Space>
                        <Button icon={<SearchOutlined />} onClick={() => setKeyword(keywordInput.trim())}>
                          {t("查询")}
                        </Button>
                        <Button icon={<ReloadOutlined />} onClick={refreshList}>
                          {t("刷新")}
                        </Button>
                        {canManage && (
                          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                            {t("新建计算")}
                          </Button>
                        )}
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

                {viewMode === "card" ? (
                  <>
                    <div className="admin-lightning-distribution-card-scroll">
                      {listQuery.isLoading && records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Spin />
                        </div>
                      ) : records.length === 0 ? (
                        <div className="admin-lightning-distribution-card-view-state">
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description={t("暂无计算任务，点击「新建计算」提交单风机计算")}
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
                    {records.length > 0 ? (
                      <div className="admin-lightning-distribution-pagination">{paginationNode}</div>
                    ) : null}
                  </>
                ) : (
                  <Table<WindTurbineCalcJobSummary>
                    rowKey="id"
                    size="middle"
                    loading={listQuery.isLoading || listQuery.isPlaceholderData}
                    columns={columns}
                    dataSource={records}
                    pagination={false}
                    scroll={{ x: 1180 }}
                    locale={{
                      emptyText: (
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("暂无计算任务，点击「新建计算」提交单风机计算")}
                        />
                      ),
                    }}
                    footer={() => paginationNode}
                  />
                )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        open={createOpen}
        title={t("新建单风机计算")}
        onCancel={() => setCreateOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={t("提交")}
        cancelText={t("取消")}
        width={640}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("参数说明")}
          description={t(
            "轮毂高度 h、接闪器径向位置 r_list（严格递增，0<r≤R）、叶片长度 R（默认 max(r_list)）、起始雷电流 Ic、旋转角列表（≤36 个）。",
          )}
        />
        <Form form={form} layout="vertical">
          <Form.Item label={t("任务名称")} name="name">
            <Input placeholder={t("可选")} />
          </Form.Item>
          <Form.Item
            label={t("轮毂高度 h (m)")}
            name="hub_height"
            rules={[{ required: true, message: t("请输入轮毂高度") }, { type: "number", min: 0.0001, message: t("h 必须大于 0") }]}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("接闪器径向位置 r_list (m)")}
            name="receptor_radii"
            rules={[{ required: true, message: t("请输入接闪器径向位置") }]}
            extra={t("逗号分隔，须严格递增")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t("叶片长度 R (m)")}
            name="blade_length"
            extra={t("留空则取 max(r_list)")}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("起始雷电流 Ic (kA)")}
            name="start_current"
            rules={[{ required: true, message: t("请输入起始雷电流") }, { type: "number", min: 0.0001, message: t("Ic 必须大于 0") }]}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("旋转角列表 (deg)")}
            name="angle_list"
            rules={[{ required: true, message: t("请输入旋转角列表") }]}
            extra={t("逗号分隔，最多 36 个，默认 0–110 步长 10")}
          >
            <Input />
          </Form.Item>
        </Form>

        <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
          <Descriptions.Item label={t("外推提示")}>
            <Text type="secondary">{t("角度击距公式只在 0–90° 拟合，其余姿态按外推处理。")}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </div>
  );
}
