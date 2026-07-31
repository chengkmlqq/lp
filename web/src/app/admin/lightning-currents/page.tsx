"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  DatePicker,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip as AntTooltip,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
} from "antd";
import { MoreOutlined, QuestionCircleOutlined, EditOutlined, SearchOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  LightningCurrentEventListResponse,
  LightningCurrentEventSummary,
  LightningCurrentExceedanceResponse,
  LightningCurrentImportResponse,
  LightningCurrentSampleListResponse,
  LightningCurrentSampleItem,
  LightningImportBatchSummary,
  LightningImportBatchListResponse,
  LightningPolarity,
} from "@/types/auth";
import { CHINESE_CITIES, type CityOption } from "@/data/chinese-cities";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

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

function formatPolarity(polarity: LightningPolarity): string {
  if (polarity === "positive") return "正极性";
  if (polarity === "negative") return "负极性";
  if (polarity === "mixed") return "混合";
  return "未知";
}

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_VIEWPORT_GAP = 40;
const LIGHTNING_TABLE_FALLBACK_RESERVE = 220;

export default function AdminLightningCurrentsPage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [importForm] = Form.useForm<ImportFormValues>();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [exceedanceModalOpen, setExceedanceModalOpen] = useState(false);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [sampleModalOpen, setSampleModalOpen] = useState(false);
  const [selectedEventForModal, setSelectedEventForModal] = useState<LightningCurrentEventSummary | null>(null);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [samplePage, setSamplePage] = useState(1);
  const [samplePageSize, setSamplePageSize] = useState(50);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedEvents, setAllLoadedEvents] = useState<LightningCurrentEventSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const trimmedKeyword = searchKeyword.trim();
  const eventListParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, trimmedKeyword]);
  const eventListPath = `/api/v1/lightning-currents?${eventListParams}`;

  const eventsQuery = useQuery({
    queryKey: [eventListPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(eventListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentEventListResponse;
    },
  });

  const events = useMemo(() => eventsQuery.data?.items ?? [], [eventsQuery.data?.items]);

  // ---- 导入批次状态查询 ----
  const importBatchesPath = "/api/v1/lightning-currents/import-batches?limit=100&import_type=waveform";
  const importBatchesQuery = useQuery({
    queryKey: [importBatchesPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(importBatchesPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningImportBatchListResponse;
    },
    refetchInterval: 5000,
  });
  const activeBatches = useMemo(
    () => (importBatchesQuery.data?.items ?? []).filter(
      (b) => b.status === "pending" || b.status === "processing" || b.status === "failed",
    ),
    [importBatchesQuery.data?.items],
  );

  const exceedancePath = useMemo(() => {
    if (!selectedEventForModal?.id) return "";
    return `/api/v1/lightning-currents/stats/exceedance`;
  }, [selectedEventForModal?.id]);

  const exceedanceQuery = useQuery({
    queryKey: [exceedancePath, selectedEventForModal?.id],
    enabled: !!user && canRead && exceedanceModalOpen && !!selectedEventForModal,
    queryFn: async () => {
      const response = await fetchWithAuth(exceedancePath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentExceedanceResponse;
    },
  });

  const samplePath = useMemo(() => {
    if (!selectedEventForModal?.id) return "";
    const offset = (samplePage - 1) * samplePageSize;
    return `/api/v1/lightning-currents/${selectedEventForModal.id}/samples?limit=${samplePageSize}&offset=${offset}`;
  }, [selectedEventForModal?.id, samplePage, samplePageSize]);

  const samplesQuery = useQuery({
    queryKey: [samplePath],
    enabled: !!user && canRead && sampleModalOpen && !!selectedEventForModal,
    queryFn: async () => {
      if (!samplePath) {
        return { items: [], total: 0, limit: 0, offset: 0 } satisfies LightningCurrentSampleListResponse;
      }
      const response = await fetchWithAuth(samplePath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentSampleListResponse;
    },
  });

  const listError = eventsQuery.error instanceof Error ? eventsQuery.error.message : "";
  const sampleError = samplesQuery.error instanceof Error ? samplesQuery.error.message : "";
  const statsError = exceedanceQuery.error instanceof Error ? exceedanceQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || listError || sampleError || statsError,
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
    "admin.lightning-currents",
    useCallback(() => {
      void refreshAll();
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

    const anchorTop = anchor.getBoundingClientRect().top;
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - LIGHTNING_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? LIGHTNING_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - LIGHTNING_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(LIGHTNING_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "table") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [error, listError, sampleError, statsError, events.length, eventsQuery.isFetching, updateTableScrollY, viewMode]);

  useEffect(() => {
    if (viewMode !== "card" || eventsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedEvents(() => events);
      } else {
        setAllLoadedEvents((prev) => {
          if (events.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(e => e.id));
          const newEvents = events.filter(e => !existingIds.has(e.id));
          return [...prev, ...newEvents];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [events, eventsQuery.isLoading, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || eventsQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = eventsQuery.data?.total ?? 0;
        const loadedCount = allLoadedEvents.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, eventsQuery.isLoading, eventsQuery.data?.total, allLoadedEvents.length]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "table") {
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
    if (viewMode !== "table") {
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
      return (await response.json()) as LightningCurrentImportResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess(
        payload.task_id
          ? `导入任务已提交（任务ID: ${payload.task_id}），正在后台处理`
          : payload.warning_count > 0
            ? `导入任务已提交，存在 ${payload.warning_count} 条告警`
            : "导入任务已提交，正在后台处理",
      );
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
    mutationFn: async (eventId: string) => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/${eventId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return eventId;
    },
    onSuccess: async () => {
      setError("");
      setSuccess("雷电流事件已删除");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const openExceedanceModal = (event: LightningCurrentEventSummary) => {
    setSelectedEventForModal(event);
    setExceedanceModalOpen(true);
  };

  const openDetailModal = (event: LightningCurrentEventSummary) => {
    setSelectedEventForModal(event);
    setDetailModalOpen(true);
  };

  const openSampleModal = (event: LightningCurrentEventSummary) => {
    setSelectedEventForModal(event);
    setSamplePage(1);
    setSampleModalOpen(true);
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const renderLightningEventCard = (event: LightningCurrentEventSummary) => {
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "exceedance",
        label: "峰值超越概率",
        onClick: () => openExceedanceModal(event),
      },
      {
        type: "divider",
      },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: !canManage,
        onClick: () => {
          Modal.confirm({
            title: "删除事件",
            content: `确认删除事件 ${event.event_id} 吗？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: async () => {
              await deleteMutation.mutateAsync(event.id);
            },
          });
        },
      },
    ];

    return (
      <AntCard
        key={event.id}
        className="admin-lightning-events-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis>
              {event.source_file_name || "-"}
            </Typography.Text>
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
            <Typography.Text>{event.city || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">安装位置</Typography.Text>
            <Typography.Text>{event.install_position || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">传感器型号</Typography.Text>
            <Typography.Text>{event.sensor_model || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-events-card-field">
            <Typography.Text type="secondary">采样点数</Typography.Text>
            <Typography.Text>{event.sample_count}</Typography.Text>
          </div>
          <Space wrap style={{ width: "100%", justifyContent: "flex-start" }}>
            <Button
              size="small"
              onClick={() => openDetailModal(event)}
            >
              详情
            </Button>
            <Button
              size="small"
              onClick={() => openSampleModal(event)}
            >
              预览
            </Button>
          </Space>
        </Space>
      </AntCard>
    );
  };

  const eventColumns = useMemo<ColumnsType<LightningCurrentEventSummary>>(
    () => [
      {
        title: "文件名称",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string | null) => value || "-",
      },
      {
        title: "城市",
        dataIndex: "city",
        width: 120,
        render: (value: string | null) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 180,
        render: (value: string) => {
          const date = new Date(value);
          const year = date.getFullYear();
          const month = String(date.getMonth() + 1).padStart(2, '0');
          const day = String(date.getDate()).padStart(2, '0');
          const hour = String(date.getHours()).padStart(2, '0');
          const minute = String(date.getMinutes()).padStart(2, '0');
          const second = String(date.getSeconds()).padStart(2, '0');
          return `${year}-${month}-${day} ${hour}:${minute}:${second}`;
        },
      },
      {
        title: "采样点数",
        dataIndex: "sample_count",
        width: 100,
      },
      {
        title: "操作",
        key: "actions",
        width: 150,
        fixed: "right",
        render: (_: unknown, row) => {
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "exceedance",
              label: "峰值超越概率",
              onClick: () => openExceedanceModal(row),
            },
            {
              type: "divider",
            },
            {
              key: "delete",
              label: "删除",
              danger: true,
              disabled: !canManage,
              onClick: () => {
                Modal.confirm({
                  title: "删除事件",
                  content: `确认删除事件 ${row.event_id} 吗？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: async () => {
                    await deleteMutation.mutateAsync(row.id);
                  },
                });
              },
            },
          ];

          return (
            <Space>
              <Button
                size="small"
                onClick={() => openDetailModal(row)}
              >
                详情
              </Button>
              <Button
                size="small"
                onClick={() => openSampleModal(row)}
              >
                预览
              </Button>
              <Dropdown
                menu={{
                  items: moreMenuItems,
                }}
                trigger={["click"]}
              >
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, deleteMutation],
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

  const samples = samplesQuery.data?.items ?? [];
  const exceedance = exceedanceQuery.data?.thresholds ?? [];

  const chartData = samples.map((item) => ({
    time_us: item.time_us,
    current_ka: item.current_ka,
  }));

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-lightning-currents-page-card"
        title="雷电流幅值统计"
        extra={
          canManage && (
            <Button type="primary" onClick={() => setImportModalOpen(true)}>
              导入
            </Button>
          )
        }
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
            <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Input
                allowClear
                placeholder="按文件名搜索"
                value={keywordInput}
                onChange={(event) => handleKeywordChange(event.target.value)}
                onPressEnter={() => {
                  setSearchKeyword(keywordInput);
                  setPagination((prev) => ({ ...prev, current: 1 }));
                  setCardViewPage(1);
                  setAllLoadedEvents([]);
                }}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0 }}>
              <Button
                htmlType="button"
                icon={<SearchOutlined />}
                onClick={() => {
                  setSearchKeyword(keywordInput);
                  setPagination((prev) => ({ ...prev, current: 1 }));
                  setCardViewPage(1);
                  setAllLoadedEvents([]);
                  void queryClient.refetchQueries({ queryKey: [eventListPath] });
                }}
                className="admin-search-btn"
              >
                查询
              </Button>
            </Form.Item>
          </Form>
          </div>
        ) : (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item">
                <Input
                  allowClear
                  placeholder="按文件名搜索"
                  value={keywordInput}
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  onPressEnter={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((prev) => ({ ...prev, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedEvents([]);
                    void queryClient.refetchQueries({ queryKey: [eventListPath] });
                  }}
                />
              </Form.Item>
              <Form.Item>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((prev) => ({ ...prev, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedEvents([]);
                    void queryClient.refetchQueries({ queryKey: [eventListPath] });
                  }}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}

        {/* 导入任务状态展示 */}
        {activeBatches.length > 0 && (
          <div style={{ marginBottom: 12, marginTop: 8 }}>
            {activeBatches.map((batch) => {
              const statusColor =
                batch.status === "failed" ? "red" :
                batch.status === "processing" ? "blue" :
                "orange";
              const statusLabel =
                batch.status === "failed" ? "导入失败" :
                batch.status === "processing" ? "导入中" :
                "等待处理";
              return (
                <Tag key={batch.batch_id} color={statusColor} style={{ marginBottom: 4, padding: "2px 8px", fontSize: 13 }}>
                  {batch.source_file_name || "未命名文件"}
                  {" — "}
                  {statusLabel}
                </Tag>
              );
            })}
          </div>
        )}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="lightning-table-anchor"
            style={{ "--lightning-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<LightningCurrentEventSummary>
              rowKey={(row) => row.id}
              columns={eventColumns}
              dataSource={events}
              loading={eventsQuery.isFetching}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total: Math.max(eventsQuery.data?.total ?? 0, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: (total) => `共 ${eventsQuery.data?.total ?? 0} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1200, y: tableScrollY }}
            />
          </div>
        ) : (
          <div className="admin-lightning-events-card-view">
            {eventsQuery.isLoading && allLoadedEvents.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[180px]" />
              </div>
            ) : allLoadedEvents.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的事件。"
                />
              </div>
            ) : (
              <div className="admin-lightning-events-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedEvents.map((eventItem) => (
                    <Col key={eventItem.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderLightningEventCard(eventItem)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <AdminPageLoading tip="加载更多..." minHeightClassName="min-h-[60px]" />
                  </div>
                )}
                {allLoadedEvents.length >= (eventsQuery.data?.total ?? 0) && allLoadedEvents.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedEvents.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      <Modal
        title="导入雷电流数据"
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
              <InputNumber className="w-full" min={0.000001} precision={6} />
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
                      支持单列电流序列（每行一个值）或"双列 time,current"格式。
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

      <Modal
        title={selectedEventForModal ? `峰值超越概率（P 曲线） - ${selectedEventForModal.event_id}` : "峰值超越概率（P 曲线）"}
        open={exceedanceModalOpen}
        onCancel={() => {
          setExceedanceModalOpen(false);
          setSelectedEventForModal(null);
        }}
        footer={null}
        width={900}
        destroyOnClose
      >
        {exceedance.length === 0 ? (
          <Empty description="暂无统计数据" />
        ) : (
          <Space direction="vertical" size={16} className="w-full">
            <ResponsiveContainer width="100%" height={400}>
              <LineChart data={exceedance.map((point) => ({
                threshold_ka: point.threshold_ka,
                exceedance_probability_pct: point.exceedance_probability * 100,
              }))}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="threshold_ka"
                  label={{ value: "阈值 (kA)", position: "insideBottomRight", offset: -5 }}
                />
                <YAxis
                  label={{ value: "超越概率 (%)", angle: -90, position: "insideLeft", offset: 10 }}
                  domain={[0, 100]}
                />
                <Tooltip
                  formatter={(value: any) => [`${Number(value).toFixed(2)}%`, "超越概率"]}
                  labelFormatter={(label) => `阈值: ${Number(label).toFixed(2)} kA`}
                />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="exceedance_probability_pct"
                  stroke="#1890ff"
                  name="超越概率 (%)"
                  strokeWidth={2}
                  dot={{ r: 4 }}
                />
              </LineChart>
            </ResponsiveContainer>
            <Table
              rowKey={(row) => `${row.threshold_ka}`}
              pagination={false}
              dataSource={exceedance}
              columns={[
                { title: "阈值(kA)", dataIndex: "threshold_ka", width: 140, render: (value: number) => formatNumber(value, 2) },
                {
                  title: "超越概率",
                  dataIndex: "exceedance_probability",
                  width: 140,
                  render: (value: number) => `${(value * 100).toFixed(2)}%`,
                },
                { title: "超越次数", dataIndex: "exceedance_count", width: 140 },
              ]}
              size="small"
              loading={exceedanceQuery.isFetching}
            />
          </Space>
        )}
      </Modal>

      <Modal
        title={selectedEventForModal ? `事件详情 - ${selectedEventForModal.event_id}` : "事件详情"}
        open={detailModalOpen}
        onCancel={() => {
          setDetailModalOpen(false);
          setSelectedEventForModal(null);
        }}
        footer={null}
        width={900}
        destroyOnClose
      >
        {selectedEventForModal && (
          <Space direction="vertical" size={16} className="w-full">
            <div>
              <Typography.Title level={5}>基本信息</Typography.Title>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="城市">{formatNullable(selectedEventForModal.city)}</Descriptions.Item>
                <Descriptions.Item label="事件发生地点">{formatNullable(selectedEventForModal.location_tag)}</Descriptions.Item>
                <Descriptions.Item label="传感器">{formatNullable(selectedEventForModal.sensor_model)}</Descriptions.Item>
                <Descriptions.Item label="安装位置">{formatNullable(selectedEventForModal.install_position)}</Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    采样点数{" "}
                    <AntTooltip title="导入波形文件中解析出的数值行数，即该次雷击波形的时序采样长度。点数越多，波形记录越精细。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {selectedEventForModal.sample_count}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    采样间隔(us){" "}
                    <AntTooltip title="采样点之间的时间间隔（μs）。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedEventForModal.sample_interval_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label="海拔(m)">{formatNullable(selectedEventForModal.altitude_m)}</Descriptions.Item>
                <Descriptions.Item label="气压(hPa)">{formatNullable(selectedEventForModal.pressure_hpa)}</Descriptions.Item>
                <Descriptions.Item label="湿度(%)">{formatNullable(selectedEventForModal.humidity_percent)}</Descriptions.Item>
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
                  {formatNumber(selectedEventForModal.peak_current_ka, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="绝对峰值(kA)">{formatNumber(selectedEventForModal.peak_abs_current_ka, 3)}</Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    波形分类{" "}
                    <AntTooltip title="将实际波形的波前时间（T1）和半峰值时间（T2）与 IEC 标准波形模板匹配，归入最接近的分类：10/350（T1=10μs, T2=350μs，典型直击雷波形）、8/20（T1=8μs, T2=20μs，典型感应雷/测试波形）、1.2/50（T1=1.2μs, T2=50μs，典型操作冲击波形）。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNullable(selectedEventForModal.wave_shape)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    极性{" "}
                    <AntTooltip title="雷电流的主导方向。自然界约 90% 为负极性雷击，正极性雷击虽少但峰值更大、危害更强。正极性：正峰值大于负峰值；负极性：负峰值大于正峰值；混合：正负峰值相近。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatPolarity(selectedEventForModal.polarity)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    波前时间 T1(us){" "}
                    <AntTooltip title="电流从峰值的 10% 上升到 90% 所需时间的 1.25 倍（μs），反映雷电流上升的陡度。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedEventForModal.wavefront_time_t1_us, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    半峰值时间 T2(us){" "}
                    <AntTooltip title="从虚拟零点到电流下降到峰值 50% 的时间（μs），反映脉冲宽度。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedEventForModal.half_value_time_t2_us, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    陡度(kA/us){" "}
                    <AntTooltip title="波形中电流变化率的最大值（kA/μs），影响感应过电压的大小。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedEventForModal.steepness_ka_per_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    I²t 作用积分(J/Ω){" "}
                    <AntTooltip title="电流平方对时间的积分（J/Ω），衡量雷电流的热效应能量。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedEventForModal.action_integral_j_ohm, 3)}
                </Descriptions.Item>
              </Descriptions>
            </div>

            <div>
              <Typography.Title level={5}>多回击峰值分布</Typography.Title>
              {selectedEventForModal.stroke_peaks_json && selectedEventForModal.stroke_peaks_json.length > 0 ? (
                <>
                  <Descriptions bordered size="small" column={1} style={{ marginBottom: 12 }}>
                    <Descriptions.Item label={
                      <span>
                        回击数{" "}
                        <AntTooltip title="一次雷击过程中检测到的多次放电次数。一次雷击通常包含 3~5 次回击，主峰最高，后续回击会产生累积热效应。">
                          <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                        </AntTooltip>
                      </span>
                    }>
                      {selectedEventForModal.stroke_count}
                    </Descriptions.Item>
                  </Descriptions>
                  <ResponsiveContainer width="100%" height={250}>
                    <LineChart data={selectedEventForModal.stroke_peaks_json.map((peak: any, idx: number) => ({
                      index: idx + 1,
                      time_us: peak.time_us || 0,
                      current_ka: peak.current_ka || 0,
                    }))}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="index" label={{ value: "回击序号", position: "insideBottomRight", offset: -5 }} />
                      <YAxis label={{ value: "峰值电流 (kA)", angle: -90, position: "insideLeft", offset: 10 }} />
                      <Tooltip
                        formatter={(value: any, name?: string | number) => {
                          if (name === "current_ka") return [formatNumber(value, 3), "峰值电流 (kA)"];
                          if (name === "time_us") return [formatNumber(value, 2), "时间 (μs)"];
                          return [value, name];
                        }}
                        labelFormatter={(label) => `回击 ${label}`}
                      />
                      <Legend />
                      <Line type="monotone" dataKey="current_ka" stroke="#1890ff" name="峰值电流 (kA)" strokeWidth={2} dot={{ r: 4 }} />
                    </LineChart>
                  </ResponsiveContainer>
                </>
              ) : (
                <Empty description="暂无多回击数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
              )}
            </div>

          </Space>
        )}
      </Modal>

      <Modal
        title={selectedEventForModal ? `采样预览 - ${selectedEventForModal.event_id}` : "采样预览"}
        open={sampleModalOpen}
        onCancel={() => {
          setSampleModalOpen(false);
          setSelectedEventForModal(null);
          setSamplePage(1);
        }}
        footer={null}
        width={1200}
        destroyOnClose
      >
        <Space direction="vertical" size={16} className="w-full">
          {samples.length === 0 ? (
            <Empty description="暂无采样数据" />
          ) : (
            <>
              <ResponsiveContainer width="100%" height={400}>
                <LineChart data={chartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="time_us" label={{ value: "时间 (μs)", position: "insideBottomRight", offset: -5 }} />
                  <YAxis label={{ value: "电流 (kA)", angle: -90, position: "insideLeft", offset: 10 }} />
                  <Tooltip
                    formatter={(value: any) => [formatNumber(value, 3), "电流 (kA)"]}
                    labelFormatter={(label) => `时间: ${formatNumber(label, 2)} μs`}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="current_ka" stroke="#8884d8" name="电流 (kA)" dot={false} />
                </LineChart>
              </ResponsiveContainer>
              <Table<LightningCurrentSampleItem>
                rowKey={(row) => row.id}
                dataSource={samples}
                loading={samplesQuery.isFetching}
                pagination={{
                  current: samplePage,
                  pageSize: samplePageSize,
                  total: samplesQuery.data?.total ?? 0,
                  showSizeChanger: true,
                  showTotal: (total) => `共 ${total} 条`,
                  pageSizeOptions: [20, 50, 100, 200],
                  hideOnSinglePage: false,
                  onChange: (page, pageSize) => {
                    setSamplePage(page);
                    if (pageSize !== samplePageSize) {
                      setSamplePageSize(pageSize);
                      setSamplePage(1);
                    }
                  },
                }}
                columns={[
                  { title: "序号", dataIndex: "seq_no", width: 100 },
                  { title: "时间 (μs)", dataIndex: "time_us", width: 150, render: (value: number) => formatNumber(value, 2) },
                  { title: "电流 (kA)", dataIndex: "current_ka", width: 150, render: (value: number) => formatNumber(value, 3) },
                ]}
                size="small"
                scroll={{ y: 300 }}
              />
            </>
          )}
        </Space>
      </Modal>
    </div>
  );
}
