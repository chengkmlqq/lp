"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Badge,
  Button,
  Card,
  Checkbox,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Tree,
  Typography,
  type CardProps,
  type MenuProps,
} from "antd";
import { FolderOutlined, MoreOutlined, EditOutlined, SearchOutlined, PoweroffOutlined, CheckOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { DataNode } from "antd/es/tree";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { IconPicker } from "@/components/icon-picker";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { ApiError, readApiError } from "@/lib/api";
import { normalizeAppRoutePath } from "@/lib/app-route-path";
import type { MenuItem, MenuListResponse, MenuTreeItem } from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type MenuFormValues = {
  code: string;
  name: string;
  path?: string;
  icon?: string;
  parent_id?: string;
  type: "directory" | "menu" | "button";
  sort_order: number;
  status: "enabled" | "disabled";
  visible: boolean;
  cacheable: boolean;
  component?: string;
};

type MenuMutationPayload = {
  code: string;
  name: string;
  path: string | null;
  icon: string | null;
  parent_id: string | null;
  type: MenuFormValues["type"];
  sort_order: number;
  status: MenuFormValues["status"];
  visible: boolean;
  cacheable: boolean;
  component: string | null;
};

const DEFAULT_FORM_VALUES: MenuFormValues = {
  code: "",
  name: "",
  path: "",
  icon: "",
  parent_id: undefined,
  type: "menu",
  sort_order: 0,
  status: "enabled",
  visible: true,
  cacheable: false,
  component: "",
};

function menuToFormValues(menu: MenuItem): MenuFormValues {
  return {
    code: menu.code,
    name: menu.name,
    path: menu.path ?? "",
    icon: menu.icon ?? "",
    parent_id: menu.parent_id ?? undefined,
    type: menu.type as MenuFormValues["type"],
    sort_order: menu.sort_order,
    status: menu.status as MenuFormValues["status"],
    visible: menu.visible,
    cacheable: menu.cacheable,
    component: menu.component ?? "",
  };
}

const ADMIN_ME_MENUS_QUERY_KEY = ["/api/v1/admin/me/menus"] as const;
const MENU_TABLE_MIN_SCROLL_Y = 180;
const MENU_TABLE_VIEWPORT_GAP = 40;
const MENU_TABLE_FALLBACK_RESERVE = 220;

function compareMenuIds(a: string, b: string): number {
  const aNum = Number(a);
  const bNum = Number(b);
  if (!Number.isNaN(aNum) && !Number.isNaN(bNum)) {
    return aNum - bNum;
  }
  return a.localeCompare(b, "zh-CN");
}

function normalizeMenuItemPath(menu: MenuItem): MenuItem {
  return {
    ...menu,
    path: normalizeAppRoutePath(menu.path),
  };
}

function buildMenuTreeData(menus: MenuItem[]): DataNode[] {
  const menuMap = new Map<string, MenuTreeItem>();
  const roots: MenuTreeItem[] = [];

  menus.forEach((menu) => {
    menuMap.set(menu.id, { ...menu, children: [] });
  });

  menus.forEach((menu) => {
    const node = menuMap.get(menu.id)!;
    if (menu.parent_id && menuMap.has(menu.parent_id)) {
      menuMap.get(menu.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  });

  const toDataNode = (item: MenuTreeItem): DataNode => {
    const isDirectory = item.type === "directory";
    return {
      key: `menu-${item.id}`,
      title: (
        <Space>
          {isDirectory ? <FolderOutlined style={{ color: "#faad14" }} /> : null}
          <span>{item.name}</span>
        </Space>
      ),
      children: item.children.length > 0 ? item.children.map(toDataNode) : undefined,
    };
  };

  return roots.map(toDataNode);
}

export default function AdminMenusPage() {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [deletingMenuId, setDeletingMenuId] = useState<string | null>(null);
  const [updatingStatusMenuId, setUpdatingStatusMenuId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingMenuId, setEditingMenuId] = useState<string | null>(null);
  const [keywordInput, setKeywordInput] = useState("");
  const [statusFilter, setStatusFilter] = useState<"enabled" | "disabled" | undefined>(undefined);
  const [searchKeyword, setSearchKeyword] = useState("");
  // 手动刷新计数：每次点击「查询」都自增并作为查询 key 的一部分，强制走一次接口，
  // 即使关键词/分页均未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [selectedTreeKey, setSelectedTreeKey] = useState<string | null>(null);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(MENU_TABLE_MIN_SCROLL_Y);
  const [viewModeOverride, setViewModeOverride] = useState<"card" | "table" | null>(null);
  const viewMode: "table" | "card" = viewModeOverride ?? (isMobile ? "card" : "table");
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedMenus, setAllLoadedMenus] = useState<MenuItem[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [treeFilterKeyword, setTreeFilterKeyword] = useState("");
  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const containerRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);
  const [form] = Form.useForm<MenuFormValues>();
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const paginationCurrent = pagination.current;
  const paginationPageSize = pagination.pageSize;

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

  const canManage = hasPermission("menu.manage");
  const canRead = hasPermission("menu.read") || hasPermission("menu.manage");

  const trimmedKeyword = searchKeyword.trim();
  const menusQueryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    if (statusFilter) {
      params.set("status", statusFilter);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, statusFilter, trimmedKeyword]);
  const menusPath = `/api/v1/admin/menus?${menusQueryParams}`;

  const loadMenus = useCallback(async () => {
    const response = await fetchWithAuth(menusPath);
    if (!response.ok) throw new Error(await readApiError(response));
    const payload = (await response.json()) as MenuListResponse;
    return {
      ...payload,
      items: payload.items.map(normalizeMenuItemPath),
    } satisfies MenuListResponse;
  }, [fetchWithAuth, menusPath]);

  const menusQuery = useQuery({
    // searchNonce 作为 queryKey 的一部分：每次点击「查询」自增，即使关键词/分页均未变化
    // 也会产生新 key 强制重新拉取；首个元素仍是 "admin.menus"，不影响失效/刷新逻辑
    queryKey: ["admin.menus", menusQueryParams, searchNonce],
    queryFn: loadMenus,
    enabled: !!user && canRead,
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询时列表闪空
    placeholderData: (previousData) => previousData,
  });

  const menus = useMemo(() => menusQuery.data?.items ?? [], [menusQuery.data?.items]);
  const menuTotal = menusQuery.data?.total ?? 0;
  const queryError = useMemo<ApiError | null>(() => menusQuery.error instanceof Error ? new ApiError(menusQuery.error.message) : null, [menusQuery.error]);
  const apiError = error || queryError;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

  const parentOptions = useMemo(
    () =>
      menus.map((menu) => ({
        value: menu.id,
        label: menu.name,
      })),
    [menus],
  );

  const menuNameById = useMemo(() => {
    const map = new Map<string, string>();
    menus.forEach((menu) => {
      map.set(menu.id, menu.name);
    });
    return map;
  }, [menus]);

  const treeMenus = useMemo(() => {
    const keyword = treeFilterKeyword.trim().toLowerCase();
    if (!keyword) return menus;

    // Find menus matching the keyword by name or code
    const matchedIds = new Set<string>();
    menus.forEach((m) => {
      if (m.name.toLowerCase().includes(keyword) || m.code.toLowerCase().includes(keyword)) {
        matchedIds.add(m.id);
      }
    });

    if (matchedIds.size === 0) return [];

    // Include ancestors so the tree structure is preserved
    let added = true;
    while (added) {
      added = false;
      menus.forEach((m) => {
        if (matchedIds.has(m.id) && m.parent_id && !matchedIds.has(m.parent_id)) {
          matchedIds.add(m.parent_id);
          added = true;
        }
      });
    }

    // Include descendants
    added = true;
    while (added) {
      added = false;
      menus.forEach((m) => {
        if (m.parent_id && matchedIds.has(m.parent_id) && !matchedIds.has(m.id)) {
          matchedIds.add(m.id);
          added = true;
        }
      });
    }

    return menus.filter((m) => matchedIds.has(m.id));
  }, [menus, treeFilterKeyword]);

  const treeData = useMemo(() => buildMenuTreeData(treeMenus), [treeMenus]);

  const filteredMenus = useMemo(() => {
    let result = menus;
    if (selectedTreeKey) {
      const childrenIds = new Set<string>();
      const collectChildren = (parentId: string) => {
        menus.forEach((menu) => {
          if (menu.parent_id === parentId && !childrenIds.has(menu.id)) {
            childrenIds.add(menu.id);
            collectChildren(menu.id);
          }
        });
      };
      collectChildren(selectedTreeKey);
      result = menus.filter((menu) => menu.parent_id === selectedTreeKey || childrenIds.has(menu.id));
    }
    return [...result].sort((a, b) => {
      if (a.sort_order !== b.sort_order) {
        return a.sort_order - b.sort_order;
      }
      return compareMenuIds(a.id, b.id);
    });
  }, [menus, selectedTreeKey]);

  const filteredTotal = useMemo(
    () => (selectedTreeKey ? filteredMenus.length : menuTotal),
    [filteredMenus.length, menuTotal, selectedTreeKey],
  );
  const editingMenu = useMemo(
    () => menus.find((menu) => menu.id === editingMenuId) ?? null,
    [editingMenuId, menus],
  );

  useTopicSubscription(
    "admin.menus",
    useCallback(() => {
      if (user && canRead) {
        void queryClient.invalidateQueries({ queryKey: ["admin.menus"] });
      }
    }, [canRead, queryClient, user]),
  );

  const refreshData = async () => {
    await queryClient.refetchQueries({ queryKey: ["admin.menus"] });
    await queryClient.invalidateQueries({ queryKey: ADMIN_ME_MENUS_QUERY_KEY });
  };

  // Update allLoadedMenus when menus data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || menusQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedMenus(() => menus);
      } else {
        setAllLoadedMenus((prev) => {
          if (menus.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(m => m.id));
          const newMenus = menus.filter(m => !existingIds.has(m.id));
          return [...prev, ...newMenus];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [menus, menusQuery.isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    // LP-255: 外层 Card 已移除，滚动容器为 .admin-menus-main（overflow-y: auto）本身；
    // 不再通过 .ant-card-body 选择器定位（该选择器会误匹配到菜单卡片 body）
    const cardBody = pageCard;

    const handleScroll = () => {
      if (isLoadingMore || menusQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const loadedCount = allLoadedMenus.length;

        if (loadedCount < filteredTotal) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [allLoadedMenus.length, menusQuery.isLoading, isLoadingMore, filteredTotal, viewMode]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    // 每次点击「查询」都强制触发一次接口请求：
    // searchNonce 作为 queryKey 的一部分自增，保证即便关键词/分页均未变化（旧实现只对
    // 这种情况 refetchQueries，且目标 key 若已被 react-query 缓存会短路不发请求）也会
    // 产生新 key 重新拉取；关键词/分页照常提交并回到第 1 页。卡片视图不清空已加载列表，
    // 由下方 Spin 遮罩保留现有卡片，接口返回后再更新，避免查询开始时闪空。
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setSearchNonce((n) => n + 1);
  };

  const handleStatusFilterChange = (value?: "enabled" | "disabled") => {
    setStatusFilter(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setAllLoadedMenus([]);
  };

  const closeDialog = useCallback(() => {
    setDialogOpen(false);
    setEditingMenuId(null);
    form.resetFields();
  }, [form]);

  const startCreate = useCallback(() => {
    setEditingMenuId(null);
    setDialogOpen(true);
  }, []);

  const startEdit = useCallback((menu: MenuItem) => {
    setEditingMenuId(menu.id);
    setDialogOpen(true);
  }, []);

  const createMenuMutation = useMutation({
    mutationFn: async (payload: MenuMutationPayload) => {
      const response = await fetchWithAuth("/api/v1/admin/menus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<MenuItem>;
    },
    onMutate: () => {
      setError(null);
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("菜单已创建");
      closeDialog();
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "创建菜单失败"));
    },
  });

  const updateMenuMutation = useMutation({
    mutationFn: async ({ menuId, payload }: { menuId: string; payload: Partial<MenuMutationPayload> }) => {
      const response = await fetchWithAuth(`/api/v1/admin/menus/${menuId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<MenuItem>;
    },
    onMutate: ({ menuId, payload }) => {
      if (payload.status && Object.keys(payload).length === 1) {
        setUpdatingStatusMenuId(menuId);
      }
      setError(null);
      setSuccess("");
    },
    onSuccess: async (_, variables) => {
      if (variables.payload.status && Object.keys(variables.payload).length === 1) {
        setSuccess(variables.payload.status === "enabled" ? "菜单已启用" : "菜单已禁用");
      } else {
        setSuccess("菜单已更新");
        closeDialog();
      }
      await refreshData();
    },
    onError: (candidate, variables) => {
      setSuccess("");
      const fallbackMessage = variables.payload.status && Object.keys(variables.payload).length === 1
        ? "菜单状态更新失败"
        : "更新菜单失败";
      setError(new ApiError(candidate instanceof Error ? candidate.message : fallbackMessage));
    },
    onSettled: (_data, _error, variables) => {
      if (variables?.payload.status && Object.keys(variables.payload).length === 1) {
        setUpdatingStatusMenuId(null);
      }
    },
  });

  const deleteMenuMutation = useMutation({
    mutationFn: async (menuId: string) => {
      const response = await fetchWithAuth(`/api/v1/admin/menus/${menuId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<{ message: string }>;
    },
    onMutate: (menuId) => {
      setDeletingMenuId(menuId);
      setError(null);
      setSuccess("");
    },
    onSuccess: async (_, menuId) => {
      setSuccess("菜单已删除");
      if (editingMenuId === menuId) {
        closeDialog();
      }
      setAllLoadedMenus((previous) => previous.filter((item) => item.id !== menuId));
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "菜单删除失败"));
    },
    onSettled: () => setDeletingMenuId(null),
  });

  const submit = useCallback(async () => {
    try {
      const values = await form.validateFields();
      const payload: MenuMutationPayload = {
        code: values.code.trim(),
        name: values.name.trim(),
        path: normalizeAppRoutePath(values.path?.trim() ? values.path.trim() : null),
        icon: values.icon?.trim() ? values.icon.trim() : null,
        parent_id: values.parent_id?.trim() ? values.parent_id.trim() : null,
        type: values.type,
        sort_order: Number(values.sort_order || 0),
        status: values.status,
        visible: values.visible,
        cacheable: values.cacheable,
        component: values.component?.trim() ? values.component.trim() : null,
      };

      if (editingMenuId) {
        updateMenuMutation.mutate({ menuId: editingMenuId, payload });
      } else {
        createMenuMutation.mutate(payload);
      }
    } catch (candidate) {
      // Form 校验失败时不额外提示。
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }

      const msg = candidate instanceof Error ? candidate.message : "提交失败，请稍后重试";
      setError(new ApiError(msg));
    }
  }, [createMenuMutation, editingMenuId, form, updateMenuMutation]);

  const updateMenuStatus = useCallback(async (menu: MenuItem) => {
    const nextStatus: "enabled" | "disabled" = menu.status === "enabled" ? "disabled" : "enabled";
    updateMenuMutation.mutate({ menuId: menu.id, payload: { status: nextStatus } });
  }, [updateMenuMutation]);

  const columns: ColumnsType<MenuItem> = [
    {
      title: t("编码"),
      dataIndex: "code",
      width: 220,
      render: (value: string) => <span className="font-mono text-xs">{value}</span>,
    },
    {
      title: t("名称"),
      dataIndex: "name",
      width: 180,
    },
    {
      title: t("路径"),
      dataIndex: "path",
      width: 220,
      render: (value: string | null) => value || "-",
    },
    {
      title: t("父菜单"),
      dataIndex: "parent_id",
      width: 220,
      render: (value: string | null) => (value ? menuNameById.get(value) ?? value : "-"),
    },
    {
      title: t("状态"),
      dataIndex: "status",
      width: 110,
      render: (value: string) =>
        value === "enabled" ? <Tag color="success">{t("已启用")}</Tag> : <Tag color="error">{t("已禁用")}</Tag>,
    },
    {
      title: t("排序"),
      dataIndex: "sort_order",
      width: 90,
    },
    ...(canManage ? [{
      title: t("操作"),
      key: "actions",
      fixed: "right",
      width: 180,
      render: (_, record) => {
        const updatingLoading = updatingStatusMenuId === record.id;
        const deleteLoading = deletingMenuId === record.id;
        const menuBusy = updatingLoading || deleteLoading;

        const moreMenuItems: MenuProps["items"] = [
          {
            key: "delete",
            label: t("删除"),
            danger: true,
            disabled: menuBusy,
            onClick: () => {
              Modal.confirm({
                title: `确认删除菜单 ${record.name}（${record.code}）？`,
                okText: t("删除"),
                cancelText: t("取消"),
                okButtonProps: { danger: true, loading: deleteLoading },
                onOk: () => deleteMenuMutation.mutate(record.id),
              });
            },
          },
        ];

        return (
          <Space size="small" style={{ whiteSpace: "nowrap" }}>
            <Button size="small" disabled={menuBusy} onClick={() => startEdit(record)}>
              编辑
            </Button>

            <Button size="small" loading={updatingLoading} disabled={menuBusy}
              onClick={() => void updateMenuStatus(record)}
            >
              {record.status === "enabled" ? "禁用" : "启用"}
            </Button>

            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button size="small" loading={deleteLoading} disabled={menuBusy} icon={<MoreOutlined />} />
            </Dropdown>
          </Space>
        );
      },
    } satisfies ColumnsType<MenuItem>[number]] : []),
  ];

  const renderMenuCard = (menuItem: MenuItem) => {
    const updatingLoading = updatingStatusMenuId === menuItem.id;
    const deleteLoading = deletingMenuId === menuItem.id;
    const menuBusy = updatingLoading || deleteLoading;

    const moreMenuItems: MenuProps["items"] = [
      {
              key: "delete",
              label: t("删除"),
              danger: true,
              disabled: menuBusy || !canManage,
              onClick: (info) => {
                info.domEvent?.stopPropagation();
                Modal.confirm({
                  title: `确认删除菜单 ${menuItem.name}（${menuItem.code}）？`,
                  okText: t("删除"),
                  cancelText: t("取消"),
                  okButtonProps: { danger: true },
                  onOk: () => deleteMenuMutation.mutate(menuItem.id),
                });
              },
            },
          ];

    return (
      <AntCard
        key={menuItem.id}
        className="admin-menus-menu-card"
        size="small"
        hoverable
        onClick={() => startEdit(menuItem)}
      >
        <div className="admin-menus-menu-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <Typography.Text strong className="truncate flex-1">{menuItem.name}</Typography.Text>
          <div className="flex flex-shrink-0 items-center gap-2">
            <Badge status={menuItem.status === "enabled" ? "success" : "error"} />
            <Typography.Text type="secondary" className="text-xs">
              {menuItem.status === "enabled" ? "已启用" : "已禁用"}
            </Typography.Text>
          </div>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
          <div className="admin-menus-menu-card-field">
            <Typography.Text type="secondary">{t("菜单编码")}</Typography.Text>
            <Typography.Text className="font-mono text-xs">{menuItem.code}</Typography.Text>
          </div>
          <div className="admin-menus-menu-card-field">
            <Typography.Text type="secondary">{t("路径")}</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: menuItem.path || "-" }}>{menuItem.path || "-"}</Typography.Text>
          </div>
          <div className="admin-menus-menu-card-field">
            <Typography.Text type="secondary">{t("父菜单")}</Typography.Text>
            <Typography.Text ellipsis>
              {menuItem.parent_id ? menuNameById.get(menuItem.parent_id) ?? menuItem.parent_id : "-"}
            </Typography.Text>
          </div>
          <div className="admin-menus-menu-card-field">
            <Typography.Text type="secondary">{t("排序")}</Typography.Text>
            <Typography.Text>{menuItem.sort_order}</Typography.Text>
          </div>
        </Space>
        <div className="admin-menus-menu-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          <div />
          <Space size="small" className="shrink-0">
            {canManage ? (
              <>
                <Tooltip title={t("编辑")}>
                                  <Button
                                    type="text"
                                    size="small"
                                    disabled={menuBusy}
                                    icon={<EditOutlined />}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      startEdit(menuItem);
                                    }}
                                  />
                                </Tooltip>
                                <Tooltip title={menuItem.status === "enabled" ? "禁用" : "启用"}>
                                  <Button
                                    type="text"
                                    size="small"
                                    loading={updatingLoading}
                                    disabled={menuBusy}
                                    icon={menuItem.status === "enabled" ? <PoweroffOutlined /> : <CheckOutlined />}
                                    onClick={(event) => {
                                      event.stopPropagation();
                                      void updateMenuStatus(menuItem);
                                    }}
                                  />
                                </Tooltip>
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Tooltip title={t("更多")}>
                    <Button
                      type="text"
                      size="small"
                      loading={updatingLoading}
                      disabled={menuBusy}
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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - MENU_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? MENU_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - MENU_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(MENU_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [apiError, filteredMenus.length, menusQuery.isFetching, paginationCurrent, paginationPageSize, updateTableScrollY]);

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
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问菜单管理页面。")}</p>
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
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `menu.read`）。")}</p>
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
      <Tabs
        type="editable-card"
        hideAdd
        defaultActiveKey="list"
        className="admin_menus_tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" onClick={startCreate}>
              新建菜单
            </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: <span className="admin-menus-tab-title">{t("菜单管理")}</span>,
            closable: false,
            children: (
              <div className="admin_menus_list_pane">
                <div ref={containerRef} className="admin-menus-page-body">
          {/* Left: Tree panel with keyword filter */}
          {!isMobile ? (
            <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
              <AntCard
                className="admin-menus-tree-card"
                style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
                styles={{ body: { flex: 1, padding: 0 } }}
              >
                <div className="admin-menus-sider-search">
                  <Input
                    className="admin-menus-search-input"
                    placeholder={t("搜索菜单...")}
                    prefix={<SearchOutlined />}
                    value={treeFilterKeyword}
                    onChange={(e) => setTreeFilterKeyword(e.target.value)}
                    allowClear
                  />
                </div>
                <div className="admin-menus-sider-menu">
                  {menusQuery.isLoading ? (
                    <div style={{ textAlign: "center", padding: "24px" }}>
                      <Spin />
                    </div>
                  ) : treeData.length > 0 ? (
                    <Tree
                      showLine
                      defaultExpandAll
                      treeData={treeData}
                      onSelect={(keys) => {
                        if (keys.length > 0) {
                          const key = keys[0] as string;
                          if (key.startsWith("menu-")) {
                            const id = key.replace("menu-", "");
                            setSelectedTreeKey(id);
                            setPagination((prev) => ({ ...prev, current: 1 }));
                          }
                        } else {
                          setSelectedTreeKey(null);
                          setPagination((prev) => ({ ...prev, current: 1 }));
                        }
                      }}
                    />
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={treeFilterKeyword.trim() ? "未找到匹配的菜单" : "暂无菜单数据"}
                    />
                  )}
                </div>
              </AntCard>
            </div>
          ) : null}
          {!isMobile ? (
            <div
              className="admin-menus-resize-handle"
              onMouseDown={handleResizeStart}
            >
              <div className="admin-menus-resize-handle-line" />
            </div>
          ) : null}
          {/* Right: Table */}
          <div
            ref={pageCardRef}
            className="admin-menus-main"
          >
            {viewMode === "card" ? (
              <div className="admin-filter-bar">
                <Form layout="inline">
                  <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Input
                      allowClear
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.currentTarget.value)}
                      placeholder={t("按编码/名称/路径筛选")}
                      onPressEnter={() => handleSearch()}
                    />
                  </Form.Item>
                  <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                    <Button
                    htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={() => handleSearch()}
                      className="admin-search-btn" loading={menusQuery.isFetching}
                    >
                      查询
                    </Button>
                  </Form.Item>
                </Form>
                <div className="flex items-center">
                  <Segmented
                    value={viewMode}
                    onChange={(value) => {
                      setViewModeOverride(value as "card" | "table");
                      setPagination((prev) => ({ ...prev, current: 1 }));
                      setCardViewPage(1);
                    }}
                    options={[
                      { label: t("卡片视图"), value: "card" },
                      { label: t("列表视图"), value: "table" },
                    ]}
                  />
                </div>
              </div>
            ) : (
              <div className="admin-filter-bar">
                <Form layout="inline">
                  <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Input
                      allowClear
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.currentTarget.value)}
                      placeholder={t("按编码/名称/路径筛选")}
                      onPressEnter={() => handleSearch()}
                    />
                  </Form.Item>

                  <Form.Item label={t("状态")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Select<"enabled" | "disabled">
                      value={statusFilter}
                      allowClear
                      placeholder={t("全部")}
                      onChange={handleStatusFilterChange}
                      options={[
                        { value: "enabled", label: t("已启用") },
                        { value: "disabled", label: t("已禁用") },
                      ]}
                      optionRender={(option) =>
                        option.value === "enabled" ? (
                          <Tag color="success" style={{ margin: 0 }}>{t("已启用")}</Tag>
                        ) : (
                          <Tag color="error" style={{ margin: 0 }}>{t("已禁用")}</Tag>
                        )
                      }
                    />
                  </Form.Item>

                  <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                    <Button
                    htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={() => handleSearch()}
                      className="admin-search-btn" loading={menusQuery.isFetching}
                    >
                      查询
                    </Button>
                  </Form.Item>
                </Form>
                <div className="flex items-center">
                  <Segmented
                    value={viewMode}
                    onChange={(value) => {
                      setViewModeOverride(value as "card" | "table");
                      setPagination((prev) => ({ ...prev, current: 1 }));
                      setCardViewPage(1);
                    }}
                    options={[
                      { label: t("卡片视图"), value: "card" },
                      { label: t("列表视图"), value: "table" },
                    ]}
                  />
                </div>
              </div>
            )}

            {viewMode === "table" ? (
              <div
                ref={tableScrollAnchorRef}
                className="admin-menus-table-anchor"
                style={{ "--admin-menus-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
              >
                <Table<MenuItem>
                  rowKey="id"
                  dataSource={filteredMenus}
                  columns={columns}
                  // 列表始终渲染：查询进行中仅叠加 antd Table 自带居中遮罩，保留现有行，
                  // 接口返回后再更新，避免查询开始时清空表格
                  loading={menusQuery.isFetching}
                  tableLayout="fixed"
                  scroll={{ y: tableScrollY }}
                  pagination={{
                    current: pagination.current,
                    pageSize: pagination.pageSize,
                    total: Math.max(filteredTotal, 1),
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100],
                    showTotal: () => `共 ${filteredTotal} 条`,
                    hideOnSinglePage: false,
                    style: { marginBottom: 0 },
                    onChange: (page, pageSize) => {
                      setPagination({ current: page, pageSize });
                    },
                  }}
                  locale={{
                    emptyText: (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={t("未找到符合筛选条件的菜单项。")}
                      />
                    ),
                  }}
                />
              </div>
            ) : (
              <div className="admin-menus-card-view">
                {menusQuery.isFetching && allLoadedMenus.length === 0 ? (
                  <div className="admin-menus-card-view-state">
                    <Spin />
                  </div>
                ) : allLoadedMenus.length === 0 ? (
                  <div className="admin-menus-card-view-state">
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={t("未找到符合筛选条件的菜单项。")}
                    />
                  </div>
                ) : (
                  <div className="admin-menus-card-view-content">
                    {/* 查询/刷新期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据 */}
                    <Spin spinning={menusQuery.isFetching}>
                      <Row gutter={[12, 12]}>
                        {allLoadedMenus.map((menuItem) => (
                          <Col key={menuItem.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                            {renderMenuCard(menuItem)}
                          </Col>
                        ))}
                      </Row>
                    </Spin>
                    {isLoadingMore && (
                      <div style={{ textAlign: "center", padding: "20px 0" }}>
                        <Spin />
                      </div>
                    )}
                    {allLoadedMenus.length >= filteredTotal && allLoadedMenus.length > 0 && (
                      <div style={{ textAlign: "center", padding: "20px 0" }}>
                        <Typography.Text type="secondary">
                          已加载全部 {allLoadedMenus.length} 条数据
                        </Typography.Text>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={editingMenu ? `编辑菜单：${editingMenu.name}（${editingMenu.id}）` : editingMenuId ? "编辑菜单" : "新建菜单"}
        open={dialogOpen}
        onCancel={closeDialog}
        onOk={() => void submit()}
        confirmLoading={createMenuMutation.isPending || updateMenuMutation.isPending}
        okText={createMenuMutation.isPending || updateMenuMutation.isPending ? "提交中..." : editingMenuId ? "保存修改" : "创建菜单"}
        cancelText={t("取消")}
        destroyOnHidden
        width={760}
      >
        <Form<MenuFormValues>
          form={form}
          layout="vertical"
          initialValues={editingMenu ? menuToFormValues(editingMenu) : DEFAULT_FORM_VALUES}
          preserve={false}
        >
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item
                label={t("菜单编码")}
                name="code"
                rules={[{ required: true, message: t("请输入菜单编码") }]}
              >
                <Input placeholder="admin.example" disabled={editingMenuId !== null} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item
                label={t("菜单名称")}
                name="name"
                rules={[{ required: true, message: t("请输入菜单名称") }]}
              >
                <Input placeholder={t("示例菜单")} />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label={t("路由路径")} name="path" rules={[{ pattern: /^\/[\w\-\/]*$/, message: t("路径需以 / 开头且仅含字母/数字/中划线/斜杠（不允许空格、分号、..）") }]}>
                <Input placeholder="/admin/example" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("图标名")} name="icon">
                <IconPicker />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label={t("父菜单")} name="parent_id">
                <Select
                  allowClear
                  placeholder={t("无")}
                  options={parentOptions.filter((item) => item.value !== editingMenuId)}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("类型")} name="type" rules={[{ required: true, message: t("请选择类型") }]}>
                <Select
                  options={[
                    { value: "directory", label: t("目录") },
                    { value: "menu", label: t("菜单") },
                    { value: "button", label: t("按钮") },
                  ]}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={24}>
              <Form.Item label={t("排序")} name="sort_order" rules={[{ required: true, message: t("请输入排序值") }]}>
                <InputNumber className="w-full" min={0} precision={0} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("状态")} name="status" rules={[{ required: true, message: t("请选择状态") }]}>
                <Select
                  options={[
                    { value: "enabled", label: t("已启用") },
                    { value: "disabled", label: t("已禁用") },
                  ]}
                />
              </Form.Item>
            </Col>

            <Col xs={24} md={12}>
              <Form.Item label={t("组件标识")} name="component">
                <Input placeholder="app/admin/users/page" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="visible" valuePropName="checked">
                <Checkbox>{t("可见")}</Checkbox>
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item name="cacheable" valuePropName="checked">
                <Checkbox>{t("可缓存")}</Checkbox>
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}