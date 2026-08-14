"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  DatePicker,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip as AntTooltip,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
} from "antd";
import { MoreOutlined, QuestionCircleOutlined, SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, type RefAttributes } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { LightningTowerView } from "@/components/lightning-tower-view";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type {
  LightningAmplitudeRecord,
  LightningAmplitudeListResponse,
  LightningAmplitudeImportResponse,
  LightningAmplitudeBackfillLine,
  LightningAmplitudeBackfillLineListResponse,
  LineListResponse,
  LineSummary,
  LightningPolarity,
} from "@/types/auth";
import { CHINESE_CITIES, type CityOption } from "@/data/chinese-cities";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

type ImportFormValues = {
  sample_interval_us: number;
  city: string;
  sensor_model: string;
  install_position: string;
  notes: string;
  location_tag: string;
  event_time: dayjs.Dayjs | null;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  sample_interval_us: 1,
  city: "",
  sensor_model: "",
  install_position: "",
  notes: "",
  location_tag: "",
  event_time: null,
};

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "导入中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

function formatNullable(value: number | string | null | undefined): string {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

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

function formatPolarity(polarity: LightningPolarity): string {
  if (polarity === "positive") return "正极性";
  if (polarity === "negative") return "负极性";
  if (polarity === "mixed") return "混合";
  return "未知";
}

function truncateFileName(name: string, maxLength = 20): string {
  if (!name) {
    return "未命名";
  }
  return name.length > maxLength ? `${name.slice(0, maxLength)}…` : name;
}

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const LIGHTNING_TABLE_BOTTOM_GAP = 8;

export default function AdminLightningCurrentsPage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const [importForm] = Form.useForm<ImportFormValues>();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [backfillLinesOpen, setBackfillLinesOpen] = useState(false);
  const [backfillLinesRecord, setBackfillLinesRecord] = useState<LightningAmplitudeRecord | null>(null);
  const [linePickerOpen, setLinePickerOpen] = useState(false);
  const [linePickerLineId, setLinePickerLineId] = useState<string | null>(null);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const trimmedKeyword = searchKeyword.trim();
  const listParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, trimmedKeyword]);
  const listPath = `/api/v1/lightning-currents/amplitudes?${listParams}`;

  const recordsQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    refetchInterval: false,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeListResponse;
    },
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);

  const listError = recordsQuery.error instanceof Error ? recordsQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const refreshAll = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lightning-currents"),
    });
  }, [queryClient]);

  useTopicSubscription(
    "admin.lightning-amplitude",
    useCallback((event) => {
      const name = event.name;
      const payload = event.payload as {
        amplitude_id?: string;
        progress?: number;
        status?: string;
        error?: string;
        sample_count?: number;
        peak_abs_current_ka?: number;
      };
      if (name === "amplitude.import_started") {
        void refreshAll();
      } else if (name === "amplitude.import_progress") {
        void refreshAll();
      } else if (name === "amplitude.import_completed") {
        setSuccess(
          payload?.sample_count != null
            ? `导入完成：采样点 ${payload.sample_count} 个，峰值 ${formatNumber(payload.peak_abs_current_ka, 2)}kA`
            : "导入完成",
        );
        void refreshAll();
      } else if (name === "amplitude.import_failed") {
        setError(payload?.error || "导入失败，请在列表中对失败记录执行重试");
        void refreshAll();
      } else {
        void refreshAll();
      }
    }, [refreshAll]),
  );

  const updateTableScrollY = useCallback(() => {
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
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? LIGHTNING_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - LIGHTNING_TABLE_BOTTOM_GAP);

    const clampedHeight = Math.max(LIGHTNING_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [error, listError, records.length, recordsQuery.isFetching, updateTableScrollY, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    if (viewMode !== "list") {
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
  }, [updateTableScrollY, viewMode]);

  // 导入中进度直接通过订阅消息 + 表格“状态”列展示，不弹进度条轮询弹窗

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const values = importForm.getFieldsValue(true);
      const formData = new FormData();
      formData.append("file", file);
      if (values.sample_interval_us !== null && values.sample_interval_us !== undefined) {
        formData.append("sample_interval_us", String(values.sample_interval_us));
      }
      if (values.city?.trim()) formData.append("city", values.city.trim());
      if (values.sensor_model?.trim()) formData.append("sensor_model", values.sensor_model.trim());
      if (values.install_position?.trim()) formData.append("install_position", values.install_position.trim());
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());
      if (values.location_tag?.trim()) formData.append("location_tag", values.location_tag.trim());
      if (values.event_time) {
        const dt = values.event_time.format("YYYY-MM-DDTHH:mm:ss");
        if (dt) formData.append("event_time", dt);
      }

      const response = await fetchWithAuth("/api/v1/lightning-currents/import-async", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeImportResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(`导入任务已提交（任务ID: ${payload.task_id}），正在后台处理`);
      setImportModalOpen(false);
      importForm.resetFields();
      setSelectedFile(null);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "导入失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (record: LightningAmplitudeRecord) => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${record.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return record.id;
    },
    onSuccess: async () => {
      setError("");
      setSuccess("雷电流幅值记录已删除");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const retryMutation = useMutation({
    mutationFn: async (record: LightningAmplitudeRecord) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const response = await fetchWithAuth(`/api/v1/lightning-currents/amplitudes/${record.id}/retry`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeImportResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(`重试任务已提交（任务ID: ${payload.task_id}）`);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "重试失败");
    },
  });

  const openDetail = useCallback((record: LightningAmplitudeRecord) => {
    const key = record.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{truncateFileName(record.source_file_name)}</span>,
          closable: true,
          children: (
            <AmplitudeDetailView
              record={record}
              canManage={canManage}
              onRetry={(recordToRetry) => retryMutation.mutate(recordToRetry)}
              retryLoading={retryMutation.isPending}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [canManage, retryMutation]);

  // 回填线路小窗查询
  const backfillLinesQuery = useQuery<LightningAmplitudeBackfillLineListResponse>({
    queryKey: ["lightning-currents", backfillLinesRecord?.id, "backfill-lines"],
    enabled: !!backfillLinesRecord,
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/amplitudes/${backfillLinesRecord?.id}/backfill-lines`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeBackfillLineListResponse;
    },
  });

  const openBackfillLines = (record: LightningAmplitudeRecord) => {
    setBackfillLinesRecord(record);
    setBackfillLinesOpen(true);
  };

  // 线路选择（杆塔列表 Tab 用）：复用现有线路列表接口
  const linesQuery = useQuery<LineListResponse>({
    queryKey: ["lines"],
    enabled: linePickerOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines?limit=1000`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  // 打开杆塔列表 Tab（key 用 line-{lineId} 去重，可同时打开多条线路的 Tab）
  const openTowerTab = useCallback((lineId: string) => {
    const key = `line-${lineId}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: (
            <Space size={6}>
              <span>杆塔列表</span>
              <Tag color="blue">回填数据</Tag>
            </Space>
          ),
          closable: true,
          children: <LightningTowerView lineId={lineId} fetchWithAuth={fetchWithAuth} />,
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth]);

  const handleTabsEdit = useCallback((targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    void queryClient.refetchQueries({ queryKey: [listPath] });
  };

  const renderRecordCard = (record: LightningAmplitudeRecord) => {
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "detail",
        label: "详情",
        onClick: () => openDetail(record),
      },
      {
        type: "divider",
      },
      ...(record.status === "failed" && canManage
        ? [
            {
              key: "retry",
              label: "重试",
              onClick: () => retryMutation.mutate(record),
            },
            {
              type: "divider" as const,
            },
          ]
        : []),
      ...(canManage
        ? [
            {
              key: "delete",
              label: "删除",
              danger: true as const,
              onClick: () => {
                Modal.confirm({
                  title: "删除记录",
                  content: `确认删除记录 ${record.source_file_name} 吗？将同时删除 MinIO 上的源文件。`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: async () => {
                    await deleteMutation.mutateAsync(record);
                  },
                });
              },
            },
          ]
        : []),
    ];

    const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };

    return (
      <AntCard
        key={record.id}
        className="admin-lightning-events-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis>
              {record.source_file_name || "-"}
            </Typography.Text>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Space>
        }
        extra={
          <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
            <Button type="text" size="small" icon={<MoreOutlined />} />
          </Dropdown>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">城市</Typography.Text>
            <Typography.Text>{record.city || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">安装位置</Typography.Text>
            <Typography.Text>{record.install_position || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">传感器型号</Typography.Text>
            <Typography.Text>{record.sensor_model || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">采样点数</Typography.Text>
            <Typography.Text>{record.sample_count}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">回填关联线路数</Typography.Text>
            {(() => {
              const count = record.backfill_line_count ?? 0;
              if (count === 0) {
                return <Typography.Text type="secondary">-</Typography.Text>;
              }
              return (
                <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openBackfillLines(record)}>
                  {count} 条
                </Button>
              );
            })()}
          </div>
          {record.status === "processing" && (
            <Progress percent={record.progress} size="small" />
          )}
        </Space>
      </AntCard>
    );
  };

  const columns = useMemo<ColumnsType<LightningAmplitudeRecord>>(
    () => [
      {
        title: "文件名称",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string) => value || "-",
      },
      {
        title: "城市",
        dataIndex: "city",
        width: 110,
        render: (value: string | null) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
      },
      {
        title: "采样点数",
        dataIndex: "sample_count",
        width: 100,
        render: (value: number) => value ?? 0,
      },
      {
        title: "峰值(kA)",
        dataIndex: "peak_abs_current_ka",
        width: 100,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "极性",
        dataIndex: "polarity",
        width: 90,
        render: (value: LightningPolarity) => formatPolarity(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 160,
        render: (_: unknown, row) => {
          const meta = STATUS_META[row.status] ?? { color: "default", label: row.status };
          const failed = row.status === "failed";
          const statusTag = (
            <Tag color={meta.color}>{meta.label}</Tag>
          );
          return (
            <Space size={6}>
              {failed && row.error_message ? (
                <AntTooltip title={row.error_message}>
                  {statusTag}
                </AntTooltip>
              ) : statusTag}
              {row.status === "processing" && (
                <Progress percent={row.progress} size="small" style={{ width: 80 }} />
              )}
            </Space>
          );
        },
      },
      {
        title: "回填关联线路数",
        dataIndex: "backfill_line_count",
        key: "backfill_line_count",
        width: 130,
        render: (_: unknown, row) => {
          const count = row.backfill_line_count ?? 0;
          if (count === 0) {
            return <Typography.Text type="secondary">-</Typography.Text>;
          }
          return (
            <Button type="link" size="small" style={{ padding: 0 }} onClick={() => openBackfillLines(row)}>
              {count} 条
            </Button>
          );
        },
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_: unknown, row) => {
          // 统一 UI 规范：默认仅展示 2 个直接按钮（详情/删除），其余条件操作收进 ⋯ 三点下拉
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "towers",
              label: "杆塔列表",
              onClick: () => {
                setLinePickerLineId(null);
                setLinePickerOpen(true);
              },
            },
            ...(row.status === "failed" && canManage
              ? [
                  {
                    key: "retry",
                    label: "重试",
                    disabled: retryMutation.isPending,
                    onClick: () => retryMutation.mutate(row),
                  },
                ]
              : []),
          ];
          return (
            <Space wrap>
              <Button
                size="small"
                onClick={() => openDetail(row)}
              >
                详情
              </Button>
              {canManage && (
                <Button
                  size="small"
                  danger
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    Modal.confirm({
                      title: "删除记录",
                      content: `确认删除记录 ${row.source_file_name} 吗？将同时删除 MinIO 上的源文件。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: async () => {
                        await deleteMutation.mutateAsync(row);
                      },
                    });
                  }}
                >
                  删除
                </Button>
              )}
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, deleteMutation, retryMutation, openDetail, openBackfillLines],
  );

  if (initializing) {
    return (
      <AdminPageLoading
        tip="初始化中..."
        minHeightClassName="min-h-[280px]"
      />
    );
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            请先登录后再访问雷电流幅值统计页面。
          </Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `lightning.read`）。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="admin-lightning-currents-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" onClick={() => setImportModalOpen(true)}>
              导入
            </Button>
          ) : null
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-lightning-currents-tab-title">雷电流幅值统计</span>,
            closable: false,
            children: (
              <div className="admin-lightning-currents-list-pane">
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="关键词" className="admin-filter-keyword-item">
              <Input
                allowClear
                placeholder="按文件名/事件编号搜索"
                value={keywordInput}
                onChange={(event) => handleKeywordChange(event.target.value)}
                onPressEnter={handleSearch}
              />
            </Form.Item>
            <Form.Item>
              <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
                查询
              </Button>
            </Form.Item>
          </Form>
          <Segmented
            value={viewMode}
            onChange={(value) => setViewMode(value as "card" | "list")}
            options={[
              { label: "卡片视图", value: "card" },
              { label: "列表视图", value: "list" },
            ]}
          />
        </div>

        {viewMode === "list" ? (
          <div
            ref={tableScrollAnchorRef}
            className="lightning-table-anchor"
            style={{ "--lightning-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<LightningAmplitudeRecord>
              rowKey={(row) => row.id}
              columns={columns}
              dataSource={records}
              loading={recordsQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total: Math.max(recordsQuery.data?.total ?? 0, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${recordsQuery.data?.total ?? 0} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1200, y: tableScrollY }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的记录。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-lightning-events-card-view">
            {recordsQuery.isLoading && records.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[180px]" />
              </div>
            ) : records.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的记录。"
                />
              </div>
            ) : (
              <>
                <div className="admin-lightning-events-card-scroll">
                  <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                    {records.map((record) => renderRecordCard(record))}
                  </div>
                </div>
                <div className="admin-lightning-events-pagination">
                  <Pagination
                    current={pagination.current}
                    pageSize={pagination.pageSize}
                    total={recordsQuery.data?.total ?? 0}
                    onChange={(page, pageSize) => {
                      setPagination({ current: page, pageSize });
                    }}
                    showSizeChanger
                    showTotal={(total) => `共 ${total} 条`}
                  />
                </div>
              </>
            )}
          </div>
        )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title="导入雷电流幅值数据"
        open={importModalOpen}
        onCancel={() => {
          setImportModalOpen(false);
          importForm.resetFields();
          setSelectedFile(null);
        }}
        footer={null}
        width={800}
        destroyOnClose
      >
        <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={INITIAL_IMPORT_VALUES}>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="city" label="城市">
              <Select
                showSearch
                placeholder="请搜索选择城市"
                filterOption={(input, option) => {
                  const keyword = input.toLowerCase().trim();
                  const data = option?.["data-data"] as CityOption | undefined;
                  if (!data) return false;
                  return (
                    data.label.includes(input)
                    || data.pinyin.includes(keyword)
                    || data.initials.includes(keyword)
                  );
                }}
                options={CHINESE_CITIES.map((item) => ({
                  label: item.label,
                  value: item.label,
                  "data-data": item,
                }))}
              />
            </Form.Item>
            <Form.Item name="location_tag" label="事件发生地点">
              <Input placeholder="例如 XX变电站、XX区域" />
            </Form.Item>
            <Form.Item name="install_position" label="安装位置">
              <Input placeholder="例如 楼顶避雷针" />
            </Form.Item>
            <Form.Item name="sensor_model" label="传感器型号">
              <Input placeholder="例如 LCS-1000" />
            </Form.Item>
            <Form.Item name="sample_interval_us" label="采样间隔(us)">
              <InputNumber style={{ width: "100%" }} min={0.000001} precision={6} />
            </Form.Item>
            <Form.Item name="event_time" label="发生时间">
              <DatePicker className="w-full" showTime placeholder="选择日期时间" />
            </Form.Item>
          </div>
          <Form.Item name="notes" label="备注">
            <Input.TextArea rows={2} placeholder="可填写天气背景、场景备注等" />
          </Form.Item>
          <div style={{ marginBottom: 16 }}>
            <Form.Item label="数据文件" required>
              <Upload.Dragger
                accept=".txt,.csv,text/plain,text/csv"
                showUploadList={false}
                beforeUpload={(file) => {
                  setSelectedFile(file);
                  return false;
                }}
                onRemove={() => setSelectedFile(null)}
              >
                {selectedFile ? (
                  <p className="ant-upload-text">{selectedFile.name}</p>
                ) : (
                  <>
                    <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                      点击或拖拽文件到此区域上传
                    </p>
                    <Typography.Text type="secondary">
                      支持单列电流序列（每行一个值）或双列 time,current 格式。原始文件将存入 MinIO。
                    </Typography.Text>
                  </>
                )}
              </Upload.Dragger>
            </Form.Item>
          </div>
          <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
            <Button
              type="primary"
              disabled={!selectedFile}
              loading={importMutation.isPending}
              onClick={async () => {
                if (!selectedFile) return;
                try {
                  await importForm.validateFields();
                  importMutation.mutate(selectedFile);
                } catch {
                  // 表单校验失败时不触发导入
                }
              }}
            >
              确认导入
            </Button>
          </div>
        </Form>
      </Modal>

      {/* 回填线路小窗 */}
      <Modal
        title={backfillLinesRecord ? `回填线路 - ${backfillLinesRecord.source_file_name}` : "回填线路"}
        open={backfillLinesOpen}
        onCancel={() => {
          setBackfillLinesOpen(false);
          setBackfillLinesRecord(null);
        }}
        footer={null}
        width={640}
      >
        <Table<LightningAmplitudeBackfillLine>
          rowKey="line_id"
          size="small"
          loading={backfillLinesQuery.isFetching}
          dataSource={backfillLinesQuery.data?.items ?? []}
          tableLayout="fixed"
          pagination={false}
          scroll={{ y: 320 }}
          columns={[
            {
              title: "线路编号",
              dataIndex: "line_code",
              key: "line_code",
              width: 120,
              render: (value: string | null) => value || "-",
            },
            {
              title: "线路名称",
              dataIndex: "line_name",
              key: "line_name",
              width: 150,
              ellipsis: true,
              render: (value: string | null) => value || "-",
            },
            {
              title: "电压(kV)",
              dataIndex: "voltage_kv",
              key: "voltage_kv",
              width: 90,
              render: (value: number | null) => (value == null ? "-" : value),
            },
            {
              title: "current_a",
              dataIndex: "current_a",
              key: "current_a",
              width: 90,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "current_b",
              dataIndex: "current_b",
              key: "current_b",
              width: 90,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "峰值max(kA)",
              dataIndex: "peak_max",
              key: "peak_max",
              width: 100,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "峰值min(kA)",
              dataIndex: "peak_min",
              key: "peak_min",
              width: 100,
              render: (value: number | null) => formatNumber(value, 3),
            },
            {
              title: "采样数",
              dataIndex: "sampled_event_count",
              key: "sampled_event_count",
              width: 70,
              render: (value: number) => value ?? 0,
            },
            {
              title: "回填时间",
              dataIndex: "prepared_at",
              key: "prepared_at",
              width: 150,
              render: (value: string | null) => formatDateTime(value),
            },
          ]}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description="该幅值尚未被任何线路回填使用"
              />
            ),
          }}
        />
      </Modal>

      {/* 杆塔列表：选择线路后打开动态 Tab */}
      <Modal
        title="选择线路查看杆塔列表"
        open={linePickerOpen}
        onCancel={() => setLinePickerOpen(false)}
        onOk={() => {
          if (linePickerLineId) {
            openTowerTab(linePickerLineId);
            setLinePickerOpen(false);
            setLinePickerLineId(null);
          }
        }}
        okText="打开杆塔列表"
        okButtonProps={{ disabled: !linePickerLineId }}
        width={480}
      >
        <Select
          style={{ width: "100%" }}
          showSearch
          optionFilterProp="label"
          placeholder="搜索并选择线路"
          value={linePickerLineId ?? undefined}
          onChange={(value) => setLinePickerLineId(value)}
          loading={linesQuery.isFetching}
          options={(linesQuery.data?.items ?? []).map((line: LineSummary) => ({
            label: `${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`,
            value: line.id,
          }))}
        />
      </Modal>

    </div>
  );
}

