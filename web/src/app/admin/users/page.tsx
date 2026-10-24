"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
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
  type CardProps,
  type MenuProps,
} from "antd";
import { CheckCircleOutlined, MoreOutlined, EditOutlined, SearchOutlined, UploadOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type ReactNode, type RefAttributes } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { ApiError, readApiError, getApiBaseUrl } from "@/lib/api";
import type { RoleItem, RoleListResponse, TempUploadResponse, UserListResponse, UserPublic } from "@/types/auth";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type UserRolePayload = {
  role_codes: string[];
};

type CreateUserValues = {
  user_id: string;
  email?: string;
  username: string;
  password: string;
};

type EditUserValues = {
  user_id: string;
  username: string;
  email: string;
  status: "active" | "disabled";
};

type ResetPasswordValues = {
  password: string;
};

function statusLabel(status: string): string {
  if (status === "active") return "启用";
  if (status === "disabled") return "禁用";
  return status || "-";
}

// 状态过滤下拉的选中项/选项以 Tag 展示，颜色与表格状态列保持一致
function statusTag(value: unknown): ReactNode {
  return <Tag color={value === "active" ? "green" : "red"}>{statusLabel(String(value ?? ""))}</Tag>;
}

const USERS_TABLE_MIN_SCROLL_Y = 180;
const USERS_TABLE_VIEWPORT_GAP = 40;
const USERS_TABLE_FALLBACK_RESERVE = 220;
const USERS_TABLE_EXTRA_HEIGHT = 15;

