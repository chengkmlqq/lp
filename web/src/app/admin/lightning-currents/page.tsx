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
  Progress,
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
import { MoreOutlined, QuestionCircleOutlined, SearchOutlined } from "@ant-design/icons";
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
  LightningAmplitudeRecord,
  LightningAmplitudeListResponse,
  LightningAmplitudeImportResponse,
  LightningAmplitudeStatusResponse,
  LightningCurrentExceedanceResponse,
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
  const [selectedRecordForModal, setSelectedRecordForModal] = useState<LightningAmplitudeRecord | null>(null);
  const [activeImportId, setActiveImportId] = useState<string | null>(null);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedRecords, setAllLoadedRecords] = useState<LightningAmplitudeRecord[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
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
    refetchInterval: 5000,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeListResponse;
    },
  });

  const records = useMemo(() => recordsQuery.data?.items ?? [], [recordsQuery.data?.items]);

  // ---- 导入任务进度轮询 ----
  const importStatusPath = activeImportId
    ? `/api/v1/lightning-currents/amplitudes/${activeImportId}/status`
    : null;
  const importStatusQuery = useQuery({
    queryKey: [importStatusPath],
    enabled: !!importStatusPath,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 2000;
    },
    queryFn: async () => {
      if (!importStatusPath) return null;
      const response = await fetchWithAuth(importStatusPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningAmplitudeStatusResponse;
    },
  });

  const activeRecord = importStatusQuery.data?.record ?? null;
  const activeStatus = importStatusQuery.data?.status;

  const exceedancePath = `/api/v1/lightning-currents/stats/exceedance`;

  const exceedanceQuery = useQuery({
    queryKey: [exceedancePath],
    enabled: !!user && canRead && exceedanceModalOpen,
    queryFn: async () => {
      const response = await fetchWithAuth(exceedancePath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningCurrentExceedanceResponse;
    },
  });

  const listError = recordsQuery.error instanceof Error ? recordsQuery.error.message : "";
  const statsError = exceedanceQuery.error instanceof Error ? exceedanceQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || listError || statsError,
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
  }, [error, listError, statsError, records.length, recordsQuery.isFetching, updateTableScrollY, viewMode]);

  useEffect(() => {
    if (viewMode !== "card" || recordsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedRecords(() => records);
      } else {
        setAllLoadedRecords((prev) => {
          if (records.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(e => e.id));
          const newRecords = records.filter(e => !existingIds.has(e.id));
          return [...prev, ...newRecords];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [records, recordsQuery.isLoading, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || recordsQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = recordsQuery.data?.total ?? 0;
        const loadedCount = allLoadedRecords.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, recordsQuery.isLoading, recordsQuery.data?.total, allLoadedRecords.length]);

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

  // 导入任务完成/失败时的反馈
  useEffect(() => {
    if (!activeImportId) return;
    if (activeStatus === "completed") {
      if (activeRecord) {
        setSuccess(
          `导入完成：采样点 ${activeRecord.sample_count} 个，峰值 ${formatNumber(activeRecord.peak_abs_current_ka, 2)}kA`,
        );
      } else {
        setSuccess("导入完成");
      }
      setActiveImportId(null);
    } else if (activeStatus === "failed") {
      setError(activeRecord?.error_message || "导入失败，请在列表中对失败记录执行重试");
      setActiveImportId(null);
    }
  }, [activeStatus, activeImportId, activeRecord]);

  // 导入中弹窗展示进度
  const importProgressModalOpen = !!activeImportId && (activeStatus === "processing" || activeStatus === "pending");

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
      setActiveImportId(payload.amplitude_id);
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
      setActiveImportId(payload.amplitude_id);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "重试失败");
    },
  });

  const openExceedanceModal = () => {
    setExceedanceModalOpen(true);
  };

  const openDetailModal = (record: LightningAmplitudeRecord) => {
    setSelectedRecordForModal(record);
    setDetailModalOpen(true);
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setAllLoadedRecords([]);
    void queryClient.refetchQueries({ queryKey: [listPath] });
  };

  const renderRecordCard = (record: LightningAmplitudeRecord) => {
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "detail",
        label: "详情",
        onClick: () => openDetailModal(record),
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
        title: "操作",
        key: "actions",
        width: 220,
        fixed: "right",
        render: (_: unknown, row) => {
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "exceedance",
              label: "峰值超越概率",
              onClick: () => openExceedanceModal(),
            },
            {
              type: "divider",
            },
            ...(row.status === "failed" && canManage
              ? [
                  {
                    key: "retry",
                    label: "重试",
                    onClick: () => retryMutation.mutate(row),
                  },
                  {
                    type: "divider" as const,
                  },
                ]
              : []),
            {
              key: "delete",
              label: "删除",
              danger: true,
              disabled: !canManage,
              onClick: () => {
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
              },
            },
          ];

          return (
            <Space wrap>
              <Button
                size="small"
                onClick={() => openDetailModal(row)}
              >
                详情
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
    [canManage, deleteMutation, retryMutation],
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

  const exceedance = exceedanceQuery.data?.thresholds ?? [];

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
        </div>

        {viewMode === "table" ? (
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
            {recordsQuery.isLoading && allLoadedRecords.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[180px]" />
              </div>
            ) : allLoadedRecords.length === 0 ? (
              <div className="admin-lightning-events-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的记录。"
                />
              </div>
            ) : (
              <div className="admin-lightning-events-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedRecords.map((record) => (
                    <Col key={record.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderRecordCard(record)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <AdminPageLoading tip="加载更多..." minHeightClassName="min-h-[60px]" />
                  </div>
                )}
                {allLoadedRecords.length >= (recordsQuery.data?.total ?? 0) && allLoadedRecords.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedRecords.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

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

      <Modal
        title="峰值超越概率（P 曲线）"
        open={exceedanceModalOpen}
        onCancel={() => {
          setExceedanceModalOpen(false);
        }}
        footer={null}
        width={900}
        destroyOnClose
      >
        {exceedance.length === 0 ? (
          <Empty description="暂无统计数据（需先导入并完成解析）" />
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
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
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
        title={selectedRecordForModal ? `记录详情 - ${selectedRecordForModal.event_id ?? selectedRecordForModal.source_file_name}` : "记录详情"}
        open={detailModalOpen}
        onCancel={() => {
          setDetailModalOpen(false);
          setSelectedRecordForModal(null);
        }}
        footer={null}
        width={900}
        destroyOnClose
      >
        {selectedRecordForModal && (
          <Space direction="vertical" size={16} className="w-full">
            <div>
              <Typography.Title level={5}>基本信息</Typography.Title>
              <Descriptions bordered size="small" column={2}>
                <Descriptions.Item label="状态">
                  {(() => {
                    const meta = STATUS_META[selectedRecordForModal.status] ?? { color: "default", label: selectedRecordForModal.status };
                    return <Tag color={meta.color}>{meta.label}</Tag>;
                  })()}
                </Descriptions.Item>
                <Descriptions.Item label="事件编号">{formatNullable(selectedRecordForModal.event_id)}</Descriptions.Item>
                <Descriptions.Item label="城市">{formatNullable(selectedRecordForModal.city)}</Descriptions.Item>
                <Descriptions.Item label="事件发生地点">{formatNullable(selectedRecordForModal.location_tag)}</Descriptions.Item>
                <Descriptions.Item label="传感器">{formatNullable(selectedRecordForModal.sensor_model)}</Descriptions.Item>
                <Descriptions.Item label="安装位置">{formatNullable(selectedRecordForModal.install_position)}</Descriptions.Item>
                <Descriptions.Item label="发生时间">{formatNullable(selectedRecordForModal.event_time)}</Descriptions.Item>
                <Descriptions.Item label="采样点数">{selectedRecordForModal.sample_count}</Descriptions.Item>
                <Descriptions.Item label="采样间隔(us)">{formatNumber(selectedRecordForModal.sample_interval_us, 6)}</Descriptions.Item>
                <Descriptions.Item label="海拔(m)">{formatNullable(selectedRecordForModal.altitude_m)}</Descriptions.Item>
                <Descriptions.Item label="气压(hPa)">{formatNullable(selectedRecordForModal.pressure_hpa)}</Descriptions.Item>
                <Descriptions.Item label="湿度(%)">{formatNullable(selectedRecordForModal.humidity_percent)}</Descriptions.Item>
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
                  {formatNumber(selectedRecordForModal.peak_current_ka, 3)}
                </Descriptions.Item>
                <Descriptions.Item label="绝对峰值(kA)">{formatNumber(selectedRecordForModal.peak_abs_current_ka, 3)}</Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    波形分类{" "}
                    <AntTooltip title="将实际波形的波前时间（T1）和半峰值时间（T2）与 IEC 标准波形模板匹配，归入最接近的分类：10/350（T1=10μs, T2=350μs，典型直击雷波形）、8/20（T1=8μs, T2=20μs，典型感应雷/测试波形）、1.2/50（T1=1.2μs, T2=50μs，典型操作冲击波形）。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNullable(selectedRecordForModal.wave_shape)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    极性{" "}
                    <AntTooltip title="雷电流的主导方向。自然界约 90% 为负极性雷击，正极性雷击虽少但峰值更大、危害更强。正极性：正峰值大于负峰值；负极性：负峰值大于正峰值；混合：正负峰值相近。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatPolarity(selectedRecordForModal.polarity)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    波前时间 T1(us){" "}
                    <AntTooltip title="电流从峰值的 10% 上升到 90% 所需时间的 1.25 倍（μs），反映雷电流上升的陡度。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedRecordForModal.wavefront_time_t1_us, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    半峰值时间 T2(us){" "}
                    <AntTooltip title="从虚拟零点到电流下降到峰值 50% 的时间（μs），反映脉冲宽度。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedRecordForModal.half_value_time_t2_us, 3)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    陡度(kA/us){" "}
                    <AntTooltip title="波形中电流变化率的最大值（kA/μs），影响感应过电压的大小。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedRecordForModal.steepness_ka_per_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label={
                  <span>
                    I²t 作用积分(J/Ω){" "}
                    <AntTooltip title="电流平方对时间的积分（J/Ω），衡量雷电流的热效应能量。">
                      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                    </AntTooltip>
                  </span>
                }>
                  {formatNumber(selectedRecordForModal.action_integral_j_ohm, 3)}
                </Descriptions.Item>
              </Descriptions>
            </div>

            {selectedRecordForModal.stroke_peaks_json && selectedRecordForModal.stroke_peaks_json.length > 0 && (
              <div>
                <Typography.Title level={5}>多回击峰值分布</Typography.Title>
                <Descriptions bordered size="small" column={1} style={{ marginBottom: 12 }}>
                  <Descriptions.Item label="回击数">{selectedRecordForModal.stroke_count}</Descriptions.Item>
                </Descriptions>
                <ResponsiveContainer width="100%" height={250}>
                  <LineChart data={selectedRecordForModal.stroke_peaks_json.map((peak: Record<string, unknown>, idx: number) => ({
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

            {selectedRecordForModal.status === "failed" && (
              <div>
                <Typography.Title level={5}>失败原因</Typography.Title>
                <Typography.Paragraph type="danger">
                  {selectedRecordForModal.error_message || "未知错误"}
                </Typography.Paragraph>
                {canManage && (
                  <Button danger loading={retryMutation.isPending} onClick={() => retryMutation.mutate(selectedRecordForModal)}>
                    重试
                  </Button>
                )}
              </div>
            )}
          </Space>
        )}
      </Modal>

      <Modal
        title="导入处理中"
        open={importProgressModalOpen}
        footer={null}
        closable={false}
        width={420}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text>
            正在解析文件并提取波形特征…
          </Typography.Text>
          <Progress percent={activeRecord?.progress ?? 0} status={activeStatus === "failed" ? "exception" : "active"} />
        </Space>
      </Modal>
    </div>
  );
}
