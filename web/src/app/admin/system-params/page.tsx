"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  Skeleton,
  Spin,
  Space,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
  type CardProps,
  type MenuProps,
  type TableColumnsType,
  type TreeProps,
} from "antd";
import { EditOutlined, MenuFoldOutlined, MenuUnfoldOutlined, MoreOutlined, PlusOutlined, SearchOutlined } from "@ant-design/icons";
import type { DataNode } from "antd/es/tree";
import type { ComponentType, RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { ParamCategoryTreeItem, SystemParamListResponse, SystemParamSummary } from "@/types/auth";

type StatusFilter = "enabled" | "disabled" | undefined;

type FormState = {
  param_key: string;
  param_name: string;
  param_value: string;
  description: string;
  category_id: number | null;
};

const EMPTY_FORM: FormState = {
  param_key: "",
  param_name: "",
  param_value: "",
  description: "",
  category_id: null,
};

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const PARAM_TABLE_MIN_SCROLL_Y = 180;
const PARAM_TABLE_VIEWPORT_GAP = 40;
const PARAM_TABLE_FALLBACK_RESERVE = 220;

function paramStatusLabel(status: SystemParamSummary["status"]): string {
  if (status === "enabled") return "启用";
  if (status === "disabled") return "禁用";
  return status || "-";
}

export default function AdminSystemParamsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [formApi] = Form.useForm<FormState>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [statusFilterInput, setStatusFilterInput] = useState<StatusFilter>(undefined);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(undefined);
  const [categoryIdFilter, setCategoryIdFilter] = useState<number | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [deletingId, setDeletingId] = useState<number | null>(null);
  const [updatingStatusId, setUpdatingStatusId] = useState<number | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(PARAM_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedParams, setAllLoadedParams] = useState<SystemParamSummary[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const paramKeyCheckTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [paramKeyValidationError, setParamKeyValidationError] = useState("");

  const canRead = hasPermission("system_param.read") || hasPermission("system_param.manage");
  const canManage = hasPermission("system_param.manage");

  // Category tree state
  const [selectedCategoryId, setSelectedCategoryId] = useState<number | null>(null);
  const [categoryEditorOpen, setCategoryEditorOpen] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [categoryNameInput, setCategoryNameInput] = useState("");
  const [categoryParentId, setCategoryParentId] = useState<number | null>(null);
  const [categoryDeleteConfirmId, setCategoryDeleteConfirmId] = useState<number | null>(null);
  const [siderCollapsed, setSiderCollapsed] = useState(false);
  const [categorySearch, setCategorySearch] = useState("");

  const categoryTreeQuery = useQuery({
    queryKey: ["/api/v1/admin/system-param-categories/tree"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/system-param-categories/tree");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as ParamCategoryTreeItem[];
    },
  });

  const convertToTreeData = (categories: ParamCategoryTreeItem[]): DataNode[] => {
    return categories.map((cat) => ({
      key: String(cat.id),
      title: cat.name,
      children: cat.children ? convertToTreeData(cat.children) : [],
    }));
  };

  const filteredTreeData = useMemo(() => {
    if (!categorySearch.trim()) return categoryTreeQuery.data ?? [];

    const searchLower = categorySearch.trim().toLowerCase();

    const filterCategories = (categories: ParamCategoryTreeItem[]): ParamCategoryTreeItem[] => {
      return categories.reduce<ParamCategoryTreeItem[]>((acc, cat) => {
        const nameMatch = cat.name.toLowerCase().includes(searchLower);
        const filteredChildren = cat.children ? filterCategories(cat.children) : [];
        if (nameMatch || filteredChildren.length > 0) {
          acc.push({
            ...cat,
            children: filteredChildren.length > 0 ? filteredChildren : cat.children,
          });
        }
        return acc;
      }, []);
    };

    return filterCategories(categoryTreeQuery.data ?? []);
  }, [categoryTreeQuery.data, categorySearch]);

  const handleCategoryClick: TreeProps["onSelect"] = (selectedKeys) => {
    if (selectedKeys.length > 0) {
      const key = selectedKeys[0] as string;
      if (key === "all") {
        setSelectedCategoryId(null);
        setCategoryIdFilter(null);
      } else {
        const catId = Number(key);
        setSelectedCategoryId(catId);
        setCategoryIdFilter(catId);
      }
      setPagination((prev) => ({ ...prev, current: 1 }));
    } else {
      setSelectedCategoryId(null);
      setCategoryIdFilter(null);
    }
  };

  const openCategoryCreate = (parentId: number | null = null) => {
    setEditingCategoryId(null);
    setCategoryNameInput("");
    setCategoryParentId(parentId);
    setCategoryDeleteConfirmId(null);
    setCategoryEditorOpen(true);
  };

  const openCategoryEdit = (cat: ParamCategoryTreeItem) => {
    setEditingCategoryId(cat.id);
    setCategoryNameInput(cat.name);
    setCategoryParentId(cat.parent_id);
    setCategoryDeleteConfirmId(null);
    setCategoryEditorOpen(true);
  };

  const saveCategoryMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) throw new Error("缺少权限");
      const name = categoryNameInput.trim();
      if (!name) throw new Error("分类名称不能为空");

      if (editingCategoryId === null) {
        const response = await fetchWithAuth("/api/v1/admin/system-param-categories", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, parent_id: categoryParentId, sort_order: 0 }),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return "created";
      }

      const response = await fetchWithAuth(`/api/v1/admin/system-param-categories/${editingCategoryId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return "updated";
    },
    onSuccess: async () => {
      setSuccess(editingCategoryId === null ? "分类已创建" : "分类已更新");
      setCategoryEditorOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/admin/system-param-categories/tree"] });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存分类失败");
    },
  });

  const deleteCategoryMutation = useMutation({
    mutationFn: async (categoryId: number) => {
      const response = await fetchWithAuth(`/api/v1/admin/system-param-categories/${categoryId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return categoryId;
    },
    onSuccess: async (categoryId) => {
      setSuccess("分类已删除");
      setCategoryDeleteConfirmId(null);
      if (selectedCategoryId === categoryId) {
        setSelectedCategoryId(null);
        setCategoryIdFilter(null);
      }
      await queryClient.invalidateQueries({ queryKey: ["/api/v1/admin/system-param-categories/tree"] });
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除分类失败");
    },
  });

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
      params.set("status", statusFilter);
    }
    if (categoryIdFilter !== null) {
      params.set("category_id", String(categoryIdFilter));
    }
    const qs = params.toString();
    return `/api/v1/admin/system-params${qs ? `?${qs}` : ""}`;
  }, [paginationCurrent, paginationPageSize, statusFilter, trimmedKeyword, categoryIdFilter]);

  const listQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as SystemParamListResponse;
    },
  });

  const refreshList = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/admin/system-params"),
    });
  }, [queryClient]);

  useTopicSubscription(
    "admin.system-params",
    useCallback(() => {
      if (!user || !canRead) return;
      void refreshList();
    }, [canRead, refreshList, user]),
  );

  const resetForm = useCallback(() => {
    setEditingId(null);
    setParamKeyValidationError("");
    formApi.setFieldsValue(EMPTY_FORM);
  }, [formApi]);

  const startCreate = useCallback(() => {
    setError("");
    setSuccess("");
    setParamKeyValidationError("");
    resetForm();
    setEditorOpen(true);
  }, [resetForm]);

  const startEdit = useCallback((item: SystemParamSummary) => {
    setError("");
    setSuccess("");
    setParamKeyValidationError("");
    setEditingId(item.id);
    formApi.setFieldsValue({
      param_key: item.param_key,
      param_name: item.param_name,
      param_value: item.param_value,
      description: item.description ?? "",
      category_id: item.category_id ?? null,
    });
    setEditorOpen(true);
  }, [formApi]);

  const validateParamKeyFormat = (paramKey: string): string | null => {
    const trimmedKey = paramKey.trim();
    if (!trimmedKey) return null;
    if (trimmedKey.length < 2) return "参数键至少 2 位";
    if (trimmedKey.length > 128) return "参数键不能超过 128 位";
    return null;
  };

  const checkParamKeyAvailability = async (paramKey: string) => {
    try {
      const params = new URLSearchParams({
        keyword: paramKey,
        limit: "200",
        offset: "0",
      });
      const response = await fetchWithAuth(`/api/v1/admin/system-params?${params.toString()}`);
      if (!response.ok) {
        return { available: false, message: "检查失败" };
      }
      const payload = (await response.json()) as SystemParamListResponse;
      const normalizedKey = paramKey.trim().toLowerCase();
      const exists = payload.items.some((item) => item.param_key.trim().toLowerCase() === normalizedKey);
      return {
        available: !exists,
        message: exists ? "参数键已存在，请更换后重试" : "参数键可用",
      };
    } catch {
      return { available: false, message: "检查失败" };
    }
  };

  const handleParamKeyChange = (value: string) => {
    if (paramKeyCheckTimeoutRef.current) {
      clearTimeout(paramKeyCheckTimeoutRef.current);
    }

    const formatError = validateParamKeyFormat(value);
    if (formatError) {
      setParamKeyValidationError(formatError);
      return;
    }

    const trimmedValue = value.trim();
    if (!trimmedValue || editingId !== null) {
      setParamKeyValidationError("");
      return;
    }

    paramKeyCheckTimeoutRef.current = setTimeout(async () => {
      const result = await checkParamKeyAvailability(trimmedValue);
      setParamKeyValidationError(result.available ? "" : result.message);
    }, 500);
  };

  const closeEditor = useCallback(() => {
    setEditorOpen(false);
    resetForm();
  }, [resetForm]);

  const saveMutation = useMutation({
    mutationFn: async () => {
      if (!canManage) {
        throw new Error("缺少 system_param.manage 权限");
      }

      const values = await formApi.validateFields();
      if (!values.param_name.trim() || !values.param_key.trim()) {
        throw new Error("参数键和参数名称不能为空");
      }

      const paramKey = values.param_key.trim();
      const paramKeyFormatError = validateParamKeyFormat(paramKey);
      if (paramKeyFormatError) {
        setParamKeyValidationError(paramKeyFormatError);
        throw new Error(paramKeyFormatError);
      }

      if (editingId === null) {
        const availabilityCheck = await checkParamKeyAvailability(paramKey);
        if (!availabilityCheck.available) {
          setParamKeyValidationError(availabilityCheck.message);
          throw new Error(availabilityCheck.message);
        }

        const response = await fetchWithAuth("/api/v1/admin/system-params", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            param_key: paramKey,
            param_name: values.param_name.trim(),
            param_value: values.param_value,
            description: values.description,
            status: "enabled",
            category_id: values.category_id ?? null,
          }),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        return "created" as const;
      }

      const response = await fetchWithAuth(`/api/v1/admin/system-params/${editingId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          param_name: values.param_name.trim(),
          param_value: values.param_value,
          description: values.description,
          category_id: values.category_id ?? null,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "updated" as const;
    },
    onMutate: () => {
      setError("");
      setSuccess("");
    },
    onSuccess: async (mode) => {
      setError("");
      setSuccess(mode === "created" ? "系统参数已创建" : "系统参数已更新");
      setEditorOpen(false);
      resetForm();
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "保存失败");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (item: SystemParamSummary) => {
      const response = await fetchWithAuth(`/api/v1/admin/system-params/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return item.id;
    },
    onSuccess: async (deletedId) => {
      if (editingId === deletedId) {
        setEditorOpen(false);
        resetForm();
      }
      setError("");
      setSuccess("系统参数已删除");
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const removeParam = useCallback(async (item: SystemParamSummary) => {
    setDeletingId(item.id);
    try {
      await deleteMutation.mutateAsync(item);
    } finally {
      setDeletingId(null);
    }
  }, [deleteMutation]);

  const updateStatusMutation = useMutation({
    mutationFn: async ({ item, status }: { item: SystemParamSummary; status: SystemParamSummary["status"] }) => {
      const response = await fetchWithAuth(`/api/v1/admin/system-params/${item.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return status;
    },
    onMutate: ({ item }) => {
      setUpdatingStatusId(item.id);
      setError("");
      setSuccess("");
    },
    onSuccess: async (status) => {
      setSuccess(status === "enabled" ? "系统参数已启用" : "系统参数已禁用");
      await refreshList();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "更新系统参数状态失败");
    },
    onSettled: () => setUpdatingStatusId(null),
  });

  const toggleParamStatus = useCallback((item: SystemParamSummary) => {
    const nextStatus: SystemParamSummary["status"] = item.status === "enabled" ? "disabled" : "enabled";
    updateStatusMutation.mutate({ item, status: nextStatus });
  }, [updateStatusMutation]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleQuery = () => {
    setSearchKeyword(keywordInput);
    setStatusFilter(statusFilterInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(() => 1);
    setAllLoadedParams(() => []);
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

  useEffect(() => {
    if (viewMode !== "card" || listQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedParams(() => items);
      } else {
        setAllLoadedParams((prev) => {
          if (items.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map((p) => p.id));
          const newParams = items.filter((p) => !existingIds.has(p.id));
          return [...prev, ...newParams];
        });
      }
      setIsLoadingMore(() => false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [items, listQuery.isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || listQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = listQuery.data?.total ?? 0;
        const loadedCount = allLoadedParams.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, listQuery.isLoading, listQuery.data?.total, allLoadedParams.length]);

  useEffect(() => {
    return () => {
      if (paramKeyCheckTimeoutRef.current) {
        clearTimeout(paramKeyCheckTimeoutRef.current);
      }
    };
  }, []);

  const renderParamCard = (param: SystemParamSummary) => {
    const deleteLoading = deletingId === param.id;
    const statusLoading = updatingStatusId === param.id;
    const rowBusy = deleteLoading || statusLoading;

    const moreMenuItems: MenuProps["items"] = [
      {
        key: "copy-key",
        label: "复制参数键",
        disabled: rowBusy,
        onClick: () => {
          void navigator.clipboard.writeText(param.param_key);
          setSuccess(`已复制参数键: ${param.param_key}`);
        },
      },
      {
        key: "toggle-status",
        label: param.status === "enabled" ? "禁用" : "启用",
        disabled: rowBusy || !canManage,
        onClick: () => toggleParamStatus(param),
      },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: rowBusy || !canManage,
        onClick: () => {
          Modal.confirm({
            title: `确认删除系统参数 ${param.param_key}？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: () => void removeParam(param),
          });
        },
      },
    ];

    return (
      <AntCard
        key={param.id}
        className="admin-system-params-param-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong>{param.param_name}</Typography.Text>
            <Tag color={param.status === "enabled" ? "green" : "default"}>
              {paramStatusLabel(param.status)}
            </Tag>
          </Space>
        }
        extra={
          canManage ? (
            <Space size={4}>
              <Button
                type="text"
                size="small"
                disabled={rowBusy}
                icon={<EditOutlined />}
                onClick={() => startEdit(param)}
              />
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button type="text" size="small" disabled={rowBusy} icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          ) : null
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">ID</Typography.Text>
            <Typography.Text>{param.id}</Typography.Text>
          </div>
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">参数键</Typography.Text>
            <Typography.Text className="font-mono text-xs">{param.param_key}</Typography.Text>
          </div>
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">参数值</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: param.param_value || "-" }}>
              {param.param_value || "-"}
            </Typography.Text>
          </div>
          {param.description && (
            <div className="admin-system-params-param-card-field">
              <Typography.Text type="secondary">说明</Typography.Text>
              <Typography.Text ellipsis={{ tooltip: param.description }}>
                {param.description}
              </Typography.Text>
            </div>
          )}
          <div className="admin-system-params-param-card-field">
            <Typography.Text type="secondary">更新时间</Typography.Text>
            <Typography.Text>{new Date(param.updated_at).toLocaleString()}</Typography.Text>
          </div>
        </Space>
      </AntCard>
    );
  };

  const columns = useMemo<TableColumnsType<SystemParamSummary>>(() => {
    const baseColumns: TableColumnsType<SystemParamSummary> = [
      {
        title: "ID",
        dataIndex: "id",
        key: "id",
        width: 80,
      },
      {
        title: "参数名",
        dataIndex: "param_key",
        key: "param_key",
        width: 180,
        render: (value: string) => <span className="font-mono text-xs">{value}</span>,
      },
      {
        title: "参数描述",
        dataIndex: "param_name",
        key: "param_name",
        width: 160,
        ellipsis: { showTitle: true },
      },
      {
        title: "参数值",
        dataIndex: "param_value",
        key: "param_value",
        ellipsis: true,
        width: 240,
        render: (value: string) => value || "-",
      },
      {
        title: "状态",
        dataIndex: "status",
        key: "status",
        width: 120,
        render: (value: SystemParamSummary["status"]) => (
          <Tag color={value === "enabled" ? "green" : "default"}>
            {paramStatusLabel(value)}
          </Tag>
        ),
      },
      {
        title: "更新时间",
        dataIndex: "updated_at",
        key: "updated_at",
        width: 180,
        render: (value: string) => {
          const date = new Date(value);
          const year = date.getFullYear();
          const month = String(date.getMonth() + 1).padStart(2, '0');
          const day = String(date.getDate()).padStart(2, '0');
          const hours = String(date.getHours()).padStart(2, '0');
          const minutes = String(date.getMinutes()).padStart(2, '0');
          const seconds = String(date.getSeconds()).padStart(2, '0');
          return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
        },
      },
    ];

    if (canManage) {
      baseColumns.push({
        title: "操作",
        key: "actions",
        width: 220,
        fixed: "right",
        render: (_, record) => {
          const deleteLoading = deletingId === record.id;
          const statusLoading = updatingStatusId === record.id;
          const rowBusy = deleteLoading || statusLoading;

          const moreMenuItems: MenuProps["items"] = [
            {
              key: "copy-key",
              label: "复制参数键",
              disabled: rowBusy,
              onClick: () => {
                void navigator.clipboard.writeText(record.param_key);
                setSuccess(`已复制参数键: ${record.param_key}`);
              },
            },
            {
              key: "toggle-status",
              label: record.status === "enabled" ? "禁用" : "启用",
              disabled: rowBusy,
              onClick: () => toggleParamStatus(record),
            },
          ];

          return (
            <Space wrap>
              <Button size="small" disabled={rowBusy} onClick={() => startEdit(record)}>
                编辑
              </Button>
              <Popconfirm
                title="删除系统参数"
                description={`确认删除系统参数 ${record.param_key} 吗？`}
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true, loading: deleteLoading }}
                onConfirm={() => void removeParam(record)}
                disabled={rowBusy}
              >
                <Button size="small" danger loading={deleteLoading} disabled={rowBusy}>
                  删除
                </Button>
              </Popconfirm>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" disabled={rowBusy} icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      });
    }

    return baseColumns;
  }, [canManage, deletingId, removeParam, startEdit, toggleParamStatus, updatingStatusId]);

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - PARAM_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? PARAM_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - PARAM_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(PARAM_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    updateTableScrollY();
  }, [items.length, listQuery.isFetching, listError, error, success, updateTableScrollY]);

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
        <Spin tip="初始化中..." />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问参数管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `system_param.read`）。</p>
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
      <Row gutter={16} style={{ flex: 1, minHeight: 0 }}>
      {/* Category Sidebar */}
      {!isMobile && (
        <Col span={siderCollapsed ? 2 : 6}>
          <AntCard
            className="admin-system-params-sider-card"
            title={siderCollapsed ? null : "参数分类"}
            extra={
              <Space size={0}>
                {!siderCollapsed && canManage && (
                  <Button type="primary" size="small" icon={<PlusOutlined />} onClick={() => openCategoryCreate(null)} />
                )}
                <Tooltip title={siderCollapsed ? "展开侧栏" : "收起侧栏"}>
                  <Button
                    aria-label={siderCollapsed ? "展开侧栏" : "收起侧栏"}
                    icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                    type="text"
                    onClick={() => setSiderCollapsed((prev) => !prev)}
                  />
                </Tooltip>
              </Space>
            }
            style={{ height: "100%", display: "flex", flexDirection: "column" }}
            bodyStyle={siderCollapsed ? { display: "none" } : { flex: 1, overflow: "auto" }}
          >
            {!siderCollapsed && (
              <>
                {!categoryTreeQuery.isLoading && categoryTreeQuery.data && categoryTreeQuery.data.length > 0 && (
                  <div style={{ padding: "8px 12px" }}>
                    <Input
                      className="admin-system-params-search-input"
                      placeholder="搜索分类..."
                      prefix={<SearchOutlined />}
                      value={categorySearch}
                      onChange={(e) => setCategorySearch(e.target.value)}
                      allowClear
                      size="small"
                    />
                  </div>
                )}
                {categoryTreeQuery.isLoading ? (
                  skeletonMenu
                ) : categoryTreeQuery.data && categoryTreeQuery.data.length > 0 ? (
                  <>
                    {categorySearch && (
                      <div className="admin-system-params-search-results-count">
                        {`找到 ${filteredTreeData.length} 个分类`}
                      </div>
                    )}
                    <div className="admin-system-params-sider-menu">
                      <Tree
                        showLine
                        selectedKeys={selectedCategoryId !== null ? [String(selectedCategoryId)] : []}
                        treeData={[
                          {
                            key: "all",
                            title: "全部参数",
                          } as DataNode,
                          ...convertToTreeData(filteredTreeData),
                        ]}
                        onSelect={handleCategoryClick}
                        style={{ fontSize: 13 }}
                      />
                    </div>
                  </>
                ) : (
                  <div className="admin-system-params-sider-empty">
                    <Empty description="暂无分类" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                  </div>
                )}
              </>
            )}
          </AntCard>
        </Col>
      )}
      <Col span={siderCollapsed ? 22 : 18}>
        <AntCard
          ref={pageCardRef}
          className="admin-system-params-page-card"
          title={isMobile ? "系统参数管理" : (() => {
            const selLabel = selectedCategoryId !== null ? ` - ${(() => {
              const findName = (items: ParamCategoryTreeItem[], id: number): string => {
                for (const item of items) {
                  if (item.id === id) return item.name;
                  if (item.children) {
                    const found = findName(item.children, id);
                    if (found) return found;
                  }
                }
                return "";
              };
              return findName(categoryTreeQuery.data ?? [], selectedCategoryId!) || "已选分类";
            })()}` : "";
            return `系统参数管理${selLabel}`;
          })()}
          extra={canManage ? (
            <Space>
              {selectedCategoryId !== null && (
                <>
                  {(() => {
                    const findCat = (items: ParamCategoryTreeItem[], id: number): ParamCategoryTreeItem | null => {
                      for (const item of items) {
                        if (item.id === id) return item;
                        if (item.children) {
                          const found = findCat(item.children, id);
                          if (found) return found;
                        }
                      }
                      return null;
                    };
                    const currentCat = findCat(categoryTreeQuery.data ?? [], selectedCategoryId);
                    return currentCat ? (
                      <>
                        <Button size="small" onClick={() => openCategoryEdit(currentCat)}>
                          编辑分类
                        </Button>
                        <Popconfirm
                          title="删除分类"
                          description={`确认删除分类 "${currentCat.name}" 吗？该分类下不能有子分类和参数。`}
                          okText="删除"
                          cancelText="取消"
                          okButtonProps={{ danger: true }}
                          onConfirm={() => deleteCategoryMutation.mutate(currentCat.id)}
                        >
                          <Button size="small" danger>
                            删除分类
                          </Button>
                        </Popconfirm>
                      </>
                    ) : null;
                  })()}
                </>
              )}
              <Button type="primary" onClick={startCreate}>
                新建参数
              </Button>
            </Space>
          ) : null}
        >
        <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  placeholder="搜索参数名"
                  value={keywordInput}
                  onChange={(event) => handleKeywordChange(event.target.value)}
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
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={handleQuery}
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
            className="admin-system-params-table-anchor"
            style={{ "--admin-system-params-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<SystemParamSummary>
              rowKey="id"
              dataSource={items}
              columns={columns}
              loading={listQuery.isLoading}
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
              scroll={{ x: 1200, y: tableScrollY }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="未找到符合筛选条件的系统参数。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-system-params-card-view">
            {listQuery.isLoading && allLoadedParams.length === 0 ? (
              <div className="admin-system-params-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedParams.length === 0 ? (
              <div className="admin-system-params-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的系统参数。"
                />
              </div>
            ) : (
              <div className="admin-system-params-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedParams.map((param) => (
                    <Col key={param.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderParamCard(param)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedParams.length >= (listQuery.data?.total ?? 0) && allLoadedParams.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedParams.length} 条数据
                    </Typography.Text>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </AntCard>

      {canManage && (
        <Modal
          title={editingId === null ? "新建系统参数" : `编辑系统参数：${formApi.getFieldValue("param_name")}（ID: ${editingId}）`}
          open={editorOpen}
          onCancel={closeEditor}
          onOk={() => formApi.submit()}
          okText={editingId === null ? "创建" : "保存"}
          cancelText="取消"
          confirmLoading={saveMutation.isPending}
          destroyOnClose
        >
          <Form<FormState>
            form={formApi}
            layout="vertical"
            initialValues={EMPTY_FORM}
            onFinish={() => saveMutation.mutate()}
            autoComplete="off"
          >
            <div className="grid gap-4 md:grid-cols-2">
              <Form.Item<FormState>
                label="参数键"
                name="param_key"
                validateStatus={paramKeyValidationError ? "error" : ""}
                help={paramKeyValidationError}
                rules={[
                  { required: true, message: "请输入参数键" },
                  { min: 2, message: "参数键至少 2 位" },
                  { max: 128, message: "参数键不能超过 128 位" },
                ]}
              >
                <Input
                  disabled={editingId !== null}
                  placeholder="请输入参数键"
                  onChange={(event) => handleParamKeyChange(event.target.value)}
                />
              </Form.Item>

              <Form.Item<FormState>
                label="参数名称"
                name="param_name"
                rules={[
                  { required: true, message: "请输入参数名称" },
                  { min: 2, message: "参数名称至少 2 位" },
                  { max: 128, message: "参数名称不能超过 128 位" },
                ]}
              >
                <Input placeholder="请输入参数名称" />
              </Form.Item>

              <Form.Item<FormState>
                label="参数分类"
                name="category_id"
              >
                <Select
                  allowClear
                  placeholder="请选择分类"
                  style={{ width: "100%" }}
                  options={(() => {
                    const flattenCategories = (cats: ParamCategoryTreeItem[], level: number = 0): { value: number; label: string }[] => {
                      return cats.flatMap((cat) => [
                        { value: cat.id, label: "　".repeat(level) + cat.name },
                        ...flattenCategories(cat.children, level + 1),
                      ]);
                    };
                    return flattenCategories(categoryTreeQuery.data ?? []);
                  })()}
                />
              </Form.Item>

              <Form.Item<FormState>
                className="md:col-span-2"
                label="参数值"
                name="param_value"
                rules={[{ max: 20000, message: "参数值不能超过 20000 位" }]}
              >
                <Input.TextArea rows={4} />
              </Form.Item>

              <Form.Item<FormState>
                className="md:col-span-2"
                label="说明"
                name="description"
                rules={[{ max: 20000, message: "说明不能超过 20000 位" }]}
              >
                <Input.TextArea rows={3} />
              </Form.Item>
            </div>
          </Form>
        </Modal>
      )}

      {/* Category management modal */}
      {canManage && (
        <Modal
          title={editingCategoryId === null ? (categoryParentId !== null ? "新建子分类" : "新建参数分类") : `编辑分类：${categoryNameInput}`}
          open={categoryEditorOpen}
          onCancel={() => setCategoryEditorOpen(false)}
          onOk={() => saveCategoryMutation.mutate()}
          okText={editingCategoryId === null ? "创建" : "保存"}
          cancelText="取消"
          confirmLoading={saveCategoryMutation.isPending}
          destroyOnClose
        >
          <Form layout="vertical" style={{ marginTop: 16 }}>
            <Form.Item label="分类名称" required>
              <Input
                placeholder="请输入分类名称"
                value={categoryNameInput}
                onChange={(e) => setCategoryNameInput(e.target.value)}
                onPressEnter={() => saveCategoryMutation.mutate()}
              />
            </Form.Item>
          </Form>
        </Modal>
      )}
      </Col>
    </Row>
    </div>
  );
}
