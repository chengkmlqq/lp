"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Breadcrumb,
  Card,
  Empty,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Table as AntTable,
  Typography,
  Upload,
  Progress,
  Dropdown,
  message as antdMessage,
  type CardProps,
  type MenuProps,
  type TableProps,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  FolderFilled,
  FolderOpenOutlined,
  EditOutlined,
  DragOutlined,
  FileOutlined,
  PlusOutlined,
  UploadOutlined,
  MoreOutlined,
} from "@ant-design/icons";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { Button } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type {
  FileEntryItem,
  FileListResponse,
  FileOperationResponse,
} from "@/types/auth";

function formatFileSize(size: number): string {
  if (size <= 0) {
    return "-";
  }
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const digits = unitIndex === 0 ? 0 : 2;
  return `${value.toFixed(digits)} ${units[unitIndex]}`;
}

function formatDate(value: string | null): string {
  if (!value) {
    return "-";
  }
  return new Date(value).toLocaleString();
}

function buildFilesApiPath(path: string): string {
  const params = new URLSearchParams();
  params.set("path", path || "/");
  return `/api/v1/admin/files?${params.toString()}`;
}

function readXhrError(xhr: XMLHttpRequest): string {
  const fallback = `HTTP ${xhr.status}`;
  const raw = xhr.responseText?.trim();
  if (!raw) {
    return fallback;
  }
  try {
    const parsed = JSON.parse(raw) as { detail?: string };
    return parsed.detail?.trim() ? parsed.detail : fallback;
  } catch {
    return raw.length > 200 ? fallback : raw;
  }
}

const FILES_TABLE_MIN_SCROLL_Y = 180;
const FILES_TABLE_VIEWPORT_GAP = 40;
const FILES_TABLE_FALLBACK_RESERVE = 220;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

