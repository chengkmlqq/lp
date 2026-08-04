"use client";

import { useMutation, useQuery, useQueryClient, useQueries } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Breadcrumb,
  Typography,
  Upload,
  type CardProps,
} from "antd";
import { UploadOutlined, FolderOutlined, FileOutlined, TableOutlined, FolderOpenOutlined, HomeOutlined, DeleteOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";
import type { AtpAssetListResponse, AtpAssetSummary, AtpAssetFileListResponse, DimensionTypeTreeItem } from "@/types/auth";
import type { DimensionItemListResponse } from "@/types/dimension";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type AssetFormValues = {
  voltage_level: string;
  tower_type: string;
  scene_type: string;
  arrester_config: string;
  files: File[];
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
const ATP_TABLE_VIEWPORT_GAP = 40;
const ATP_TABLE_FALLBACK_RESERVE = 220;

export default function AtpModelsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<AssetFormValues>();
  const isMobile = useMobileDetection();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [fileList, setFileList] = useState<File[]>([]);
  const [tableScrollY, setTableScrollY] = useState(ATP_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [displayMode, setDisplayMode] = useState<"list" | "file">("file");
  const [fileViewPath, setFileViewPath] = useState<string[]>([]);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedAssets, setAllLoadedAssets] = useState<AtpAssetSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("atp.manage");
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
    queryKey: ["atp-assets", assetsQueryParams],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets?${assetsQueryParams}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetListResponse;
    },
  });

  const createAssetMutation = useMutation({
    mutationFn: async (values: AssetFormValues) => {
      if (values.files.length === 0) {
        throw new Error("请先选择模型文件");
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

      if (values.files.length > 0) {
        const formData = new FormData();
        const JSZip = (await import("jszip")).default;
        const zip = new JSZip();
        for (const file of values.files) {
          const fullPath = (file as any).webkitRelativePath || file.name;
          // Strip the outermost directory level
          const pathParts = fullPath.split('/');
          const strippedPath = pathParts.length > 1 ? pathParts.slice(1).join('/') : fullPath;
          if (strippedPath) {
            zip.file(strippedPath, file);
          }
        }
        const zipBlob = await zip.generateAsync({ type: "blob" });
        formData.append("files", zipBlob, "model.zip");

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
      setError("");
      setModalOpen(false);
      setFileList([]);
      form.resetFields();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "创建模型失败");
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
      setError("");
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除模型失败");
    },
  });

  const openCreateModal = useCallback(() => {
    setError("");
    setSuccess("");
    setFileList([]);
    form.setFieldsValue(EMPTY_FORM);
    setModalOpen(true);
  }, [form]);

  const closeModal = () => {
    if (createAssetMutation.isPending) return;
    setModalOpen(false);
    setFileList([]);
    form.resetFields();
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

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

  // File view mode needs ALL assets to build the dimension tree correctly.
  // The paginated query only fetches 20 items which may all be from one voltage level.
  // API max limit is 200, so we page through to get all items.
  const fileViewAssetsQuery = useQuery({
    queryKey: ["atp-assets-all", trimmedKeyword],
    enabled: Boolean(user && canRead && displayMode === "file"),
    queryFn: async () => {
      const limit = 200;
      let offset = 0;
      let allItems: AtpAssetSummary[] = [];
      while (true) {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        params.set("offset", String(offset));
        if (trimmedKeyword) {
          params.set("keyword", trimmedKeyword);
        }
        const response = await fetchWithAuth(`/api/v1/atp/assets?${params.toString()}`);
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const data = (await response.json()) as AtpAssetListResponse;
        allItems = allItems.concat(data.items);
        if (data.items.length < limit) break;
        offset += limit;
      }
      return { items: allItems, total: allItems.length } as AtpAssetListResponse;
    },
  });
  const fileViewAssetItems = useMemo(
    () => fileViewAssetsQuery.data?.items ?? assetItems,
    [fileViewAssetsQuery.data?.items, assetItems],
  );
  const assetTotal = assetsQuery.data?.total ?? 0;
  const queryError = assetsQuery.error instanceof Error ? assetsQuery.error.message : "";
  const anyError = error || queryError;

  useToastFeedback({
    errorMessage: anyError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  useEffect(() => {
    if (viewMode !== "card" || assetsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedAssets(() => assetItems);
      } else {
        setAllLoadedAssets((previous) => {
          if (assetItems.length === 0) {
            return previous;
          }
          const existingIds = new Set(previous.map((item) => item.id));
          const newAssets = assetItems.filter((item) => !existingIds.has(item.id));
          return [...previous, ...newAssets];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [assetItems, assetsQuery.isLoading, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || assetsQuery.isLoading) return;

      const { scrollTop, scrollHeight, clientHeight } = cardBody;

      if (scrollTop + clientHeight >= scrollHeight - 100 && allLoadedAssets.length < assetTotal) {
        setIsLoadingMore(true);
        setCardViewPage((previous) => previous + 1);
        setPagination((previous) => ({ ...previous, current: previous.current + 1 }));
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [allLoadedAssets.length, assetTotal, assetsQuery.isLoading, isLoadingMore, viewMode]);

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - ATP_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? ATP_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - ATP_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(ATP_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [anyError, paginationCurrent, paginationPageSize, assetItems.length, assetsQuery.isFetching, displayMode, viewMode, updateTableScrollY]);

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
  }, [updateTableScrollY, displayMode, viewMode]);

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
        width: 100,
        render: (_, item) => {
          const deleteLoading = deleteMutation.isPending;
          const rowBusy = deleteLoading;

          return (
            <Button danger size="small" icon={<DeleteOutlined />} loading={deleteLoading} disabled={!canManage || rowBusy}
              onClick={() => {
                Modal.confirm({
                  title: "删除模型",
                  content: "这会同时删除其文件与运行记录。",
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true, loading: deleteLoading },
                  onOk: () => deleteMutation.mutate(item.id),
                });
              }}
            >
              删除
            </Button>
          );
        },
      },
    ],
    [canManage, deleteMutation, formatDimensionValue],
  );

  type FileViewItem = {
    type: "folder" | "file";
    name: string;
    displayName: string;
    value: string;
    item?: AtpAssetSummary;
    isDir?: boolean;
    relativePath?: string;
  };

  const matchingAssets = useMemo(() => {
    if (fileViewPath.length < 4) {
      return [];
    }

    const voltage = fileViewPath[0];
    const tower = fileViewPath[1];
    const scene = fileViewPath[2];
    const arrester = fileViewPath[3];

    return fileViewAssetItems.filter(
      (item) =>
        (item.voltage_level || "未分类") === voltage &&
        (item.tower_type || "未分类") === tower &&
        (item.scene_type || "未分类") === scene &&
        (item.arrester_config || "未分类") === arrester
    );
  }, [fileViewAssetItems, fileViewPath]);

  const filesQueries = useQueries({
    queries: matchingAssets.map((asset) => ({
      queryKey: ["atp-asset-files", asset.id],
      enabled: Boolean(user && canRead && displayMode === "file" && fileViewPath.length >= 4),
      queryFn: async () => {
        const response = await fetchWithAuth(`/api/v1/atp/assets/${asset.id}/files`);
        if (!response.ok) {
          return { asset_id: asset.id, release_id: null, storage_mount_code: "", storage_root_path: "", items: [], total: 0 } satisfies AtpAssetFileListResponse;
        }
        return (await response.json()) as AtpAssetFileListResponse;
      },
    })),
  });

  const isFileViewLoading = displayMode === "file" && fileViewPath.length >= 4 && filesQueries.some((query) => query.isLoading);

  const fileViewItems = useMemo<FileViewItem[]>(() => {
    const currentLevel = fileViewPath.length;

    if (currentLevel === 0) {
      const voltageSet = new Set<string>();
      fileViewAssetItems.forEach((item) => {
        const voltage = item.voltage_level || "未分类";
        voltageSet.add(voltage);
      });
      return Array.from(voltageSet)
        .sort((a, b) => a.localeCompare(b, "zh-CN"))
        .map((voltage) => ({
          type: "folder" as const,
          name: voltage,
          displayName: formatDimensionValue(voltage, "voltage_level"),
          value: voltage,
        }));
    }

    if (currentLevel === 1) {
      const voltage = fileViewPath[0];
      const towerSet = new Set<string>();
      fileViewAssetItems
        .filter((item) => (item.voltage_level || "未分类") === voltage)
        .forEach((item) => {
          const tower = item.tower_type || "未分类";
          towerSet.add(tower);
        });
      return Array.from(towerSet)
        .sort((a, b) => a.localeCompare(b, "zh-CN"))
        .map((tower) => ({
          type: "folder" as const,
          name: tower,
          displayName: formatDimensionValue(tower, "tower_type"),
          value: tower,
        }));
    }

    if (currentLevel === 2) {
      const voltage = fileViewPath[0];
      const tower = fileViewPath[1];
      const sceneSet = new Set<string>();
      fileViewAssetItems
        .filter(
          (item) =>
            (item.voltage_level || "未分类") === voltage &&
            (item.tower_type || "未分类") === tower
        )
        .forEach((item) => {
          const scene = item.scene_type || "未分类";
          sceneSet.add(scene);
        });
      return Array.from(sceneSet)
        .sort((a, b) => a.localeCompare(b, "zh-CN"))
        .map((scene) => ({
          type: "folder" as const,
          name: scene,
          displayName: formatDimensionValue(scene, "scene_type"),
          value: scene,
        }));
    }

    if (currentLevel === 3) {
      const voltage = fileViewPath[0];
      const tower = fileViewPath[1];
      const scene = fileViewPath[2];
      const arresterSet = new Set<string>();
      fileViewAssetItems
        .filter(
          (item) =>
            (item.voltage_level || "未分类") === voltage &&
            (item.tower_type || "未分类") === tower &&
            (item.scene_type || "未分类") === scene
        )
        .forEach((item) => {
          const arrester = item.arrester_config || "未分类";
          arresterSet.add(arrester);
        });
      return Array.from(arresterSet)
        .sort((a, b) => a.localeCompare(b, "zh-CN"))
        .map((arrester) => ({
          type: "folder" as const,
          name: arrester,
          displayName: formatDimensionValue(arrester, "arrester_config"),
          value: arrester,
        }));
    }

    if (currentLevel >= 4) {
      if (filesQueries.some((query) => query.isLoading)) {
        return [];
      }

      const allFiles: Array<{ name: string; relativePath: string; isDir: boolean }> = [];
      filesQueries.forEach((query, index) => {
        const asset = matchingAssets[index];
        if (!asset || !query.data?.items) {
          return;
        }
        query.data.items.forEach((file) => {
          allFiles.push({
            name: file.name,
            relativePath: file.relative_path,
            isDir: file.is_dir,
          });
        });
      });

      if (currentLevel === 4) {
        const rootFiles = allFiles.filter((file) => !file.relativePath.includes("/"));

        const fileMap = new Map<string, typeof rootFiles[0]>();
        rootFiles.forEach((file) => {
          if (!fileMap.has(file.name) || file.isDir) {
            fileMap.set(file.name, file);
          }
        });

        return Array.from(fileMap.values())
          .sort((a, b) => {
            if (a.isDir === b.isDir) return a.name.localeCompare(b.name, "zh-CN");
            return a.isDir ? -1 : 1;
          })
          .map((file) => ({
            type: file.isDir ? ("folder" as const) : ("file" as const),
            name: file.name,
            displayName: file.name,
            value: file.relativePath,
            isDir: file.isDir,
            relativePath: file.relativePath,
          }));
      }

      const pathInAsset = fileViewPath.slice(4).join("/");
      const prefix = pathInAsset + "/";

      const filesInPath = allFiles.filter((file) => {
        if (!file.relativePath.startsWith(prefix)) {
          return false;
        }
        const remainder = file.relativePath.substring(prefix.length);
        return !remainder.includes("/");
      });

      const fileMap = new Map<string, typeof filesInPath[0]>();
      filesInPath.forEach((file) => {
        if (!fileMap.has(file.name) || file.isDir) {
          fileMap.set(file.name, file);
        }
      });

      return Array.from(fileMap.values())
        .sort((a, b) => {
          if (a.isDir === b.isDir) return a.name.localeCompare(b.name, "zh-CN");
          return a.isDir ? -1 : 1;
        })
        .map((file) => ({
          type: file.isDir ? ("folder" as const) : ("file" as const),
          name: file.name,
          displayName: file.name,
          value: file.relativePath,
          isDir: file.isDir,
          relativePath: file.relativePath,
        }));
    }

    return [];
  }, [assetItems, fileViewPath, matchingAssets, filesQueries, formatDimensionValue]);

  const handleFileViewItemClick = (item: FileViewItem) => {
    if (item.type === "folder") {
      setFileViewPath([...fileViewPath, item.name]);
    }
  };

  const handleBreadcrumbClick = (index: number) => {
    if (index === -1) {
      setFileViewPath([]);
    } else {
      setFileViewPath(fileViewPath.slice(0, index + 1));
    }
  };

  const getBreadcrumbLabel = (index: number): string => {
    if (index === 0) return formatDimensionValue(fileViewPath[0], "voltage_level");
    if (index === 1) return formatDimensionValue(fileViewPath[1], "tower_type");
    if (index === 2) return formatDimensionValue(fileViewPath[2], "scene_type");
    if (index === 3) return formatDimensionValue(fileViewPath[3], "arrester_config");
    if (index >= 4) {
      return fileViewPath[index];
    }
    return "";
  };

  const renderAtpModelCard = (item: AtpAssetSummary) => {
    const deleteLoading = deleteMutation.isPending;
    const rowBusy = deleteLoading;

    return (
      <AntCard
        key={item.id}
        className="admin-atp-models-model-card"
        size="small"
        title={
          <Typography.Text strong ellipsis={{ tooltip: item.name }}>
            {item.name}
          </Typography.Text>
        }
        extra={
          <Button
            danger
            size="small"
            disabled={!canManage || rowBusy}
            loading={deleteLoading}
            onClick={() => {
              Modal.confirm({
                title: "删除模型",
                content: "这会同时删除其文件与运行记录。",
                okText: "删除",
                cancelText: "取消",
                okButtonProps: { danger: true },
                onOk: () => deleteMutation.mutate(item.id),
              });
            }}
          >
            删除
          </Button>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-atp-models-model-card-field">
            <Typography.Text type="secondary">电压等级</Typography.Text>
            <Typography.Text>{formatDimensionValue(item.voltage_level, "voltage_level")}</Typography.Text>
          </div>
          <div className="admin-atp-models-model-card-field">
            <Typography.Text type="secondary">塔型</Typography.Text>
            <Typography.Text>{formatDimensionValue(item.tower_type, "tower_type")}</Typography.Text>
          </div>
          <div className="admin-atp-models-model-card-field">
            <Typography.Text type="secondary">场景</Typography.Text>
            <Typography.Text>{formatDimensionValue(item.scene_type, "scene_type")}</Typography.Text>
          </div>
          <div className="admin-atp-models-model-card-field">
            <Typography.Text type="secondary">避雷器组合</Typography.Text>
            <Typography.Text>{formatDimensionValue(item.arrester_config, "arrester_config")}</Typography.Text>
          </div>
          <div className="admin-atp-models-model-card-field">
            <Typography.Text type="secondary">更新时间</Typography.Text>
            <Typography.Text>{formatDateTime(item.update_date)}</Typography.Text>
          </div>
        </Space>
      </AntCard>
    );
  };

  if (initializing) {
    return <AdminPageLoading tip="加载 ATP 模型中..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <AntCard title="ATP 模型管理">
        <Typography.Text type="secondary">
          {!user ? "请先登录后再查看 ATP 模型管理。" : "当前账号无 ATP 模块权限（需要 atp.read/atp.run/atp.manage）。"}
        </Typography.Text>
      </AntCard>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AntCard
        ref={pageCardRef}
        className="admin-atp-models-page-card"
        title="ATP 模型管理"
        extra={
          <Button
            type="primary"
            disabled={!canManage}
            onClick={openCreateModal}
          >
            新建模型
          </Button>
        }
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                    allowClear
                    value={keywordInput}
                    onChange={(event) => handleKeywordChange(event.target.value)}
                    placeholder="按编码/名称搜索"
                    onPressEnter={() => {
                      setSearchKeyword(keywordInput);
                      setPagination((previous) => ({ ...previous, current: 1 }));
                      setCardViewPage(1);
                      void queryClient.refetchQueries({
                        predicate: (query) =>
                          Array.isArray(query.queryKey)
                          && typeof query.queryKey[0] === "string"
                          && query.queryKey[0].startsWith("atp-assets"),
                      });
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
                    void queryClient.refetchQueries({
                      predicate: (query) =>
                        Array.isArray(query.queryKey)
                        && typeof query.queryKey[0] === "string"
                        && query.queryKey[0].startsWith("atp-assets"),
                    });
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
            <Form layout="inline" style={{ flex: 'none' }}>
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  value={keywordInput}
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  placeholder="按编码/名称搜索"
                  onPressEnter={() => {
                    setSearchKeyword(keywordInput);
                    setPagination((previous) => ({ ...previous, current: 1 }));
                    setCardViewPage(1);
                    void queryClient.refetchQueries({
                      predicate: (query) =>
                        Array.isArray(query.queryKey)
                        && typeof query.queryKey[0] === "string"
                        && query.queryKey[0].startsWith("atp-assets"),
                    });
                  }}
                />
              </Form.Item>
            </Form>
            <Button
              htmlType="button"
              icon={<SearchOutlined />}
              onClick={() => {
                setSearchKeyword(keywordInput);
                setPagination((previous) => ({ ...previous, current: 1 }));
                setCardViewPage(1);
                void queryClient.refetchQueries({
                  predicate: (query) =>
                    Array.isArray(query.queryKey)
                    && typeof query.queryKey[0] === "string"
                    && query.queryKey[0].startsWith("atp-assets"),
                });
              }}
              className="admin-search-btn"
            >
              查询
            </Button>
            {!isMobile && (
              <div style={{ marginLeft: 'auto' }}>
                <Segmented
                  value={displayMode}
                  onChange={(value) => {
                    setDisplayMode(value as "list" | "file");
                    if (value === "list") {
                      setFileViewPath([]);
                    }
                  }}
                  options={[
                    { value: "list", icon: <TableOutlined /> },
                    { value: "file", icon: <FolderOpenOutlined /> },
                  ]}
                />
              </div>
            )}
          </div>
        )}

        {displayMode === "file" && viewMode === "table" ? (
          <div className="admin-atp-models-file-view" style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
            <div style={{ margin: "16px 0" }}>
              <Breadcrumb
                items={[
                  {
                    title: (
                      <a onClick={() => handleBreadcrumbClick(-1)}>
                        <HomeOutlined /> ATP模型
                      </a>
                    ),
                  },
                  ...fileViewPath.map((_, index) => ({
                    title: (
                      <a onClick={() => handleBreadcrumbClick(index)}>
                        {getBreadcrumbLabel(index)}
                      </a>
                    ),
                  })),
                ]}
              />
            </div>
            <div style={{ flex: 1, minHeight: 0, overflow: "auto", border: "1px solid #f0f0f0", borderRadius: "4px" }}>
              {assetsQuery.isLoading || assetsQuery.isFetching || isFileViewLoading ? (
                <div style={{ textAlign: "center", padding: "40px 0" }}>
                  <Spin tip="加载中..." />
                </div>
              ) : fileViewItems.length === 0 ? (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="当前目录为空"
                />
              ) : (
                <div>
                  {fileViewItems.map((item, index) =>
                    item.type === "folder" ? (
                      <div
                        key={index}
                        onClick={() => handleFileViewItemClick(item)}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          padding: "12px 16px",
                          cursor: "pointer",
                          borderBottom: index < fileViewItems.length - 1 ? "1px solid #f0f0f0" : "none",
                          transition: "background-color 0.2s",
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.backgroundColor = "#f5f5f5";
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.backgroundColor = "transparent";
                        }}
                      >
                        <FolderOutlined style={{ fontSize: "20px", color: "#faad14", marginRight: "12px" }} />
                        <Typography.Text style={{ flex: 1 }}>{item.displayName}</Typography.Text>
                      </div>
                    ) : (
                      <div
                        key={index}
                        style={{
                          display: "flex",
                          alignItems: "center",
                          padding: "12px 16px",
                          borderBottom: index < fileViewItems.length - 1 ? "1px solid #f0f0f0" : "none",
                        }}
                      >
                        <FileOutlined style={{ fontSize: "20px", color: "#1890ff", marginRight: "12px" }} />
                        <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                          <div style={{ display: "flex", flexDirection: "column" }}>
                            <Typography.Text>{item.displayName}</Typography.Text>
                            <Typography.Text type="secondary" style={{ fontSize: "12px" }}>
                              {item.item && formatDateTime(item.item.update_date)}
                            </Typography.Text>
                          </div>
                          {item.item && (
                            <Button danger size="small" disabled={!canManage}
                              onClick={() => {
                                Modal.confirm({
                                  title: "删除模型",
                                  content: "这会同时删除其文件与运行记录。",
                                  okText: "删除",
                                  cancelText: "取消",
                                  okButtonProps: { danger: true },
                                  onOk: () => item.item && deleteMutation.mutate(item.item.id),
                                });
                              }}
                            >
                              删除
                            </Button>
                          )}
                        </div>
                      </div>
                    )
                  )}
                </div>
              )}
            </div>
          </div>
        ) : viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-atp-models-table-anchor"
            style={{ "--admin-atp-models-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<AtpAssetSummary>
              rowKey="id"
              loading={assetsQuery.isLoading || assetsQuery.isFetching}
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
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${assetTotal} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
                onChange: (page, pageSize) => {
                  setPagination({ current: page, pageSize });
                },
              }}
              scroll={{ y: tableScrollY }}
            />
          </div>
        ) : (
          <div className="admin-atp-models-card-view">
            {assetsQuery.isLoading && allLoadedAssets.length === 0 ? (
              <div className="admin-atp-models-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedAssets.length === 0 ? (
              <div className="admin-atp-models-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的 ATP 模型。"
                />
              </div>
            ) : (
              <div className="admin-atp-models-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedAssets.map((item) => (
                    <Col key={item.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderAtpModelCard(item)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedAssets.length >= assetTotal && allLoadedAssets.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedAssets.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      <Modal
        title="新建 ATP 模型"
        open={modalOpen}
        onCancel={closeModal}
        onOk={() => void form.submit()}
        confirmLoading={createAssetMutation.isPending}
        destroyOnClose
        okText={createAssetMutation.isPending ? "提交中..." : "创建模型"}
        cancelText="取消"
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
              <Upload
                beforeUpload={(file) => {
                  setFileList((prev) => [...prev, file]);
                  return false;
                }}
                directory
                multiple
                showUploadList={false}
              >
                <Button icon={<UploadOutlined />}>选择文件夹</Button>
              </Upload>
              {fileList.length > 0 && (
                <div style={{
                  marginTop: 8,
                  maxHeight: '200px',
                  overflowY: 'auto',
                  border: '1px solid #d9d9d9',
                  borderRadius: '4px',
                  padding: '8px',
                  backgroundColor: '#fafafa'
                }}>
                  <div style={{ marginBottom: 8, fontWeight: 500, color: '#666' }}>
                    已选择 {fileList.length} 个文件
                  </div>
                  {fileList.map((file, index) => (
                    <div key={index} style={{
                      padding: '4px 0',
                      fontSize: '13px',
                      color: '#595959',
                      borderBottom: index < fileList.length - 1 ? '1px solid #f0f0f0' : 'none',
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
    </div>
  );
}
