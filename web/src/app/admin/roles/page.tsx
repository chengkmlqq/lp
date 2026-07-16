"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  TreeSelect,
  Typography,
  type CardProps,
  type MenuProps,
} from "antd";
import { EditOutlined, MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { CSSProperties, ComponentType, RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { MenuItem, RoleItem } from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type RolesWithMenusResponse = {
  roles: RoleItem[];
  roles_total: number;
  menus: MenuItem[];
  menus_total: number;
};

type RoleFormValues = {
  code: string;
  name: string;
  menu_ids: string[];
};

const EMPTY_FORM: RoleFormValues = {
  code: "",
  name: "",
  menu_ids: [],
};

const ROLE_TABLE_MIN_SCROLL_Y = 180;
const ROLE_TABLE_VIEWPORT_GAP = 40;
const ROLE_TABLE_FALLBACK_RESERVE = 220;

export default function AdminRolesPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [form] = Form.useForm<RoleFormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [roleCodeValidationError, setRoleCodeValidationError] = useState("");
  const [editingRole, setEditingRole] = useState<RoleItem | null>(null);
  const [deletingRoleId, setDeletingRoleId] = useState<string | null>(null);
  const [savingRoleId, setSavingRoleId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const roleCodeCheckTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [tableScrollY, setTableScrollY] = useState(ROLE_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedRoles, setAllLoadedRoles] = useState<RoleItem[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const canRead = hasPermission("role.read") || hasPermission("role.manage");
  const canManage = hasPermission("role.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const trimmedKeyword = searchKeyword.trim();
  const rolesQueryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, trimmedKeyword]);
  const rolesQueryUrl = `/api/v1/admin/roles-with-menus?${rolesQueryParams}`;

  const loadRolesWithMenus = useCallback(async () => {
    const response = await fetchWithAuth(rolesQueryUrl);
    if (!response.ok) throw new Error(await readApiError(response));
    return (await response.json()) as RolesWithMenusResponse;
  }, [fetchWithAuth, rolesQueryUrl]);

  const rolesQuery = useQuery({
    queryKey: ["admin.roles", rolesQueryParams],
    queryFn: loadRolesWithMenus,
    enabled: !!user && canRead,
  });

  useTopicSubscription(
    "admin.roles",
    useCallback(() => {
      if (!user || !canRead) return;
      void queryClient.invalidateQueries({ queryKey: ["admin.roles"] });
    }, [canRead, queryClient, user]),
  );

  useTopicSubscription(
    "admin.menus",
    useCallback(() => {
      if (!user || !canRead) return;
      void queryClient.invalidateQueries({ queryKey: ["admin.roles"] });
    }, [canRead, queryClient, user]),
  );

  const roles = useMemo(() => rolesQuery.data?.roles ?? [], [rolesQuery.data?.roles]);
  const menus = useMemo(() => rolesQuery.data?.menus ?? [], [rolesQuery.data?.menus]);

  const refreshData = async () => {
    await queryClient.refetchQueries({ queryKey: ["admin.roles"] });
  };

  const createRoleMutation = useMutation({
    mutationFn: async (values: RoleFormValues) => {
      const response = await fetchWithAuth("/api/v1/admin/roles", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<RoleItem>;
    },
    onSuccess: async () => {
      setSuccess("角色已创建");
      setError("");
      form.resetFields();
      setDialogOpen(false);
      setEditingRole(null);
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "创建角色失败");
    },
  });

  const updateRoleMutation = useMutation({
    mutationFn: async ({ roleId, payload }: {
      roleId: string;
      payload: { name: string; menu_ids: string[] };
    }) => {
      const response = await fetchWithAuth(`/api/v1/admin/roles/${roleId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<RoleItem>;
    },
    onMutate: ({ roleId }) => {
      setSavingRoleId(roleId);
      setError("");
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("角色已更新");
      setDialogOpen(false);
      setEditingRole(null);
      form.resetFields();
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "更新角色失败");
    },
    onSettled: () => setSavingRoleId(null),
  });

  const deleteRoleMutation = useMutation({
    mutationFn: async (roleId: string) => {
      const response = await fetchWithAuth(`/api/v1/admin/roles/${roleId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<{ message: string }>;
    },
    onMutate: (roleId) => {
      setDeletingRoleId(roleId);
      setError("");
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("角色已删除");
      if (editingRole && deletingRoleId === editingRole.id) {
        setDialogOpen(false);
        setEditingRole(null);
        form.resetFields();
      }
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除角色失败");
    },
    onSettled: () => setDeletingRoleId(null),
  });

  const menuTreeOptions = useMemo(() => {
    // Build lookup map
    const menuMap = new Map<string, MenuItem>();
    for (const menu of menus) {
      menuMap.set(menu.id, menu);
    }

    // Group children by parent_id
    const childrenByParent = new Map<string | null, MenuItem[]>();
    for (const menu of menus) {
      const parentKey = menu.parent_id ?? "__root__";
      const group = childrenByParent.get(parentKey) ?? [];
      group.push(menu);
      childrenByParent.set(parentKey, group);
    }

    // Sort each group by sort_order
    for (const group of childrenByParent.values()) {
      group.sort((a, b) => a.sort_order - b.sort_order);
    }

    // Build tree recursively
    function buildNodes(parentKey: string | null): { title: string; value: string; key: string; children?: unknown[]; selectable: boolean }[] {
      const key = parentKey === null ? "__root__" : parentKey;
      const children = childrenByParent.get(key) ?? [];
      return children.map((menu) => {
        const isDir = menu.type === "directory";
        const label = isDir ? `📁 ${menu.name}` : menu.name;
        const subChildren = buildNodes(menu.id);
        return {
          title: label,
          value: menu.id,
          key: menu.id,
          selectable: true,
          children: subChildren.length > 0 ? subChildren : undefined,
        };
      });
    }

    return buildNodes(null);
  }, [menus]);

  const menuNameById = useMemo(() => {
    return new Map(menus.map((menu) => [menu.id, menu.name]));
  }, [menus]);

  const validateRoleCodeFormat = useCallback((roleCode: string): string | null => {
    const trimmedCode = roleCode.trim();
    if (!trimmedCode) return null;

    const validPattern = /^[a-zA-Z0-9_.-]+$/;
    if (!validPattern.test(trimmedCode)) {
      return "角色编码只能包含英文字母、数字、下划线、点和短横线";
    }

    return null;
  }, []);

  const checkRoleCodeAvailability = useCallback(async (roleCode: string) => {
    try {
      const params = new URLSearchParams({
        limit: "20",
        offset: "0",
        keyword: roleCode,
      });
      const response = await fetchWithAuth(`/api/v1/admin/roles?${params.toString()}`);
      if (!response.ok) {
        return { available: true, message: "" };
      }
      const data = (await response.json()) as { items?: RoleItem[] };
      const existingRole = data.items?.some(
        (role) => role.code.trim().toLowerCase() === roleCode.trim().toLowerCase(),
      );
      return {
        available: !existingRole,
        message: existingRole ? "角色编码已存在，请更换后重试" : "",
      };
    } catch {
      return { available: true, message: "" };
    }
  }, [fetchWithAuth]);

  const handleRoleCodeChange = useCallback((value: string) => {
    if (roleCodeCheckTimeoutRef.current) {
      clearTimeout(roleCodeCheckTimeoutRef.current);
    }

    const formatError = validateRoleCodeFormat(value);
    if (formatError) {
      setRoleCodeValidationError(formatError);
      return;
    }

    const trimmedValue = value.trim();
    if (!trimmedValue) {
      setRoleCodeValidationError("");
      return;
    }

    roleCodeCheckTimeoutRef.current = setTimeout(async () => {
      const result = await checkRoleCodeAvailability(trimmedValue);
      setRoleCodeValidationError(result.available ? "" : result.message);
    }, 500);
  }, [checkRoleCodeAvailability, validateRoleCodeFormat]);

  const closeDialog = useCallback(() => {
    if (createRoleMutation.isPending || updateRoleMutation.isPending) return;
    setEditingRole(null);
    setDialogOpen(false);
    setRoleCodeValidationError("");
    form.resetFields();
  }, [createRoleMutation.isPending, form, updateRoleMutation.isPending]);

  const startCreate = useCallback(() => {
    setError("");
    setSuccess("");
    setRoleCodeValidationError("");
    setEditingRole(null);
    form.setFieldsValue(EMPTY_FORM);
    setDialogOpen(true);
  }, [form]);

  const startEdit = useCallback((role: RoleItem) => {
    setError("");
    setSuccess("");
    setRoleCodeValidationError("");
    setEditingRole(role);
    form.setFieldsValue({
      code: role.code,
      name: role.name,
      menu_ids: role.menu_ids,
    });
    setDialogOpen(true);
  }, [form]);

  const submit = useCallback(async () => {
    setError("");
    setSuccess("");

    try {
      const values = await form.validateFields();
      const payload: RoleFormValues = {
        code: values.code.trim(),
        name: values.name.trim(),
        menu_ids: values.menu_ids ?? [],
      };
      const formatError = validateRoleCodeFormat(payload.code);
      if (formatError) {
        setRoleCodeValidationError(formatError);
        return;
      }

      if (editingRole) {
        updateRoleMutation.mutate({
          roleId: editingRole.id,
          payload: {
            name: payload.name,
            menu_ids: payload.menu_ids,
          },
        });
      } else {
        const availabilityCheck = await checkRoleCodeAvailability(payload.code);
        if (!availabilityCheck.available) {
          setRoleCodeValidationError(availabilityCheck.message);
          return;
        }
        createRoleMutation.mutate(payload);
      }
    } catch (candidate) {
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }

      const nextError = candidate instanceof Error ? candidate.message : "提交失败，请稍后重试";
      setError(nextError);
    }
  }, [checkRoleCodeAvailability, createRoleMutation, editingRole, form, updateRoleMutation, validateRoleCodeFormat]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
  };

  const queryError = rolesQuery.error instanceof Error ? rolesQuery.error.message : "";
  const anyError = error || queryError;

  useToastFeedback({
    errorMessage: anyError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  // Update allLoadedRoles when roles data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || rolesQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedRoles(roles);
      } else {
        setAllLoadedRoles((prev) => {
          if (roles.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(r => r.id));
          const newRoles = roles.filter(r => !existingIds.has(r.id));
          return [...prev, ...newRoles];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [roles, rolesQuery.isLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const cardBody = pageCard.querySelector<HTMLElement>(".ant-card-body");
    if (!cardBody) return;

    const handleScroll = () => {
      if (isLoadingMore || rolesQuery.isLoading) return;

      const scrollTop = cardBody.scrollTop;
      const scrollHeight = cardBody.scrollHeight;
      const clientHeight = cardBody.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = rolesQuery.data?.roles_total ?? 0;
        const loadedCount = allLoadedRoles.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    cardBody.addEventListener("scroll", handleScroll);
    return () => cardBody.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, rolesQuery.isLoading, rolesQuery.data?.roles_total, allLoadedRoles.length]);

  const columns = useMemo<ColumnsType<RoleItem>>(() => {
    const base: ColumnsType<RoleItem> = [
      {
        title: "角色编码",
        dataIndex: "code",
        width: 140,
      },
      {
        title: "角色名称",
        dataIndex: "name",
        width: 140,
      },
      {
        title: "菜单",
        dataIndex: "menu_ids",
        width: 300,
        render: (value: string[]) => {
          if (value.length === 0) {
            return <Typography.Text type="secondary">未绑定菜单</Typography.Text>;
          }
          const menuLabels = value.map((menuId) => menuNameById.get(menuId) ?? String(menuId));
          const fullText = menuLabels.join("、");
          const compactText = menuLabels.length > 2
            ? `${menuLabels.slice(0, 2).join("、")}等${menuLabels.length}个...`
            : fullText;
          return (
            <Typography.Text
              title={fullText}
              style={{
                display: "inline-block",
                verticalAlign: "bottom",
              }}
            >
              {compactText}
            </Typography.Text>
          );
        },
      },
    ];

    if (canManage) {
      base.push({
        title: "操作",
        key: "actions",
        fixed: "right",
        width: 140,
        render: (_, role) => {
          const isDeleting = deletingRoleId === role.id;
          const isSaving = savingRoleId === role.id;
          const rowBusy = isDeleting || isSaving || createRoleMutation.isPending || updateRoleMutation.isPending;

          return (
            <Space wrap>
              <Button
                size="small"
                disabled={rowBusy}
                onClick={() => startEdit(role)}
              >
                编辑
              </Button>
              <Popconfirm
                title={`确认删除角色 ${role.code} 吗？`}
                description="删除后无法恢复，请谨慎操作。"
                okText="删除"
                cancelText="取消"
                okButtonProps={{ danger: true, loading: isDeleting }}
                onConfirm={() => deleteRoleMutation.mutate(role.id)}
                disabled={rowBusy}
              >
                <Button
                  danger
                  size="small"
                  loading={isDeleting}
                  disabled={rowBusy}
                >
                  删除
                </Button>
              </Popconfirm>
            </Space>
          );
        },
      });
    }

    return base;
  }, [canManage, createRoleMutation.isPending, deletingRoleId, deleteRoleMutation, menuNameById, savingRoleId, startEdit, updateRoleMutation.isPending]);

  const renderRoleCard = (role: RoleItem) => {
    const isDeleting = deletingRoleId === role.id;
    const isSaving = savingRoleId === role.id;
    const rowBusy = isDeleting || isSaving || createRoleMutation.isPending || updateRoleMutation.isPending;
    const menuLabels = role.menu_ids.length > 0
      ? role.menu_ids.map((menuId) => menuNameById.get(menuId) ?? String(menuId))
      : [];
    const fullText = menuLabels.length > 0 ? menuLabels.join("、") : "未绑定菜单";
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "view-menus",
        label: "查看菜单",
        disabled: menuLabels.length === 0,
        onClick: () => {
          Modal.info({
            title: `角色菜单：${role.name}（${role.code}）`,
            content: (
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                {menuLabels.length > 0 ? (
                  menuLabels.map((label) => (
                    <Typography.Text key={label}>{label}</Typography.Text>
                  ))
                ) : (
                  <Typography.Text type="secondary">未绑定菜单</Typography.Text>
                )}
              </Space>
            ),
            okText: "知道了",
          });
        },
      },
      {
        key: "delete",
        label: "删除",
        danger: true,
        disabled: rowBusy,
        onClick: () => {
          Modal.confirm({
            title: `确认删除角色 ${role.code} 吗？`,
            content: "删除后无法恢复，请谨慎操作。",
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true, loading: isDeleting },
            onOk: () => deleteRoleMutation.mutate(role.id),
          });
        },
      },
    ];

    return (
      <AntCard
        key={role.id}
        className="admin-roles-role-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis={{ tooltip: role.name }}>
              {role.name}
            </Typography.Text>
            <Typography.Text type="secondary" ellipsis={{ tooltip: role.code }}>
              {role.code}
            </Typography.Text>
          </Space>
        }
        extra={
          canManage ? (
            <Space size={4}>
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                disabled={rowBusy}
                onClick={() => startEdit(role)}
              />
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button
                  type="text"
                  size="small"
                  icon={<MoreOutlined />}
                  disabled={rowBusy}
                />
              </Dropdown>
            </Space>
          ) : null
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">角色编码</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: role.code }}>
              {role.code}
            </Typography.Text>
          </div>
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">角色名称</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: role.name }}>
              {role.name}
            </Typography.Text>
          </div>
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">菜单</Typography.Text>
            <Typography.Text
              title={fullText}
              ellipsis={{ tooltip: fullText }}
            >
              {menuLabels.length > 2
                ? `${menuLabels.slice(0, 2).join("、")}等${menuLabels.length}个...`
                : fullText}
            </Typography.Text>
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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - ROLE_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? ROLE_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(
        window.innerHeight - anchorTop - topGap - nonBodyHeight - ROLE_TABLE_VIEWPORT_GAP,
      );
    }

    const clampedHeight = Math.max(ROLE_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [anyError, paginationCurrent, paginationPageSize, roles.length, rolesQuery.isFetching, updateTableScrollY]);

  useEffect(() => {
    return () => {
      if (roleCodeCheckTimeoutRef.current) {
        clearTimeout(roleCodeCheckTimeoutRef.current);
      }
    };
  }, []);

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
        <Spin tip="初始化中..." />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问角色管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `role.read`）。</p>
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
        className="admin-roles-page-card"
        title="角色管理"
        extra={
          canManage ? (
            <Button type="primary" onClick={startCreate}>
              新建角色
            </Button>
          ) : null
        }
      >
        {viewMode === "card" ? (
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  placeholder="按角色编码/名称/菜单搜索"
                  value={keywordInput}
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  onPressEnter={handleSearch}
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  icon={<SearchOutlined />}
                  onClick={handleSearch}
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
                  allowClear
                  placeholder="按角色编码/名称/菜单搜索"
                  value={keywordInput}
                  onChange={(event) => handleKeywordChange(event.target.value)}
                  onPressEnter={handleSearch}
                />
              </Form.Item>
              <Form.Item style={ marginBottom: 0 }>
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
          </div>
        )}

        {viewMode === "table" ? (
          <div
            ref={tableScrollAnchorRef}
            className="admin-roles-table-anchor"
            style={{ "--admin-roles-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table<RoleItem>
              rowKey="id"
              columns={columns}
              dataSource={roles}
              loading={rolesQuery.isLoading}
              tableLayout="fixed"
              scroll={{ y: tableScrollY }}
              pagination={{
                current: paginationCurrent,
                pageSize: paginationPageSize,
                total: Math.max(rolesQuery.data?.roles_total ?? 0, 1),
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${rolesQuery.data?.roles_total ?? 0} 条`,
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
                    description="未找到符合筛选条件的角色。"
                  />
                ),
              }}
            />
          </div>
        ) : (
          <div className="admin-roles-card-view">
            {rolesQuery.isLoading && allLoadedRoles.length === 0 ? (
              <div className="admin-roles-card-view-state">
                <Spin tip="加载中..." />
              </div>
            ) : allLoadedRoles.length === 0 ? (
              <div className="admin-roles-card-view-state">
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的角色。"
                />
              </div>
            ) : (
              <div className="admin-roles-card-view-content">
                <Row gutter={[12, 12]}>
                  {allLoadedRoles.map((role) => (
                    <Col key={role.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                      {renderRoleCard(role)}
                    </Col>
                  ))}
                </Row>
                {isLoadingMore && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Spin tip="加载更多..." />
                  </div>
                )}
                {allLoadedRoles.length >= (rolesQuery.data?.roles_total ?? 0) && allLoadedRoles.length > 0 && (
                  <div style={{ textAlign: "center", padding: "20px 0" }}>
                    <Typography.Text type="secondary">
                      已加载全部 {allLoadedRoles.length} 条数据
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
          title={editingRole ? `编辑角色：${editingRole.name}（${editingRole.code}）` : "新建角色"}
          open={dialogOpen}
          destroyOnHidden
          okText={editingRole ? "保存修改" : "创建角色"}
          cancelText="取消"
          confirmLoading={createRoleMutation.isPending || updateRoleMutation.isPending}
          onCancel={closeDialog}
          onOk={() => void submit()}
        >
          <Form<RoleFormValues>
            form={form}
            layout="vertical"
            initialValues={EMPTY_FORM}
            preserve={false}
          >
            <Row gutter={12}>
              <Col xs={24}>
                <Form.Item
                  label="角色编码"
                  name="code"
                  validateStatus={roleCodeValidationError ? "error" : ""}
                  help={roleCodeValidationError}
                  rules={[
                    { required: true, message: "请输入角色编码" },
                    { min: 2, message: "角色编码至少 2 位" },
                    { max: 64, message: "角色编码不能超过 64 位" },
                  ]}
                >
                  <Input
                    disabled={editingRole !== null}
                    placeholder="admin.operator"
                    onChange={(event) => handleRoleCodeChange(event.target.value)}
                  />
                </Form.Item>
              </Col>
              <Col xs={24}>
                <Form.Item
                  label="角色名称"
                  name="name"
                  rules={[
                    { required: true, message: "请输入角色名称" },
                    { max: 120, message: "角色名称不能超过 120 位" },
                  ]}
                >
                  <Input placeholder="运营管理员" />
                </Form.Item>
              </Col>
              <Col xs={24}>
                <Form.Item label="可见菜单" name="menu_ids">
                  <TreeSelect
                    allowClear
                    showSearch
                    treeCheckable
                    showCheckedStrategy="SHOW_PARENT"
                    treeData={menuTreeOptions}
                    placeholder="请选择可见菜单"
                    maxTagCount={3}
                    maxTagPlaceholder={(omitted) => `+${omitted.length} 项`}
                  />
                </Form.Item>
              </Col>
            </Row>
          </Form>
        </Modal>
      )}
    </div>
  );
}