export default function AdminUsersPage() {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();

  const [createForm] = Form.useForm<CreateUserValues>();
  const [editUserForm] = Form.useForm<EditUserValues>();
  const [resetPasswordForm] = Form.useForm<ResetPasswordValues>();

  const [savingUserId, setSavingUserId] = useState<string | null>(null);
  const [deletingUserId, setDeletingUserId] = useState<string | null>(null);
  const [resettingUserId, setResettingUserId] = useState<string | null>(null);
  const [updatingStatusUserId, setUpdatingStatusUserId] = useState<string | null>(null);
  const [createUserModalOpen, setCreateUserModalOpen] = useState(false);
  const [selectedCreateAvatarFile, setSelectedCreateAvatarFile] = useState<File | null>(null);
  const [createAvatarPreview, setCreateAvatarPreview] = useState<string>("");
  const [createAvatarUploading, setCreateAvatarUploading] = useState(false);
  const [createAvatarTempFileId, setCreateAvatarTempFileId] = useState<string | null>(null);
  const [createAvatarUploadProgress, setCreateAvatarUploadProgress] = useState(0);
  const [createAvatarUploadError, setCreateAvatarUploadError] = useState("");
  const [editAvatarTempFileId, setEditAvatarTempFileId] = useState<string | null>(null);
  const [editAvatarUploadProgress, setEditAvatarUploadProgress] = useState(0);
  const [editAvatarUploadError, setEditAvatarUploadError] = useState("");
  const [editingUser, setEditingUser] = useState<UserPublic | null>(null);
  const [resetPasswordTarget, setResetPasswordTarget] = useState<UserPublic | null>(null);
  const [assigningRolesUser, setAssigningRolesUser] = useState<UserPublic | null>(null);
  const [roleForm] = Form.useForm<{ role_codes: string[] }>();
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  // 手动刷新计数：每次点击「查询」都自增并作为 queryKey 的一部分，强制走一次接口，
  // 即使关键词/分页未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [statusFilter, setStatusFilter] = useState<"active" | "disabled" | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(USERS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedUsers, setAllLoadedUsers] = useState<UserPublic[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);

  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [userIdValidationError, setUserIdValidationError] = useState("");
  const [editUserIdValidationError, setEditUserIdValidationError] = useState("");
  const userIdCheckTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const canManage = hasPermission("user.manage");
  const canReadRoles = hasPermission("role.read") || hasPermission("role.manage");
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const trimmedKeyword = searchKeyword.trim();
  const usersQueryParams = useMemo(() => {
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
  const usersPath = `/api/v1/users?${usersQueryParams}`;
  const rolesPath = "/api/v1/admin/roles?limit=200&offset=0";

  const loadUsers = useCallback(async () => {
    const response = await fetchWithAuth(usersPath);
    if (!response.ok) throw new Error(await readApiError(response));
    return (await response.json()) as UserListResponse;
  }, [fetchWithAuth, usersPath]);

  const loadRoles = useCallback(async () => {
    const response = await fetchWithAuth(rolesPath);
    if (!response.ok) throw new Error(await readApiError(response));
    return (await response.json()) as RoleListResponse;
  }, [fetchWithAuth]);

  const usersQuery = useQuery({
    queryKey: ["admin.users", usersQueryParams, searchNonce],
    queryFn: loadUsers,
    enabled: !!user && canManage,
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免每次点击查询/翻页时列表闪空
    placeholderData: (previousData) => previousData,
  });

  const rolesQuery = useQuery({
    queryKey: [rolesPath],
    queryFn: loadRoles,
    enabled: !!user && canManage && canReadRoles,
  });

  useTopicSubscription(
    "admin.users",
    useCallback(() => {
      if (!user || !canManage) return;
      void queryClient.invalidateQueries({ queryKey: ["admin.users"] });
      if (canReadRoles) {
        void queryClient.invalidateQueries({ queryKey: [rolesPath] });
      }
    }, [canManage, canReadRoles, queryClient, user]),
  );

  const users = useMemo(() => usersQuery.data?.items ?? [], [usersQuery.data?.items]);
  const roles = useMemo<RoleItem[]>(() => {
    if (canReadRoles) return rolesQuery.data?.items ?? [];
    return Array.from(new Set(users.flatMap((item) => item.role_codes))).map((code, index) => ({
      id: `fallback-${index + 1}`,
      code,
      name: code,
      permission_codes: [],
      menu_ids: [],
    } satisfies RoleItem));
  }, [canReadRoles, rolesQuery.data?.items, users]);

  const roleOptions = useMemo(() => roles.map((item) => item.code), [roles]);

  const roleCodeToName = useMemo(() => {
    const map = new Map<string, string>();
    roles.forEach((role) => {
      map.set(role.code, role.name);
    });
    return map;
  }, [roles]);

  const getRoleName = useCallback((code: string): string => {
    return roleCodeToName.get(code) || code;
  }, [roleCodeToName]);

  const existingEmails = useMemo(
    () => new Set(users.map((item) => item.email.trim().toLowerCase())),
    [users],
  );
  const existingUsernames = useMemo(
    () => new Set(users.map((item) => item.username.trim().toLowerCase())),
    [users],
  );

  const refreshData = async () => {
    await queryClient.refetchQueries({ queryKey: ["admin.users"] });
    if (canReadRoles) {
      await queryClient.refetchQueries({ queryKey: [rolesPath] });
    }
  };

  const createUserMutation = useMutation({
    mutationFn: async (values: CreateUserValues) => {
      const response = await fetchWithAuth("/api/v1/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<UserPublic>;
    },
    onSuccess: async (createdUser) => {
      if (createAvatarTempFileId) {
        setCreateAvatarUploading(true);
        try {
          await avatarUploadMutation.mutateAsync({
            userId: createdUser.id,
            tempFileId: createAvatarTempFileId,
          });
        } catch {
          setError(new ApiError("用户已创建，但 Logo 上传失败，可在编辑中重试"));
          setSuccess("");
        } finally {
          setCreateAvatarUploading(false);
        }
      } else {
        setSuccess("用户已创建");
      }
      setError(null);
      createForm.resetFields();
      setSelectedCreateAvatarFile(null);
      setCreateAvatarPreview("");
      setCreateAvatarTempFileId(null);
      setCreateAvatarUploadProgress(0);
      setCreateAvatarUploadError("");
      setCreateUserModalOpen(false);
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "创建用户失败"));
    },
  });

  const updateRolesMutation = useMutation({
    mutationFn: async ({ userId, roleCodes }: { userId: string; roleCodes: string[] }) => {
      const response = await fetchWithAuth(`/api/v1/users/${userId}/roles`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role_codes: roleCodes } satisfies UserRolePayload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<UserPublic>;
    },
    onMutate: ({ userId }) => {
      setSavingUserId(userId);
      setError(null);
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("用户角色已更新");
      await refreshData();
    },
    onError: (mutationError) => {
      setError(new ApiError(mutationError instanceof Error ? mutationError.message : "更新失败"));
    },
    onSettled: () => setSavingUserId(null),
  });

  const resetPasswordMutation = useMutation({
    mutationFn: async ({ userId, password }: { userId: string; password: string }) => {
      const response = await fetchWithAuth(`/api/v1/users/${userId}/password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ new_password: password }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<UserPublic>;
    },
    onMutate: ({ userId }) => {
      setResettingUserId(userId);
      setError(null);
      setSuccess("");
    },
    onSuccess: () => {
      setSuccess("密码已重置");
      setResetPasswordTarget(null);
      resetPasswordForm.resetFields();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "重置密码失败"));
    },
    onSettled: () => setResettingUserId(null),
  });

  const updateUserProfileMutation = useMutation({
    mutationFn: async ({ userId, payload }: {
      userId: string;
      payload: {
        new_user_id?: string;
        username?: string;
        email?: string;
        status?: "active" | "disabled";
      };
    }) => {
      const response = await fetchWithAuth(`/api/v1/users/${userId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<UserPublic>;
    },
    onMutate: ({ userId }) => {
      setUpdatingStatusUserId(userId);
      setError(null);
      setSuccess("");
    },
    onSuccess: async (_, variables) => {
      if (variables.payload.status) {
        setSuccess(variables.payload.status === "active" ? "用户已启用" : "用户已禁用");
      } else {
        setSuccess("用户信息已更新");
      }
      setEditingUser(null);
      editUserForm.resetFields();
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "更新用户信息失败"));
    },
    onSettled: () => setUpdatingStatusUserId(null),
  });

  const deleteUserMutation = useMutation({
    mutationFn: async (userId: string) => {
      const response = await fetchWithAuth(`/api/v1/users/${userId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<{ message: string }>;
    },
    onMutate: (userId) => {
      setDeletingUserId(userId);
      setError(null);
      setSuccess("");
    },
    onSuccess: async () => {
      setSuccess("用户已删除");
      await refreshData();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(new ApiError(candidate instanceof Error ? candidate.message : "删除用户失败"));
    },
    onSettled: () => setDeletingUserId(null),
  });

  const [uploadingAvatarUserId, setUploadingAvatarUserId] = useState<string | null>(null);

  const avatarUploadMutation = useMutation({
    mutationFn: async ({ userId, tempFileId }: { userId: string; tempFileId: string }) => {
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      const response = await fetchWithAuth(`/api/v1/users/${userId}/avatar`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<UserPublic>;
    },
    onMutate: ({ userId }) => {
      setUploadingAvatarUserId(userId);
    },
    onSuccess: (updatedUser) => {
      setSuccess("头像已更新");
      // 同步更新编辑弹窗快照，使弹窗头像即时刷新
      setEditingUser((prev) => (prev ? { ...prev, ...updatedUser } : prev));
      void refreshData();
    },
    onError: (candidate) => {
      setError(new ApiError(candidate instanceof Error ? candidate.message : "上传头像失败"));
    },
    onSettled: () => setUploadingAvatarUserId(null),
  });

  // 两段式头像上传：选择图片后立即上传到临时目录（展示进度条），确认提交时携带 temp_file_id。
  const handleAvatarTempUpload = useCallback(
    (file: File, mode: "create" | "edit") => {
      if (mode === "create") {
        setSelectedCreateAvatarFile(file);
        setCreateAvatarPreview(URL.createObjectURL(file));
        setCreateAvatarTempFileId(null);
        setCreateAvatarUploadProgress(0);
        setCreateAvatarUploadError("");
      } else {
        setEditAvatarTempFileId(null);
        setEditAvatarUploadProgress(0);
        setEditAvatarUploadError("");
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
        if (mode === "create") {
          setCreateAvatarUploadProgress(percent);
        } else {
          setEditAvatarUploadProgress(percent);
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          if (mode === "create") {
            setCreateAvatarUploadProgress(100);
          } else {
            setEditAvatarUploadProgress(100);
          }
          try {
            const payload = JSON.parse(xhr.responseText) as TempUploadResponse;
            if (mode === "create") {
              setCreateAvatarTempFileId(payload.temp_file_id);
            } else if (editingUser) {
              setEditAvatarTempFileId(payload.temp_file_id);
              avatarUploadMutation.mutate({ userId: editingUser.id, tempFileId: payload.temp_file_id });
            }
          } catch {
            const detail = "上传成功但响应解析失败，请重新选择文件";
            if (mode === "create") {
              setCreateAvatarUploadError(detail);
            } else {
              setEditAvatarUploadError(detail);
            }
          }
          return;
        }
        let detail = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) detail = parsed.detail;
        } catch {
          // 忽略非 JSON 响应
        }
        if (mode === "create") {
          setCreateAvatarUploadError(detail);
        } else {
          setEditAvatarUploadError(detail);
        }
      };
      xhr.onerror = () => {
        const detail = "网络异常，上传失败";
        if (mode === "create") {
          setCreateAvatarUploadError(detail);
        } else {
          setEditAvatarUploadError(detail);
        }
      };
      xhr.onabort = () => {
        const detail = "上传已取消";
        if (mode === "create") {
          setCreateAvatarUploadError(detail);
        } else {
          setEditAvatarUploadError(detail);
        }
      };

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [avatarUploadMutation, getAccessToken, editingUser],
  );

  const validateUserIdFormat = (userId: string): string | null => {
    const trimmedId = userId.trim();
    if (!trimmedId) return null;

    const validPattern = /^[a-zA-Z0-9_]+$/;
    if (!validPattern.test(trimmedId)) {
      return "用户 ID 只能包含英文字母、数字和下划线";
    }

    return null;
  };

  const checkUserIdAvailability = async (userId: string, excludeUserId?: string) => {
    try {
      const params = new URLSearchParams({ user_id: userId });
      if (excludeUserId) {
        params.set("exclude_user_id", excludeUserId);
      }
      const response = await fetchWithAuth(`/api/v1/users/check-id/${encodeURIComponent(userId)}?${excludeUserId ? `exclude_user_id=${encodeURIComponent(excludeUserId)}` : ""}`);
      if (!response.ok) {
        return { available: false, message: t("检查失败") };
      }
      return (await response.json()) as { available: boolean; message: string };
    } catch {
      return { available: false, message: t("检查失败") };
    }
  };

  const handleUserIdChange = async (value: string, isEdit: boolean = false) => {
    if (userIdCheckTimeoutRef.current) {
      clearTimeout(userIdCheckTimeoutRef.current);
    }

    const formatError = validateUserIdFormat(value);

    if (formatError) {
      if (isEdit) {
        setEditUserIdValidationError(formatError);
      } else {
        setUserIdValidationError(formatError);
      }
      return;
    }

    const trimmedValue = value.trim();
    if (!trimmedValue) {
      if (isEdit) {
        setEditUserIdValidationError("");
      } else {
        setUserIdValidationError("");
      }
      return;
    }

    userIdCheckTimeoutRef.current = setTimeout(async () => {
      const result = await checkUserIdAvailability(
        trimmedValue,
        isEdit && editingUser ? editingUser.id : undefined
      );

      if (isEdit) {
        setEditUserIdValidationError(result.available ? "" : result.message);
      } else {
        setUserIdValidationError(result.available ? "" : result.message);
      }
    }, 500);
  };

  const handleCreateUser = async (values: CreateUserValues) => {
    setError(null);
    setSuccess("");

    if (selectedCreateAvatarFile && !createAvatarTempFileId) {
      setError(new ApiError(createAvatarUploadError || "Logo 上传尚未完成，请等待上传完成后再创建用户"));
      return;
    }

    const payload: CreateUserValues = {
      user_id: values.user_id.trim(),
      username: values.username.trim(),
      password: values.password,
    };

    if (values.email && values.email.trim()) {
      payload.email = values.email.trim();
    }

    const formatError = validateUserIdFormat(payload.user_id);
    if (formatError) {
      setError(new ApiError(formatError));
      return;
    }

    const availabilityCheck = await checkUserIdAvailability(payload.user_id);
    if (!availabilityCheck.available) {
      setError(new ApiError(availabilityCheck.message));
      return;
    }

    const candidateEmail = payload.email?.toLowerCase();
    const candidateUsername = payload.username.toLowerCase();

    if (candidateEmail && existingEmails.has(candidateEmail)) {
      setError(new ApiError("邮箱已存在，请更换后重试"));
      return;
    }
    if (existingUsernames.has(candidateUsername)) {
      setError(new ApiError("用户名已存在，请更换后重试"));
      return;
    }

    createUserMutation.mutate(payload);
  };

  const openResetPasswordModal = (target: UserPublic) => {
    setError(null);
    setSuccess("");
    setResetPasswordTarget(target);
    resetPasswordForm.resetFields();
  };

  const closeResetPasswordModal = () => {
    if (resetPasswordMutation.isPending) return;
    setResetPasswordTarget(null);
    resetPasswordForm.resetFields();
  };

  const openAssignRolesModal = (target: UserPublic) => {
    setError(null);
    setSuccess("");
    setAssigningRolesUser(target);
    roleForm.setFieldsValue({ role_codes: target.role_codes });
  };

  const closeAssignRolesModal = () => {
    if (updateRolesMutation.isPending) return;
    setAssigningRolesUser(null);
    roleForm.resetFields();
  };

  const handleSubmitAssignRoles = async () => {
    if (!assigningRolesUser) return;

    try {
      const values = await roleForm.validateFields();
      updateRolesMutation.mutate(
        { userId: assigningRolesUser.id, roleCodes: values.role_codes },
        {
          onSuccess: () => {
            closeAssignRolesModal();
          },
        },
      );
    } catch {
      // Validation errors are already shown in the form
    }
  };

  const openEditUserModal = (target: UserPublic) => {
    setError(null);
    setSuccess("");
    setEditUserIdValidationError("");
    setEditingUser(target);
    setEditAvatarTempFileId(null);
    setEditAvatarUploadProgress(0);
    setEditAvatarUploadError("");
    editUserForm.setFieldsValue({
      user_id: target.id,
      username: target.username,
      email: target.email,
      status: target.status === "disabled" ? "disabled" : "active",
    });
  };

  const closeEditUserModal = () => {
    if (updateUserProfileMutation.isPending) return;
    setEditingUser(null);
    setEditUserIdValidationError("");
    editUserForm.resetFields();
  };

  const handleSubmitEditUser = async (values: EditUserValues) => {
    if (!editingUser) return;
    const nextUserId = values.user_id.trim();
    const nextUsername = values.username.trim();
    const nextEmail = values.email ? values.email.trim().toLowerCase() : "";
    const nextStatus = values.status;

    const formatError = validateUserIdFormat(nextUserId);
    if (formatError) {
      setError(new ApiError(formatError));
      return;
    }

    const payload: { new_user_id?: string; username?: string; email?: string; status?: "active" | "disabled" } = {};

    if (nextUserId !== editingUser.id) {
      const availabilityCheck = await checkUserIdAvailability(nextUserId, editingUser.id);
      if (!availabilityCheck.available) {
        setError(new ApiError(availabilityCheck.message));
        return;
      }
      payload.new_user_id = nextUserId;
    }
    if (nextUsername !== editingUser.username) {
      payload.username = nextUsername;
    }
    if (nextEmail && nextEmail !== editingUser.email.toLowerCase()) {
      payload.email = nextEmail;
    }
    if (nextStatus !== editingUser.status) {
      payload.status = nextStatus;
    }

    if (Object.keys(payload).length === 0) {
      setSuccess("未检测到变更");
      closeEditUserModal();
      return;
    }

    updateUserProfileMutation.mutate({
      userId: editingUser.id,
      payload,
    });
  };

  const handleSubmitResetPassword = (values: ResetPasswordValues) => {
    if (!resetPasswordTarget) return;
    resetPasswordMutation.mutate({ userId: resetPasswordTarget.id, password: values.password });
  };

  const openCreateUserModal = () => {
    setError(null);
    setSuccess("");
    setUserIdValidationError("");
    createForm.resetFields();
    setSelectedCreateAvatarFile(null);
    setCreateAvatarPreview("");
    setCreateAvatarTempFileId(null);
    setCreateAvatarUploadProgress(0);
    setCreateAvatarUploadError("");
    setCreateUserModalOpen(true);
  };

  const closeCreateUserModal = () => {
    if (createUserMutation.isPending || createAvatarUploading) return;
    setCreateUserModalOpen(false);
    setUserIdValidationError("");
    createForm.resetFields();
    setSelectedCreateAvatarFile(null);
    setCreateAvatarPreview("");
    setCreateAvatarTempFileId(null);
    setCreateAvatarUploadProgress(0);
    setCreateAvatarUploadError("");
  };

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const handleSearch = () => {
    // 每次点击「查询」都强制触发一次接口请求：searchNonce 作为 queryKey 的一部分自增，
    // 即便关键词/分页均未变化（旧实现仅 refetchQueries，目标 key 已被 react-query 缓存时
    // 会短路不发请求）也会产生新 key 重新拉取；关键词/分页照常提交并回到第 1 页。
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setSearchNonce((n) => n + 1);
  };

  const queryError = useMemo<ApiError | null>(() =>
    (usersQuery.error instanceof Error ? new ApiError(usersQuery.error.message) : null)
    || (rolesQuery.error instanceof Error ? new ApiError(rolesQuery.error.message) : null),
    [usersQuery.error, rolesQuery.error],
  );
  const apiError = error || queryError;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

  // Update allLoadedUsers when users data changes in card view
  useEffect(() => {
    // isPlaceholderData 期间展示的是上一份占位数据（新查询进行中），与 isLoading 一样
    // 不能写入累积列表，否则翻页加载会被提前合并、打乱加载更多顺序
    if (viewMode !== "card" || usersQuery.isLoading || usersQuery.isPlaceholderData) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- Mobile card view intentionally mirrors paged query results into an accumulated list.
        setAllLoadedUsers(() => users);
      } else {
        setAllLoadedUsers((prev) => {
          if (users.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(u => u.id));
          const newUsers = users.filter(u => !existingIds.has(u.id));
          return [...prev, ...newUsers];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [users, usersQuery.isLoading, usersQuery.isPlaceholderData, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    const pageCard = pageCardRef.current;
    if (!pageCard) return;

    const handleScroll = () => {
      if (isLoadingMore || usersQuery.isLoading) return;

      const scrollTop = pageCard.scrollTop;
      const scrollHeight = pageCard.scrollHeight;
      const clientHeight = pageCard.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = usersQuery.data?.total ?? 0;
        const loadedCount = allLoadedUsers.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    pageCard.addEventListener("scroll", handleScroll);
    return () => pageCard.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, usersQuery.isLoading, usersQuery.data?.total, allLoadedUsers.length]);

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - USERS_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? USERS_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - USERS_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(USERS_TABLE_MIN_SCROLL_Y, nextHeight + USERS_TABLE_EXTRA_HEIGHT);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [apiError, paginationCurrent, paginationPageSize, users.length, usersQuery.isFetching, updateTableScrollY]);

  useEffect(() => {
    return () => {
      if (userIdCheckTimeoutRef.current) {
        clearTimeout(userIdCheckTimeoutRef.current);
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

  const columns: ColumnsType<UserPublic> = [
    {
      title: "Logo",
      key: "avatar",
      width: 80,
      render: (_value, row) => (
        <Avatar
          size={32}
          src={row.avatar_url ? `${getApiBaseUrl()}${row.avatar_url}?t=${encodeURIComponent(row.updated_at ?? "")}` : undefined}
          style={{ backgroundColor: "var(--ant-color-primary)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}
        >
          {!row.avatar_url ? row.username.trim().charAt(0).toUpperCase() || "U" : undefined}
        </Avatar>
      ),
    },
    {
      title: t("用户 ID"),
      dataIndex: "id",
      width: 140,
    },
    {
      title: t("用户名"),
      dataIndex: "username",
      width: 140,
    },
    {
      title: t("角色"),
      dataIndex: "role_codes",
      width: 180,
      render: (roleCodes: string[]) => (
        <Space wrap size={[4, 4]}>
          {roleCodes && roleCodes.length > 0 ? (
            roleCodes.map((code) => (
              <Tag key={code} color="blue">
                {getRoleName(code)}
              </Tag>
            ))
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          )}
        </Space>
      ),
    },
    {
      title: t("邮箱"),
      dataIndex: "email",
      width: 200,
    },
    {
      title: t("状态"),
      dataIndex: "status",
      width: 100,
      align: "center",
      render: (value: string) => (
        <Tag color={value === "active" ? "green" : "red"}>{statusLabel(value)}</Tag>
      ),
    },
    {
      title: t("操作"),
      key: "actions",
      fixed: "right",
      width: 200,
      render: (_value, row) => {
        const updatingLoading = updatingStatusUserId === row.id;
        const resetLoading = resettingUserId === row.id;
        const deleteLoading = deletingUserId === row.id;
        const savingLoading = savingUserId === row.id;
        const rowBusy = updatingLoading || resetLoading || deleteLoading || savingLoading;

        const moreMenuItems: MenuProps["items"] = [
          {
            key: "assign-roles",
            label: t("分配角色"),
            disabled: rowBusy,
            onClick: () => openAssignRolesModal(row),
          },
          {
            key: "reset-password",
            label: t("重置密码"),
            disabled: rowBusy,
            onClick: () => openResetPasswordModal(row),
          },
          {
            key: "toggle-status",
            label: row.status === "active" ? "禁用" : "启用",
            disabled: rowBusy || row.id === user?.id,
            onClick: () => {
              if (row.id === user?.id) {
                setError(new ApiError("不能修改当前登录账号的状态"));
                return;
              }
              const nextStatus: "active" | "disabled" = row.status === "active" ? "disabled" : "active";
              updateUserProfileMutation.mutate({ userId: row.id, payload: { status: nextStatus } });
            },
          },
        ];

        return (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy}
              onClick={() => openEditUserModal(row)}
            >
              编辑
            </Button>

            <Button danger size="small" loading={deleteLoading} disabled={rowBusy}
              onClick={() => {
                Modal.confirm({
                  title: `确认删除用户 ${row.username}（${row.id}）？`,
                  okText: t("删除"),
                  cancelText: t("取消"),
                  okButtonProps: { danger: true, loading: deleteLoading },
                  onOk: () => deleteUserMutation.mutate(row.id),
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
    },
  ];

  const renderUserCard = (userItem: UserPublic) => {
    const updatingLoading = updatingStatusUserId === userItem.id;
    const resetLoading = resettingUserId === userItem.id;
    const deleteLoading = deletingUserId === userItem.id;
    const savingLoading = savingUserId === userItem.id;
    const rowBusy = updatingLoading || resetLoading || deleteLoading || savingLoading;

    const moreMenuItems: MenuProps["items"] = [
      {
        key: "delete",
        label: t("删除"),
        danger: true,
        disabled: rowBusy,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          Modal.confirm({
            title: `确认删除用户 ${userItem.username}（${userItem.id}）？`,
            okText: t("删除"),
            cancelText: t("取消"),
            okButtonProps: { danger: true },
            onOk: () => deleteUserMutation.mutate(userItem.id),
          });
        },
      },
      {
        key: "assign-roles",
        label: t("分配角色"),
        disabled: rowBusy,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          openAssignRolesModal(userItem);
        },
      },
      {
        key: "reset-password",
        label: t("重置密码"),
        disabled: rowBusy,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          openResetPasswordModal(userItem);
        },
      },
      {
        key: "toggle-status",
        label: userItem.status === "active" ? "禁用" : "启用",
        disabled: rowBusy || userItem.id === user?.id,
        onClick: (info) => {
          info.domEvent?.stopPropagation();
          if (userItem.id === user?.id) {
            setError(new ApiError("不能修改当前登录账号的状态"));
            return;
          }
          const nextStatus: "active" | "disabled" = userItem.status === "active" ? "disabled" : "active";
          updateUserProfileMutation.mutate({ userId: userItem.id, payload: { status: nextStatus } });
        },
      },
    ];

    return (
      <AntCard
        key={userItem.id}
        className="admin-users-user-card"
        size="small"
        hoverable
        onClick={() => openEditUserModal(userItem)}
      >
        <div className="admin-users-user-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <Typography.Text strong className="truncate flex-1">{userItem.username}</Typography.Text>
          <div className="flex flex-shrink-0 items-center gap-2">
            <Badge status={userItem.status === "active" ? "success" : "error"} />
            <Typography.Text type="secondary" className="text-xs">{statusLabel(userItem.status)}</Typography.Text>
          </div>
        </div>
        <Space direction="vertical" size={10} style={{ width: "100%" }} className="px-4 py-3">
          <div className="admin-users-user-card-field">
            <Typography.Text type="secondary">{t("用户 ID")}</Typography.Text>
            <Typography.Text>{userItem.id}</Typography.Text>
          </div>
          <div className="admin-users-user-card-field">
            <Typography.Text type="secondary">{t("角色")}</Typography.Text>
            <Space wrap size={[4, 4]}>
              {userItem.role_codes && userItem.role_codes.length > 0 ? (
                userItem.role_codes.map((code) => (
                  <Tag key={code} color="blue" bordered={false}>
                    {getRoleName(code)}
                  </Tag>
                ))
              ) : (
                <Typography.Text type="secondary">-</Typography.Text>
              )}
            </Space>
          </div>
          <div className="admin-users-user-card-field">
            <Typography.Text type="secondary">{t("邮箱")}</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: userItem.email || "-" }}>
              {userItem.email || "-"}
            </Typography.Text>
          </div>
        </Space>
        <div className="admin-users-user-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
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
                  openEditUserModal(userItem);
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
      </AntCard>
    );
  };

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
        <p className="text-sm text-[var(--gray-11)]">{t("请先登录后再访问用户管理页面。")}</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  if (!canManage) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `user.manage`）。")}</p>
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
        className="admin_users_tabs"
        tabBarExtraContent={
          <Button type="primary" onClick={openCreateUserModal}>
            {t("新建用户")}
          </Button>
        }
        items={[
          {
            key: "list",
            label: <span className="admin_users_tab_title">{t("用户管理")}</span>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="admin_users_list_pane">
            {viewMode === "card" ? (
              <div className="admin-filter-bar">
                <Form layout="inline">
                  <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Input
                      allowClear
                      placeholder={t("按用户 ID/邮箱/用户名搜索")}
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.target.value)}
                      onPressEnter={handleSearch}
                    />
                  </Form.Item>

                  <Form.Item label={t("状态")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Select<"active" | "disabled">
                      value={statusFilter}
                      allowClear
                      placeholder={t("全部")}
                      options={[
                        { value: "active", label: t("已启用") },
                        { value: "disabled", label: t("已禁用") },
                      ]}
                      labelRender={(props) => statusTag(props.value)}
                      optionRender={(option) => statusTag(option.value)}
                      onChange={(value) => {
                        setStatusFilter(value);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedUsers([]);
                      }}
                    />
                  </Form.Item>

                  <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                    <Button
                      htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={handleSearch}
                      className="admin-search-btn" loading={usersQuery.isFetching}
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
                      allowClear
                      placeholder={t("按用户 ID/邮箱/用户名搜索")}
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.target.value)}
                      onPressEnter={handleSearch}
                    />
                  </Form.Item>
    
                  <Form.Item label={t("状态")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Select<"active" | "disabled">
                      value={statusFilter}
                      allowClear
                      placeholder={t("全部")}
                      options={[
                        { value: "active", label: t("已启用") },
                        { value: "disabled", label: t("已禁用") },
                      ]}
                      labelRender={(props) => statusTag(props.value)}
                      optionRender={(option) => statusTag(option.value)}
                      onChange={(value) => {
                        setStatusFilter(value);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedUsers([]);
                      }}
                    />
                  </Form.Item>
    
                  <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                    <Button
                      htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={handleSearch}
                      className="admin-search-btn" loading={usersQuery.isFetching}
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
                className="admin-users-table-anchor"
                style={{ "--admin-users-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
              >
                <Table<UserPublic>
                  rowKey="id"
                  dataSource={users}
                  columns={columns}
                  loading={usersQuery.isFetching || rolesQuery.isLoading}
                  tableLayout="fixed"
                  pagination={{
                    current: pagination.current,
                    pageSize: pagination.pageSize,
                    total: Math.max(usersQuery.data?.total ?? 0, 1),
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100],
                    showTotal: () => `共 ${usersQuery.data?.total ?? 0} 条`,
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
                        description={t("未找到符合筛选条件的用户。")}
                      />
                    ),
                  }}
                />
              </div>
            ) : (
              <div className="admin-users-card-view">
                {(usersQuery.isLoading || usersQuery.isFetching) && allLoadedUsers.length === 0 ? (
                  <div className="admin-users-card-view-state">
                    <Spin />
                  </div>
                ) : allLoadedUsers.length === 0 ? (
                  <div className="admin-users-card-view-state">
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={t("未找到符合筛选条件的用户。")}
                    />
                  </div>
                ) : (
                  // 查询/加载期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新数据
                  <Spin spinning={usersQuery.isFetching}>
                    <div className="admin-users-card-view-content">
                      <Row gutter={[12, 12]}>
                        {allLoadedUsers.map((userItem) => (
                          <Col key={userItem.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                            {renderUserCard(userItem)}
                          </Col>
                        ))}
                      </Row>
                      {isLoadingMore && (
                        <div style={{ textAlign: "center", padding: "20px 0" }}>
                          <Spin />
                        </div>
                      )}
                      {allLoadedUsers.length >= (usersQuery.data?.total ?? 0) && allLoadedUsers.length > 0 && (
                        <div style={{ textAlign: "center", padding: "20px 0" }}>
                          <Typography.Text type="secondary">
                            已加载全部 {allLoadedUsers.length} 条数据
                          </Typography.Text>
                        </div>
                      )}
                    </div>
                  </Spin>
                )}
              </div>
            )}
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={t("新增用户")}
        open={createUserModalOpen}
        forceRender
        destroyOnHidden
        onCancel={closeCreateUserModal}
        onOk={() => createForm.submit()}
        okText={t("创建用户")}
        cancelText={t("取消")}
        confirmLoading={createUserMutation.isPending || createAvatarUploading}
      >
        <div style={{ textAlign: "center", marginBottom: 16 }}>
          <Avatar
            size={80}
            src={createAvatarPreview || undefined}
            style={{ backgroundColor: "var(--ant-color-primary)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 40 }}
          >
            {!createAvatarPreview ? "U" : undefined}
          </Avatar>
          <div style={{ marginTop: 8 }}>
            <Upload
              accept="image/png,image/jpeg,image/gif,image/webp"
              showUploadList={false}
              beforeUpload={(file) => {
                handleAvatarTempUpload(file, "create");
                return false;
              }}
            >
              <Button size="small" icon={<UploadOutlined />}>
                {t("上传 Logo")}
              </Button>
            </Upload>
            {selectedCreateAvatarFile && (
              <Typography.Text type="secondary" style={{ marginLeft: 8 }}>
                {selectedCreateAvatarFile.name}
              </Typography.Text>
            )}
            {createAvatarUploadProgress > 0 && createAvatarUploadProgress < 100 ? (
              <Progress percent={createAvatarUploadProgress} size="small" style={{ width: 200, marginTop: 8 }} />
            ) : null}
            {createAvatarUploadProgress >= 100 && createAvatarTempFileId && !createAvatarUploadError ? (
              <Typography.Text type="success" style={{ display: "block", marginTop: 8 }}>
                <CheckCircleOutlined /> 上传完成，可以提交创建
              </Typography.Text>
            ) : null}
            {createAvatarUploadError ? (
              <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                {createAvatarUploadError}
              </Typography.Text>
            ) : null}
          </div>
        </div>
        <Form<CreateUserValues>
          form={createForm}
          layout="vertical"
          onFinish={handleCreateUser}
          autoComplete="off"
        >
          <Form.Item
            label={t("用户 ID")}
            name="user_id"
            validateStatus={userIdValidationError ? "error" : ""}
            help={userIdValidationError}
            rules={[
              { required: true, message: t("请输入用户 ID") },
              { min: 3, message: t("用户 ID 至少 3 位") },
              { max: 64, message: t("用户 ID 不能超过 64 位") },
            ]}
          >
            <Input
              placeholder={t("例如 ck001")}
              onChange={(e) => handleUserIdChange(e.target.value, false)}
            />
          </Form.Item>

          <Form.Item
            label={t("用户名")}
            name="username"
            rules={[
              { required: true, message: t("请输入用户名") },
              { min: 3, message: t("用户名至少 3 位") },
              { max: 64, message: t("用户名不能超过 64 位") },
            ]}
          >
            <Input placeholder={t("请输入用户名")} />
          </Form.Item>

          <Form.Item
            label={t("初始密码")}
            name="password"
            rules={[
              { required: true, message: t("请输入初始密码") },
              { min: 8, message: t("密码至少 8 位") },
              { max: 128, message: t("密码不能超过 128 位") },
            ]}
          >
            <Input.Password placeholder={t("至少 8 位")} />
          </Form.Item>

          <Form.Item
            label={t("邮箱")}
            name="email"
            rules={[
              { type: "email", message: t("邮箱格式不正确") },
            ]}
          >
            <Input placeholder={t("请输入邮箱（可选）")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={editingUser ? `编辑用户：${editingUser.username}` : "编辑用户"}
        open={!!editingUser}
        destroyOnHidden
        onCancel={closeEditUserModal}
        onOk={() => editUserForm.submit()}
        okText={t("保存")}
        cancelText={t("取消")}
        confirmLoading={updateUserProfileMutation.isPending}
        okButtonProps={{ disabled: !!editUserIdValidationError }}
      >
        {editingUser && (
          <div style={{ textAlign: "center", marginBottom: 16 }}>
            <Avatar
              size={80}
              src={editingUser.avatar_url ? `${getApiBaseUrl()}${editingUser.avatar_url}?t=${encodeURIComponent(editingUser.updated_at ?? "")}` : undefined}
              style={{ backgroundColor: "var(--ant-color-primary)", display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 40 }}
            >
              {!editingUser.avatar_url ? editingUser.username.trim().charAt(0).toUpperCase() || "U" : undefined}
            </Avatar>
            <div style={{ marginTop: 8 }}>
              <input
                type="file"
                id="avatar-upload-input"
                accept="image/png,image/jpeg,image/gif,image/webp"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    handleAvatarTempUpload(file, "edit");
                  }
                  e.target.value = "";
                }}
              />
              <Button
                size="small"
                loading={uploadingAvatarUserId === editingUser.id}
                onClick={() => document.getElementById("avatar-upload-input")?.click()}
              >
                {t("上传头像")}
              </Button>
              {editAvatarUploadProgress > 0 && editAvatarUploadProgress < 100 ? (
                <Progress percent={editAvatarUploadProgress} size="small" style={{ width: 200, marginTop: 8 }} />
              ) : null}
              {editAvatarUploadProgress >= 100 && editAvatarTempFileId && !editAvatarUploadError ? (
                <Typography.Text type="success" style={{ display: "block", marginTop: 8 }}>
                  <CheckCircleOutlined /> 上传完成，头像已更新
                </Typography.Text>
              ) : null}
              {editAvatarUploadError ? (
                <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                  {editAvatarUploadError}
                </Typography.Text>
              ) : null}
            </div>
          </div>
        )}
        <Form<EditUserValues>
          form={editUserForm}
          layout="vertical"
          onFinish={handleSubmitEditUser}
          autoComplete="off"
        >
          <Form.Item
            label={t("用户 ID")}
            name="user_id"
            validateStatus={editUserIdValidationError ? "error" : ""}
            help={editUserIdValidationError}
            rules={[
              { required: true, message: t("请输入用户 ID") },
              { min: 3, message: t("用户 ID 至少 3 位") },
              { max: 64, message: t("用户 ID 不能超过 64 位") },
            ]}
          >
            <Input
              placeholder={t("请输入用户 ID")}
              onChange={(e) => handleUserIdChange(e.target.value, true)}
            />
          </Form.Item>
          <Form.Item
            label={t("用户名")}
            name="username"
            rules={[
              { required: true, message: t("请输入用户名") },
              { min: 3, message: t("用户名至少 3 位") },
              { max: 64, message: t("用户名不能超过 64 位") },
            ]}
          >
            <Input placeholder={t("请输入用户名")} />
          </Form.Item>
          <Form.Item
            label={t("邮箱")}
            name="email"
            rules={[
              { type: "email", message: t("邮箱格式不正确") },
            ]}
          >
            <Input placeholder={t("请输入邮箱")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={resetPasswordTarget ? `重置密码：${resetPasswordTarget.username}` : "重置密码"}
        open={!!resetPasswordTarget}
        destroyOnHidden
        onCancel={closeResetPasswordModal}
        onOk={() => resetPasswordForm.submit()}
        okText={t("确认重置")}
        cancelText={t("取消")}
        confirmLoading={
          !!resetPasswordTarget
          && resettingUserId === resetPasswordTarget.id
          && resetPasswordMutation.isPending
        }
      >
        <Form<ResetPasswordValues>
          form={resetPasswordForm}
          layout="vertical"
          onFinish={handleSubmitResetPassword}
          autoComplete="off"
        >
          <Form.Item
            label={t("新密码")}
            name="password"
            rules={[
              { required: true, message: t("请输入新密码") },
              { min: 8, message: t("新密码至少 8 位") },
              { max: 128, message: t("新密码不能超过 128 位") },
            ]}
          >
            <Input.Password placeholder={t("请输入新密码")} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={assigningRolesUser ? `分配角色：${assigningRolesUser.username}` : "分配角色"}
        open={!!assigningRolesUser}
        destroyOnHidden
        onCancel={closeAssignRolesModal}
        onOk={handleSubmitAssignRoles}
        okText={t("保存")}
        cancelText={t("取消")}
        confirmLoading={updateRolesMutation.isPending && savingUserId === assigningRolesUser?.id}
      >
        <Form<{ role_codes: string[] }>
          form={roleForm}
          layout="vertical"
          onFinish={(values) => {
            if (!assigningRolesUser) return;
            updateRolesMutation.mutate(
              { userId: assigningRolesUser.id, roleCodes: values.role_codes },
              {
                onSuccess: () => {
                  closeAssignRolesModal();
                },
              },
            );
          }}
          autoComplete="off"
        >
          <Form.Item
            label={t("角色")}
            name="role_codes"
            rules={[{ required: true, message: t("请至少选择一个角色") }]}
          >
            <Select
              mode="multiple"
              placeholder={t("请选择角色")}
              options={roleOptions.map((code) => ({ label: getRoleName(code), value: code }))}
              allowClear
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
