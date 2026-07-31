"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Form,
  Image as AntImageBase,
  Input,
  InputNumber,
  Modal,
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
import { EditOutlined, MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  FileListResponse,
  FileStorageMount,
  TowerModelImageUploadResponse,
  TowerModelListResponse,
  TowerModelSummary,
} from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;
const AntImage = AntImageBase as unknown as ComponentType<{
  alt?: string;
  height?: number;
  preview?: boolean;
  src?: string;
  style?: CSSProperties;
  width?: number;
}>;

type TowerModelFormValues = {
  code: string;
  name: string;
  tower_type: string;
  description: string;
  sort_order: number;
};

const EMPTY_FORM: TowerModelFormValues = {
  code: "",
  name: "",
  tower_type: "",
  description: "",
  sort_order: 0,
};

const TOWER_MODEL_TABLE_MIN_SCROLL_Y = 180;
const TOWER_MODEL_VIEWPORT_GAP = 40;
const TOWER_MODEL_FALLBACK_RESERVE = 220;
const TOWER_MODEL_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const TOWER_MODEL_DEFAULT_PAGE_SIZE = 20;

function toEditValues(item: TowerModelSummary): TowerModelFormValues {
  return {
    code: item.code,
    name: item.name,
    tower_type: item.tower_type ?? "",
    description: item.description ?? "",
    sort_order: item.sort_order,
  };
}

function buildPayload(values: TowerModelFormValues): Record<string, unknown> {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    tower_type: values.tower_type.trim() || null,
    description: values.description.trim() || null,
    sort_order: values.sort_order ?? 0,
  };
}

type TowerModelImageCellProps = {
  model: TowerModelSummary;
  fetchWithAuth: ReturnType<typeof useAuth>["fetchWithAuth"];
  onPreviewError: (message: string) => void;
};