function AmplitudeDetailView({
  record,
  canManage,
  onRetry,
  retryLoading,
}: {
  record: LightningAmplitudeRecord;
  canManage: boolean;
  onRetry: (record: LightningAmplitudeRecord) => void;
  retryLoading: boolean;
}) {
  return (
    <Space direction="vertical" size={12} className="w-full admin-lightning-currents-detail-pane">
      <div>
        <Typography.Title level={5}>基本信息</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label="状态">
            {(() => {
              const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };
              return <Tag color={meta.color}>{meta.label}</Tag>;
            })()}
          </Descriptions.Item>
          <Descriptions.Item label="事件编号">{formatNullable(record.event_id)}</Descriptions.Item>
          <Descriptions.Item label="城市">{formatNullable(record.city)}</Descriptions.Item>
          <Descriptions.Item label="事件发生地点">{formatNullable(record.location_tag)}</Descriptions.Item>
          <Descriptions.Item label="传感器">{formatNullable(record.sensor_model)}</Descriptions.Item>
          <Descriptions.Item label="安装位置">{formatNullable(record.install_position)}</Descriptions.Item>
          <Descriptions.Item label="发生时间">{formatNullable(record.event_time)}</Descriptions.Item>
          <Descriptions.Item label="采样点数">{record.sample_count}</Descriptions.Item>
          <Descriptions.Item label="采样间隔(us)">{formatNumber(record.sample_interval_us, 6)}</Descriptions.Item>
          <Descriptions.Item label="海拔(m)">{formatNullable(record.altitude_m)}</Descriptions.Item>
          <Descriptions.Item label="气压(hPa)">{formatNullable(record.pressure_hpa)}</Descriptions.Item>
          <Descriptions.Item label="湿度(%)">{formatNullable(record.humidity_percent)}</Descriptions.Item>
        </Descriptions>
      </div>

      <div>
        <Typography.Title level={5}>波形特征参数</Typography.Title>
        <Descriptions bordered size="small" column={2}>
          <Descriptions.Item label={
            <span>
              峰值电流(kA){" "}
              <AntTooltip title="波形序列中绝对值最大的电流值（kA），代表该次雷击的最强瞬间。是衡量雷击强度的核心指标。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.peak_current_ka, 3)}
          </Descriptions.Item>
          <Descriptions.Item label="绝对峰值(kA)">{formatNumber(record.peak_abs_current_ka, 3)}</Descriptions.Item>
          <Descriptions.Item label={
            <span>
              波形分类{" "}
              <AntTooltip title="将实际波形的波前时间（T1）和半峰值时间（T2）与 IEC 标准波形模板匹配，归入最接近的分类：10/350（T1=10μs, T2=350μs，典型直击雷波形）、8/20（T1=8μs, T2=20μs，典型感应雷/测试波形）、1.2/50（T1=1.2μs, T2=50μs，典型操作冲击波形）。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNullable(record.wave_shape)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              极性{" "}
              <AntTooltip title="雷电流的主导方向。自然界约 90% 为负极性雷击，正极性雷击虽少但峰值更大、危害更强。正极性：正峰值大于负峰值；负极性：负峰值大于正峰值；混合：正负峰值相近。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatPolarity(record.polarity)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              波前时间 T1(us){" "}
              <AntTooltip title="电流从峰值的 10% 上升到 90% 所需时间的 1.25 倍（μs），反映雷电流上升的陡度。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.wavefront_time_t1_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              半峰值时间 T2(us){" "}
              <AntTooltip title="从虚拟零点到电流下降到峰值 50% 的时间（μs），反映脉冲宽度。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.half_value_time_t2_us, 3)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              陡度(kA/us){" "}
              <AntTooltip title="波形中电流变化率的最大值（kA/μs），影响感应过电压的大小。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.steepness_ka_per_us, 6)}
          </Descriptions.Item>
          <Descriptions.Item label={
            <span>
              I²t 作用积分(J/Ω){" "}
              <AntTooltip title="电流平方对时间的积分（J/Ω），衡量雷电流的热效应能量。">
                <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
              </AntTooltip>
            </span>
          }>
            {formatNumber(record.action_integral_j_ohm, 3)}
          </Descriptions.Item>
        </Descriptions>
      </div>

      {record.stroke_peaks_json && record.stroke_peaks_json.length > 0 && (
        <div>
          <Typography.Title level={5}>多回击峰值分布</Typography.Title>
          <Descriptions bordered size="small" column={1} style={{ marginBottom: 12 }}>
            <Descriptions.Item label="回击数">{record.stroke_count}</Descriptions.Item>
          </Descriptions>
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={record.stroke_peaks_json.map((peak: Record<string, unknown>, idx: number) => ({
              index: idx + 1,
              time_us: Number(peak.time_us) || 0,
              current_ka: Number(peak.current_ka) || 0,
            }))}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="index" label={{ value: "回击序号", position: "insideBottomRight", offset: -5 }} />
              <YAxis label={{ value: "峰值电流 (kA)", angle: -90, position: "insideLeft", offset: 10 }} />
              <Tooltip
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                formatter={(value: any, name?: string | number) => {
                  if (name === "current_ka") return [formatNumber(Number(value), 3), "峰值电流 (kA)"];
                  if (name === "time_us") return [formatNumber(Number(value), 2), "时间 (μs)"];
                  return [value, name];
                }}
                labelFormatter={(label) => `回击 ${label}`}
              />
              <Legend />
              <Line type="monotone" dataKey="current_ka" stroke="#1890ff" name="峰值电流 (kA)" strokeWidth={2} dot={{ r: 4 }} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {record.status === "failed" && (
        <div>
          <Typography.Title level={5}>失败原因</Typography.Title>
          <Typography.Paragraph type="danger">
            {record.error_message || "未知错误"}
          </Typography.Paragraph>
          {canManage && (
            <Button danger loading={retryLoading} onClick={() => onRetry(record)}>
              重试
            </Button>
          )}
        </div>
      )}
    </Space>
  );
}
