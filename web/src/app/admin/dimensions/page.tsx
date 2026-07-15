"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  type CardProps,
  type MenuProps,
} from "antd";
import { MoreOutlined, EditOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { DimensionItem, DimensionItemListResponse } from "@/types/dimension";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type CreateDimensionValues = {
  dimension_type: string | string[];
  code: string;
  name: string;
  parent_id?: string;
  description?: string;
  is_enabled: boolean;
  sort_order: number;
};

type EditDimensionValues = {
  code: string;
  name: string;
  parent_id?: string;
  description?: string;
  is_enabled: boolean;
  sort_order: number;
};

function dimensionTypeLabel(type: string): string {
  return type;
}

function statusLabel(enabled: boolean): string {
  return enabled ? "启用" : "禁用";
}

const DIMENSIONS_TABLE_MIN_SCROLL_Y = 180;
const DIMENSIONS_TABLE_VIEWPORT_GAP = 40;
const DIMENSIONS_TABLE_FALLBACK_RESERVE = 220;

export default function AdminDimensionsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();

  const [createForm] = Form.useForm<CreateDimensionValues>();
  const [editForm] = Form.useForm<EditDimensionValues>();

  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState<DimensionItem | null>(null);
  const [selectedDimensionType, setSelectedDimensionType] = useState<string | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(DIMENSIONS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedDimensions, setAllLoadedDimensions] = useState<DimensionItem[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const canManage = hasPermission("dimension.manage");
  const canRead = hasPermission("dimension.read") || canManage;
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const dimensionsQueryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    params.set("sort_by", "dimension_type");
    params.set("sort_order", "asc");
    if (selectedDimensionType) {
      params.set("dimension_type", selectedDimensionType);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, selectedDimensionType]);

  const dimensionsPath = `/api/v1/dimensions?${dimensionsQueryParams}`;

  const loadDimensions = useCallback(async () => {
    const response = await fetchWithAuth(dimensionsPath);
    if (!response.ok) throw new Error(await readApiError(response));
    return (await response.json()) as DimensionItemListResponse;
  }, [fetchWithAuth, dimensionsPath]);

  const dimensionsQuery = useQuery({
    queryKey: ["admin.dimensions", dimensionsQueryParams],
    queryFn: loadDimensions,
    enabled: !!user && canRead,
  });

  useTopicSubscription(
    "admin.dimension-items",
    useCallback(() => {
      if (!user || !canRead) return;
      void queryClient.invalidateQueries({ queryKey: ["admin.dimensions"] });
    }, [canRead, queryClient, user]),
  );

  const dimensions = useMemo(() => dimensionsQuery.data?.items ?? [], [dimensionsQuery.data?.items]);

  // Update allLoadedDimensions when dimensions data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || dimensionsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedDimensions(() => dimensions);
      } else {
        setAllLoadedDimensions((prev) => {
          if (dimensions.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(d => d.id));
          const newDimensions = dimensions.filter(d => !existingIds.has(d.id));
          return [...prev, ...newDimensions];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [dimensions, dimensionsQuery.isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || dimensionsQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = dimensionsQuery.data?.total ?? 0;
        const loadedCount = allLoadedDimensions.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, dimensionsQuery.isLoading, dimensionsQuery.data?.total, allLoadedDimensions.length]);

  const uniqueDimensionTypes = useMemo(() => {
    const types = new Set(dimensions.map((d) => d.dimension_type));
    return Array.from(types).sort();
  }, [dimensions]);

  const getAvailableParents = useCallback((currentItemId?: string) => {
    return dimensions.filter((d) => {
      if (currentItemId && d.id === currentItemId) return false;
      if (currentItemId) {
        const isDescendant = (itemId: string, ancestorId: string): boolean => {
          const item = dimensions.find((dim) => dim.id === itemId);
          if (!item || !item.parent_id) return false;
          if (item.parent_id === ancestorId) return true;
          return isDescendant(item.parent_id, ancestorId);
        };
        if (isDescendant(d.id, currentItemId)) return false;
      }
      return true;
    });
  }, [dimensions]);

  const refreshData = async () => {
    await queryClient.refetchQueries({ queryKey: ["admin.dimensions"] });
  };

  const createDimensionMutation = useMutation({
    mutationFn: async (values: CreateDimensionValues) => {
      const response = await fetchWithAuth("/api/v1/dimensions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<DimensionItem>;
    },
    onSuccess: async () => {
      setSuccess("维度项已创建");
      setError("");
      createForm.resetFields();
      setCreateModalOpen(false);
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "创建维度项失败");
    },
  });

  const updateDimensionMutation = useMutation({
    mutationFn: async ({ itemId, payload }: { itemId: string; payload: EditDimensionValues }) => {
      const response = await fetchWithAuth(`/api/v1/dimensions/${itemId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<DimensionItem>;
    },
    onSuccess: async () => {
      setSuccess("维度项已更新");
      setEditingItem(null);
      editForm.resetFields();
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "更新维度项失败");
    },
  });

  const deleteDimensionMutation = useMutation({
    mutationFn: async (itemId: string) => {
      const response = await fetchWithAuth(`/api/v1/dimensions/${itemId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<{ success: boolean }>;
    },
    onMutate: (itemId) => {
      setDeletingId(itemId);
      setError("");
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("维度项已删除");
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除维度项失败");
    },
    onSettled: () => setDeletingId(null),
  });

  const handleCreateDimension = async (values: CreateDimensionValues) => {
    setError("");
    setSuccess("");

    // Handle dimension_type from tags mode Select (returns array)
    const payload = {
      ...values,
      dimension_type: Array.isArray(values.dimension_type)
        ? values.dimension_type[0]
        : values.dimension_type
    };

    createDimensionMutation.mutate(payload);
  };

  const openEditModal = (item: DimensionItem) => {
    setError("");
    setSuccess("");
    setEditingItem(item);
    editForm.setFieldsValue({
      code: item.code,
      name: item.name,
      parent_id: item.parent_id || undefined,
      description: item.description || undefined,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order,
    });
  };

  const closeEditModal = () => {
    if (updateDimensionMutation.isPending) return;
    setEditingItem(null);
    editForm.resetFields();
  };

  const handleSubmitEdit = async (values: EditDimensionValues) => {
    if (!editingItem) return;
    updateDimensionMutation.mutate({ itemId: editingItem.id, payload: values });
  };

  const openCreateModal = () => {
    setError("");
    setSuccess("");
    createForm.resetFields();
    if (selectedDimensionType) {
      createForm.setFieldsValue({ dimension_type: selectedDimensionType });
    }
    setCreateModalOpen(true);
  };

  const closeCreateModal = () => {
    if (createDimensionMutation.isPending) return;
    setCreateModalOpen(false);
    createForm.resetFields();
  };

  const queryError = dimensionsQuery.error instanceof Error ? dimensionsQuery.error.message : "";
  const anyError = error || queryError;

  useToastFeedback({
    errorMessage: anyError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - DIMENSIONS_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? DIMENSIONS_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - DIMENSIONS_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(DIMENSIONS_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [anyError, paginationCurrent, paginationPageSize, dimensions.length, dimensionsQuery.isFetching, updateTableScrollY]);

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

  const columns: ColumnsType<DimensionItem> = [
    {
      title: "维度类型",
      dataIndex: "dimension_type",
      width: 120,
      render: (value: string) => dimensionTypeLabel(value),
    },
    {
      title: "维度编码",
      dataIndex: "code",
      width: 140,
    },
    {
      title: "维度名称",
      dataIndex: "name",
      width: 180,
    },
    {
      title: "父维度",
      dataIndex: "parent_id",
      width: 180,
      render: (value: string | null) => {
        if (!value) return "-";
        const parent = dimensions.find((d) => d.id === value);
        return parent ? `${parent.name} (${parent.code})` : value;
      },
    },
    {
      title: "描述",
      dataIndex: "description",
      width: 200,
      render: (value: string | null) => value || "-",
    },
    {
      title: "状态",
      dataIndex: "is_enabled",
      width: 100,
      align: "center",
      render: (value: boolean) => (
        <Tag color={value ? "green" : "default"}>{statusLabel(value)}</Tag>
      ),
    },
    {
      title: "排序",
      dataIndex: "sort_order",
      width: 80,
      align: "center",
    },
    {
      title: "操作",
      key: "actions",
      width: 200,
      render: (_value, row) => {
        const deleteLoading = deletingId === row.id;
        const rowBusy = deleteLoading;

        const moreMenuItems: MenuProps["items"] = [
          {
            key: "toggle-status",
            label: row.is_enabled ? "禁用" : "启用",
            disabled: rowBusy,
            onClick: () => {
              updateDimensionMutation.mutate({
                itemId: row.id,
                payload: {
                  code: row.code,
                  name: row.name,
                  parent_id: row.parent_id || undefined,
                  description: row.description || undefined,
                  is_enabled: !row.is_enabled,
                  sort_order: row.sort_order,
                },
              });
            },
          },
        ];

        return (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy || !canManage}
              onClick={() => openEditModal(row)}
            >
              编辑
            </Button>

            <Popconfirm
              title={`确认删除维度项 ${row.name}（${row.code}）？`}
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true, loading: deleteLoading }}
              onConfirm={() => deleteDimensionMutation.mutate(row.id)}
              disabled={rowBusy || !canManage}
            >
              <Button danger size="small" loading={deleteLoading} disabled={rowBusy || !canManage}>
                删除
              </Button>
            </Popconfirm>

            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button size="small" disabled={rowBusy || !canManage} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  const renderDimensionCard = (item: DimensionItem) => {
    const deleteLoading = deletingId === item.id;
    const rowBusy = deleteLoading;

    const moreMenuItems: MenuProps["items"] = [
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: rowBusy,
        onClick: () => {
          Modal.confirm({
            title: `确认删除维度项 ${item.name}（${item.code}）？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: () => deleteDimensionMutation.mutate(item.id),
          });
        },
      },
      {
        key: "toggle-status",
        label: item.is_enabled ? "禁用" : "启用",
        disabled: rowBusy,
        onClick: () => {
          updateDimensionMutation.mutate({
            itemId: item.id,
            payload: {
              code: item.code,
              name: item.name,
              parent_id: item.parent_id || undefined,
              description: item.description || undefined,
              is_enabled: !item.is_enabled,
              sort_order: item.sort_order,
            },
          });
        },
      },
    ];

    const parent = item.parent_id ? dimensions.find((d) => d.id === item.parent_id) : null;

    return (
      <AntCard
        key={item.id}
        className="admin-dimensions-dimension-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong>{item.name}</Typography.Text>
            <Tag color={item.is_enabled ? "green" : "default"}>{statusLabel(item.is_enabled)}</Tag>
          </Space>
        }
        extra={
          <Space size={4}>
            <Button
              type="text"
              size="small"
              disabled={rowBusy || !canManage}
              icon={<EditOutlined />}
              onClick={() => openEditModal(item)}
            />
            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button type="text" size="small" disabled={rowBusy || !canManage} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-dimensions-dimension-card-field">
            <Typography.Text type="secondary">维度类型</Typography.Text>
            <Typography.Text>{dimensionTypeLabel(item.dimension_type)}</Typography.Text>
          </div>
          <div className="admin-dimensions-dimension-card-field">
            <Typography.Text type="secondary">维度编码</Typography.Text>
            <Typography.Text>{item.code}</Typography.Text>
          </div>
          <div className="admin-dimensions-dimension-card-field">
            <Typography.Text type="secondary">父维度</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: parent ? `${parent.name} (${parent.code})` : "-" }}>
              {parent ? `${parent.name} (${parent.code})` : "-"}
            </Typography.Text>
          </div>
          <div className="admin-dimensions-dimension-card-field">
            <Typography.Text type="secondary">描述</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: item.description || "-" }}>
              {item.description || "-"}
            </Typography.Text>
          </div>
          <div className="admin-dimensions-dimension-card-field">
            <Typography.Text type="secondary">排序</Typography.Text>
            <Typography.Text>{item.sort_order}</Typography.Text>
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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问维度管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `dimension.read` 或 `dimension.manage`）。</p>
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
    <div className="flex flex-1 flex-col space-y-6">
      <AntCard
        ref={pageCardRef}
        style={{ height: '100%' }}
        title="维度管理"
        extra={
          canManage && (
            <Button type="primary" onClick={openCreateModal}>
              新增维度项
            </Button>
          )
        }
      >
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label="维度类型" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
              <Select
                value={selectedDimensionType}
                allowClear
                placeholder="全部"
                style={{ width: "100%" }}
                options={uniqueDimensionTypes.map((type) => ({ value: type, label: type }))}
                onChange={(value) => {
                  setSelectedDimensionType(value);
                  setPagination((prev) => ({ ...prev, current: 1 }));
                  setCardViewPage(1);
                  setAllLoadedDimensions([]);
                }}
              />
            </Form.Item>
            <Form.Item style={ marginBottom: 0 }>
              <Button
                htmlType="button"
                icon={<SearchOutlined />}
                onClick={() => {
                  setPagination((prev) => ({ ...prev, current: 1 }));
                  setCardViewPage(1);
                  setAllLoadedDimensions([]);
                }}
                className="admin-search-btn"
              >
                查询
              </Button>
            </Form.Item>
          </Form>
        </div>

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-dimensions-table-anchor"
            style={{ "--admin-dimensions-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<DimensionItem>
              rowKey="id"
              dataSource={dimensions}
              columns={columns}
              loading={dimensionsQuery.isLoading}
              tableLayout="fixed"
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                total: Math.max(dimensionsQuery.data?.total ?? 0, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${dimensionsQuery.data?.total ?? 0} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ y: tableScrollY }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的维度项。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-dimensions-card-view">
            {dimensionsQuery.isLoading && allLoadedDimensions.length === 0 ? (
              <div className="admin-dimensions-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedDimensions.length === 0 ? (
              <div className="admin-dimensions-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的维度项。"
                />
              </div>
            ) : (
              <div className="admin-dimensions-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedDimensions.map((item) => (
                    <Col key={item.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderDimensionCard(item)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedDimensions.length >= (dimensionsQuery.data?.total ?? 0) && allLoadedDimensions.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedDimensions.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      <Modal
        title="新增维度项"
        open={createModalOpen}
        destroyOnClose
        onCancel={closeCreateModal}
        onOk={() => createForm.submit()}
        okText="创建维度项"
        cancelText="取消"
        confirmLoading={createDimensionMutation.isPending}
      >
        <Form<CreateDimensionValues>
          form={createForm}
          layout="vertical"
          onFinish={handleCreateDimension}
          autoComplete="off"
          initialValues={{ is_enabled: true, sort_order: 0 }}
        >
          <Form.Item
            label="维度类型"
            name="dimension_type"
            rules={[{ required: true, message: "请选择或输入维度类型" }]}
          >
            <Select
              placeholder="请选择或输入维度类型"
              showSearch
              allowClear
              mode="tags"
              maxCount={1}
              options={uniqueDimensionTypes.map((type) => ({ value: type, label: type }))}
            />
          </Form.Item>

          <Form.Item
            label="维度编码"
            name="code"
            rules={[
              { required: true, message: "请输入维度编码" },
              { min: 1, message: "维度编码至少 1 位" },
              { max: 128, message: "维度编码不能超过 128 位" },
            ]}
          >
            <Input placeholder="例如 110kv" />
          </Form.Item>

          <Form.Item
            label="维度名称"
            name="name"
            rules={[
              { required: true, message: "请输入维度名称" },
              { min: 1, message: "维度名称至少 1 位" },
              { max: 255, message: "维度名称不能超过 255 位" },
            ]}
          >
            <Input placeholder="例如 110千伏" />
          </Form.Item>

          <Form.Item label="父维度" name="parent_id">
            <Select
              placeholder="留空表示顶级节点"
              allowClear
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
              }
              options={getAvailableParents().map((d) => ({
                value: d.id,
                label: `${d.name} (${d.code})`,
              }))}
            />
          </Form.Item>

          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} placeholder="可选" maxLength={2000} />
          </Form.Item>

          <Form.Item label="启用状态" name="is_enabled" valuePropName="checked">
            <Select
              options={[
                { value: true, label: "启用" },
                { value: false, label: "禁用" },
              ]}
            />
          </Form.Item>

          <Form.Item
            label="排序"
            name="sort_order"
            rules={[{ required: true, message: "请输入排序值" }]}
          >
            <Input type="number" placeholder="0" />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingItem ? `编辑维度项：${editingItem.name}（${editingItem.code}）` : "编辑维度项"}
        open={!!editingItem}
        destroyOnClose
        onCancel={closeEditModal}
        onOk={() => editForm.submit()}
        okText="保存"
        cancelText="取消"
        confirmLoading={updateDimensionMutation.isPending}
      >
        <Form<EditDimensionValues>
          form={editForm}
          layout="vertical"
          onFinish={handleSubmitEdit}
          autoComplete="off"
        >
          <Form.Item
            label="维度编码"
            name="code"
            rules={[
              { required: true, message: "请输入维度编码" },
              { min: 1, message: "维度编码至少 1 位" },
              { max: 128, message: "维度编码不能超过 128 位" },
            ]}
          >
            <Input placeholder="例如 110kv" />
          </Form.Item>

          <Form.Item
            label="维度名称"
            name="name"
            rules={[
              { required: true, message: "请输入维度名称" },
              { min: 1, message: "维度名称至少 1 位" },
              { max: 255, message: "维度名称不能超过 255 位" },
            ]}
          >
            <Input placeholder="例如 110千伏" />
          </Form.Item>

          <Form.Item label="父维度" name="parent_id">
            <Select
              placeholder="留空表示顶级节点"
              allowClear
              showSearch
              filterOption={(input, option) =>
                (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
              }
              options={getAvailableParents(editingItem?.id).map((d) => ({
                value: d.id,
                label: `${d.name} (${d.code})`,
              }))}
            />
          </Form.Item>

          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} placeholder="可选" maxLength={2000} />
          </Form.Item>

          <Form.Item label="启用状态" name="is_enabled" valuePropName="checked">
            <Select
              options={[
                { value: true, label: "启用" },
                { value: false, label: "禁用" },
              ]}
            />
          </Form.Item>

          <Form.Item
            label="排序"
            name="sort_order"
            rules={[{ required: true, message: "请输入排序值" }]}
          >
            <Input type="number" placeholder="0" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
