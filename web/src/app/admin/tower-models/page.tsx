"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
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
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  message,
  type CardProps,
  type MenuProps,
} from "antd";
import { CheckCircleOutlined, EditOutlined, MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { getApiBaseUrl, readApiError } from "@/lib/api";
import type {
  FileListResponse,
  FileStorageMount,
  TowerModelImageUploadResponse,
  TowerModelListResponse,
  TowerModelSummary,
  TowerModelTempUploadResponse,
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
  default_ground_resistance_ohm: number | null;
  default_lightning_density: number | null;
  default_span_small_m: number | null;
  default_span_large_m: number | null;
  default_slope_1: number | null;
  default_slope_2: number | null;
};

const EMPTY_FORM: TowerModelFormValues = {
  code: "",
  name: "",
  tower_type: "",
  description: "",
  sort_order: 0,
  default_ground_resistance_ohm: null,
  default_lightning_density: null,
  default_span_small_m: null,
  default_span_large_m: null,
  default_slope_1: null,
  default_slope_2: null,
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
    default_ground_resistance_ohm: item.default_ground_resistance_ohm ?? null,
    default_lightning_density: item.default_lightning_density ?? null,
    default_span_small_m: item.default_span_small_m ?? null,
    default_span_large_m: item.default_span_large_m ?? null,
    default_slope_1: item.default_slope_1 ?? null,
    default_slope_2: item.default_slope_2 ?? null,
  };
}

function buildPayload(values: TowerModelFormValues): Record<string, unknown> {
  return {
    code: values.code.trim(),
    name: values.name.trim(),
    tower_type: values.tower_type.trim() || null,
    description: values.description.trim() || null,
    sort_order: values.sort_order ?? 0,
    default_ground_resistance_ohm: values.default_ground_resistance_ohm ?? null,
    default_lightning_density: values.default_lightning_density ?? null,
    default_span_small_m: values.default_span_small_m ?? null,
    default_span_large_m: values.default_span_large_m ?? null,
    default_slope_1: values.default_slope_1 ?? null,
    default_slope_2: values.default_slope_2 ?? null,
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
  const { t } = useI18n();
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
      const message = candidate instanceof Error ? candidate.message : t("图片加载失败");
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
            {loading ? t("加载中") : t("无预览")}
          </Typography.Text>
        </div>
      )}
      <Button size="small" onClick={() => void openPreview()} loading={previewing}>
        {t("查看")}
      </Button>
    </Space>
  );
}