export default function AdminFilesPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const [messageApi, messageContextHolder] = antdMessage.useMessage();
  const { modal } = App.useApp();
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken, refreshAccessToken } = useAuth();

  const [currentPath, setCurrentPath] = useState("/");
  const [createDirectoryModalOpen, setCreateDirectoryModalOpen] = useState(false);
  const [newDirectoryName, setNewDirectoryName] = useState("");
  const [errorMessage, setErrorMessage] = useState("");

  const pageDisplayName = t("文件管理");

  const [renameTarget, setRenameTarget] = useState<FileEntryItem | null>(null);
  const [renameName, setRenameName] = useState("");

  const [moveTarget, setMoveTarget] = useState<FileEntryItem | null>(null);
  const [moveTargetParentPath, setMoveTargetParentPath] = useState("/");
  const [moveNewName, setMoveNewName] = useState("");
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadFileName, setUploadFileName] = useState("");
  const [tableScrollY, setTableScrollY] = useState(FILES_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const canRead = hasPermission("file.read") || hasPermission("file.manage");
  const canManage = hasPermission("file.manage");

  const filesPath = useMemo(() => buildFilesApiPath(currentPath), [currentPath]);

  const filesQuery = useQuery({
    queryKey: [filesPath],
    queryFn: async () => {
      const response = await fetchWithAuth(filesPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileListResponse;
    },
    enabled: !!user && canRead,
  });

  const activeMountCode = filesQuery.data?.current_mount.code ?? "";

  const refreshCurrentPath = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: [filesPath] });
  }, [filesPath, queryClient]);

  const refreshAllFiles = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/admin/files?"),
    });
  }, [queryClient]);

  const closeCreateDirectoryModal = useCallback(() => {
    setCreateDirectoryModalOpen(false);
    setNewDirectoryName("");
  }, []);

  const closeRenameModal = useCallback(() => {
    setRenameTarget(null);
    setRenameName("");
  }, []);

  const closeMoveModal = useCallback(() => {
    setMoveTarget(null);
    setMoveTargetParentPath(currentPath || "/");
    setMoveNewName("");
  }, [currentPath]);

  const resetActionPanels = useCallback(() => {
    closeCreateDirectoryModal();
    closeRenameModal();
    closeMoveModal();
  }, [closeCreateDirectoryModal, closeMoveModal, closeRenameModal]);

  const applyMutationSuccess = useCallback(
    async (payload: FileOperationResponse, fallbackMessage: string) => {
      const nextMessage = payload.action ? `操作成功：${payload.action}` : fallbackMessage;
      setErrorMessage("");
      messageApi.success(nextMessage);
      resetActionPanels();
      await refreshAllFiles();
      await refreshCurrentPath();
    },
    [messageApi, refreshAllFiles, refreshCurrentPath, resetActionPanels],
  );

  useTopicSubscription(
    "admin.files",
    useCallback(() => {
      void refreshCurrentPath();
    }, [refreshCurrentPath]),
  );

  const createDirectoryMutation = useMutation({
    mutationFn: async () => {
      if (!activeMountCode) {
        throw new Error(t("当前无可用存储挂载"));
      }
      const response = await fetchWithAuth("/api/v1/admin/files/directories", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mount_code: activeMountCode,
          parent_path: filesQuery.data?.current_path ?? currentPath,
          name: newDirectoryName,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileOperationResponse;
    },
    onSuccess: async (payload) => {
      setNewDirectoryName("");
      setCreateDirectoryModalOpen(false);
      await applyMutationSuccess(payload, t("目录已创建"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("目录创建失败");
      setErrorMessage(message);
      messageApi.error(message);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (item: FileEntryItem) => {
      if (!activeMountCode) {
        throw new Error(t("当前无可用存储挂载"));
      }
      const response = await fetchWithAuth("/api/v1/admin/files/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mount_code: activeMountCode,
          path: item.path,
          is_dir: item.is_dir,
          recursive: item.is_dir,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileOperationResponse;
    },
    onSuccess: async (payload) => {
      await applyMutationSuccess(payload, t("路径已删除"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("删除失败");
      setErrorMessage(message);
      messageApi.error(message);
    },
  });

  const renameMutation = useMutation({
    mutationFn: async (item: FileEntryItem) => {
      if (!activeMountCode) {
        throw new Error(t("当前无可用存储挂载"));
      }
      const response = await fetchWithAuth("/api/v1/admin/files/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mount_code: activeMountCode,
          path: item.path,
          is_dir: item.is_dir,
          new_name: renameName,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileOperationResponse;
    },
    onSuccess: async (payload) => {
      await applyMutationSuccess(payload, t("重命名成功"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("重命名失败");
      setErrorMessage(message);
      messageApi.error(message);
    },
  });

  const moveMutation = useMutation({
    mutationFn: async (item: FileEntryItem) => {
      if (!activeMountCode) {
        throw new Error(t("当前无可用存储挂载"));
      }
      const response = await fetchWithAuth("/api/v1/admin/files/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mount_code: activeMountCode,
          path: item.path,
          is_dir: item.is_dir,
          target_parent_path: moveTargetParentPath,
          new_name: moveNewName.trim() ? moveNewName : undefined,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileOperationResponse;
    },
    onSuccess: async (payload) => {
      await applyMutationSuccess(payload, t("移动成功"));
    },
    onError: (error) => {
      const message = error instanceof Error ? error.message : t("移动失败");
      setErrorMessage(message);
      messageApi.error(message);
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!activeMountCode) {
        throw new Error(t("当前无可用存储挂载"));
      }
      setUploadProgress(0);
      setUploadFileName(file.name || t("未命名文件"));

      const params = new URLSearchParams({
        mount_code: activeMountCode,
        parent_path: filesQuery.data?.current_path ?? currentPath,
      });

      const uploadWithXhr = (token: string | null) =>
        new Promise<FileOperationResponse>((resolve, reject) => {
          const xhr = new XMLHttpRequest();
          xhr.open("POST", `${window.location.origin}/api/v1/admin/files/upload?${params.toString()}`);
          xhr.withCredentials = true;
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
                resolve(JSON.parse(xhr.responseText) as FileOperationResponse);
              } catch {
                reject(new Error(t("上传成功但响应解析失败")));
              }
              return;
            }
            reject(new Error(readXhrError(xhr)));
          };

          xhr.onerror = () => reject(new Error(t("网络异常，上传失败")));
          xhr.onabort = () => reject(new Error(t("上传已取消")));

          const formData = new FormData();
          formData.append("file", file);
          xhr.send(formData);
        });

      let payload: FileOperationResponse;
      try {
        payload = await uploadWithXhr(getAccessToken());
      } catch (error) {
        const message = error instanceof Error ? error.message : t("上传失败");
        const isUnauthorized = message.includes("401") || message.includes("未授权");
        if (!isUnauthorized) {
          throw error;
        }
        const refreshed = await refreshAccessToken();
        if (!refreshed) {
          throw error;
        }
        payload = await uploadWithXhr(getAccessToken());
      }
      return payload;
    },
    onSuccess: async (payload) => {
      await applyMutationSuccess(payload, t("上传成功"));
      setUploadFileName("");
      setUploadProgress(0);
    },
    onError: (error) => {
      setUploadProgress(0);
      const message = error instanceof Error ? error.message : t("上传失败");
      setErrorMessage(message);
      messageApi.error(message);
    },
  });

  const handleOpenDirectory = (item: FileEntryItem) => {
    if (!item.is_dir) {
      return;
    }
    setCurrentPath(item.path);
    setErrorMessage("");
    resetActionPanels();
  };

  const handleDelete = useCallback(
    (item: FileEntryItem) => {
      const content = item.is_dir
        ? `确认删除目录 ${item.name} 吗？将递归删除目录内全部内容。`
        : `确认删除文件 ${item.name} 吗？`;

      modal.confirm({
        title: t("删除确认"),
        content,
        okText: t("确认删除"),
        cancelText: t("取消"),
        okType: "danger",
        onOk: () => deleteMutation.mutateAsync(item),
      });
    },
    [deleteMutation, modal],
  );

  const startRename = (item: FileEntryItem) => {
    setRenameTarget(item);
    setRenameName(item.name);
    setErrorMessage("");
  };

  const startMove = (item: FileEntryItem) => {
    setMoveTarget(item);
    setMoveTargetParentPath(item.parent_path || currentPath || "/");
    setMoveNewName(item.name);
    setErrorMessage("");
  };

  const submitRename = () => {
    if (!renameTarget) {
      return;
    }
    if (!renameName.trim()) {
      setErrorMessage(t("新名称不能为空"));
      return;
    }
    void renameMutation.mutateAsync(renameTarget);
  };

  const submitMove = () => {
    if (!moveTarget) {
      return;
    }
    if (!moveTargetParentPath.trim()) {
      setErrorMessage(t("目标目录不能为空"));
      return;
    }
    void moveMutation.mutateAsync(moveTarget);
  };

  const submitCreateDirectory = () => {
    if (!newDirectoryName.trim()) {
      setErrorMessage(t("目录名称不能为空"));
      return;
    }
    void createDirectoryMutation.mutateAsync();
  };

  const handleUploadFile = useCallback(
    (file: File) => {
      setErrorMessage("");
      void uploadMutation.mutateAsync(file);
    },
    [uploadMutation],
  );

  const handleDownloadFile = async (item: FileEntryItem) => {
    if (!activeMountCode) {
      setErrorMessage(t("当前无可用存储挂载"));
      return;
    }

    try {
      const params = new URLSearchParams({
        mount_code: activeMountCode,
        path: item.path,
      });
      const response = await fetchWithAuth(`/api/v1/admin/files/download?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = item.name || "download";
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setErrorMessage("");
      messageApi.success(`下载已开始：${item.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : t("下载失败");
      setErrorMessage(message);
      messageApi.error(message);
    }
  };

  const handleDownloadDirectory = async (item: FileEntryItem) => {
    if (!activeMountCode) {
      setErrorMessage(t("当前无可用存储挂载"));
      return;
    }

    try {
      const params = new URLSearchParams({
        mount_code: activeMountCode,
        path: item.path,
      });
      const response = await fetchWithAuth(`/api/v1/admin/files/download-zip?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }

      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = `${item.name || "directory"}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(objectUrl);
      setErrorMessage("");
      messageApi.success(`目录下载已开始：${item.name}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : t("目录下载失败");
      setErrorMessage(message);
      messageApi.error(message);
    }
  };

  const listError = filesQuery.error instanceof Error ? filesQuery.error.message : "";

  useToastFeedback({
    errorMessage: errorMessage || listError,
    clearError: () => setErrorMessage(""),
  });
  const listData = filesQuery.data;
  const items = listData?.items ?? [];
  const operationBusy =
    createDirectoryMutation.isPending
    || deleteMutation.isPending
    || renameMutation.isPending
    || moveMutation.isPending
    || uploadMutation.isPending;

  const breadcrumbItems = useMemo(
    () =>
      (listData?.breadcrumbs ?? [{ name: t("根目录"), path: "/" }]).map((crumb) => ({
        title: (
          <Button
            type="text"
            color="gray"
            size="small"
            onClick={() => {
              setCurrentPath(crumb.path);
              resetActionPanels();
            }}
            className="px-1 !text-[var(--gray-12)] hover:!text-[var(--accent-11)]"
          >
            {crumb.name}
          </Button>
        ),
      })),
    [listData?.breadcrumbs, resetActionPanels],
  );

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
    const tableContent = anchor.querySelector<HTMLElement>(".ant-table-content");

    let nextHeight = Math.floor(window.innerHeight - anchorTop - FILES_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height
        ?? tableContent?.getBoundingClientRect().height
        ?? FILES_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - FILES_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(FILES_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    updateTableScrollY();
  }, [errorMessage, filesQuery.isFetching, items.length, listError, updateTableScrollY]);

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

  const columns: TableProps<FileEntryItem>["columns"] = [
      {
        title: t("名称"),
        dataIndex: "name",
        key: "name",
        render: (_value, item) => (
          <Space size={10}>
            {item.is_dir ? (
              <FolderFilled className="text-lg text-[var(--accent-11)]" />
            ) : (
              <FileOutlined className="text-base text-[var(--gray-10)]" />
            )}
            {item.is_dir ? (
              <Typography.Link
                onClick={() => handleOpenDirectory(item)}
                className="font-medium hover:text-[var(--accent-10)]"
              >
                {item.name}
              </Typography.Link>
            ) : (
              <Typography.Text className="font-medium">{item.name}</Typography.Text>
            )}
          </Space>
        ),
      },
      {
        title: t("类型"),
        key: "type",
        width: 180,
        render: (_value, item) => (
          <Typography.Text type="secondary" className="text-sm">
            {item.is_dir ? t("目录") : item.mime_type ?? t("文件")}
          </Typography.Text>
        ),
      },
      {
        title: t("大小"),
        key: "size",
        width: 140,
        render: (_value, item) => (
          <Typography.Text type="secondary" className="text-sm font-medium">
            {item.is_dir ? "-" : formatFileSize(item.size)}
          </Typography.Text>
        ),
      },
      {
        title: t("修改时间"),
        key: "modified_at",
        width: 220,
        render: (_value, item) => (
          <Typography.Text type="secondary" className="text-xs">
            {formatDate(item.modified_at)}
          </Typography.Text>
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        fixed: "right",
      width: 150,
        render: (_value, item) => {
          const menuItems: MenuProps["items"] = [
            {
              key: "move",
              label: t("移动"),
              icon: <DragOutlined />,
              disabled: operationBusy,
            },
            {
              type: "divider",
            },
            {
              key: "delete",
              label: t("删除"),
              icon: <DeleteOutlined />,
              danger: true,
              disabled: deleteMutation.isPending,
            },
          ];

          return (
            <Space wrap size="small">
              <Button
                type="button"
                color="gray"
                size="small"
                variant="soft"
                onClick={() => item.is_dir ? void handleDownloadDirectory(item) : void handleDownloadFile(item)}
                icon={<DownloadOutlined />}
              >
                下载
              </Button>

              {canManage && (
                <Button
                  type="button"
                  color="gray"
                  size="small"
                  variant="soft"
                  onClick={() => startRename(item)}
                  icon={<EditOutlined />}
                  disabled={operationBusy}
                >
                  重命名
                </Button>
              )}

              {canManage && (
                <Dropdown
                  menu={{
                    items: menuItems,
                    onClick: ({ key }) => {
                      if (key === "move") {
                        startMove(item);
                        return;
                      }
                      if (key === "delete") {
                        handleDelete(item);
                      }
                    },
                  }}
                  trigger={["click"]}
                >
                  <Button
                    type="button"
                    color="gray"
                    size="small"
                    variant="soft"
                    icon={<MoreOutlined />}
                  />
                </Dropdown>
              )}
            </Space>
          );
        },
      },
  ];

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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问{pageDisplayName}页面。</p>
        <Link href="/" className="inline-flex items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)] disabled:cursor-not-allowed disabled:opacity-60 w-fit">{t("返回首页")}</Link>
      </main>
    );
  }

  if (!canRead) {
    return (
      <main className="mx-auto flex min-h-screen w-full max-w-4xl flex-col justify-center gap-4 px-6 py-20">
        <p className="text-sm text-[var(--gray-11)]">{t("你没有访问该页面的权限（需要 `file.read`）。")}</p>
        <Link href="/" className="inline-flex items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)] disabled:cursor-not-allowed disabled:opacity-60 w-fit">{t("返回首页")}</Link>
      </main>
    );
  }

  return (
    <div className="space-y-5">
      {messageContextHolder}

      <AntCard
        title={
          <div className="flex items-center gap-2">
            <FolderFilled className="text-lg text-[var(--accent-11)]" />
            <span className="text-base font-semibold">{t("文件管理")}</span>
          </div>
        }
        extra={(
          <Space wrap size="small">

            {canManage && (
              <Upload
                showUploadList={false}
                maxCount={1}
                beforeUpload={(file) => {
                  handleUploadFile(file as File);
                  return false;
                }}
                disabled={uploadMutation.isPending || !activeMountCode}
              >
                <Button
                  type="button"
                  color="blue"
                  size="small"
                  variant="solid"
                  disabled={uploadMutation.isPending || !activeMountCode}
                  icon={<UploadOutlined />}
                >
                  {uploadMutation.isPending ? t("上传中...") : t("上传文件")}
                </Button>
              </Upload>
            )}
          </Space>
        )}
        styles={{
          header: {
            borderBottom: '1px solid var(--ant-color-border-secondary)',
            padding: '16px 20px'
          },
          body: { padding: '20px' }
        }}
      >
        <div className="space-y-4">
          {uploadMutation.isPending && (
            <div className="rounded-xl border border-[var(--accent-6)] bg-gradient-to-r from-[var(--accent-a2)] to-transparent p-4 shadow-sm">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <UploadOutlined className="text-[var(--accent-11)] flex-shrink-0" />
                  <Typography.Text
                    ellipsis={{ tooltip: uploadFileName || undefined }}
                    className="font-medium text-[var(--gray-12)]"
                  >
                    {uploadFileName || t("未命名文件")}
                  </Typography.Text>
                </div>
                <Typography.Text className="font-semibold text-[var(--accent-11)] flex-shrink-0">
                  {uploadProgress}%
                </Typography.Text>
              </div>
              <Progress
                percent={uploadProgress}
                size="small"
                showInfo={false}
                strokeColor="var(--accent-11)"
                trailColor="var(--accent-a3)"
              />
            </div>
          )}

          <div className="rounded-xl border border-[var(--gray-6)] bg-gradient-to-br from-[var(--gray-a2)] to-transparent px-4 py-3 shadow-sm [&_.ant-breadcrumb-link]:!text-[var(--gray-12)] [&_.ant-breadcrumb-separator]:!text-[var(--gray-10)]">
            <Breadcrumb items={breadcrumbItems} separator="/" />
          </div>

          <div
            ref={tableScrollAnchorRef}
            className="admin-files-table-anchor"
            style={{ "--admin-files-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <AntTable<FileEntryItem>
              rowKey={(item) => `${item.path}-${item.id}`}
              columns={columns}
              dataSource={items}
              pagination={{
                pageSize: 20,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: (total) => `共 ${total} 项`,
                hideOnSinglePage: true,
              }}
              loading={filesQuery.isLoading || filesQuery.isFetching}
              size="middle"
              scroll={{ x: 690, y: tableScrollY }}
              locale={{
                emptyText: (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={t("当前目录为空")}
                    className="py-12"
                  />
                ),
              }}
              className="[&_.ant-table]:rounded-lg [&_.ant-table-thead>tr>th]:bg-[var(--fquiz-theme-table-header-bg)] [&_.ant-table-thead>tr>th]:font-semibold [&_.ant-table-tbody>tr:hover>td]:bg-[var(--accent-a2)]"
            />
          </div>
        </div>
      </AntCard>

      <Modal
        title={t("新建目录")}
        open={createDirectoryModalOpen}
        onCancel={closeCreateDirectoryModal}
        onOk={submitCreateDirectory}
        okText={t("确认创建")}
        cancelText={t("取消")}
        confirmLoading={createDirectoryMutation.isPending}
        destroyOnHidden
        styles={{
          header: { paddingBottom: '12px', borderBottom: '1px solid var(--ant-color-border-secondary)' },
          body: { paddingTop: '20px' }
        }}
      >
        <Form layout="vertical">
          <Form.Item
            label={t("目录名称")}
            required
            validateStatus={newDirectoryName.trim() ? undefined : "error"}
            help={newDirectoryName.trim() ? undefined : t("目录名称不能为空")}
          >
            <Input
              value={newDirectoryName}
              onChange={(event) => setNewDirectoryName(event.currentTarget.value)}
              placeholder={t("请输入目录名称")}
              allowClear
              autoFocus
              size="large"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={renameTarget ? `${t("重命名")}：${renameTarget.name}` : t("重命名")}
        open={Boolean(renameTarget)}
        onCancel={closeRenameModal}
        onOk={submitRename}
        okText={t("确认重命名")}
        cancelText={t("取消")}
        confirmLoading={renameMutation.isPending}
        destroyOnHidden
        styles={{
          header: { paddingBottom: '12px', borderBottom: '1px solid var(--ant-color-border-secondary)' },
          body: { paddingTop: '20px' }
        }}
      >
        <Form layout="vertical">
          <Form.Item
            label={t("新名称")}
            required
            validateStatus={renameName.trim() ? undefined : "error"}
            help={renameName.trim() ? undefined : t("新名称不能为空")}
          >
            <Input
              value={renameName}
              onChange={(event) => setRenameName(event.currentTarget.value)}
              placeholder={t("请输入新名称")}
              autoFocus
              size="large"
            />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title={moveTarget ? `${t("移动")}：${moveTarget.name}` : t("移动")}
        open={Boolean(moveTarget)}
        onCancel={closeMoveModal}
        onOk={submitMove}
        okText={t("确认移动")}
        cancelText={t("取消")}
        confirmLoading={moveMutation.isPending}
        destroyOnHidden
        styles={{
          header: { paddingBottom: '12px', borderBottom: '1px solid var(--ant-color-border-secondary)' },
          body: { paddingTop: '20px' }
        }}
      >
        <Form layout="vertical">
          <Form.Item
            label={t("目标目录")}
            required
            validateStatus={moveTargetParentPath.trim() ? undefined : "error"}
            help={moveTargetParentPath.trim() ? undefined : t("目标目录不能为空")}
          >
            <Input
              value={moveTargetParentPath}
              onChange={(event) => setMoveTargetParentPath(event.currentTarget.value)}
              placeholder={t("目标目录（如 /a/b）")}
              autoFocus
              size="large"
            />
          </Form.Item>
          <Form.Item label={t("新名称（可选）")}>
            <Input
              value={moveNewName}
              onChange={(event) => setMoveNewName(event.currentTarget.value)}
              placeholder={t("留空则使用当前名称")}
              size="large"
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
