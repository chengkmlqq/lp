"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Row,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
} from "antd";
import { MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useMemo, useRef, useState, type ComponentType, type CSSProperties, type RefAttributes, useEffect } from "react";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { LightningDistributionMap } from "@/components/lightning-distribution-map";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  LightningDistributionImportResponse,
  LightningDistributionScatterPoint,
  LightningDistributionStatsResponse,
  LightningPolarity,
  LightningTowerBufferStatsResponse,
  LightningImportBatchSummary,
  LightningImportBatchListResponse,
  LightningImportBatchEventsResponse,
  LightningImportBatchEventItem,
} from "@/types/auth";

type ImportFormValues = {
  event_year: number;
  region_id: string;
  city: string;
  longitude: number;
  latitude: number;
  notes: string;
};

type DistributionFilterValues = {
  grid_size_km: number;
  years: number | null;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  event_year: new Date().getFullYear(),
  region_id: "",
  city: "",
  longitude: 0,
  latitude: 0,
  notes: "",
};

const INITIAL_DISTRIBUTION_FILTERS: DistributionFilterValues = {
  grid_size_km: 1,
  years: null,
};

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_VIEWPORT_GAP = 40;
const LIGHTNING_TABLE_FALLBACK_RESERVE = 220;

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

export default function AdminLightningDistributionPage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [importForm] = Form.useForm<ImportFormValues>();
  const [distributionForm] = Form.useForm<DistributionFilterValues>();

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [statsModalOpen, setStatsModalOpen] = useState(false);

  const [distributionFilters, setDistributionFilters] = useState<DistributionFilterValues>(INITIAL_DISTRIBUTION_FILTERS);
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [selectedBatchForEvents, setSelectedBatchForEvents] = useState<LightningImportBatchSummary | null>(null);
  const [selectedBatchForScatter, setSelectedBatchForScatter] = useState<LightningImportBatchSummary | null>(null);
  const [eventsModalOpen, setEventsModalOpen] = useState(false);
  const [scatterModalOpen, setScatterModalOpen] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedBatches, setAllLoadedBatches] = useState<LightningImportBatchSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });


  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");

  const trimmedKeyword = searchKeyword.trim();
  const importBatchesPath = useMemo(() => {
    const params = new URLSearchParams();
    if (trimmedKeyword) params.set("keyword", trimmedKeyword);
    params.set("limit", "100");
    params.set("offset", "0");
    return `/api/v1/lightning-currents/import-batches?${params.toString()}`;
  }, [trimmedKeyword]);

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
  });

  const importBatches = useMemo(() => importBatchesQuery.data?.items ?? [], [importBatchesQuery.data?.items]);
  const batchesError = importBatchesQuery.error instanceof Error ? importBatchesQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || batchesError,
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

  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const values = importForm.getFieldsValue(true);
      const formData = new FormData();
      formData.append("file", file);
      formData.append("event_year", String(values.event_year));
      formData.append("region_id", values.region_id.trim());
      formData.append("city", values.city.trim());
      formData.append("longitude", String(values.longitude));
      formData.append("latitude", String(values.latitude));
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());

      const response = await fetchWithAuth("/api/v1/lightning-currents/import-distribution", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionImportResponse;
    },

    onSuccess: async (payload) => {
      setError("");
      setSuccess(
        payload.warning_count > 0
          ? `分布导入完成：共 ${payload.record.total_points} 个坐标点，跳过 ${payload.skipped_count} 条，告警 ${payload.warning_count} 条`
          : `分布导入完成：共 ${payload.record.total_points} 个坐标点`,
      );
      setImportModalOpen(false);
      importForm.resetFields();
      setSelectedFile(null);
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "分布导入失败");
    },
  });

  const deleteBatchMutation = useMutation({
    mutationFn: async (batch: LightningImportBatchSummary) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const params = new URLSearchParams();
      if (batch.source_file_name) params.set("source_file_name", batch.source_file_name);
      params.set("import_time", batch.import_time);
      if (batch.region_id) params.set("region_id", batch.region_id);
      if (batch.location_tag) params.set("location_tag", batch.location_tag);
      if (batch.city) params.set("city", batch.city);

      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/import-batches?${params.toString()}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return response.json();
    },
    onSuccess: async () => {
      setError("");
      setSuccess("批次删除成功");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除批次失败");
    },
  });

  const openEventsModal = (batch: LightningImportBatchSummary) => {
    setSelectedBatchForEvents(batch);
    setEventsModalOpen(true);
  };

  const openScatterModal = (batch: LightningImportBatchSummary) => {
    setSelectedBatchForScatter(batch);
    setScatterModalOpen(true);
  };

  const closeImportModal = () => {
    setImportModalOpen(false);
    importForm.resetFields();
    setSelectedFile(null);
  };

  const handleImportConfirm = async () => {
    try {
      await importForm.validateFields();
      if (selectedFile) {
        importMutation.mutate(selectedFile);
      }
    } catch {
      // 表单校验失败时不触发导入
    }
  };

  const closeEventsModal = () => {
    setEventsModalOpen(false);
    setSelectedBatchForEvents(null);
  };

  const closeScatterModal = () => {
    setScatterModalOpen(false);
    setSelectedBatchForScatter(null);
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setAllLoadedBatches([]);
  };

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
    if (viewMode !== "card" || importBatchesQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedBatches(() => importBatches);
      } else {
        setAllLoadedBatches((prev) => {
          if (importBatches.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(b => b.batch_id));
          const newBatches = importBatches.filter(b => !existingIds.has(b.batch_id));
          return [...prev, ...newBatches];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [importBatches, importBatchesQuery.isLoading, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || importBatchesQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const loadedCount = allLoadedBatches.length;
        const totalCount = importBatches.length;

        if (loadedCount < totalCount) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, importBatchesQuery.isLoading, allLoadedBatches.length, importBatches.length]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "table") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [error, batchesError, importBatches.length, importBatchesQuery.isFetching, pagination.current, pagination.pageSize, updateTableScrollY, viewMode]);

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

  const batchColumns = useMemo<ColumnsType<LightningImportBatchSummary>>(
    () => [
      {
        title: "城市",
        dataIndex: "city",
        width: 120,
        render: (value: string | null) => value || "-",
      },
      {
        title: "地点标签",
        dataIndex: "location_tag",
        width: 150,
        render: (value: string | null) => value || "-",
      },
      {
        title: "文件名",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string | null) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "import_time",
        width: 180,
        render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
      },
      {
        title: "事件数",
        dataIndex: "event_count",
        width: 100,
        render: (value: number) => value,
      },
      {
        title: "最大电流(kA)",
        dataIndex: "max_abs_current_ka",
        width: 120,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "平均电流(kA)",
        dataIndex: "avg_abs_current_ka",
        width: 120,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "操作",
        key: "actions",
        width: canManage ? 280 : 200,
        fixed: "right",
        render: (_: unknown, row) => (
          <Space wrap>
            <Button size="small" onClick={() => openEventsModal(row)}>
              事件明细
            </Button>
            <Button size="small" onClick={() => openScatterModal(row)}>
              散点图
            </Button>
            {canManage && (
              <Popconfirm
                title="确认删除该批次所有事件记录？"
                description="此操作不可恢复，请谨慎操作。"
                onConfirm={() => deleteBatchMutation.mutate(row)}
                okText="确认删除"
                cancelText="取消"
                okButtonProps={{ danger: true }}
              >
                <Button size="small" danger loading={deleteBatchMutation.isPending}>
                  删除
                </Button>
              </Popconfirm>
            )}
          </Space>
        ),
      },
    ],
    [canManage, deleteBatchMutation],
  );

  const renderBatchCard = (batch: LightningImportBatchSummary) => {
    const dropdownItems: MenuProps["items"] = [
      {
        key: "events",
        label: "事件明细",
        onClick: () => openEventsModal(batch),
      },
      {
        key: "scatter",
        label: "散点图",
        onClick: () => openScatterModal(batch),
      },
      ...(canManage
        ? [
            {
              key: "delete",
              label: "删除",
              danger: true as const,
              onClick: () => {
                Modal.confirm({
                  title: "确认删除",
                  content: "确认删除该批次所有事件记录？此操作不可恢复。",
                  okText: "确认删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => deleteBatchMutation.mutate(batch),
                });
              },
            },
          ]
        : []),
    ];

    return (
      <AntCard
        key={batch.batch_id}
        className="admin-lightning-distribution-batch-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong>{batch.source_file_name || "未命名文件"}</Typography.Text>
          </Space>
        }
        extra={
          <Dropdown menu={{ items: dropdownItems }}>
            <Button type="text" size="small" icon={<MoreOutlined />} />
          </Dropdown>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">城市</Typography.Text>
            <Typography.Text>{batch.city || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">地点标签</Typography.Text>
            <Typography.Text>{batch.location_tag || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">导入时间</Typography.Text>
            <Typography.Text>
              {new Date(batch.import_time).toLocaleString("zh-CN", { hour12: false })}
            </Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">事件数</Typography.Text>
            <Typography.Text>{batch.event_count}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">电流范围</Typography.Text>
            <Typography.Text>
              {formatNumber(batch.max_abs_current_ka, 2)} kA (最大)
            </Typography.Text>
          </div>
        </Space>
      </AntCard>
    );
  };

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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问地闪密度统计页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `lightning.read`）。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-lightning-distribution-page-card"
        title="地闪密度统计"
        extra={
          canManage && (
            <Button type="primary" onClick={() => setImportModalOpen(true)}>
              导入地闪密度数据
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
                    placeholder="按地点/标签/文件名筛选"
                    value={keywordInput}
                    onChange={(event) => handleKeywordChange(event.target.value)}
                    onPressEnter={handleSearch}
                  />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
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
                  placeholder="按地点/标签/文件名筛选"
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
        )}

        {viewMode === "table" ? (
          <div ref={tableScrollAnchorRef} className="admin-lightning-distribution-table-anchor" style={{ "--admin-lightning-distribution-table-body-min-height": `${tableScrollY}px` } as CSSProperties}>
            <Table<LightningImportBatchSummary>
                rowKey="batch_id"
                columns={batchColumns}
                dataSource={importBatches}
                loading={importBatchesQuery.isFetching}
                tableLayout="fixed"
                pagination={{
                  current: pagination.current,
                  pageSize: pagination.pageSize,
                  total: Math.max(importBatches.length, 1),
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  showTotal: (total) => `共 ${importBatches.length} 条`,
                  hideOnSinglePage: false,
                  style: { marginBottom: 0 },
                  onChange: (page, pageSize) => {
                    setPagination({ current: page, pageSize });
                  },
                }}
                scroll={{ x: 1400, y: tableScrollY }}
                locale={{
                  emptyText: (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="未找到符合筛选条件的导入记录。"
                    />
                  ),
                }}
              />
            </div>
          ) : (
            <div className="admin-lightning-distribution-card-view">
              {importBatchesQuery.isLoading && allLoadedBatches.length === 0 ? (
                <div className="admin-lightning-distribution-card-view-state">
                  <Spin tip="加载中..." />
                </div>
              ) : allLoadedBatches.length === 0 ? (
                <div className="admin-lightning-distribution-card-view-state">
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的导入记录。"
                  />
                </div>
              ) : (
                <div className="admin-lightning-distribution-card-view-content">
                  <Row gutter={[12, 12]}>
                    {allLoadedBatches.map((batch) => (
                      <Col key={batch.batch_id} xs={24} sm={24} md={12} lg={8} xl={6}>
                        {renderBatchCard(batch)}
                      </Col>
                    ))}
                  </Row>
                  {isLoadingMore && (
                    <div style={{ textAlign: "center", padding: "20px 0" }}>
                      <Spin tip="加载更多..." />
                    </div>
                  )}
                  {allLoadedBatches.length >= importBatches.length && allLoadedBatches.length > 0 && (
                    <div style={{ textAlign: "center", padding: "20px 0" }}>
                      <Typography.Text type="secondary">
                        已加载全部 {allLoadedBatches.length} 条数据
                      </Typography.Text>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
      </AntCard>

      <Modal
        title="导入地闪密度数据"
        open={importModalOpen}
        onCancel={closeImportModal}
        footer={null}
        width={800}
        destroyOnClose
      >
        <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={INITIAL_IMPORT_VALUES}>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="city" label="城市/区域" rules={[{ required: true, message: "请填写城市/区域" }]}>
              <Input placeholder="例如 上海" />
            </Form.Item>
            <Form.Item name="region_id" label="区域标识" rules={[{ required: true, message: "请填写区域标识" }]}>
              <Input placeholder="例如 SH-001" />
            </Form.Item>
            <Form.Item name="longitude" label="参考中心经度" rules={[{ required: true, message: "请填写参考中心经度" }]}>
              <InputNumber className="w-full" placeholder="例如 121.47" />
            </Form.Item>
            <Form.Item name="latitude" label="参考中心纬度" rules={[{ required: true, message: "请填写参考中心纬度" }]}>
              <InputNumber className="w-full" placeholder="例如 31.23" />
            </Form.Item>
            <Form.Item name="event_year" label="发生年份" rules={[{ required: true, message: "请填写年份" }]}>
              <InputNumber className="w-full" min={1900} max={2100} />
            </Form.Item>
            <Form.Item name="notes" label="数据说明">
              <Input placeholder="可填写数据来源、采集说明等" />
            </Form.Item>
          </div>

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
                      支持包含经纬度和电流的 CSV 或 TXT 文件。
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
              onClick={handleImportConfirm}
            >
              确认导入
            </Button>
          </div>
        </Form>
      </Modal>

      <EventsModal
        batch={selectedBatchForEvents}
        open={eventsModalOpen}
        onClose={closeEventsModal}
        fetchWithAuth={fetchWithAuth}
      />

      <ScatterModal
        batch={selectedBatchForScatter}
        open={scatterModalOpen}
        onClose={closeScatterModal}
        fetchWithAuth={fetchWithAuth}
        distributionFilters={distributionFilters}
      />
    </div>
  );
}

function EventsModal({
  batch,
  open,
  onClose,
  fetchWithAuth,
}: {
  batch: LightningImportBatchSummary | null;
  open: boolean;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
}) {
  const eventsQuery = useQuery({
    queryKey: [
      "/api/v1/lightning-currents/import-batches/events",
      batch?.source_file_name,
      batch?.import_time,
      batch?.region_id,
      batch?.location_tag,
      batch?.city,
    ],
    enabled: open && !!batch,
    queryFn: async () => {
      if (!batch) return null;
      const params = new URLSearchParams();
      if (batch.source_file_name) params.set("source_file_name", batch.source_file_name);
      params.set("import_time", batch.import_time);
      if (batch.region_id) params.set("region_id", batch.region_id);
      if (batch.location_tag) params.set("location_tag", batch.location_tag);
      if (batch.city) params.set("city", batch.city);

      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/import-batches/events?${params.toString()}`
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningImportBatchEventsResponse;
    },
  });

  const events = eventsQuery.data?.events ?? [];

  const eventColumns: ColumnsType<LightningImportBatchEventItem> = [
    {
      title: "事件编号",
      dataIndex: "event_id",
      width: 180,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: "经度",
      dataIndex: "longitude",
      width: 120,
      render: (value: number | null) => formatNumber(value, 5),
    },
    {
      title: "纬度",
      dataIndex: "latitude",
      width: 120,
      render: (value: number | null) => formatNumber(value, 5),
    },
    {
      title: "电流(kA)",
      dataIndex: "current_ka",
      width: 120,
      render: (value: number | null) => formatNumber(value, 2),
    },
    {
      title: "绝对值(kA)",
      dataIndex: "abs_current_ka",
      width: 120,
      render: (value: number | null) => formatNumber(value, 2),
    },
    {
      title: "极性",
      dataIndex: "polarity",
      width: 100,
      render: (value: LightningPolarity) => formatPolarity(value),
    },
    {
      title: "事件时间",
      dataIndex: "event_time",
      width: 180,
      render: (value: string | null) =>
        value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "-",
    },
  ];

  return (
    <Modal
      title={batch ? `事件明细 - ${batch.source_file_name || "未命名"}` : "事件明细"}
      open={open}
      onCancel={onClose}
      footer={null}
      width={1200}
      destroyOnClose
    >
      {batch && (
        <Space direction="vertical" size={16} className="w-full">
          <Descriptions bordered size="small" column={2}>
            <Descriptions.Item label="文件名">{batch.source_file_name || "-"}</Descriptions.Item>
            <Descriptions.Item label="导入时间">
              {new Date(batch.import_time).toLocaleString("zh-CN", { hour12: false })}
            </Descriptions.Item>
            <Descriptions.Item label="城市">{batch.city || "-"}</Descriptions.Item>
            <Descriptions.Item label="地点标签">{batch.location_tag || "-"}</Descriptions.Item>
            <Descriptions.Item label="事件总数">{batch.event_count}</Descriptions.Item>
          </Descriptions>

          <Table
            rowKey="id"
            columns={eventColumns}
            dataSource={events}
            loading={eventsQuery.isLoading}
            pagination={{ pageSize: 20, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
            scroll={{ x: 1000, y: 400 }}
            locale={{
              emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无事件数据" />,
            }}
          />
        </Space>
      )}
    </Modal>
  );
}

function ScatterModal({
  batch,
  open,
  onClose,
  fetchWithAuth,
  distributionFilters,
}: {
  batch: LightningImportBatchSummary | null;
  open: boolean;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  distributionFilters: DistributionFilterValues;
}) {
  const distributionStatsPath = useMemo(() => {
    if (!batch || !open) return null;
    const params = new URLSearchParams();
    if (batch.region_id) params.set("region_id", batch.region_id);
    if (batch.location_tag) params.set("location_tag", batch.location_tag);
    if (batch.city) params.set("city", batch.city);
    if (distributionFilters.years !== null) params.set("years", String(distributionFilters.years));
    params.set("grid_size_km", String(distributionFilters.grid_size_km));
    params.set("grid_limit", "1000");
    params.set("scatter_limit", "2000");
    return `/api/v1/lightning-currents/stats/distribution?${params.toString()}`;
  }, [batch, open, distributionFilters]);

  const distributionQuery = useQuery({
    queryKey: [distributionStatsPath],
    enabled: !!distributionStatsPath,
    queryFn: async () => {
      if (!distributionStatsPath) return null;
      const response = await fetchWithAuth(distributionStatsPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionStatsResponse;
    },
  });

  const distributionStats = distributionQuery.data;

  return (
    <Modal
      title={batch ? `散点图 - ${batch.source_file_name || "未命名"}` : "散点图"}
      open={open}
      onCancel={onClose}
      footer={null}
      width={1200}
      destroyOnClose
    >
      {batch && distributionStats && (
        <Space direction="vertical" size={16} className="w-full">
          <Descriptions bordered size="small" column={4}>
            <Descriptions.Item label="记录总数">{distributionStats.summary.total_records}</Descriptions.Item>
            <Descriptions.Item label="统计面积(km²)">
              {formatNumber(distributionStats.summary.area_km2, 3)}
            </Descriptions.Item>
            <Descriptions.Item label="统计年限">
              {formatNumber(distributionStats.summary.data_years, 3)}
            </Descriptions.Item>
            <Descriptions.Item label="整体 Ng">
              {formatNumber(distributionStats.summary.overall_ng_per_km2_year, 4)}
            </Descriptions.Item>
            <Descriptions.Item label="Imax(kA)">
              {formatNumber(distributionStats.summary.max_abs_current_ka, 2)}
            </Descriptions.Item>
            <Descriptions.Item label="Iavg(kA)">
              {formatNumber(distributionStats.summary.avg_abs_current_ka, 2)}
            </Descriptions.Item>
            <Descriptions.Item label="正极占比">
              {`${(distributionStats.polarity.positive_ratio * 100).toFixed(2)}%`}
            </Descriptions.Item>
            <Descriptions.Item label="负极占比">
              {`${(distributionStats.polarity.negative_ratio * 100).toFixed(2)}%`}
            </Descriptions.Item>
          </Descriptions>

          <div>
            <Typography.Title level={5}>空间分布地图</Typography.Title>
            <LightningDistributionMap
              points={distributionStats.scatter_points}
              grids={distributionStats.grid_cells}
              loading={distributionQuery.isFetching}
            />
          </div>
        </Space>
      )}
    </Modal>
  );
}