export default function AdminTowerModelsPage() {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, getAccessToken, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<TowerModelFormValues>();
  const isMobile = useMobileDetection();
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [enabledFilter, setEnabledFilter] = useState<"enabled" | "disabled" | undefined>(undefined);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingModel, setEditingModel] = useState<TowerModelSummary | null>(null);
  const [uploadModel, setUploadModel] = useState<TowerModelSummary | null>(null);
  const [selectedImageFile, setSelectedImageFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
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
      setSuccess(mode === "created" ? t("杆塔模型已创建") : t("杆塔模型已更新"));
      setError("");
      setDialogOpen(false);
      setEditingModel(null);
      form.resetFields();
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : t("保存杆塔模型失败"));
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
      setSuccess(t("杆塔模型已删除"));
      setError("");
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : t("删除杆塔模型失败"));
    },
  });

  const uploadImageMutation = useMutation({
    mutationFn: async (payload: { modelId: string; mountCode: string }) => {
      if (!tempFileId) {
        throw new Error(t("文件尚未上传完成，请等待上传后再确认"));
      }
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
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
      setSuccess(t("模型图片上传成功"));
      setError("");
      setUploadModel(null);
      setSelectedImageFile(null);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");
      await refreshList();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : t("图片上传失败"));
    },
  });

  const handleTempUpload = useCallback(
    (file: File) => {
      setSelectedImageFile(file);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getApiBaseUrl()}/api/v1/tower-models/upload-temp`);
      xhr.withCredentials = true;
      const token = getAccessToken();
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
        if (!event.lengthComputable || event.total <= 0) {
          return;
        }
        const percent = Math.min(99, Math.max(0, Math.round((event.loaded / event.total) * 100)));
        setUploadProgress(percent);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setUploadProgress(100);
          try {
            const payload = JSON.parse(xhr.responseText) as TowerModelTempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError(t("上传成功但响应解析失败，请重新选择文件"));
          }
          return;
        }
        let messageText = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) messageText = parsed.detail;
        } catch {
          // 忽略非 JSON 响应
        }
        setUploadError(messageText);
      };
      xhr.onerror = () => setUploadError(t("网络异常，上传失败"));
      xhr.onabort = () => setUploadError(t("上传已取消"));

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [getAccessToken],
  );

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

  const openUpload = useCallback((row: TowerModelSummary) => {
    setUploadModel(row);
    setSelectedImageFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
  }, []);

  const tableColumns = useMemo<ColumnsType<TowerModelSummary>>(
    () => [
      {
        title: t("模型编码"),
        dataIndex: "code",
        width: 160,
        render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
      },
      {
        title: t("模型名称"),
        dataIndex: "name",
        width: 200,
      },
      {
        title: t("塔型"),
        dataIndex: "tower_type",
        width: 100,
        render: (value: string | null) => value || "-",
      },
      {
        title: t("默认参数"),
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
        title: t("图片"),
        key: "image",
        width: 200,
        render: (_: unknown, row) => {
          if (!row.image_path) {
            return <Typography.Text type="secondary">{t("未上传")}</Typography.Text>;
          }
          return <TowerModelImageCell model={row} fetchWithAuth={fetchWithAuth} onPreviewError={handleImagePreviewError} />;
        },
      },
      {
        title: t("状态"),
        dataIndex: "is_enabled",
        width: 80,
        align: "center",
        render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? t("启用") : t("禁用")}</Tag>,
      },
      {
        title: t("排序"),
        dataIndex: "sort_order",
        width: 80,
      },
      {
        title: t("操作"),
        key: "actions",
        fixed: "right",
      width: 180,
        render: (_: unknown, row) => {
          const rowBusy = isDeletingModel || isSavingModel || isUploadingImage;
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "delete",
              label: t("删除"),
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
                <Button size="small" disabled={rowBusy} onClick={() => openUpload(row)}>
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
                          title: t("删除杆塔模型"),
                          content: `确认删除模型 ${row.code} 吗？`,
                          okText: t("删除"),
                          cancelText: t("取消"),
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
    [t, canManage, deleteModelAsync, fetchWithAuth, handleImagePreviewError, isDeletingModel, isSavingModel, isUploadingImage, openEdit, openUpload],
  );

  const renderDefaultSummary = (row: TowerModelSummary) => (
    <Space size={[4, 4]} wrap>
      <Tag bordered={false}>接地 {row.default_ground_resistance_ohm ?? "-"}Ω</Tag>
      <Tag bordered={false}>地闪 {row.default_lightning_density ?? "-"}</Tag>
      <Tag bordered={false}>档距 {row.default_span_small_m ?? "-"} / {row.default_span_large_m ?? "-"}</Tag>
    </Space>
  );

  const renderTowerModelCard = (row: TowerModelSummary, t: (s: string) => string) => {
    const rowBusy = isDeletingModel || isSavingModel || isUploadingImage;
    const statusLabel = row.is_enabled ? t("启用") : t("禁用");
    const statusColor = row.is_enabled ? "success" : "default";

    const moreMenuItems: MenuProps["items"] = [
      {
        key: "upload-image",
        label: t("上传图片"),
        disabled: rowBusy,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          openUpload(row);
        },
      },
      {
        key: "delete",
        label: t("删除"),
        danger: true,
        disabled: rowBusy,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          Modal.confirm({
            title: t("删除杆塔模型"),
            content: `确认删除模型 ${row.code} 吗？`,
            okText: t("删除"),
            cancelText: t("取消"),
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
        hoverable
        onClick={() => openEdit(row)}
      >
        <div className="admin-tower-models-card-header">
          <Typography.Text strong ellipsis={{ tooltip: row.name }}>
            {row.name}
          </Typography.Text>
          <div className="admin-tower-models-card-status">
            <Badge status={statusColor} />
            <Typography.Text type="secondary">{statusLabel}</Typography.Text>
          </div>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">{t("模型编码")}</Typography.Text>
            <Typography.Text code ellipsis={{ tooltip: row.code }}>
              {row.code}
            </Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">{t("塔型")}</Typography.Text>
            <Typography.Text>{row.tower_type || "-"}</Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">{t("排序")}</Typography.Text>
            <Typography.Text>{row.sort_order}</Typography.Text>
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">{t("默认参数")}</Typography.Text>
            {renderDefaultSummary(row)}
          </div>
          <div className="admin-tower-models-model-card-field">
            <Typography.Text type="secondary">{t("模型图片")}</Typography.Text>
            {row.image_path ? (
              <TowerModelImageCell model={row} fetchWithAuth={fetchWithAuth} onPreviewError={handleImagePreviewError} />
            ) : (
              <Typography.Text type="secondary">{t("未上传")}</Typography.Text>
            )}
          </div>
        </Space>
        {canManage ? (
          <div className="admin-tower-models-card-actions">
            <div />
            <Space size="small" className="shrink-0">
              <Tooltip title={t("编辑")}>
                <Button
                  type="text"
                  size="small"
                  disabled={rowBusy}
                  icon={<EditOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openEdit(row);
                  }}
                />
              </Tooltip>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Tooltip title={t("更多")}>
                  <Button
                    type="text"
                    size="small"
                    disabled={rowBusy}
                    icon={<MoreOutlined />}
                    onClick={(event) => event.stopPropagation()}
                  />
                </Tooltip>
              </Dropdown>
            </Space>
          </div>
        ) : null}
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
        <Spin />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问杆塔模型管理页面。")}</p>
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
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `tower_model.read`）。")}</p>
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
        title={t("杆塔模型管理")}
        extra={canManage ? (
          <Button onClick={openCreate} type="primary">{t("新建模型")}</Button>
        ) : null}
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  value={keywordInput}
                  allowClear
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  placeholder={t("按模型编码/名称/塔型搜索")}
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
                  className="admin-search-btn" loading={towerModelsQuery.isFetching}
                >
                  {t("查询")}
                </Button>
              </Form.Item>
            </Form>
          </div>
        ) : (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  value={keywordInput}
                  allowClear
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  placeholder={t("按模型编码/名称/塔型搜索")}
                  onPressEnter={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedModels([]);
                  }}
                />
              </Form.Item>
              <Form.Item label={t("状态")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select<"enabled" | "disabled">
                  value={enabledFilter}
                  allowClear
                  placeholder={t("全部")}
                  options={[
                    { value: "enabled", label: t("已启用") },
                    { value: "disabled", label: t("已禁用") },
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
                  className="admin-search-btn" loading={towerModelsQuery.isFetching}
                >
                  {t("查询")}
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
                    description={t("未找到符合筛选条件的杆塔模型。")}
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-tower-models-card-view">
            {towerModelsQuery.isLoading && allLoadedModels.length === 0 ? (
              <div className="admin-tower-models-card-view-state">
                <Spin />
              </div>
            ) : allLoadedModels.length === 0 ? (
              <div className="admin-tower-models-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description={t("未找到符合筛选条件的杆塔模型。")}
                />
              </div>
            ) : (
              <div className="admin-tower-models-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedModels.map((row) => (
                    <Col key={row.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderTowerModelCard(row, t)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin />
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
        title={editingModel ? t("编辑杆塔模型") : t("新建杆塔模型")}
        open={dialogOpen}
        width={720}
        forceRender
        okText={editingModel ? t("保存") : t("创建")}
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
          <Tabs
            className="admin-tower-models-modal-tabs"
            items={[
              {
                key: "basic",
                label: t("基本信息"),
                children: (
                  <>
                    <div className="grid gap-3 md:grid-cols-2">
                      <Form.Item name="code" label={t("模型编码")} rules={[{ required: true, message: t("请输入模型编码") }]}>
                        <Input disabled={!!editingModel} />
                      </Form.Item>
                      <Form.Item name="name" label={t("模型名称")} rules={[{ required: true, message: t("请输入模型名称") }]}>
                        <Input />
                      </Form.Item>
                      <Form.Item name="tower_type" label={t("塔型")}>
                        <Select
                          allowClear
                          options={[
                            { value: "直线", label: t("直线") },
                            { value: "耐张", label: t("耐张") },
                          ]}
                        />
                      </Form.Item>
                      <Form.Item name="sort_order" label={t("排序")}>
                        <InputNumber min={0} max={1_000_000} className="w-full" />
                      </Form.Item>
                    </div>
                    <Form.Item name="description" label={t("描述")}>
                      <Input.TextArea rows={3} />
                    </Form.Item>
                  </>
                ),
              },
              {
                key: "defaults",
                label: t("默认参数"),
                children: (
                  <div className="grid gap-3 md:grid-cols-2">
                    <Form.Item
                      name="default_ground_resistance_ohm"
                      label={t("接地电阻（Ω）")}
                      tooltip={t("杆塔默认接地电阻，用于雷击特性计算。")}
                    >
                      <InputNumber min={0} max={10000} step={0.1} className="w-full" />
                    </Form.Item>
                    <Form.Item
                      name="default_lightning_density"
                      label={t("地闪密度（次/km²·年）")}
                      tooltip={t("杆塔默认地闪密度（Ng）。")}
                    >
                      <InputNumber min={0} max={1000} step={0.1} className="w-full" />
                    </Form.Item>
                    <Form.Item
                      name="default_span_small_m"
                      label={t("小号侧档距（m）")}
                    >
                      <InputNumber min={0} max={100000} className="w-full" />
                    </Form.Item>
                    <Form.Item
                      name="default_span_large_m"
                      label={t("大号侧档距（m）")}
                    >
                      <InputNumber min={0} max={100000} className="w-full" />
                    </Form.Item>
                    <Form.Item
                      name="default_slope_1"
                      label={t("地面倾角 1（°）")}
                    >
                      <InputNumber min={-90} max={90} step={0.1} className="w-full" />
                    </Form.Item>
                    <Form.Item
                      name="default_slope_2"
                      label={t("地面倾角 2（°）")}
                    >
                      <InputNumber min={-90} max={90} step={0.1} className="w-full" />
                    </Form.Item>
                  </div>
                ),
              },
            ]}
          />
        </Form>
      </Modal>

      <Modal
        title={t("上传模型图片")}
        open={!!uploadModel}
        okText={t("上传")}
        okButtonProps={{ disabled: !tempFileId }}
        confirmLoading={uploadImageMutation.isPending}
        onCancel={() => {
          if (uploadImageMutation.isPending) return;
          setUploadModel(null);
          setSelectedImageFile(null);
          setTempFileId(null);
          setUploadProgress(0);
          setUploadError("");
        }}
        onOk={() => {
          if (!uploadModel) return;
          if (!tempFileId) {
            setUploadError(t("请先选择并上传图片文件"));
            return;
          }
          const mount = mounts[0];
          if (!mount) {
            setError(t("未查询到可用文件挂载点"));
            return;
          }
          uploadImageMutation.mutate({
            modelId: uploadModel.id,
            mountCode: mount.code,
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
          <div>
            <div style={{ marginBottom: 8 }}>
              <Typography.Text>{t("图片文件")}</Typography.Text>
            </div>
            <Upload.Dragger
              accept=".jpg,.jpeg,.png,.webp,.gif,.bmp,image/*"
              showUploadList={false}
              beforeUpload={(file) => {
                const maxMB = 50;
                const allowedExts = ["jpg", "jpeg", "png", "webp", "gif", "bmp"];
                const ext = file.name.split(".").pop()?.toLowerCase() || "";
                if (file.size > maxMB * 1024 * 1024) {
                  message.error(`文件大小超过 ${maxMB}MB 限制，请压缩后重新上传`);
                  return Upload.LIST_IGNORE;
                }
                if (!allowedExts.includes(ext)) {
                  message.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
                  return Upload.LIST_IGNORE;
                }
                return true;
              }}
              customRequest={({ file }) => handleTempUpload(file as File)}
              onRemove={() => {
                setSelectedImageFile(null);
                setTempFileId(null);
                setUploadProgress(0);
                setUploadError("");
              }}
            >
              {selectedImageFile ? (
                <>
                  <p className="ant-upload-text">{selectedImageFile.name}</p>
                  {uploadProgress < 100 ? (
                    <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                  ) : tempFileId ? (
                    <Typography.Text type="success">
                      <CheckCircleOutlined /> 上传完成，可以确认上传
                    </Typography.Text>
                  ) : (
                    <Typography.Text type="warning">{t("上传中…")}</Typography.Text>
                  )}
                </>
              ) : (
                <>
                  <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                    点击或拖拽图片文件到此区域上传
                  </p>
                  <Typography.Text type="secondary">
                    支持 jpg/jpeg/png/webp/gif/bmp 格式。选择文件后立即上传到临时存储。
                  </Typography.Text>
                </>
              )}
              {uploadError && (
                <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                  {uploadError}
                </Typography.Text>
              )}
            </Upload.Dragger>
          </div>
        </Space>
      </Modal>
    </div>
  );
}
