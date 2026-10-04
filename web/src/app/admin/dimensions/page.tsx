"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Badge,
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Skeleton,
  Spin,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
  Typography,
  type CardProps,
  type MenuProps,
  type TableColumnsType,
  type TreeProps,
} from "antd";
import { EditOutlined, MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import type { ComponentType, RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  DimensionTypeTreeItem,
} from "@/types/auth";
import type { DimensionItem, DimensionItemListResponse } from "@/types/dimension";

type StatusFilter = "enabled" | "disabled" | undefined;

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const DIMENSIONS_TABLE_MIN_SCROLL_Y = 180;
const DIMENSIONS_TABLE_VIEWPORT_GAP = 40;
const DIMENSIONS_TABLE_FALLBACK_RESERVE = 220;

function statusLabel(enabled: boolean): string {
  return enabled ? "启用" : "禁用";
}

function flattenTypeOptions(types: DimensionTypeTreeItem[] | undefined | null, level: number = 0): { value: string; label: string }[] {
  if (!Array.isArray(types)) return [];
  return types.flatMap((t) => [
    { value: t.id, label: "　".repeat(level) + (t.name || t.code) },
    ...flattenTypeOptions(t.children, level + 1),
  ]);
}

function findType(types: DimensionTypeTreeItem[] | undefined | null, id: string): DimensionTypeTreeItem | null {
  if (!Array.isArray(types)) return null;
  for (const t of types) {
    if (t.id === id) return t;
    const found = findType(t.children, id);
    if (found) return found;
  }
  return null;
}

// 从维度列表查询 URL 中取出 type_id 参数值：type_id 变化即表示切换到另一份数据集
// （点击左侧类型树/移动端类型下拉），此时不应沿用上一份数据作占位。
function identityTypeOf(path: unknown): string {
  if (typeof path !== "string") return "";
  const search = path.split("?")[1];
  if (!search) return "";
  return new URLSearchParams(search).get("type_id") ?? "";
}

export default function AdminDimensionsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  // 手动刷新计数：每次点击「查询」都自增并作为 queryKey 的一部分，强制走一次接口，
  // 即使关键词/分页未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [statusFilterInput, setStatusFilterInput] = useState<StatusFilter>(undefined);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(undefined);
  const [typeIdFilter, setTypeIdFilter] = useState<string | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [tableScrollY, setTableScrollY] = useState(DIMENSIONS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [viewModeOverride, setViewModeOverride] = useState<"card" | "table" | null>(null);
  const viewMode: "table" | "card" = viewModeOverride ?? (isMobile ? "card" : "table");
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedDimensions, setAllLoadedDimensions] = useState<DimensionItem[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const containerRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      setLeftPanelWidth(Math.max(180, Math.min(600, e.clientX - rect.left)));
    };
    const handleMouseUp = () => {
      if (isResizing.current) {
        isResizing.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  const canRead = hasPermission("dimension.read") || hasPermission("dimension.manage");
  const canManage = hasPermission("dimension.manage");

  // ===== Type tree state =====
  const [selectedTypeId, setSelectedTypeId] = useState<string | null>(null);
  const [typeSearch, setTypeSearch] = useState("");
  const [typeEditorOpen, setTypeEditorOpen] = useState(false);
  const [editingTypeId, setEditingTypeId] = useState<string | null>(null);
  const [typeCodeInput, setTypeCodeInput] = useState("");
  const [typeNameInput, setTypeNameInput] = useState("");
  const [typeParentId, setTypeParentId] = useState<string | null>(null);
  const [typeSortInput, setTypeSortInput] = useState("0");

  const [dimensionEditorOpen, setDimensionEditorOpen] = useState(false);
  const [editingDimension, setEditingDimension] = useState<DimensionItem | null>(null);
  const [dimensionForm] = Form.useForm<{
    type_id: string;
    code: string;
    name: string;
    parent_id?: string;
    description?: string;
    is_enabled: boolean;
    sort_order: number;
  }>();

  const typeTreeQuery = useQuery({
    queryKey: ["/api/v1/dimensions/types/tree"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/dimensions/types/tree");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as unknown;
      if (!Array.isArray(data)) {
        throw new Error("维度类型数据格式异常");
      }
      return data as DimensionTypeTreeItem[];
    },
  });

  const filteredTreeData = useMemo(() => {
    if (!typeSearch.trim()) return typeTreeQuery.data ?? [];

    const searchLower = typeSearch.trim().toLowerCase();
    const filterTypes = (types: DimensionTypeTreeItem[] | undefined | null): DimensionTypeTreeItem[] => {
      if (!Array.isArray(types)) return [];
      return types.reduce<DimensionTypeTreeItem[]>((acc, t) => {
        const nameMatch = (t.name || t.code).toLowerCase().includes(searchLower);
        const filteredChildren = t.children ? filterTypes(t.children) : [];
        if (nameMatch || filteredChildren.length > 0) {
          acc.push({
            ...t,
            children: filteredChildren.length > 0 ? filteredChildren : t.children,
          });
        }
        return acc;
      }, []);
    };
    return filterTypes(typeTreeQuery.data ?? []);
  }, [typeTreeQuery.data, typeSearch]);

  const handleTypeClick: TreeProps["onSelect"] = (selectedKeys) => {
    if (selectedKeys.length > 0) {
      const key = selectedKeys[0] as string;
      if (key === "all") {
        setSelectedTypeId(null);
        setTypeIdFilter(null);
      } else {
        setSelectedTypeId(key);
        setTypeIdFilter(key);
      }
      setPagination((prev) => ({ ...prev, current: 1 }));
      setCardViewPage(1);
      setAllLoadedDimensions([]);
    } else {
      setSelectedTypeId(null);
      setTypeIdFilter(null);
    }
  };

  const openTypeCreate = (parentId: string | null = null) => {
    setEditingTypeId(null);
    setTypeCodeInput("");
    setTypeNameInput("");
    setTypeParentId(parentId);
    setTypeSortInput("0");
    setTypeEditorOpen(true);
  };

  const openTypeEdit = (t: DimensionTypeTreeItem) => {
    setEditingTypeId(t.id);
    setTypeCodeInput(t.code);
    setTypeNameInput(t.name);
    setTypeParentId(t.parent_id);
    setTypeSortInput(String(t.sort_order ?? 0));
    setTypeEditorOpen(true);
  };

  const saveTypeMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) throw new Error("缺少权限");
      const code = typeCodeInput.trim();
      const name = typeNameInput.trim();
      if (!code) throw new Error("类型编码不能为空");
      if (!name) throw new Error("类型名称不能为空");
      const sortOrder = Number(typeSortInput) || 0;

      if (editingTypeId === null) {
        const response = await fetchWithAuth("/api/v1/dimensions/types", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, name, parent_id: typeParentId, sort_order: sortOrder, is_enabled: true }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return "created";
      }

      const response = await fetchWithAuth(`/api/v1/dimensions/types/${editingTypeId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code, name, sort_order: sortOrder }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return "updated";
    },
    onSuccess: async (mode) => {
      setSuccess(mode === "created" ? "维度类型已创建" : "维度类型已更新");
      setTypeEditorOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/dimensions/types/tree"] });
      await queryClient.invalidateQueries({ queryKey: ["admin.dimensions"] });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存维度类型失败");
    },
  });

  const deleteTypeMutation = useMutation({
    mutationFn: async (typeId: string) => {
      const response = await fetchWithAuth(`/api/v1/dimensions/types/${typeId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return typeId;
    },
    onSuccess: async (typeId) => {
      setSuccess("维度类型已删除");
      if (selectedTypeId === typeId) {
        setSelectedTypeId(null);
        setTypeIdFilter(null);
        setPagination((prev) => ({ ...prev, current: 1 }));
      }
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/dimensions/types/tree"] });
      await queryClient.invalidateQueries({ queryKey: ["admin.dimensions"] });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除维度类型失败");
    },
  });

  const getParentOptions = useCallback(() => {
    return flattenTypeOptions(typeTreeQuery.data ?? [])
      .filter((o) => o.value !== editingTypeId && o.value !== selectedTypeId);
  }, [typeTreeQuery.data, editingTypeId, selectedTypeId]);

  // ===== Dimension list =====
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const trimmedKeyword = searchKeyword.trim();

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    if (statusFilter) {
      params.set("enabled", statusFilter === "enabled" ? "true" : "false");
    }
    if (typeIdFilter !== null) {
      params.set("type_id", typeIdFilter);
    }
    const qs = params.toString();
    return `/api/v1/dimensions${qs ? `?${qs}` : ""}`;
  }, [paginationCurrent, paginationPageSize, statusFilter, trimmedKeyword, typeIdFilter]);

  const listQuery = useQuery({
    queryKey: [listPath, searchNonce],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as DimensionItemListResponse;
    },
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询/翻页时列表闪空。
    // type_id 属数据身份：切换类型后沿用旧占位会短暂显示上一个类型下的维度项，故仅当
    // 两次查询的 type_id 一致时才沿用上一份数据；关键词/状态/翻页变化时保留，行不闪空。
    placeholderData: (previousData, previousQuery) => {
      const previousKey = previousQuery?.queryKey;
      const previousPath = Array.isArray(previousKey) ? previousKey[0] : undefined;
      return identityTypeOf(previousPath) === identityTypeOf(listPath) ? previousData : undefined;
    },
  });

  const refreshList = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/dimensions"),
    });
  }, [queryClient]);

  useTopicSubscription(
    "admin.dimension-types",
    useCallback(() => {
      if (!user || !canRead) return;
      void queryClient.invalidateQueries({ queryKey: ["/api/v1/dimensions/types/tree"] });
      void refreshList();
    }, [canRead, refreshList, user, queryClient]),
  );

  useTopicSubscription(
    "admin.dimension-items",
    useCallback(() => {
      if (!user || !canRead) return;
      void refreshList();
    }, [canRead, refreshList, user]),
  );

  // ===== Dimension CRUD =====
  const openDimensionCreate = useCallback(() => {
    setError("");
    setSuccess("");
    setEditingDimension(null);
    dimensionForm.resetFields();
    dimensionForm.setFieldsValue({
      is_enabled: true,
      sort_order: 0,
      type_id: selectedTypeId ?? undefined,
    });
    setDimensionEditorOpen(true);
  }, [dimensionForm, selectedTypeId]);

  const openDimensionEdit = useCallback((item: DimensionItem) => {
    setError("");
    setSuccess("");
    setEditingDimension(item);
    dimensionForm.setFieldsValue({
      type_id: item.type_id ?? undefined,
      code: item.code,
      name: item.name,
      parent_id: item.parent_id || undefined,
      description: item.description || undefined,
      is_enabled: item.is_enabled,
      sort_order: item.sort_order,
    });
    setDimensionEditorOpen(true);
  }, [dimensionForm]);

  const saveDimensionMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) throw new Error("缺少 dimension.manage 权限");
      const values = await dimensionForm.validateFields();
      if (!values.code.trim() || !values.name.trim()) {
        throw new Error("维度编码和维度名称不能为空");
      }
      const typeId = values.type_id ?? null;
      if (!typeId) {
        throw new Error("请选择维度类型");
      }

      if (editingDimension === null) {
        const response = await fetchWithAuth("/api/v1/dimensions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            type_id: typeId,
            dimension_type: "",
            code: values.code.trim(),
            name: values.name.trim(),
            parent_id: values.parent_id ?? null,
            description: values.description ?? null,
            is_enabled: values.is_enabled,
            sort_order: values.sort_order ?? 0,
          }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return "created";
      }

      const response = await fetchWithAuth(`/api/v1/dimensions/${editingDimension.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type_id: typeId,
          code: values.code.trim(),
          name: values.name.trim(),
          parent_id: values.parent_id ?? null,
          description: values.description ?? null,
          is_enabled: values.is_enabled,
          sort_order: values.sort_order ?? 0,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return "updated" as const;
    },
    onMutate: () => {
      setError("");
      setSuccess("");
    },
    onSuccess: async (mode) => {
      setSuccess(mode === "created" ? "维度项已创建" : "维度项已更新");
      setDimensionEditorOpen(false);
      setEditingDimension(null);
      dimensionForm.resetFields();
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "保存维度项失败");
    },
  });

  const deleteDimensionMutation = useMutation({
    mutationFn: async (id: string) => {
      const response = await fetchWithAuth(`/api/v1/dimensions/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return id;
    },
    onSuccess: async () => {
      setSuccess("维度项已删除");
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除维度项失败");
    },
  });

  const removeDimension = useCallback(async (id: string) => {
    setDeletingId(id);
    try {
      await deleteDimensionMutation.mutateAsync(id);
    } finally {
      setDeletingId(null);
    }
  }, [deleteDimensionMutation]);

  const updateStatusMutation = useMutation({
    mutationFn: async ({ item, is_enabled }: { item: DimensionItem; is_enabled: boolean }) => {
      const response = await fetchWithAuth(`/api/v1/dimensions/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_enabled }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return is_enabled;
    },
    onMutate: ({ item }) => {
      setUpdatingId(item.id);
      setSuccess("");
    },
    onSuccess: async (enabled) => {
      setSuccess(enabled ? "维度项已启用" : "维度项已禁用");
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "更新维度项状态失败");
    },
    onSettled: () => setUpdatingId(null),
  });

  const toggleDimensionStatus = useCallback((item: DimensionItem) => {
    updateStatusMutation.mutate({ item, is_enabled: !item.is_enabled });
  }, [updateStatusMutation]);

  const handleQuery = () => {
    // 每次点击「查询」都强制触发一次接口请求：searchNonce 作为 queryKey 的一部分自增，
    // 即便关键词/分页均未变化（旧实现仅 refetchQueries，目标 key 已被 react-query 缓存时
    // 会短路不发请求）也会产生新 key 重新拉取；关键词/状态照常提交并回到第 1 页。
    // 卡片累积列表不清空：新查询进行中旧卡片保留在 Spin 遮罩之下，接口返回后再由
    // 累积 effect（cardViewPage===1）整体替换，避免查询开始时卡片闪空。
    setSearchKeyword(keywordInput);
    setStatusFilter(statusFilterInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(() => 1);
    setSearchNonce((n) => n + 1);
  };

  const rawItems = useMemo(() => listQuery.data?.items ?? [], [listQuery.data?.items]);
  const items = useMemo(() => {
    const total = listQuery.data?.total ?? 0;
    if (rawItems.length > paginationPageSize && rawItems.length === total) {
      const start = (paginationCurrent - 1) * paginationPageSize;
      return rawItems.slice(start, start + paginationPageSize);
    }
    return rawItems;
  }, [listQuery.data?.total, paginationCurrent, paginationPageSize, rawItems]);
  const listError = listQuery.error instanceof Error ? listQuery.error.message : "";

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  // Card-view infinite scroll accumulation
  useEffect(() => {
    // isPlaceholderData 期间展示的是上一份占位数据（新查询进行中），与 isLoading 一样
    // 不能写入累积列表，否则翻页加载会被提前合并、打乱加载更多顺序
    if (viewMode !== "card" || listQuery.isLoading || listQuery.isPlaceholderData) {
      return;
    }
    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedDimensions(() => items);
      } else {
        setAllLoadedDimensions((prev) => {
          if (items.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map((p) => p.id));
          const newItems = items.filter((p) => !existingIds.has(p.id));
          return [...prev, ...newItems];
        });
      }
      setIsLoadingMore(() => false);
    });
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [items, listQuery.isLoading, listQuery.isPlaceholderData, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;
    const scrollContainer = pageCardRef.current;
    if (!scrollContainer) return;
    const handleScroll = () => {
      if (isLoadingMore || listQuery.isLoading) return;
      const scrollTop = scrollContainer.scrollTop;
      const scrollHeight = scrollContainer.scrollHeight;
      const clientHeight = scrollContainer.clientHeight;
      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = listQuery.data?.total ?? 0;
        const loadedCount = allLoadedDimensions.length;
        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };
    scrollContainer.addEventListener("scroll", handleScroll);
    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, listQuery.isLoading, listQuery.data?.total, allLoadedDimensions.length]);

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
  }, [paginationCurrent, paginationPageSize, items.length, listQuery.isFetching, listError, error, success, updateTableScrollY]);

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

  const columns = useMemo<TableColumnsType<DimensionItem>>(() => {
    const baseColumns: TableColumnsType<DimensionItem> = [
      {
        title: "维度类型",
        dataIndex: "type_id",
        key: "type_id",
        width: 140,
        render: (value: string | null) => typeName(value, typeTreeQuery.data),
      },
      {
        title: "维度编码",
        dataIndex: "code",
        key: "code",
        width: 140,
      },
      {
        title: "维度名称",
        dataIndex: "name",
        key: "name",
        width: 180,
        ellipsis: { showTitle: true },
      },
      {
        title: "父级",
        dataIndex: "parent_id",
        key: "parent_id",
        width: 160,
        render: (value: string | null) => {
          if (!value) return "-";
          const parent = rawItems.find((d) => d.id === value);
          return parent ? `${parent.name}（${parent.code}）` : value;
        },
      },
      {
        title: "状态",
        dataIndex: "is_enabled",
        key: "is_enabled",
        width: 100,
        align: "center",
        render: (value: boolean) => (
          <Tag color={value ? "green" : "default"}>{statusLabel(value)}</Tag>
        ),
      },
      {
        title: "排序",
        dataIndex: "sort_order",
        key: "sort_order",
        width: 80,
        align: "center",
      },
      {
        title: "更新时间",
        dataIndex: "update_date",
        key: "update_date",
        width: 180,
        render: (value: string) => formatDateTime(value),
      },
    ];

    if (canManage) {
      baseColumns.push({
        title: "操作",
        key: "actions",
        width: 180,
        fixed: "right",
      render: (_, record) => {
          const deleteLoading = deletingId === record.id;
          const statusLoading = updatingId === record.id;
          const rowBusy = deleteLoading || statusLoading;
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "toggle-status",
              label: record.is_enabled ? "禁用" : "启用",
              disabled: rowBusy,
              onClick: () => toggleDimensionStatus(record),
            },
            {
              key: "delete",
              label: "删除",
              danger: true,
              disabled: rowBusy,
              onClick: () => {
                Modal.confirm({
                  title: "删除维度项",
                  content: `确认删除维度项 ${record.name}（${record.code}）吗？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => void removeDimension(record.id),
                });
              },
            },
          ];
          return (
            <Space wrap>
              <Button size="small" disabled={rowBusy} onClick={() => openDimensionEdit(record)}>
                编辑
              </Button>
              <Button
                size="small"
                danger
                loading={deleteLoading}
                disabled={rowBusy}
                onClick={() => {
                  Modal.confirm({
                    title: "删除维度项",
                    content: `确认删除维度项 ${record.name}（${record.code}）吗？`,
                    okText: "删除",
                    cancelText: "取消",
                    okButtonProps: { danger: true, loading: deleteLoading },
                    onOk: () => void removeDimension(record.id),
                  });
                }}
              >
                删除
              </Button>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" disabled={rowBusy} icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      });
    }

    return baseColumns;
  }, [canManage, deletingId, openDimensionEdit, rawItems, removeDimension, toggleDimensionStatus, typeTreeQuery.data]);

  const renderDimensionCard = (item: DimensionItem) => {
    const deleteLoading = deletingId === item.id;
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "toggle-status",
        label: item.is_enabled ? "禁用" : "启用",
        disabled: deleteLoading,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          toggleDimensionStatus(item);
        },
      },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: deleteLoading,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          Modal.confirm({
            title: "删除维度项",
            content: `确认删除维度项 ${item.name}（${item.code}）吗？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: () => void removeDimension(item.id),
          });
        },
      },
    ];
    const parent = item.parent_id ? rawItems.find((d) => d.id === item.parent_id) : null;
    return (
      <AntCard
        key={item.id}
        className="admin-system-params-param-card"
        size="small"
        hoverable
        onClick={() => openDimensionEdit(item)}
      >
        <div className="admin-system-params-param-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <Typography.Text strong className="truncate flex-1">{item.name}</Typography.Text>
          <div className="flex flex-shrink-0 items-center gap-2">
            <Badge status={item.is_enabled ? "success" : "default"} />
            <Typography.Text type="secondary" className="text-xs">{statusLabel(item.is_enabled)}</Typography.Text>
          </div>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">维度类型</Typography.Text>
            <Typography.Text>{typeName(item.type_id, typeTreeQuery.data)}</Typography.Text>
          </div>
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">维度编码</Typography.Text>
            <Typography.Text className="font-mono text-xs">{item.code}</Typography.Text>
          </div>
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">父级</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: parent ? `${parent.name}（${parent.code}）` : "-" }}>
              {parent ? `${parent.name}（${parent.code}）` : "-"}
            </Typography.Text>
          </div>
          {item.description && (
            <div className="admin-system-params-param-card-field">
              <Typography.Text type="secondary">描述</Typography.Text>
              <Typography.Text ellipsis={{ tooltip: item.description }}>
                {item.description}
              </Typography.Text>
            </div>
          )}
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">排序</Typography.Text>
            <Typography.Text>{item.sort_order}</Typography.Text>
          </div>
        </Space>
        <div className="admin-system-params-param-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          <div />
          <Space size="small" className="shrink-0">
            {canManage ? (
              <>
                <Tooltip title="编辑">
                  <Button
                    type="text"
                    size="small"
                    disabled={deleteLoading}
                    icon={<EditOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      openDimensionEdit(item);
                    }}
                  />
                </Tooltip>
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Tooltip title="更多">
                    <Button
                      type="text"
                      size="small"
                      disabled={deleteLoading}
                      icon={<MoreOutlined />}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </Tooltip>
                </Dropdown>
              </>
            ) : null}
          </Space>
        </div>
      </AntCard>
    );
  };

  const skeletonMenu = (
    <div className="admin-system-params-skeleton-menu">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="admin-system-params-skeleton-item"
          style={i % 3 === 0 ? {} : { paddingLeft: 20 }}
        >
          <Skeleton.Input active size="small" block style={{ width: `${50 + (i % 3) * 15}%` }} />
        </div>
      ))}
    </div>
  );

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

  const selectedType = selectedTypeId ? findType(typeTreeQuery.data ?? [], selectedTypeId) : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="admin_dimensions_tabs"
        tabBarExtraContent={
          <Space>
            {canManage && (
              <Button type="primary" onClick={openDimensionCreate}>
                <PlusOutlined /> 新建维度项
              </Button>
            )}
            {canManage && selectedTypeId !== null ? (
              <Space>
                <Button size="small" onClick={() => selectedType && openTypeEdit(selectedType)}>
                  编辑类型
                </Button>
                <Button
                  size="small"
                  danger
                  onClick={() => {
                    Modal.confirm({
                      title: "删除类型",
                      content: `确认删除类型 "${selectedType?.name}" 吗？该类型下不能有维度值。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: () => deleteTypeMutation.mutate(selectedType!.id),
                    });
                  }}
                >
                  删除类型
                </Button>
              </Space>
            ) : null}
          </Space>
        }
        items={[
          {
            key: "list",
            label: <span className="admin-dimensions-tab-title">维度管理</span>,
            closable: false,
            children: (
              <div className="admin_dimensions_list_pane">
        {/* ===== Body Area: Two-column layout ===== */}
        <div ref={containerRef} className="admin-dimensions-page-body">
          {/* Type sidebar (hidden on mobile) */}
          {!isMobile && (
            <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
              <AntCard
                className="admin-system-params-sider-card"
                style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
                styles={{ body: { flex: 1, overflow: "auto", padding: 0 } }}
                actions={canManage ? [
                  <Button type="text" key="add-type" onClick={() => openTypeCreate(null)} style={{ width: "100%", color: "var(--ant-color-primary)" }}>
                    <PlusOutlined /> 新建类型
                  </Button>,
                ] : undefined}
              >
                {!typeTreeQuery.isLoading && typeTreeQuery.data && typeTreeQuery.data.length > 0 && (
                  <div className="admin-system-params-sider-card-search">
                    <Input
                      className="admin-system-params-search-input"
                      placeholder="搜索类型..."
                      prefix={<SearchOutlined />}
                      value={typeSearch}
                      onChange={(e) => setTypeSearch(e.target.value)}
                      allowClear
                      size="small"
                    />
                  </div>
                )}
                {typeTreeQuery.isLoading ? (
                  skeletonMenu
                ) : typeTreeQuery.data && typeTreeQuery.data.length > 0 ? (
                  <>
                    {typeSearch && (
                      <div className="admin-system-params-search-results-count">
                        {`找到 ${filteredTreeData.length} 个类型`}
                      </div>
                    )}
                    <div className="admin-system-params-sider-menu">
                      <Tree
                        showLine
                        selectedKeys={selectedTypeId !== null ? [selectedTypeId] : []}
                        treeData={[
                          {
                            key: "all",
                            title: "全部维度",
                          } as DataNode,
                          ...convertToTypeData(filteredTreeData),
                        ]}
                        onSelect={handleTypeClick}
                        style={{ fontSize: 13 }}
                      />
                    </div>
                  </>
                ) : (
                  <div className="admin-system-params-sider-empty">
                    <Empty description="暂无类型" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  </div>
                )}
              </AntCard>
            </div>
          )}
          {!isMobile && (
            <div
              className="admin-system-params-resize-handle"
              onMouseDown={handleResizeStart}
            >
              <div className="admin-system-params-resize-handle-line" />
            </div>
          )}

          {/* Right Panel: filter + table/card view */}
          <div
            ref={pageCardRef}
            className="admin-system-params-main"
          >
            <div className="admin-filter-bar">
              <Form layout="inline">
                <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                  <Input
                    allowClear
                    placeholder="搜索维度编码/名称"
                    value={keywordInput}
                    onChange={(event) => setKeywordInput(event.target.value)}
                    onPressEnter={handleQuery}
                  />
                </Form.Item>
                <Form.Item label="状态" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                  <Select<StatusFilter>
                    value={statusFilterInput}
                    allowClear
                    placeholder="全部"
                    options={[
                      { value: "enabled", label: "已启用" },
                      { value: "disabled", label: "已禁用" },
                    ]}
                    onChange={(value) => setStatusFilterInput(value)}
                  />
                </Form.Item>
                <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                  <Button
                    htmlType="button"
                    icon={<SearchOutlined />}
                    onClick={handleQuery}
                    className="admin-search-btn" loading={listQuery.isFetching}
                  >
                    查询
                  </Button>
                </Form.Item>
                {isMobile && (
                  <Form.Item label="类型" style={{ marginBottom: 0 }}>
                    <Select
                      value={typeIdFilter}
                      allowClear
                      placeholder="全部类型"
                      style={{ width: 180 }}
                      options={flattenTypeOptions(typeTreeQuery.data ?? [])}
                      onChange={(value) => {
                        setSelectedTypeId(value ?? null);
                        setTypeIdFilter(value ?? null);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDimensions([]);
                      }}
                    />
                  </Form.Item>
                )}
              </Form>
              <div className="flex items-center">
                <Segmented
                  value={viewMode}
                  onChange={(value) => {
                    setViewModeOverride(value as "card" | "table");
                    setPagination((prev) => ({ ...prev, current: 1 }));
                    setCardViewPage(1);
                    setAllLoadedDimensions([]);
                  }}
                  options={[
                    { label: "卡片视图", value: "card" },
                    { label: "列表视图", value: "table" },
                  ]}
                />
              </div>
            </div>

            {viewMode === "table" ? (
              <div
                ref={tableScrollAnchorRef}
                className="admin-system-params-table-anchor"
                style={{ "--admin-system-params-table-body-min-height": `${tableScrollY}px` } as React.CSSProperties}
              >
                <Table<DimensionItem>
                  rowKey="id"
                  dataSource={items}
                  columns={columns}
                  // 列表始终渲染：查询进行中仅叠加 antd Table 自带居中遮罩，保留现有行，
                  // 接口返回后再更新，避免查询开始时清空表格
                  loading={listQuery.isFetching}
                  tableLayout="fixed"
                  pagination={{
                    current: pagination.current,
                    pageSize: pagination.pageSize,
                    total: Math.max(listQuery.data?.total ?? 0, 1),
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100],
                    showTotal: () => `共 ${listQuery.data?.total ?? 0} 条`,
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
              <div className="admin-system-params-card-view">
                {(listQuery.isLoading || listQuery.isFetching) && allLoadedDimensions.length === 0 ? (
                  <div className="admin-system-params-card-view-state">
                    <Spin />
                  </div>
                ) : allLoadedDimensions.length === 0 ? (
                  <div className="admin-system-params-card-view-state">
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="未找到符合筛选条件的维度项。"
                    />
                  </div>
                ) : (
                  // 查询/加载期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据
                  <Spin spinning={listQuery.isFetching}>
                    <div className="admin-system-params-card-view-content">
                      <Row gutter={[12, 12]}>
                        {allLoadedDimensions.map((item) => (
                          <Col key={item.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                            {renderDimensionCard(item)}
                          </Col>
                        ))}
                      </Row>
                      {isLoadingMore && (
                        <div style={{ textAlign: "center", padding: "20px 0" }}>
                          <Spin />
                        </div>
                      )}
                      {allLoadedDimensions.length >= (listQuery.data?.total ?? 0) && allLoadedDimensions.length > 0 && (
                        <div style={{ textAlign: "center", padding: "20px 0" }}>
                          <Typography.Text type="secondary">
                            已加载全部 {allLoadedDimensions.length} 条数据
                          </Typography.Text>
                        </div>
                      )}
                    </div>
                  </Spin>
                )}
              </div>
            )}
          </div>

          {/* Dimension value create/edit modal */}
          {canManage && (
            <Modal
              title={editingDimension === null ? "新建维度项" : `编辑维度项：${editingDimension.name}（${editingDimension.code}）`}
              open={dimensionEditorOpen}
              forceRender
              onCancel={() => {
                setDimensionEditorOpen(false);
                setEditingDimension(null);
                dimensionForm.resetFields();
              }}
              onOk={() => saveDimensionMutation.mutate()}
              okText={editingDimension === null ? "创建" : "保存"}
              cancelText="取消"
              confirmLoading={saveDimensionMutation.isPending}
              destroyOnHidden
            >
              <Form
                form={dimensionForm}
                layout="vertical"
                initialValues={{ is_enabled: true, sort_order: 0 }}
                onFinish={() => saveDimensionMutation.mutate()}
                autoComplete="off"
              >
                <Form.Item
                  label="维度类型"
                  name="type_id"
                  rules={[{ required: true, message: "请选择维度类型" }]}
                >
                  <Select
                    placeholder="请选择维度类型"
                    showSearch
                    optionFilterProp="label"
                    options={flattenTypeOptions(typeTreeQuery.data ?? [])}
                  />
                </Form.Item>

                <Form.Item
                  label="维度编码"
                  name="code"
                  rules={[
                    { required: true, message: "请输入维度编码" },
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
                    { max: 255, message: "维度名称不能超过 255 位" },
                  ]}
                >
                  <Input placeholder="例如 110千伏" />
                </Form.Item>

                <Form.Item label="父级" name="parent_id">
                  <Select
                    placeholder="留空表示顶级节点"
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    options={rawItems
                      .filter((d) => d.id !== editingDimension?.id)
                      .map((d) => ({ value: d.id, label: `${d.name}（${d.code}）` }))}
                  />
                </Form.Item>

                <Form.Item label="描述" name="description">
                  <Input.TextArea rows={3} placeholder="可选" maxLength={2000} />
                </Form.Item>

                <Form.Item label="启用状态" name="is_enabled">
                  <Select
                    options={[
                      { value: true, label: "启用" },
                      { value: false, label: "禁用" },
                    ]}
                  />
                </Form.Item>

                <Form.Item label="排序" name="sort_order">
                  <Input type="number" placeholder="0" />
                </Form.Item>
              </Form>
            </Modal>
          )}

          {/* Type management modal */}
          {canManage && (
            <Modal
              title={editingTypeId === null ? (typeParentId !== null ? "新建子类型" : "新建维度类型") : `编辑类型：${typeNameInput}`}
              open={typeEditorOpen}
              onCancel={() => setTypeEditorOpen(false)}
              onOk={() => saveTypeMutation.mutate()}
              okText={editingTypeId === null ? "创建" : "保存"}
              cancelText="取消"
              confirmLoading={saveTypeMutation.isPending}
              destroyOnHidden
            >
              <Form layout="vertical" style={{ marginTop: 16 }}>
                <Form.Item label="类型编码" required>
                  <Input
                    placeholder="如 voltage_level"
                    value={typeCodeInput}
                    onChange={(e) => setTypeCodeInput(e.target.value)}
                  />
                </Form.Item>
                <Form.Item label="类型名称" required>
                  <Input
                    placeholder="如 电压等级"
                    value={typeNameInput}
                    onChange={(e) => setTypeNameInput(e.target.value)}
                    onPressEnter={() => saveTypeMutation.mutate()}
                  />
                </Form.Item>
                <Form.Item label="父类型">
                  <Select
                    placeholder="留空表示顶级类型"
                    allowClear
                    showSearch
                    optionFilterProp="label"
                    value={typeParentId}
                    onChange={(v) => setTypeParentId(v ?? null)}
                    options={getParentOptions()}
                  />
                </Form.Item>
                <Form.Item label="排序值">
                  <Input
                    type="number"
                    placeholder="0"
                    value={typeSortInput}
                    onChange={(e) => setTypeSortInput(e.target.value)}
                  />
                </Form.Item>
              </Form>
            </Modal>
          )}
        </div>
              </div>
            ),
          },
        ]}
      />
    </div>
  );
}

function typeName(typeId: string | null, types: DimensionTypeTreeItem[] | undefined | null): string {
  if (!typeId) return "-";
  const t = findType(types, typeId);
  return t ? t.name || t.code : "-";
}

function convertToTypeData(types: DimensionTypeTreeItem[] | undefined | null): DataNode[] {
  if (!Array.isArray(types)) return [];
  return types.map((t) => ({
    key: t.id,
    title: t.name || t.code,
    children: t.children ? convertToTypeData(t.children) : [],
  }));
}

function formatDateTime(value: string): string {
  const date = new Date(value);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  const hours = String(date.getHours()).padStart(2, "0");
  const minutes = String(date.getMinutes()).padStart(2, "0");
  const seconds = String(date.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}