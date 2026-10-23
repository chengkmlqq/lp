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
  Row,
  Space,
  Spin,
  Table,
  Tabs,
  Tooltip,
  TreeSelect,
  Typography,
  type CardProps,
  type MenuProps,
} from "antd";
import { DeleteOutlined, EditOutlined, KeyOutlined, MoreOutlined, QuestionCircleOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import type { CSSProperties, ComponentType, RefAttributes } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { ApiError, readApiError } from "@/lib/api";
import type { DataNode } from "antd/es/tree";
import type { MenuItem, RoleItem } from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type RolesWithMenusResponse = {
  roles: RoleItem[];
  roles_total: number;
  menus: MenuItem[];
  menus_total: number;
};

/** 「新建 / 编辑角色」弹窗：只含角色自身属性。 */
type RoleFormValues = {
  code: string;
  name: string;
};

/** 「分配权限」弹窗：只含菜单与操作权限（按钮级）。 */
type RolePermissionFormValues = {
  menu_ids: string[];
};

const EMPTY_FORM: RoleFormValues = {
  code: "",
  name: "",
};

const EMPTY_PERMISSION_FORM: RolePermissionFormValues = {
  menu_ids: [],
};

const ROLE_TABLE_MIN_SCROLL_Y = 180;
const ROLE_TABLE_VIEWPORT_GAP = 40;
const ROLE_TABLE_FALLBACK_RESERVE = 220;

export default function AdminRolesPage() {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [form] = Form.useForm<RoleFormValues>();
  // 权限分配用独立表单实例：与角色属性表单分开渲染（两个弹窗可各自独立校验/重置）
  const [permissionForm] = Form.useForm<RolePermissionFormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  // 手动刷新计数：每次点击「查询」都自增并作为查询 key 的一部分，强制走一次接口，
  // 即使关键词/分页未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [roleCodeValidationError, setRoleCodeValidationError] = useState("");
  const [editingRole, setEditingRole] = useState<RoleItem | null>(null);
  const [deletingRoleId, setDeletingRoleId] = useState<string | null>(null);
  const [savingRoleId, setSavingRoleId] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  // 「分配权限」独立弹窗：与「编辑角色」拆成两个入口，
  // 避免改角色名时误把菜单/操作权限一起提交（反之亦然）。
  const [permissionDialogOpen, setPermissionDialogOpen] = useState(false);
  const [editingPermissionRole, setEditingPermissionRole] = useState<RoleItem | null>(null);
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
    // searchNonce 作为 queryKey 的一部分：每次点击「查询」自增，即使关键词/分页均未变化
    // 也会产生新 key 强制重新拉取；首个元素仍是 "admin.roles"，不影响失效/刷新逻辑
    queryKey: ["admin.roles", rolesQueryParams, searchNonce],
    queryFn: loadRolesWithMenus,
    enabled: !!user && canRead,
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询时列表闪空
    placeholderData: (previousData) => previousData,
  });

  useTopicSubscription(
    "admin.roles",
    useCallback(() => {
      if (!user || !canRead) return;
      void queryClient.invalidateQueries({ queryKey: ["admin.roles"] });
    }, [canRead, queryClient, user]),
  );

  // 权限码清单(供角色「权限码」多选下拉)
  const permissionsQuery = useQuery({
    queryKey: ["admin.permissions"],
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/permissions");
      if (!response.ok) throw new Error(await readApiError(response));
      const data = (await response.json()) as { items?: { id: number; code: string; name: string; label: string; module: string }[] };
      return data.items ?? [];
    },
    enabled: !!user && canRead,
    staleTime: 5 * 60 * 1000,
  });

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
      setError(null);
      form.resetFields();
      setDialogOpen(false);
      setEditingRole(null);
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "创建角色失败"));
    },
  });

  const updateRoleMutation = useMutation({
    mutationFn: async ({ roleId, payload }: {
      roleId: string;
      // 字段均可选：后端 PATCH 对 None 字段视为「不修改」，
      // 因此「编辑角色」只传 name、「分配权限」只传 menu_ids/permission_codes。
      payload: { name?: string; menu_ids?: string[]; permission_codes?: string[] };
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
      setError(null);
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("角色已更新");
      setDialogOpen(false);
      setPermissionDialogOpen(false);
      setEditingRole(null);
      setEditingPermissionRole(null);
      form.resetFields();
      permissionForm.resetFields();
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "更新角色失败"));
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
      setError(null);
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
      setError(new ApiError(candidate instanceof Error ? candidate.message : "删除角色失败"));
    },
    onSettled: () => setDeletingRoleId(null),
  });

  const menuTreeOptions = useMemo(() => {
    // 权限码按模块前缀分组:perm:list -> [perm item...](供叶子菜单挂子节点)
    const permsByModule = new Map<string, { code: string; label: string }[]>();
    for (const item of permissionsQuery.data ?? []) {
      const mod = item.module || "";
      const arr = permsByModule.get(mod) ?? [];
      arr.push({ code: item.code, label: item.label || item.code });
      permsByModule.set(mod, arr);
    }
    // 叶子菜单 -> 其 permission_code 模块前缀对应的权限码(菜单页面权限 + 该模块操作按钮)
    // 叶子菜单 value=menu:<id>{t(", 权限码 value=perm:")}<code>, 提交/回显时分拆。
    const menuMap = new Map<string, MenuItem>();
    for (const menu of menus) {
      menuMap.set(menu.id, menu);
    }

    const childrenByParent = new Map<string | null, MenuItem[]>();
    for (const menu of menus) {
      const parentKey = menu.parent_id ?? "__root__";
      const group = childrenByParent.get(parentKey) ?? [];
      group.push(menu);
      childrenByParent.set(parentKey, group);
    }

    for (const group of childrenByParent.values()) {
      group.sort((a, b) => a.sort_order - b.sort_order);
    }

    function buildNodes(parentKey: string | null): DataNode[] {
      const key = parentKey === null ? "__root__" : parentKey;
      const children = childrenByParent.get(key) ?? [];
      return children.map((menu) => {
        const isDir = menu.type === "directory";
        const isButtonParent = menu.type === "menu";
        const label = isDir ? `📁 ${menu.name}` : isButtonParent ? `📄 ${menu.name}` : menu.name;
        const subChildren = buildNodes(menu.id);
        const buttonChildren = (childrenByParent.get(menu.id) ?? []).filter((b) => b.type === "button").sort((a, b) => a.sort_order - b.sort_order).map((b) => ({ title: `🔘 ${b.name}${b.permission_code ? `（${b.permission_code}）` : ""}`, value: `menu:${b.id}`, key: b.id, selectable: true }));
        let permNodes: DataNode[] | undefined;
        // 叶子菜单(非目录)且带 permission_code -> 在树下挂该模块权限码 checkbox
        if (buttonChildren.length === 0 && !isDir && subChildren.length === 0 && menu.permission_code) {
          const mod = menu.permission_code.split(".")[0];
          const perms = permsByModule.get(mod);
          if (perms && perms.length > 0) {
            permNodes = perms.map((p) => ({
              title: p.label,
              value: `perm:${p.code}`,
              key: `perm:${p.code}`,
              selectable: true,
            }));
          }
        }
        const merged = [...subChildren, ...buttonChildren, ...(permNodes ?? [])];
        return {
          title: label,
          value: `menu:${menu.id}`,
          key: menu.id,
          selectable: true,
          children: merged.length > 0 ? merged : undefined,
        };
      });
    }

    return buildNodes(null);
  }, [menus, permissionsQuery.data]);

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

  const closePermissionDialog = useCallback(() => {
    if (updateRoleMutation.isPending) return;
    setEditingPermissionRole(null);
    setPermissionDialogOpen(false);
    permissionForm.resetFields();
  }, [permissionForm, updateRoleMutation.isPending]);

  const startCreate = useCallback(() => {
    setError(null);
    setSuccess("");
    setRoleCodeValidationError("");
    setEditingRole(null);
    form.setFieldsValue(EMPTY_FORM);
    setDialogOpen(true);
  }, [form]);

  /** 编辑角色：只填角色自身属性（编码只读、名称可改），不含权限。 */
  const startEditRole = useCallback((role: RoleItem) => {
    setError(null);
    setSuccess("");
    setRoleCodeValidationError("");
    setEditingRole(role);
    form.setFieldsValue({ code: role.code, name: role.name });
    setDialogOpen(true);
  }, [form]);

  /**
   * 分配权限：只处理「菜单 + 操作权限（按钮级）」。
   *
   * 勾选值用统一前缀编码：`menu:<id>{t("` 表示菜单/按钮行，`perm:")}<code>` 表示模块权限码；
   * 提交时分拆并合并按钮自身的 permission_code（与后端 role_menus / role_permissions 双写对应）。
   */
  const startEditPermissions = useCallback((role: RoleItem) => {
    setError(null);
    setSuccess("");
    const menuVals = (role.menu_ids ?? []).map((mid) => `menu:${mid}`);
    const permVals = (role.permission_codes ?? []).map((pc) => `perm:${pc}`);
    setEditingPermissionRole(role);
    permissionForm.setFieldsValue({ menu_ids: [...new Set([...menuVals, ...permVals])] });
    setPermissionDialogOpen(true);
  }, [permissionForm]);

  /** 提交「新建 / 编辑角色」：只发角色自身属性。 */
  const submitRole = useCallback(async () => {
    setError(null);
    setSuccess("");

    try {
      const values = await form.validateFields();
      const payload: RoleFormValues = {
        code: values.code.trim(),
        name: values.name.trim(),
      };
      const formatError = validateRoleCodeFormat(payload.code);
      if (formatError) {
        setRoleCodeValidationError(formatError);
        return;
      }

      if (editingRole) {
        // 只提交 name：menu_ids / permission_codes 一律不传，
        // 后端对 None 字段视为「不修改」，因此编辑角色不会把已有权限清空。
        updateRoleMutation.mutate({
          roleId: editingRole.id,
          payload: { name: payload.name },
        });
      } else {
        const availabilityCheck = await checkRoleCodeAvailability(payload.code);
        if (!availabilityCheck.available) {
          setRoleCodeValidationError(availabilityCheck.message);
          return;
        }
        // 新建时不带菜单/权限（后端默认为空列表），权限创建后经「分配权限」授予。
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
      setError(new ApiError(nextError));
    }
  }, [checkRoleCodeAvailability, createRoleMutation, editingRole, form, updateRoleMutation, validateRoleCodeFormat]);

  /** 提交「分配权限」：只发 menu_ids / permission_codes，不动角色名称。 */
  const submitPermissions = useCallback(async () => {
    setError(null);
    setSuccess("");
    if (!editingPermissionRole) return;

    try {
      const values = await permissionForm.validateFields();
      const checkedValues: string[] = values.menu_ids ?? [];
      const menuIds = checkedValues
        .filter((v) => v.startsWith("menu:"))
        .map((v) => v.slice("menu:".length));
      const permCodes = checkedValues
        .filter((v) => v.startsWith("perm:"))
        .map((v) => v.slice("perm:".length));
      const menuById = new Map(menus.map((m) => [m.id, m]));
      const buttonPerms = menuIds.map((mid) => menuById.get(mid)).filter((m): m is (typeof menus)[number] => Boolean(m && m.type === "button" && m.permission_code)).map((m) => m.permission_code as string);

      updateRoleMutation.mutate({
        roleId: editingPermissionRole.id,
        payload: {
          menu_ids: menuIds,
          permission_codes: [...new Set([...permCodes, ...buttonPerms])],
        },
      });
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
      setError(new ApiError(nextError));
    }
  }, [editingPermissionRole, menus, permissionForm, updateRoleMutation]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    // 每次点击「查询」都强制触发一次接口请求：
    // searchNonce 作为 queryKey 的一部分自增，保证即便关键词/分页均未变化（旧实现只对
    // 这种情况 refetchQueries，且目标 key 若已被 react-query 缓存会短路不发请求）也会
    // 产生新 key 重新拉取；关键词/分页照常提交并回到第 1 页。
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setSearchNonce((n) => n + 1);
  };

  const queryError = useMemo<ApiError | null>(() => rolesQuery.error instanceof Error ? new ApiError(rolesQuery.error.message) : null, [rolesQuery.error]);
  const apiError = error || queryError;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
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

    // pageCardRef 已迁到 list-pane 容器（admin_roles_list_pane），
    // 该容器自身即 overflow-y:auto 滚动容器，直接使用即可
    const scrollContainer = pageCardRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      if (isLoadingMore || rolesQuery.isLoading) return;

      const scrollTop = scrollContainer.scrollTop;
      const scrollHeight = scrollContainer.scrollHeight;
      const clientHeight = scrollContainer.clientHeight;

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

    scrollContainer.addEventListener("scroll", handleScroll);
    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, rolesQuery.isLoading, rolesQuery.data?.roles_total, allLoadedRoles.length]);

  const columns = useMemo<ColumnsType<RoleItem>>(() => {
    const base: ColumnsType<RoleItem> = [
      {
        title: t("角色编码"),
        dataIndex: "code",
        width: 140,
      },
      {
        title: t("角色名称"),
        dataIndex: "name",
        width: 140,
      },
      {
        title: t("菜单"),
        dataIndex: "menu_ids",
        // 不设置固定宽度：在 tableLayout="fixed" 下作为弹性列吸收表格富余宽度，
        // 使「角色编码」「角色名称」「操作」等固定宽度列不随窗口缩放而变化。
        render: (value: string[]) => {
          if (value.length === 0) {
            return <Typography.Text type="secondary">{t("未绑定菜单")}</Typography.Text>;
          }
          const menuLabels = value.map((menuId) => menuNameById.get(menuId) ?? String(menuId));
          const fullText = menuLabels.join("、");
          const compactText = menuLabels.length > 5
            ? `${menuLabels.slice(0, 5).join("、")}等${menuLabels.length}个...`
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
        title: t("操作"),
        key: "actions",
        fixed: "right",
        width: 170,
        render: (_, role) => {
          const isDeleting = deletingRoleId === role.id;
          const isSaving = savingRoleId === role.id;
          const rowBusy = isDeleting || isSaving || createRoleMutation.isPending || updateRoleMutation.isPending;

          // 操作列按线路管理页（power-lines）模式：最多 2 个按钮直接展示，
          // 多余的收进「⋯」三点下拉（删除为破坏性操作，放下拉并标红）。
          const overflowItems: MenuProps["items"] = [
            {
              key: "delete",
              label: (
                <Space size={4}>
                  <DeleteOutlined />
                  <span>{t("删除")}</span>
                </Space>
              ),
              danger: true,
              disabled: rowBusy,
              onClick: () => {
                Modal.confirm({
                  title: `确认删除角色 ${role.code} 吗？`,
                  content: t("删除后无法恢复，请谨慎操作。"),
                  okText: t("删除"),
                  cancelText: t("取消"),
                  okButtonProps: { danger: true, loading: isDeleting },
                  onOk: () => deleteRoleMutation.mutate(role.id),
                });
              },
            },
          ];

          return (
            <Space size={4}>
              <Button
                size="small"
                disabled={rowBusy}
                onClick={() => startEditRole(role)}
              >
                编辑
              </Button>
              <Button
                size="small"
                disabled={rowBusy}
                onClick={() => startEditPermissions(role)}
              >
                权限
              </Button>
              <Dropdown menu={{ items: overflowItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      });
    }

    return base;
  }, [t, canManage, createRoleMutation.isPending, deletingRoleId, deleteRoleMutation, menuNameById, savingRoleId, startEditRole, startEditPermissions, updateRoleMutation.isPending]);

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
        label: t("查看菜单"),
        disabled: menuLabels.length === 0,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          Modal.info({
            title: `角色菜单：${role.name}（${role.code}）`,
            content: (
              <Space direction="vertical" size={6} style={{ width: "100%" }}>
                {menuLabels.length > 0 ? (
                  menuLabels.map((label) => (
                    <Typography.Text key={label}>{label}</Typography.Text>
                  ))
                ) : (
                  <Typography.Text type="secondary">{t("未绑定菜单")}</Typography.Text>
                )}
              </Space>
            ),
            okText: t("知道了"),
          });
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
            title: `确认删除角色 ${role.code} 吗？`,
            content: t("删除后无法恢复，请谨慎操作。"),
            okText: t("删除"),
            cancelText: t("取消"),
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
        hoverable
        onClick={() => startEditRole(role)}
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
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">{t("角色编码")}</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: role.code }}>
              {role.code}
            </Typography.Text>
          </div>
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">{t("角色名称")}</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: role.name }}>
              {role.name}
            </Typography.Text>
          </div>
          <div className="admin-roles-role-card-field">
            <Typography.Text type="secondary">{t("菜单")}</Typography.Text>
            <Typography.Text
              title={fullText}
              ellipsis={{ tooltip: fullText }}
            >
              {menuLabels.length > 5
                ? `${menuLabels.slice(0, 5).join("、")}等${menuLabels.length}个...`
                : fullText}
            </Typography.Text>
          </div>
        </Space>
        <div className="admin-roles-role-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          <div />
          <Space size="small" className="shrink-0">
            {canManage ? (
              <>
                <Tooltip title={t("编辑")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    disabled={rowBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      startEditRole(role);
                    }}
                  />
                </Tooltip>
                <Tooltip title={t("分配权限")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<KeyOutlined />}
                    disabled={rowBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      startEditPermissions(role);
                    }}
                  />
                </Tooltip>
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Tooltip title={t("更多")}>
                    <Button
                      type="text"
                      size="small"
                      icon={<MoreOutlined />}
                      disabled={rowBusy}
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
  }, [apiError, paginationCurrent, paginationPageSize, roles.length, rolesQuery.isFetching, updateTableScrollY]);

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
        <Spin />
      </div>
    );
  }

  if (!user) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问角色管理页面。")}</p>
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
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `role.read`）。")}</p>
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
        activeKey="list"
        className="admin_roles_tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" onClick={startCreate}>
              新建角色
            </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: <span className="admin-roles-tab-title">{t("角色管理")}</span>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="admin_roles_list_pane">
                {viewMode === "card" ? (
                  <div className="admin-filter-bar">
                    <Form layout="inline">
                      <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                        <Input
                          allowClear
                          placeholder={t("按角色编码/名称/菜单搜索")}
                          value={keywordInput}
                          onChange={(event) => handleKeywordChange(event.target.value)}
                          onPressEnter={handleSearch}
                        />
                      </Form.Item>
                      <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                        <Button
                          icon={<SearchOutlined />}
                          onClick={handleSearch}
                          className="admin-search-btn" loading={rolesQuery.isFetching}
                        >
                          查询
                        </Button>
                      </Form.Item>
                    </Form>
                  </div>
                ) : (
                  <div className="admin-filter-bar">
                    <Form layout="inline">
                      <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                        <Input
                          allowClear
                          placeholder={t("按角色编码/名称/菜单搜索")}
                          value={keywordInput}
                          onChange={(event) => handleKeywordChange(event.target.value)}
                          onPressEnter={handleSearch}
                        />
                      </Form.Item>
                      <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                        <Button
                          htmlType="button"
                          icon={<SearchOutlined />}
                          onClick={handleSearch}
                          className="admin-search-btn" loading={rolesQuery.isFetching}
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
                      // 列表始终渲染：查询进行中仅叠加 antd Table 自带居中遮罩，保留现有行，
                      // 接口返回后再更新，避免查询开始时清空表格
                      loading={rolesQuery.isFetching}
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
                            description={t("未找到符合筛选条件的角色。")}
                          />
                        ),
                      }}
                    />
                  </div>
                ) : (
                  <div className="admin-roles-card-view">
                    {rolesQuery.isFetching && allLoadedRoles.length === 0 ? (
                      <div className="admin-roles-card-view-state">
                        <Spin />
                      </div>
                    ) : allLoadedRoles.length === 0 ? (
                      <div className="admin-roles-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={t("未找到符合筛选条件的角色。")}
                        />
                      </div>
                    ) : (
                      <div className="admin-roles-card-view-content">
                        {/* 查询/刷新期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据 */}
                        <Spin spinning={rolesQuery.isFetching}>
                          <Row gutter={[12, 12]}>
                            {allLoadedRoles.map((role) => (
                              <Col key={role.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                                {renderRoleCard(role)}
                              </Col>
                            ))}
                          </Row>
                        </Spin>
                        {isLoadingMore && (
                          <div style={{ textAlign: "center", padding: "20px 0" }}>
                            <Spin />
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
              </div>
            ),
          },
        ]}
      />

      {canManage && (
        <Modal
          title={editingRole ? `编辑角色：${editingRole.name}` : "新建角色"}
          open={dialogOpen}
          forceRender
          destroyOnHidden
          okText={editingRole ? "保存修改" : "创建角色"}
          cancelText={t("取消")}
          confirmLoading={createRoleMutation.isPending || updateRoleMutation.isPending}
          onCancel={closeDialog}
          onOk={() => void submitRole()}
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
                  label={t("角色编码")}
                  name="code"
                  validateStatus={roleCodeValidationError ? "error" : ""}
                  help={roleCodeValidationError}
                  rules={[
                    { required: true, message: t("请输入角色编码") },
                    { min: 2, message: t("角色编码至少 2 位") },
                    { max: 64, message: t("角色编码不能超过 64 位") },
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
                  label={t("角色名称")}
                  name="name"
                  rules={[
                    { required: true, message: t("请输入角色名称") },
                    { max: 120, message: t("角色名称不能超过 120 位") },
                  ]}
                >
                  <Input placeholder={t("运营管理员")} />
                </Form.Item>
              </Col>
              {!editingRole && (
                <Col xs={24}>
                  <Typography.Text type="secondary">
                    新角色默认无任何权限，创建后请在「分配权限」中授予菜单与操作权限。
                  </Typography.Text>
                </Col>
              )}
            </Row>
          </Form>
        </Modal>
      )}

      {/* 分配权限：与「编辑角色」拆开的独立入口，只提交 menu_ids / permission_codes */}
      {canManage && (
        <Modal
          title={editingPermissionRole ? `分配权限：${editingPermissionRole.name}（${editingPermissionRole.code}）` : "分配权限"}
          open={permissionDialogOpen}
          forceRender
          destroyOnHidden
          width={560}
          okText={t("保存权限")}
          cancelText={t("取消")}
          confirmLoading={updateRoleMutation.isPending}
          onCancel={closePermissionDialog}
          onOk={() => void submitPermissions()}
        >
          <Form<RolePermissionFormValues>
            form={permissionForm}
            layout="vertical"
            initialValues={EMPTY_PERMISSION_FORM}
            preserve={false}
          >
            <Form.Item
              name="menu_ids"
              label={
                <span>
                  菜单与操作权限{" "}
                  <Tooltip title={t("勾选菜单即授予页面查看权限；展开菜单可勾选查看/管理/运行等操作权限（按钮级）。")}>
                    <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px" }} />
                  </Tooltip>
                </span>
              }
            >
              <TreeSelect
                allowClear
                showSearch
                treeCheckable
                showCheckedStrategy="SHOW_PARENT"
                treeData={menuTreeOptions}
                placeholder={t("请选择菜单与操作权限")}
                maxTagCount={6}
                maxTagPlaceholder={(omitted) => `+${omitted.length} 项`}
                style={{ width: "100%" }}
              />
            </Form.Item>
          </Form>
        </Modal>
      )}
    </div>
  );
}
