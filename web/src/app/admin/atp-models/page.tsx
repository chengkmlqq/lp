"use client";

import { useMutation, useQuery, useQueryClient, useQueries } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Progress,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Typography,
  Upload,
  type MenuProps,
} from "antd";
import { CheckCircleOutlined, DeleteOutlined, EditOutlined, InboxOutlined, MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type MouseEvent as ReactMouseEvent, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { AtpModelCardList } from "@/components/atp-models/atp-model-card-list";
import { AtpModelDetailTab } from "@/components/atp-models/atp-model-detail-tab";
import { AtpModelTestDrawer } from "@/components/atp-models/atp-model-test-drawer";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { ApiError, getApiBaseUrl, readApiError } from "@/lib/api";
import type { AtpAssetListResponse, AtpAssetSummary, DimensionTypeTreeItem, TempUploadResponse } from "@/types/auth";
import type { DimensionItemListResponse } from "@/types/dimension";

type AssetFormValues = {
  voltage_level: string;
  tower_type: string;
  scene_type: string;
  arrester_config: string;
  files: File[];
};

type AssetEditFormValues = {
  name: string;
  description: string;
  voltage_level: string;
  tower_type: string;
  scene_type: string;
  arrester_config: string;
  storage_mount_code: string;
  storage_root_path: string;
};

const EMPTY_FORM: AssetFormValues = {
  voltage_level: "",
  tower_type: "",
  scene_type: "",
  arrester_config: "",
  files: [],
};

function getUploadRelativePath(file: File): string {
  const candidate = file as File & { webkitRelativePath?: string };
  return candidate.webkitRelativePath || file.name;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function generateName(values: AssetFormValues): string {
  const parts = [
    values.voltage_level,
    values.tower_type,
    values.scene_type,
    values.arrester_config,
  ].filter(Boolean);
  return parts.join("-");
}

function generateCode(): string {
  return `atp-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
}

// ATP 页面字段名 → 维度管理类型 code 的映射
// 注意：scene_type 的类型 code 为 scenario，arrester_config 的类型 code 为 arrester_combination
const ATP_DIMENSION_FIELD_TO_TYPE_CODE: Record<string, string> = {
  voltage_level: "voltage_level",
  tower_type: "tower_type",
  scene_type: "scenario",
  arrester_config: "arrester_combination",
};

const ATP_DIMENSION_FIELDS = ["voltage_level", "tower_type", "scene_type", "arrester_config"] as const;
type AtpDimensionField = (typeof ATP_DIMENSION_FIELDS)[number];

function flattenTypeNodes(types: DimensionTypeTreeItem[]): DimensionTypeTreeItem[] {
  return types.flatMap((t) => [t, ...flattenTypeNodes(t.children)]);
}

function findDimensionTypeByCode(types: DimensionTypeTreeItem[], code: string): DimensionTypeTreeItem | undefined {
  return flattenTypeNodes(types).find((t) => t.code === code);
}

const ATP_TABLE_MIN_SCROLL_Y = 180;
const ATP_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const ATP_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const ATP_TABLE_BOTTOM_GAP = 8;

export default function AtpModelsPage() {
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<AssetFormValues>();
  const [editForm] = Form.useForm<AssetEditFormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  // 手动刷新计数：每次点击「查询」都自增并作为 queryKey 的一部分，强制走一次接口，
  // 即使关键词/分页未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingAsset, setEditingAsset] = useState<AtpAssetSummary | null>(null);
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  // 模型测试抽屉：从操作列打开，以当前模型为上下文
  const [testAsset, setTestAsset] = useState<AtpAssetSummary | null>(null);
  const [detailTabs, setDetailTabs] = useState<{ key: string; label: React.ReactNode; assetId: string }[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>("list");
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState(ATP_TABLE_MIN_SCROLL_Y);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("atp.manage");
  const canTest = hasPermission("atp.run") || hasPermission("atp.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const trimmedKeyword = searchKeyword.trim();
  const assetsQueryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, trimmedKeyword]);

  const assetsQuery = useQuery({
    // searchNonce 作为 queryKey 的一部分：每次点击「查询」自增，即使关键词/分页均未变化
    // 也会产生新 key 强制重新拉取；首个元素仍是 "atp-assets"，不影响失效/刷新逻辑
    queryKey: ["atp-assets", assetsQueryParams, searchNonce],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets?${assetsQueryParams}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetListResponse;
    },
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询时列表闪空
    placeholderData: (previousData) => previousData,
  });

  const createAssetMutation = useMutation({
    mutationFn: async (values: AssetFormValues) => {
      if (values.files.length === 0) {
        throw new Error("请先选择模型文件");
      }
      if (!tempFileId) {
        throw new Error("模型文件尚未上传完成，请等待上传完成后再创建模型");
      }

      const payload = {
        code: generateCode(),
        name: generateName(values),
        description: "",
        voltage_level: values.voltage_level.trim() || null,
        tower_type: values.tower_type.trim() || null,
        scene_type: values.scene_type.trim() || null,
        arrester_config: values.arrester_config.trim() || null,
      };

      const response = await fetchWithAuth("/api/v1/atp/assets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(await readApiError(response));
      }

      const createdAsset = await response.json();

      if (tempFileId) {
        const formData = new FormData();
        formData.append("temp_file_id", tempFileId);

        const uploadResponse = await fetchWithAuth(
          `/api/v1/atp/assets/${createdAsset.id}/files`,
          {
            method: "POST",
            body: formData,
          }
        );

        if (!uploadResponse.ok) {
          throw new Error(await readApiError(uploadResponse));
        }
      }

      return createdAsset;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-assets"] });
      setSuccess("模型已创建并上传文件");
      setError(null);
      setModalOpen(false);
      setFileList([]);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");
      form.resetFields();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "创建模型失败"));
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (assetId: string) => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-assets"] });
      setSuccess("模型已删除");
      setError(null);
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "删除模型失败"));
    },
  });

  const updateAssetMutation = useMutation({
    mutationFn: async (values: AssetEditFormValues) => {
      if (!editingAsset) {
        throw new Error("未选择要编辑的模型");
      }
      const payload = {
        name: values.name.trim() || null,
        description: values.description.trim() || null,
        voltage_level: values.voltage_level.trim() || null,
        tower_type: values.tower_type.trim() || null,
        scene_type: values.scene_type.trim() || null,
        arrester_config: values.arrester_config.trim() || null,
        storage_mount_code: values.storage_mount_code.trim() || null,
        storage_root_path: values.storage_root_path.trim() || null,
      };
      const response = await fetchWithAuth(`/api/v1/atp/assets/${editingAsset.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetSummary;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-assets"] });
      setSuccess("模型信息已更新");
      setError(null);
      setEditModalOpen(false);
      setEditingAsset(null);
      editForm.resetFields();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "更新模型失败"));
    },
  });

  const handleTempUpload = useCallback(
    async (files: File[]) => {
      if (files.length === 0) {
        setTempFileId(null);
        setUploadProgress(0);
        setUploadError("");
        return;
      }
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

      let zipBlob: Blob;
      try {
        const JSZip = (await import("jszip")).default;
        const zip = new JSZip();
        // 计算所有文件的公共目录前缀（webkitRelativePath 第一段），剥掉它，
        // 使 ZIP 根直接是模型文件（work.atp + lib/dat），与资产分层目录
        // /atp-assets/<电压>/<塔型>/<场景>/<避雷器组合> 对齐。
        const fullPaths = files.map((file) => getUploadRelativePath(file));
        let prefixDepth = 0;
        if (fullPaths.length > 0) {
          const firstSegments = fullPaths[0].split('/').filter(Boolean);
          while (
            prefixDepth < firstSegments.length - 1 &&
            fullPaths.every((path) => path.split('/').filter(Boolean)[prefixDepth] === firstSegments[prefixDepth])
          ) {
            prefixDepth += 1;
          }
        }
        for (const file of files) {
          const pathParts = getUploadRelativePath(file).split('/').filter(Boolean);
          const strippedPath = pathParts.slice(prefixDepth).join('/');
          if (strippedPath) {
            zip.file(strippedPath, file);
          }
        }
        zipBlob = await zip.generateAsync({ type: "blob" });
      } catch {
        setUploadError("模型文件打包失败，请重新选择文件夹");
        return;
      }

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getApiBaseUrl()}/api/v1/uploads/temp`);
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
            const payload = JSON.parse(xhr.responseText) as TempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError("上传成功但响应解析失败，请重新选择文件夹");
          }
          return;
        }
        let message = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) message = parsed.detail;
        } catch {
          // 忽略非 JSON 响应
        }
        setUploadError(message);
      };
      xhr.onerror = () => setUploadError("网络异常，上传失败");
      xhr.onabort = () => setUploadError("上传已取消");

      const formData = new FormData();
      formData.append("file", zipBlob, "model.zip");
      xhr.send(formData);
    },
    [getAccessToken],
  );

  useEffect(() => {
    if (fileList.length === 0) {
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");
      return;
    }
    const timer = window.setTimeout(() => {
      void handleTempUpload(fileList);
    }, 200);
    return () => window.clearTimeout(timer);
  }, [fileList, handleTempUpload]);

  const openCreateModal = useCallback(() => {
    setError(null);
    setSuccess("");
    setFileList([]);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
    form.setFieldsValue(EMPTY_FORM);
    setModalOpen(true);
  }, [form]);

  const openEditModal = useCallback((asset: AtpAssetSummary) => {
    setError(null);
    setSuccess("");
    setEditingAsset(asset);
    editForm.setFieldsValue({
      name: asset.name ?? "",
      description: asset.description ?? "",
      voltage_level: asset.voltage_level ?? "",
      tower_type: asset.tower_type ?? "",
      scene_type: asset.scene_type ?? "",
      arrester_config: asset.arrester_config ?? "",
      storage_mount_code: asset.storage_mount_code ?? "",
      storage_root_path: asset.storage_root_path ?? "",
    });
    setEditModalOpen(true);
  }, [editForm]);

  const closeEditModal = () => {
    if (updateAssetMutation.isPending) return;
    setEditModalOpen(false);
    setEditingAsset(null);
    editForm.resetFields();
  };

  const closeModal = () => {
    if (createAssetMutation.isPending) return;
    setModalOpen(false);
    setFileList([]);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
    form.resetFields();
  };

  const handleSearch = useCallback(() => {
    // 每次点击「查询」都强制触发一次接口请求：
    // searchNonce 作为 queryKey 的一部分自增，保证即便关键词/分页均未变化（旧实现只对
    // 这种情况 refetchQueries，且目标 key 若已被 react-query 缓存会短路不发请求）也会
    // 产生新 key 重新拉取；关键词/分页照常提交并回到第 1 页。
    setSearchKeyword(keywordInput);
    setPagination((previous) => ({ ...previous, current: 1 }));
    setSearchNonce((n) => n + 1);
  }, [keywordInput]);

  const assetItems = useMemo(() => assetsQuery.data?.items ?? [], [assetsQuery.data?.items]);

  // ===== 维度管理数据源（替代硬编码 DEFAULT_* 常量）=====
  // 1. 获取维度类型树（types/tree），解析出四个类型 id
  const dimensionTypesQuery = useQuery({
    queryKey: ["/api/v1/dimensions/types/tree"],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/dimensions/types/tree");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as DimensionTypeTreeItem[];
    },
  });

  // 2. 按类型 code 找到对应的类型 id（不存在时留空，页面回退为空选项）
  const dimensionTypeIds = useMemo(() => {
    const types = dimensionTypesQuery.data ?? [];
    const result: Partial<Record<AtpDimensionField, string | undefined>> = {};
    for (const field of ATP_DIMENSION_FIELDS) {
      const typeCode = ATP_DIMENSION_FIELD_TO_TYPE_CODE[field];
      result[field] = findDimensionTypeByCode(types, typeCode)?.id;
    }
    return result;
  }, [dimensionTypesQuery.data]);

  // 3. 每个类型各 fetch 一次启用的维度项（code → value，name → label）
  const dimensionItemsQueries = useQueries({
    queries: ATP_DIMENSION_FIELDS.map((field) => {
      const typeId = dimensionTypeIds[field];
      return {
        queryKey: ["/api/v1/dimensions", { type_id: typeId, enabled: true }],
        enabled: Boolean(user && canRead && typeId),
        queryFn: async () => {
          const params = new URLSearchParams();
          params.set("type_id", typeId!);
          params.set("enabled", "true");
          params.set("limit", "200");
          const response = await fetchWithAuth(`/api/v1/dimensions?${params.toString()}`);
          if (!response.ok) {
            throw new Error(await readApiError(response));
          }
          return (await response.json()) as DimensionItemListResponse;
        },
      };
    }),
  });

  // 4. 维度项缓存：typeCode → (code → { label, value })，供 Select options 与 formatDimensionValue 使用
  const dimensionOptionMap = useMemo(() => {
    const map: Record<AtpDimensionField, Array<{ label: string; value: string }>> = {
      voltage_level: [],
      tower_type: [],
      scene_type: [],
      arrester_config: [],
    };
    dimensionItemsQueries.forEach((query, index) => {
      const field = ATP_DIMENSION_FIELDS[index];
      const items = query.data?.items ?? [];
      map[field] = items
        .map((item) => ({ label: item.name, value: item.code }))
        .sort((left, right) => left.label.localeCompare(right.label, "zh-CN"));
    });
    return map;
  }, [dimensionItemsQueries]);

  const dimensionLabelMap = useMemo(() => {
    const map: Record<AtpDimensionField, Map<string, string>> = {
      voltage_level: new Map(),
      tower_type: new Map(),
      scene_type: new Map(),
      arrester_config: new Map(),
    };
    dimensionItemsQueries.forEach((query, index) => {
      const field = ATP_DIMENSION_FIELDS[index];
      for (const item of query.data?.items ?? []) {
        map[field].set(item.code, item.name);
      }
    });
    return map;
  }, [dimensionItemsQueries]);

  const formatDimensionValue = useCallback((value: string | null, field: AtpDimensionField): string => {
    if (!value) return "-";
    return dimensionLabelMap[field].get(value) ?? value;
  }, [dimensionLabelMap]);

  const voltageLevelOptions = dimensionOptionMap.voltage_level;
  const towerTypeOptions = dimensionOptionMap.tower_type;
  const sceneTypeOptions = dimensionOptionMap.scene_type;
  const arresterConfigOptions = dimensionOptionMap.arrester_config;

  const assetTotal = assetsQuery.data?.total ?? 0;
  const queryError = useMemo<ApiError | null>(() => assetsQuery.error instanceof Error ? new ApiError(assetsQuery.error.message) : null, [assetsQuery.error]);
  const apiError = error || queryError;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }

    // 用「视口可用高度」推导：anchor 自身高度会被表体 min-height 撑大，用它反推
    // 会形成正反馈（每次翻页多累加一次未计入间距，表体持续变高）。2026-09-12 修复
    const anchorTop = anchor.getBoundingClientRect().top;
    // 以可滚动容器（列表面板）的 padding-box 底边为准：用 window.innerHeight 会漏掉
    // 面板底部 padding 与页面底边距 → 溢出约 12px，表格外层出现多余纵向滚动条
    const pane = anchor.closest<HTMLElement>(".admin-atp-models-list-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? ATP_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? ATP_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available = containerRect.bottom - containerPadBottom - anchorTop - ATP_TABLE_BOTTOM_GAP;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
    const clampedHeight = Math.max(ATP_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollHeight);
  }, [assetsQuery.error, assetsQuery.isFetching, assetItems.length, updateTableScrollHeight, viewMode]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    if (viewMode !== "list") {
      return;
    }

    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };

    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight, viewMode]);

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
      window.requestAnimationFrame(updateTableScrollHeight);
    });
    resizeObserver.observe(anchor);

    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollHeight, viewMode]);

  const openDetail = useCallback((asset: { id: string; name: string }) => {
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === asset.id)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: asset.id,
          label: <span className="admin-atp-models-tab-title">模型详情 - {asset.name || asset.id}</span>,
          assetId: asset.id,
        },
      ];
    });
    setActiveTabKey(asset.id);
  }, []);

  const openDetailById = useCallback((id: string) => {
    const asset = assetItems.find((item) => item.id === id);
    if (asset) {
      openDetail(asset);
    }
  }, [assetItems, openDetail]);

  const openTestDrawer = useCallback((asset: AtpAssetSummary) => {
    setTestAsset(asset);
  }, []);

  const columns = useMemo<ColumnsType<AtpAssetSummary>>(
    () => [
      {
        title: "电压等级",
        dataIndex: "voltage_level",
        width: 120,
        render: (value: string | null) => formatDimensionValue(value, "voltage_level"),
      },
      {
        title: "塔型",
        dataIndex: "tower_type",
        width: 120,
        render: (value: string | null) => formatDimensionValue(value, "tower_type"),
      },
      {
        title: "场景",
        dataIndex: "scene_type",
        width: 120,
        render: (value: string | null) => formatDimensionValue(value, "scene_type"),
      },
      {
        title: "避雷器组合",
        dataIndex: "arrester_config",
        width: 120,
        render: (value: string | null) => formatDimensionValue(value, "arrester_config"),
      },
      {
        title: "更新时间",
        dataIndex: "update_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "操作",
        key: "actions",
        fixed: "right",
      align: "right" as const,
      width: 180,
        render: (_, item) => {
          const deleteLoading = deleteMutation.isPending;
          const rowBusy = deleteLoading;

          // 编辑收进 ⋯ 三点下拉，删除仅在具备管理权限时出现（对齐 power-lines 线路管理页操作列）
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "edit",
              label: (
                <Space size={4}>
                  <EditOutlined />
                  <span>编辑</span>
                </Space>
              ),
              disabled: !canManage || rowBusy,
              onClick: () => openEditModal(item),
            },
            ...(canManage
              ? [
                  {
                    key: "delete",
                    label: (
                      <Space size={4}>
                        <DeleteOutlined />
                        <span>删除</span>
                      </Space>
                    ),
                    danger: true,
                    disabled: rowBusy,
                    onClick: () => {
                      Modal.confirm({
                        title: "删除模型",
                        content: "这会同时删除其文件与运行记录。",
                        okText: "删除",
                        cancelText: "取消",
                        okButtonProps: { danger: true, loading: deleteLoading },
                        onOk: () => deleteMutation.mutate(item.id),
                      });
                    },
                  },
                ]
              : []),
          ];

          return (
            <Space size={4}>
              <Button size="small" onClick={() => openDetailById(item.id)}>
                详情
              </Button>
              <Button
                size="small"
                disabled={!canTest}
                onClick={() => openTestDrawer(item)}
              >
                测试
              </Button>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, canTest, deleteMutation, formatDimensionValue, openDetailById, openEditModal, openTestDrawer],
  );

  const handleTabsEdit = useCallback((targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    setDetailTabs((previous) => {
      const removedIndex = previous.findIndex((tab) => tab.key === key);
      const next = previous.filter((tab) => tab.key !== key);
      setActiveTabKey((current) => {
        if (current !== key) {
          return current;
        }
        return next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? "list";
      });
      return next;
    });
  }, []);

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            {!user ? "请先登录后再查看 ATP 模型管理。" : "当前账号无 ATP 模块权限（需要 atp.read/atp.run/atp.manage）。"}
          </Typography.Text>
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
        className="admin-atp-models-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" disabled={!canManage} onClick={openCreateModal} icon={<PlusOutlined />}>
               新建模型
             </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: <span className="admin-atp-models-tab-title">ATP 模型管理</span>,
            closable: false,
            children: (
              <div className="admin-atp-models-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        placeholder="按编码/名称搜索"
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={handleSearch}
                        className="admin-search-btn"
                      >
                        查询
                      </Button>
                    </Form.Item>
                  </Form>
                  <div className="flex items-center">
                    <Segmented
                      value={viewMode}
                      onChange={(value) => setViewMode(value as "card" | "list")}
                      options={[
                        { label: "卡片视图", value: "card" },
                        { label: "列表视图", value: "list" },
                      ]}
                    />
                  </div>
                </div>

                {apiError && (
                  <Alert
                    type="error"
                    showIcon
                    message={apiError.message || "加载失败"}
                  />
                )}

                {viewMode === "list" ? (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-atp-models-table-view"
                    style={{ "--admin-atp-models-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<AtpAssetSummary>
                      rowKey="id"
                      // 列表始终渲染：查询进行中仅叠加 antd Table 自带居中遮罩，保留现有行，
                      // 接口返回后再更新，避免查询开始时清空表格
                      loading={assetsQuery.isFetching}
                      columns={columns}
                      dataSource={assetItems}
                      tableLayout="fixed"
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到符合筛选条件的 ATP 模型。"
                          />
                        ),
                      }}
                      pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total: Math.max(assetTotal, 1),
                        showSizeChanger: true,
                        showTotal: () => `共 ${assetTotal} 条`,
                        hideOnSinglePage: false,
                        onChange: (page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        },
                      }}
                      scroll={{ x: 1200, y: tableScrollY }}
                    />
                  </div>
                ) : (
                  <div className="admin-atp-models-card-view">
                    {assetItems.length === 0 ? (
                      // 无数据可展示且请求进行中（首载/切换关键词后暂无结果）：整区居中加载指示；
                      // 有卡片时由下方 Spin 遮罩保留现有卡片，接口返回后再更新，避免查询时闪空
                      assetsQuery.isFetching ? (
                        <div className="flex w-full flex-1 items-center justify-center">
                          <Spin />
                        </div>
                      ) : (
                        <Empty description="暂无 ATP 模型数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                      )
                    ) : (
                      <>
                        <div className="admin-atp-models-card-scroll">
                          {/* 查询/刷新期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据 */}
                          <Spin spinning={assetsQuery.isFetching}>
                            <AtpModelCardList
                              assets={assetItems}
                              canManage={canManage}
                              canTest={canTest}
                              deleteLoading={deleteMutation.isPending}
                              onView={(asset) => openDetail(asset)}
                              onEdit={(asset) => openEditModal(asset)}
                              onDelete={(id) => deleteMutation.mutate(id)}
                              onTest={(asset) => openTestDrawer(asset)}
                              dimensionLabelMap={dimensionLabelMap}
                            />
                          </Spin>
                        </div>

                        <div className="admin-atp-models-pagination">
                          <Pagination
                            current={pagination.current}
                            pageSize={pagination.pageSize}
                            total={Math.max(assetTotal, 1)}
                            onChange={(page, pageSize) => {
                              setPagination({ current: page, pageSize });
                            }}
                            showSizeChanger
                            showTotal={() => `共 ${assetTotal} 条`}
                          />
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs.map((tab) => ({
            key: tab.key,
            label: tab.label,
            closable: true,
            children: (
              <AtpModelDetailTab
                assetId={tab.assetId}
              />
            ),
          })),
        ]}
        />

      <Modal
        title="新建 ATP 模型"
        open={modalOpen}
        forceRender
        onCancel={closeModal}
        onOk={() => void form.submit()}
        confirmLoading={createAssetMutation.isPending}
        destroyOnHidden
        okText={createAssetMutation.isPending ? "提交中..." : "创建模型"}
        cancelText="取消"
        okButtonProps={{ disabled: !tempFileId }}
      >
        <Form
          form={form}
          layout="vertical"
          initialValues={EMPTY_FORM}
          onFinish={(values) => {
            values.files = fileList;
            void createAssetMutation.mutateAsync(values);
          }}
          autoComplete="off"
        >
          <Form.Item name="voltage_level" label="电压等级" rules={[{ required: true, message: "请选择电压等级" }]}>
            <Select
              showSearch
              allowClear
              placeholder="请选择电压等级"
              options={voltageLevelOptions}
            />
          </Form.Item>
          <Form.Item name="tower_type" label="塔型" rules={[{ required: true, message: "请选择塔型" }]}>
            <Select
              showSearch
              allowClear
              placeholder="请选择塔型"
              options={towerTypeOptions}
            />
          </Form.Item>
          <Form.Item name="scene_type" label="场景" rules={[{ required: true, message: "请选择场景" }]}>
            <Select
              showSearch
              allowClear
              placeholder="请选择场景"
              options={sceneTypeOptions}
            />
          </Form.Item>
          <Form.Item name="arrester_config" label="避雷器装设组合" rules={[{ required: true, message: "请选择避雷器装设组合" }]}>
            <Select
              showSearch
              allowClear
              placeholder="请选择避雷器装设组合"
              options={arresterConfigOptions}
            />
          </Form.Item>
          <Form.Item label="上传模型文件" required>
            <div>
              <Upload.Dragger
                directory
                multiple
                showUploadList={false}
                beforeUpload={(file) => {
                  setFileList((prev) => [...prev, file]);
                  return false;
                }}
                onRemove={() => {
                  setFileList([]);
                  setTempFileId(null);
                  setUploadProgress(0);
                  setUploadError("");
                }}
              >
                {fileList.length === 0 ? (
                  <>
                    <InboxOutlined style={{ fontSize: 40, color: "#999" }} />
                    <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                      点击或拖拽模型文件夹到此区域上传
                    </p>
                    <Typography.Text type="secondary">
                      支持选择整个 ATP 模型目录（含 work.atp 与 lib 等文件），选择后自动打包上传到临时存储。
                    </Typography.Text>
                  </>
                ) : (
                  <>
                    <p className="ant-upload-text">已选择 {fileList.length} 个文件</p>
                    {uploadProgress > 0 && uploadProgress < 100 ? (
                      <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                    ) : tempFileId ? (
                      <Typography.Text type="success">
                        <CheckCircleOutlined /> 上传完成，可以创建模型
                      </Typography.Text>
                    ) : (
                      <Typography.Text type="warning">上传中…</Typography.Text>
                    )}
                  </>
                )}
                {uploadError && (
                  <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                    {uploadError}
                  </Typography.Text>
                )}
              </Upload.Dragger>
              {fileList.length > 0 && (
                <div style={{
                  marginTop: 8,
                  maxHeight: '200px',
                  overflowY: 'auto',
                  border: '1px solid var(--ant-color-border)',
                  borderRadius: '4px',
                  padding: '8px',
                  backgroundColor: 'var(--ant-color-bg-container)'
                }}>
                  {fileList.map((file, index) => (
                    <div key={index} style={{
                      padding: '4px 0',
                      fontSize: '13px',
                      color: 'var(--ant-color-text-secondary)',
                      borderBottom: index < fileList.length - 1 ? '1px solid var(--ant-color-border-secondary)' : 'none',
                      wordBreak: 'break-all'
                    }}>
                      {getUploadRelativePath(file)}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={`编辑 ATP 模型${editingAsset ? ` - ${editingAsset.name || editingAsset.code}` : ""}`}
        open={editModalOpen}
        forceRender
        onCancel={closeEditModal}
        onOk={() => void editForm.submit()}
        confirmLoading={updateAssetMutation.isPending}
        destroyOnHidden
        okText={updateAssetMutation.isPending ? "提交中..." : "保存"}
        cancelText="取消"
        width={640}
      >
        <Form
          form={editForm}
          layout="vertical"
          onFinish={(values) => {
            void updateAssetMutation.mutateAsync(values);
          }}
          autoComplete="off"
        >
          <div className="grid gap-x-4 md:grid-cols-2">
            <Form.Item name="name" label="名称" rules={[{ required: true, message: "请输入名称" }]}>
              <Input placeholder="模型名称" maxLength={255} />
            </Form.Item>
            <Form.Item name="storage_mount_code" label="存储挂载">
              <Input placeholder="如 main" maxLength={64} />
            </Form.Item>
            <Form.Item name="voltage_level" label="电压等级" rules={[{ required: true, message: "请选择电压等级" }]}>
              <Select
                showSearch
                allowClear
                placeholder="请选择电压等级"
                options={voltageLevelOptions}
              />
            </Form.Item>
            <Form.Item name="tower_type" label="塔型" rules={[{ required: true, message: "请选择塔型" }]}>
              <Select
                showSearch
                allowClear
                placeholder="请选择塔型"
                options={towerTypeOptions}
              />
            </Form.Item>
            <Form.Item name="scene_type" label="场景" rules={[{ required: true, message: "请选择场景" }]}>
              <Select
                showSearch
                allowClear
                placeholder="请选择场景"
                options={sceneTypeOptions}
              />
            </Form.Item>
            <Form.Item name="arrester_config" label="避雷器装设组合" rules={[{ required: true, message: "请选择避雷器装设组合" }]}>
              <Select
                showSearch
                allowClear
                placeholder="请选择避雷器装设组合"
                options={arresterConfigOptions}
              />
            </Form.Item>
            <Form.Item name="storage_root_path" label="存储目录" className="md:col-span-2" rules={[{ required: true, message: "请输入存储目录" }]}>
              <Input placeholder="如 /atp-assets/220kV/猫头塔/平原/避雷器组合A" maxLength={2048} />
            </Form.Item>
            <Form.Item name="description" label="描述" className="md:col-span-2">
              <Input.TextArea rows={2} placeholder="模型描述（可选）" maxLength={8000} />
            </Form.Item>
          </div>
        </Form>
      </Modal>

      <AtpModelTestDrawer
        asset={testAsset}
        open={Boolean(testAsset)}
        onClose={() => setTestAsset(null)}
      />
    </div>
  );
}