function TowerModelImageCell({
  model,
  fetchWithAuth,
  onPreviewError,
}: TowerModelImageCellProps) {
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewing, setPreviewing] = useState(false);

  useEffect(() => {
    let objectUrl: string | null = null;
    const abortController = new AbortController();

    const loadPreview = async () => {
      if (!model.image_path) {
        setImageUrl(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        const response = await fetchWithAuth(`/api/v1/tower-models/${model.id}/image`, {
          signal: abortController.signal,
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        objectUrl = URL.createObjectURL(await response.blob());
        setImageUrl(objectUrl);
      } catch (candidate) {
        if (!(candidate instanceof DOMException && candidate.name === "AbortError")) {
          setImageUrl(null);
        }
      } finally {
        setLoading(false);
      }
    };

    void loadPreview();

    return () => {
      abortController.abort();
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [fetchWithAuth, model.id, model.image_path]);

  const openPreview = useCallback(async () => {
    setPreviewing(true);
    try {
      const response = await fetchWithAuth(`/api/v1/tower-models/${model.id}/image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const nextWindow = window.open(objectUrl, "_blank", "noopener,noreferrer");
      if (!nextWindow) {
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.target = "_blank";
        anchor.rel = "noopener noreferrer";
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      }
      window.setTimeout(() => {
        URL.revokeObjectURL(objectUrl);
      }, 60_000);
    } catch (candidate) {
      const message = candidate instanceof Error ? candidate.message : "图片加载失败";
      onPreviewError(message);
    } finally {
      setPreviewing(false);
    }
  }, [fetchWithAuth, model.id, onPreviewError]);

  return (
    <Space size={8}>
      {imageUrl ? (
        <AntImage
          src={imageUrl}
          alt={model.name}
          width={56}
          height={56}
          preview={false}
          style={{ objectFit: "cover", borderRadius: 6, border: "1px solid #ddd" }}
        />
      ) : (
        <div
          style={{
            width: 56,
            height: 56,
            borderRadius: 6,
            border: "1px solid #ddd",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
          }}
        >
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {loading ? "加载中" : "无预览"}
          </Typography.Text>
        </div>
      )}
      <Button size="small" onClick={() => void openPreview()} loading={previewing}>
        查看
      </Button>
    </Space>
  );
}

export default function AdminTowerModelsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<TowerModelFormValues>();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const isMobile = useMobileDetection();
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<"enabled" | "disabled" | undefined>(undefined);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<TowerModelSummary | null>(null);
  const [uploadModel, setUploadModel] = useState<TowerModelSummary | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: TOWER_MODEL_DEFAULT_PAGE_SIZE });
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedModels, setAllLoadedModels] = useState<TowerModelSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [tableScrollY, setTableScrollY] = useState(TOWER_MODEL_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";

  const handleImagePreviewError = useCallback((message: string) => {
    setError(message);
  }, []);

  const canRead = hasPermission("tower_model.read") || hasPermission("tower_model.manage") || hasPermission("tower.read") || hasPermission("tower.manage");
  const canManage = hasPermission("tower_model.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const trimmedKeyword = searchKeyword.trim();

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    if (enabledFilter) {
      params.set("enabled", enabledFilter === "enabled" ? "true" : "false");
    }
    return `/api/v1/tower-models?${params.toString()}`;
  }, [enabledFilter, paginationCurrent, paginationPageSize, trimmedKeyword]);

  const mountsQuery = useQuery({
    queryKey: ["/api/v1/admin/files?path=/"],
    enabled: !!user && canManage,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/files?path=/");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileListResponse;
    },
  });

  const towerModelsQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerModelListResponse;
    },
  });

  const listError = towerModelsQuery.error instanceof Error ? towerModelsQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });
  const listData = towerModelsQuery.data;
  const listItems = useMemo(() => listData?.items ?? [], [listData?.items]);
  const totalItems = listData?.total ?? listItems.length;
  const paginationMaxPage = Math.max(1, Math.ceil(totalItems / paginationPageSize));
  const tableCurrentPage = Math.min(paginationCurrent, paginationMaxPage);

  const refreshList = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/tower-models"),
    });
  }, [queryClient]);

  useTopicSubscription("admin.tower-models", useCallback(() => {
    void refreshList();
  }, [refreshList]));

  useEffect(() => {
    if (viewMode !== "card" || towerModelsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedModels(() => listItems);
      } else {
        setAllLoadedModels((previous) => {
          if (listItems.length === 0) {
            return previous;
          }
          const existingIds = new Set(previous.map((item) => item.id));
          const newModels = listItems.filter((item) => !existingIds.has(item.id));
          return [...previous, ...newModels];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [cardViewPage, listItems, towerModelsQuery.isLoading, viewMode]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || towerModelsQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = totalItems;
        const loadedCount = allLoadedModels.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, towerModelsQuery.isLoading, totalItems, allLoadedModels.length]);

  const saveMutation = useMutation({
    mutationFn: async (values: TowerModelFormValues) => {
      const payload = buildPayload(values);
      if (editingModel) {
        const response = await fetchWithAuth(`/api/v1/tower-models/${editingModel.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        return "updated" as const;
      }

      const response = await fetchWithAuth("/api/v1/tower-models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "created" as const;
    },
    onSuccess: async (mode) => {
      setSuccess(mode === "created" ? "杆塔模型已创建" : "杆塔模型已更新");
      setError("");
      setDialogOpen(false);
      setEditingModel(null);
      form.resetFields();
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存杆塔模型失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (modelId: string) => {
      const response = await fetchWithAuth(`/api/v1/tower-models/${modelId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
    },
    onSuccess: async () => {
      setSuccess("杆塔模型已删除");
      setError("");
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除杆塔模型失败");
    },
  });

  const uploadImageMutation = useMutation({
    mutationFn: async (payload: { modelId: string; mountCode: string; file: File }) => {
      const formData = new FormData();
      formData.append("file", payload.file);
      const params = new URLSearchParams({ mount_code: payload.mountCode });
      const response = await fetchWithAuth(`/api/v1/tower-models/${payload.modelId}/image?${params.toString()}`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerModelImageUploadResponse;
    },
    onSuccess: async () => {
      setSuccess("模型图片上传成功");
      setError("");
      setUploadModel(null);
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "图片上传失败");
    },
  });

  const openCreate = () => {
    setError("");
    setSuccess("");
    setEditingModel(null);
    form.setFieldsValue(EMPTY_FORM);
    setDialogOpen(true);
  };

  const openEdit = useCallback((item: TowerModelSummary) => {
    setError("");
    setSuccess("");
    setEditingModel(item);
    form.setFieldsValue(toEditValues(item));
    setDialogOpen(true);
  }, [form]);
  const isDeletingModel = deleteMutation.isPending;
  const isSavingModel = saveMutation.isPending;
  const isUploadingImage = uploadImageMutation.isPending;
  const deleteModelAsync = deleteMutation.mutateAsync;

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const tableColumns = useMemo<ColumnsType<TowerModelSummary>>(
    () => [
      {
        title: "模型编码",
        dataIndex: "code",
        width: 160,
        render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
      },
      {
        title: "模型名称",
        dataIndex: "name",
        width: 200,
      },
      {
        title: "塔型",
        dataIndex: "tower_type",
        width: 100,
        render: (value: string | null) => value || "-",
      },
      {
        title: "默认参数",
        key: "defaults",
        width: 320,
        render: (_: unknown, row) => (
          <Space size={[8, 4]} wrap>
            <Tag>接地电阻 {row.default_ground_resistance_ohm ?? "-"}Ω</Tag>
            <Tag>地闪密度 {row.default_lightning_density ?? "-"}</Tag>
            <Tag>档距 {row.default_span_small_m ?? "-"} / {row.default_span_large_m ?? "-"}</Tag>
            <Tag>倾角 {row.default_slope_1 ?? "-"} / {row.default_slope_2 ?? "-"}</Tag>
          </Space>
        ),
      },
      {
        title: "图片",
        key: "image",
        width: 200,
        render: (_: unknown, row) => {
          if (!row.image_path) {
            return <Typography.Text type="secondary">未上传</Typography.Text>;
          }
          return <TowerModelImageCell model={row} fetchWithAuth={fetchWithAuth} onPreviewError={handleImagePreviewError} />;
        },
      },
      {
        title: "状态",
        dataIndex: "is_enabled",
        width: 80,
        align: "center",
        render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? "启用" : "禁用"}</Tag>,
      },
      {
        title: "排序",
        dataIndex: "sort_order",
        width: 80,
      },
      {
        title: "操作",
        key: "actions",
        fixed: "right",
        width: 180,
        render: (_: unknown, row) => {
          const rowBusy = isDeletingModel || isSavingModel || isUploadingImage;
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "delete",
              label: "删除",
              danger: true,
              disabled: rowBusy,
            },
          ];

          return (
            <Space wrap>
              {canManage && (
                <Button size="small" disabled={rowBusy} onClick={() => openEdit(row)}>
                  编辑
                </Button>
              )}
              {canManage && (
                <Button size="small" disabled={rowBusy} onClick={() => setUploadModel(row)}>
                  上传图片
                </Button>
              )}
              {canManage && (
                <Dropdown
                  menu={{
                    items: moreMenuItems,
                    onClick: ({ key }) => {
                      if (key === "delete") {
                        Modal.confirm({
                          title: "删除杆塔模型",
                          content: `确认删除模型 ${row.code} 吗？`,
                          okText: "删除",
                          cancelText: "取消",
                          okButtonProps: { danger: true },
                          onOk: async () => {
                            await deleteModelAsync(row.id);
                          },
                        });
                      }
                    },
                  }}
                  trigger={["click"]}
                >
                  <Button size="small" disabled={rowBusy} icon={<MoreOutlined />} />
                </Dropdown>
              )}
            </Space>
          );
        },
      },
    ],
    [canManage, deleteModelAsync, fetchWithAuth, handleImagePreviewError, isDeletingModel, isSavingModel, isUploadingImage, openEdit],
  );

  const renderDefaultSummary = (row: TowerModelSummary) => (
    <Space size={[4, 4]} wrap>
      <Tag bordered={false}>接地 {row.default_ground_resistance_ohm ?? "-"}Ω</Tag>
      <Tag bordered={false}>地闪 {row.default_lightning_density ?? "-"}</Tag>
      <Tag bordered={false}>档距 {row.default_span_small_m ?? "-"} / {row.default_span_large_m ?? "-"}</Tag>
    </Space>
  );

  const renderTowerModelCard = (row: TowerModelSummary) => {
    const rowBusy = isDeletingModel || isSavingModel || isUploadingImage;
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "upload-image",
        label: "上传图片",
        disabled: rowBusy,
        onClick: () => setUploadModel(row),
      },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: rowBusy,
        onClick: () => {
          Modal.confirm({
            title: "删除杆塔模型",
            content: `确认删除模型 ${row.code} 吗？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: async () => {
              await deleteModelAsync(row.id);
            },
          });
        },
      },
    ];

    return (
      <AntCard
        key={row.id}
        className="admin-tower-models-model-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis={{ tooltip: row.name }}>
              {row.name}
            </Typography.Text>
            <Tag color={row.is_enabled ? "green" : "default"}>{row.is_enabled ? "启用" : "禁用"}</Tag>
          </Space>
        }
        extra={canManage ? (
          <Space size={4}>
            <Button
              type="text"
              size="small"
              disabled={rowBusy}
              icon={<EditOutlined />}
              onClick={() => openEdit(row)}
            />
            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button type="text" size="small" disabled={rowBusy} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        ) : null}
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">模型编码</Typography.Text>
            <Typography.Text code ellipsis={{ tooltip: row.code }}>
              {row.code}
            </Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">塔型</Typography.Text>
            <Typography.Text>{row.tower_type || "-"}</Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">排序</Typography.Text>
            <Typography.Text>{row.sort_order}</Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">默认参数</Typography.Text>
            {renderDefaultSummary(row)}
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">模型图片</Typography.Text>
            {row.image_path ? (
              <TowerModelImageCell model={row} fetchWithAuth={fetchWithAuth} onPreviewError={handleImagePreviewError} />
            ) : (
              <Typography.Text type="secondary">未上传</Typography.Text>
            )}
          </div>
        </Space>
      </AntCard>
    );
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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - TOWER_MODEL_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? TOWER_MODEL_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - TOWER_MODEL_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(TOWER_MODEL_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [error, listError, listItems.length, paginationCurrent, paginationPageSize, success, towerModelsQuery.isFetching, updateTableScrollY]);

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

  const mounts = mountsQuery.data?.mounts ?? [];

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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问杆塔模型管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `tower_model.read`）。</p>
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
        className="admin-tower-models-page-card"
        title="杆塔模型管理"
        extra={canManage ? (
          <Button onClick={openCreate} type="primary">新建模型</Button>
        ) : null}
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  value={keywordInput}
                  allowClear
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  placeholder="按模型编码/名称/塔型搜索"
                  onPressEnter={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                  }}
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                    void queryClient.refetchQueries({ queryKey: [listPath] });
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
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  value={keywordInput}
                  allowClear
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  placeholder="按模型编码/名称/塔型搜索"
                  onPressEnter={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                  }}
                />
              </Form.Item>
              <Form.Item label="状态" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select<"enabled" | "disabled">
                  value={enabledFilter}
                  allowClear
                  placeholder="全部"
                  options={[
                    { value: "enabled", label: "已启用" },
                    { value: "disabled", label: "已禁用" },
                  ]}
                  onChange={(value) => {
                    setEnabledFilter(value);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                  }}
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                    void queryClient.refetchQueries({ queryKey: [listPath] });
                  }}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
        )}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-tower-models-table-anchor"
            style={{ "--admin-tower-models-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<TowerModelSummary>
              rowKey={(row) => row.id}
              columns={tableColumns}
              dataSource={listItems}
              loading={towerModelsQuery.isLoading}
              tableLayout="fixed"
              pagination={{
                current: tableCurrentPage,
                pageSize: pagination.pageSize,
                total: Math.max(totalItems, 1),
                showSizeChanger: true,
                pageSizeOptions: TOWER_MODEL_PAGE_SIZE_OPTIONS,
                showTotal: () => `共 ${totalItems} 条`,
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
                    description="未找到符合筛选条件的杆塔模型。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-tower-models-card-view">
            {towerModelsQuery.isLoading && allLoadedModels.length === 0 ? (
              <div className="admin-tower-models-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedModels.length === 0 ? (
              <div className="admin-tower-models-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的杆塔模型。"
                />
              </div>
            ) : (
              <div className="admin-tower-models-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedModels.map((row) => (
                    <Col key={row.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderTowerModelCard(row)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedModels.length >= totalItems && allLoadedModels.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedModels.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      <Modal
        title={editingModel ? "编辑杆塔模型" : "新建杆塔模型"}
        open={dialogOpen}
        width={720}
        okText={editingModel ? "保存" : "创建"}
        confirmLoading={saveMutation.isPending}
        onCancel={() => {
          if (saveMutation.isPending) return;
          setDialogOpen(false);
        }}
        onOk={async () => {
          const values = await form.validateFields();
          saveMutation.mutate(values);
        }}
      >
        <Form<TowerModelFormValues> form={form} layout="vertical" initialValues={EMPTY_FORM}>
          <div className="grid gap-3 md:grid-cols-2">
            <Form.Item name="code" label="模型编码" rules={[{ required: true, message: "请输入模型编码" }]}>
              <Input disabled={!!editingModel} />
            </Form.Item>
            <Form.Item name="name" label="模型名称" rules={[{ required: true, message: "请输入模型名称" }]}>
              <Input />
            </Form.Item>
            <Form.Item name="tower_type" label="塔型">
              <Select
                allowClear
                options={[
                  { value: "直线", label: "直线" },
                  { value: "耐张", label: "耐张" },
                ]}
              />
            </Form.Item>
            <Form.Item name="sort_order" label="排序">
              <InputNumber min={0} max={1_000_000} className="w-full" />
            </Form.Item>
          </div>
          <Form.Item name="description" label="描述">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="上传模型图片"
        open={!!uploadModel}
        okText="上传"
        confirmLoading={uploadImageMutation.isPending}
        onCancel={() => {
          if (uploadImageMutation.isPending) return;
          setUploadModel(null);
        }}
        onOk={() => {
          if (!uploadModel) return;
          const file = fileInputRef.current?.files?.[0];
          if (!file) {
            setError("请先选择图片文件");
            return;
          }
          const mount = mounts[0];
          if (!mount) {
            setError("未查询到可用文件挂载点");
            return;
          }
          uploadImageMutation.mutate({
            modelId: uploadModel.id,
            mountCode: mount.code,
            file,
          });
        }}
      >
        <Space direction="vertical" size={12} className="w-full">
          <Typography.Text type="secondary">
            当前模型：{uploadModel?.code} / {uploadModel?.name}
          </Typography.Text>
          <Typography.Text type="secondary">
            目标挂载：{(mounts[0] as FileStorageMount | undefined)?.code ?? "-"}（默认第一个可用挂载）
          </Typography.Text>
          <input
            ref={fileInputRef}
            type="file"
            accept=".jpg,.jpeg,.png,.webp,.gif,.bmp,image/*"
            className="block w-full"
          />
        </Space>
      </Modal>
    </div>
  );
}
