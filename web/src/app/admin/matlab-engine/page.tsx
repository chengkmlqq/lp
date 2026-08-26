"use client";

import {
  ClockCircleOutlined,
  CloudSyncOutlined,
  DeleteOutlined,
  DeploymentUnitOutlined,
  EditOutlined,
  InboxOutlined,
  MoreOutlined,
  PlusOutlined,
  RollbackOutlined,
  SearchOutlined,
  UploadOutlined,
  CodeOutlined,
  SwapOutlined,
  ApartmentOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Badge,
  Button,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Pagination,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  Upload,
  type MenuProps,
} from "antd";
import type { UploadFile } from "antd/es/upload";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { ApiError } from "@/lib/api";
import {
  createMatlabModule,
  deleteMatlabModule,
  fetchMatlabModuleVersions,
  fetchMatlabModules,
  publishMatlabDraft,
  rollbackMatlabVersion,
  syncMatlabModule,
  updateMatlabModule,
  uploadMatlabDraft,
} from "@/lib/matlab-engine-api";
import type { MatlabModule, MatlabVersion } from "@/types/matlab-engine";

type ModuleFormValues = {
  name: string;
  slug?: string;
  description?: string;
  worker_deploy_path?: string;
  required_files?: string;
};

type PublishFormValues = {
  version_tag: string;
  changelog?: string;
};

const DEFAULT_MODULE_FORM_VALUES: ModuleFormValues = {
  name: "",
  slug: "",
  description: "",
  worker_deploy_path: "",
  required_files: "",
};

const DEFAULT_PUBLISH_FORM_VALUES: PublishFormValues = {
  version_tag: "",
  changelog: "",
};

const TABLE_MIN_SCROLL_Y = 180;
const TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const TABLE_BOTTOM_GAP = 8;

function formatSize(bytes: number): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}

export default function AdminMatlabEnginePage() {
  const { message: messageApi } = App.useApp();
  const { user, initializing, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [form] = Form.useForm<ModuleFormValues>();
  const [publishForm] = Form.useForm<PublishFormValues>();

  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const [moduleModalOpen, setModuleModalOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<MatlabModule | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("文件列表");
  const [previewFiles, setPreviewFiles] = useState<string[]>([]);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const [moduleKeywordInput, setModuleKeywordInput] = useState("");
  const [moduleKeyword, setModuleKeyword] = useState("");
  const [versionKeywordInput, setVersionKeywordInput] = useState("");
  const [versionKeyword, setVersionKeyword] = useState("");
  const [versionStatus, setVersionStatus] = useState<"draft" | "released" | undefined>(undefined);
  const [modulePage, setModulePage] = useState(1);
  const [modulePageSize, setModulePageSize] = useState(12);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const isResizing = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const [viewMode, setViewMode] = useState<"table" | "card">(isMobile ? "card" : "table");

  const canManage = hasPermission("line.manage");
  const canRead = hasPermission("line.read") || canManage;

  const modulesQuery = useQuery({
    queryKey: ["admin.matlab.modules"],
    enabled: canRead,
    queryFn: async () => fetchMatlabModules(),
  });

  const versionsQuery = useQuery({
    queryKey: ["admin.matlab.versions", selectedSlug],
    enabled: Boolean(canRead && selectedSlug),
    queryFn: async () => {
      if (!selectedSlug) return { draft: null, releases: [] };
      return fetchMatlabModuleVersions(selectedSlug);
    },
  });

  const syncMutation = useMutation({
    mutationFn: async (slug: string) => syncMatlabModule(slug),
    onSuccess: (_data, slug) => {
      messageApi.success("同步任务已提交，请等待 Worker 处理");
      void queryClient.invalidateQueries({ queryKey: ["admin.matlab.versions", slug] });
    },
    onError: (candidate) => {
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "同步失败"));
    },
  });

  const deleteModuleMutation = useMutation({
    mutationFn: async (item: MatlabModule) => deleteMatlabModule(item.slug),
    onSuccess: async (_data, item) => {
      messageApi.success("模块已删除");
      await modulesQuery.refetch();
      if (selectedSlug === item.slug) {
        const remaining = modulesQuery.data?.filter((m) => m.slug !== item.slug) ?? [];
        setSelectedSlug(remaining[0]?.slug ?? null);
      }
    },
    onError: (candidate) => {
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "删除失败"));
    },
  });

  const saveModuleMutation = useMutation({
    mutationFn: async (values: ModuleFormValues) => {
      const payload = {
        name: values.name.trim(),
        slug: values.slug?.trim() || values.name.trim(),
        description: values.description?.trim() || "",
        worker_deploy_path: values.worker_deploy_path?.trim() || "",
        required_files: (values.required_files || "")
          .split(/[\n,，]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      };
      if (editingModule) {
        await updateMatlabModule(editingModule.slug, payload);
        return { mode: "updated" as const, module: editingModule };
      }
      const created = await createMatlabModule(payload);
      return { mode: "created" as const, module: created };
    },
    onSuccess: async ({ mode }) => {
      messageApi.success(mode === "created" ? "模块已创建" : "模块已更新");
      setModuleModalOpen(false);
      setEditingModule(null);
      form.resetFields();
      await modulesQuery.refetch();
    },
    onError: (candidate) => {
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "保存失败"));
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async () => {
      const raw = fileList[0]?.originFileObj;
      if (!raw) {
        throw new ApiError("请先选择 ZIP 文件");
      }
      if (!selectedSlug) {
        throw new ApiError("请先选择模块");
      }
      await uploadMatlabDraft(selectedSlug, raw);
    },
    onSuccess: async () => {
      messageApi.success("上传成功");
      setUploadModalOpen(false);
      setFileList([]);
      await versionsQuery.refetch();
    },
    onError: (candidate) => {
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "上传失败"));
    },
  });

  const publishMutation = useMutation({
    mutationFn: async (values: PublishFormValues) => {
      if (!selectedSlug || !draft) {
        throw new ApiError("当前没有草稿版本");
      }
      await publishMatlabDraft(selectedSlug, {
        version_tag: values.version_tag.trim(),
        changelog: values.changelog?.trim() || "",
      });
    },
    onSuccess: async () => {
      messageApi.success("发布成功");
      setPublishModalOpen(false);
      publishForm.resetFields();
      await versionsQuery.refetch();
    },
    onError: (candidate) => {
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "发布失败"));
    },
  });

  const rollbackMutation = useMutation({
    mutationFn: async (version: MatlabVersion) => {
      if (!selectedSlug) return;
      await rollbackMatlabVersion(selectedSlug, version.version_hash);
    },
    onSuccess: async () => {
      messageApi.success("已回退为新草稿，请重新发布");
      await versionsQuery.refetch();
    },
    onError: (candidate) => {
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "回退失败"));
    },
  });

  const refetchCurrent = useCallback(async () => {
    await modulesQuery.refetch();
    if (selectedSlug) {
      await versionsQuery.refetch();
    }
  }, [modulesQuery, selectedSlug, versionsQuery]);

  useTopicSubscription(
    "admin.matlab-engine",
    useCallback(
      (event) => {
        const payload = event.payload as Record<string, unknown> | undefined;
        const slug = (payload?.slug as string | undefined) ?? null;
        if (slug === null || slug === selectedSlug) {
          void refetchCurrent();
        } else {
          void modulesQuery.refetch();
        }

        if (event.name === "engine.sync_completed") {
          messageApi.success("同步完成");
        }
        if (event.name === "engine.sync_failed") {
          setApiError(new ApiError((payload?.error as string | undefined) ?? "同步失败"));
        }
        if (event.name === "engine.draft_uploaded") {
          messageApi.success("上传成功");
        }
        if (event.name === "engine.published") {
          messageApi.success("发布成功");
        }
        if (event.name === "engine.rollbacked") {
          messageApi.success("已回退");
        }
      },
      [messageApi, modulesQuery, refetchCurrent, selectedSlug],
    ),
  );

  const totalModules = modules.length;
  const modulePageSlice = useMemo(() => {
    const start = (paginationCurrent - 1) * paginationPageSize;
    return modules.slice(start, start + paginationPageSize);
  }, [paginationCurrent, paginationPageSize, modules]);

  const selectedModule = useMemo(
    () => modulesQuery.data?.find((item) => item.slug === selectedSlug) ?? null,
    [modulesQuery.data, selectedSlug],
  );

  const draft = versionsQuery.data?.draft ?? null;
  const releases = versionsQuery.data?.releases ?? [];
  const currentRelease = releases[0] ?? null;

  const allVersions = useMemo(() => {
    const items: MatlabVersion[] = [];
    if (draft) items.push(draft);
    items.push(...releases);
    return items;
  }, [draft, releases]);

  const filteredVersions = useMemo(() => {
    const keyword = versionKeyword.trim().toLowerCase();
    let result = allVersions;
    if (keyword) {
      result = result.filter((item) => {
        const text = `${item.version_tag ?? ""} ${item.version_hash} ${item.changelog ?? ""} ${item.uploaded_by_name ?? item.uploaded_by ?? ""}`.toLowerCase();
        return text.includes(keyword);
      });
    }
    if (versionStatus === "draft") {
      result = result.filter((item) => item === draft);
    }
    if (versionStatus === "released") {
      result = result.filter((item) => item !== draft);
    }
    return result;
  }, [allVersions, draft, versionKeyword, versionStatus]);

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

  const openCreateModule = useCallback(() => {
    setEditingModule(null);
    form.setFieldsValue(DEFAULT_MODULE_FORM_VALUES);
    setModuleModalOpen(true);
  }, [form]);

  const openEditModule = useCallback((item: MatlabModule) => {
    setEditingModule(item);
    form.setFieldsValue({
      name: item.name,
      slug: item.slug,
      description: item.description || "",
      worker_deploy_path: item.worker_deploy_path || "",
      required_files: (item.required_files || []).join("\n"),
    });
    setModuleModalOpen(true);
  }, [form]);

  const closeModuleModal = useCallback(() => {
    setModuleModalOpen(false);
    setEditingModule(null);
    form.resetFields();
  }, [form]);

  const saveModule = useCallback(async () => {
    const values = await form.validateFields();
    await saveModuleMutation.mutateAsync(values);
  }, [form, saveModuleMutation]);

  const deleteModule = useCallback(
    async (item: MatlabModule) => {
      await deleteModuleMutation.mutateAsync(item);
    },
    [deleteModuleMutation],
  );

  const handleUpload = useCallback(async () => {
    await uploadMutation.mutateAsync();
  }, [uploadMutation]);

  const handlePublish = useCallback(async () => {
    const values = await publishForm.validateFields();
    await publishMutation.mutateAsync(values);
  }, [publishForm, publishMutation]);

  const handleRollback = useCallback(
    async (version: MatlabVersion) => {
      if (!selectedSlug) return;
      await rollbackMutation.mutateAsync(version);
    },
    [rollbackMutation, selectedSlug],
  );

  const handleSync = useCallback(async () => {
    if (!selectedSlug) return;
    await syncMutation.mutateAsync(selectedSlug);
  }, [selectedSlug, syncMutation]);

  const handleVersionSearch = useCallback(() => {
    setVersionKeyword(versionKeywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, [versionKeywordInput]);

  const handleModuleSearch = useCallback(() => {
    setModuleKeyword(moduleKeywordInput);
  }, [moduleKeywordInput]);

  const handleVersionStatusChange = useCallback((value: "draft" | "released" | undefined) => {
    setVersionStatus(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") return TABLE_MIN_SCROLL_Y;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return TABLE_MIN_SCROLL_Y;
    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const pagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = pagination?.getBoundingClientRect().height ?? TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - TABLE_BOTTOM_GAP);
    return Math.max(TABLE_MIN_SCROLL_Y, nextHeight);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const frameId = window.requestAnimationFrame(() => {
      const nextHeight = updateTableScrollY();
      setTableScrollY((previous) => (Math.abs(previous - nextHeight) <= 1 ? previous : nextHeight));
    });
    return () => window.cancelAnimationFrame(frameId);
  }, [updateTableScrollY, viewMode, filteredVersions.length, versionsQuery.isFetching]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onViewportChange = () => {
      window.requestAnimationFrame(() => {
        const nextHeight = updateTableScrollY();
        setTableScrollY((previous) => (Math.abs(previous - nextHeight) <= 1 ? previous : nextHeight));
      });
    };
    window.addEventListener("resize", onViewportChange);
    return () => window.removeEventListener("resize", onViewportChange);
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(() => {
        const nextHeight = updateTableScrollY();
        setTableScrollY((previous) => (Math.abs(previous - nextHeight) <= 1 ? previous : nextHeight));
      });
    });
    resizeObserver.observe(anchor);
    return () => resizeObserver.disconnect();
  }, [updateTableScrollY]);

  useEffect(() => {
    if (modulesQuery.data?.length && !selectedSlug) {
      setSelectedSlug(modulesQuery.data[0].slug);
    }
  }, [modulesQuery.data, selectedSlug]);

  if (initializing) {
    return <AdminPageLoading tip="加载 MATLAB 程序管理..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <Card title="MATLAB 引擎管理">
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            {!user ? "请先登录后访问。" : "当前账号无权限（需要 line.read）。"}
          </Typography.Text>
        </Space>
      </Card>
    );
  }

  const openPreview = (title: string, files: string[]) => {
    setPreviewTitle(title);
    setPreviewFiles(files);
    setPreviewOpen(true);
  };

  const renderVersionCard = (item: MatlabVersion) => {
    const isDraft = item === draft;
    const statusConfig = isDraft ? { color: "warning", text: "草稿" } : { color: "success", text: "已发布" };
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "preview",
        label: "查看文件列表",
        onClick: () => openPreview(`版本文件列表 (${item.version_tag || item.version_hash})`, item.file_list || []),
      },
      ...(canManage && !isDraft
        ? [
            {
              key: "rollback",
              label: "回退",
              danger: true,
              onClick: () => {
                Modal.confirm({
                  title: "回退到此版本",
                  content: "此操作将把该历史版本复制为新的草稿，需要重新发布后才会同步到 Worker。",
                  okText: "回退",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => handleRollback(item),
                });
              },
            } as const,
          ]
        : []),
    ];

    return (
      <Card
        key={`${item.version_hash}-${isDraft ? "draft" : "release"}`}
        className="admin-matlab-version-card"
        size="small"
        hoverable
        onClick={() => openPreview(`版本文件列表 (${item.version_tag || item.version_hash})`, item.file_list || [])}
      >
        <div className="flex flex-col">
          <div className="admin-matlab-version-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <CodeOutlined className="text-base text-gray-500" />
            <Typography.Text strong className="truncate flex-1">{item.version_tag || "未命名版本"}</Typography.Text>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Badge status={statusConfig.color as "default" | "processing" | "success" | "error"} />
              <Typography.Text type="secondary" className="text-xs">{statusConfig.text}</Typography.Text>
            </div>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <SwapOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs">变更日志：{item.changelog || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <ClockCircleOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">发布时间：{formatDateTime(item.upload_time)}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <EditOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">发布人：{item.uploaded_by_name || item.uploaded_by || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <InboxOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">大小：{formatSize(item.size_bytes)}</Typography.Text>
            </div>
          </div>

          <div className="admin-matlab-version-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            {isDraft && canManage ? (
              <Button type="primary" size="small" onClick={(event) => { event.stopPropagation(); openPublishModal(); }}>
                发布
              </Button>
            ) : (
              <div />
            )}
            <Space size="small">
              <Tooltip title="查看文件列表">
                <Button
                  type="text"
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    openPreview(`版本文件列表 (${item.version_tag || item.version_hash})`, item.file_list || []);
                  }}
                />
              </Tooltip>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button
                  type="text"
                  size="small"
                  icon={<MoreOutlined />}
                  onClick={(event) => event.stopPropagation()}
                />
              </Dropdown>
            </Space>
          </div>
        </div>
      </Card>
    );
  };

  const columns = useMemo(
    () => [
      {
        title: "版本号",
        dataIndex: "version_tag",
        key: "version_tag",
        width: 140,
        render: (value: string, record: MatlabVersion) => {
          const isDraft = record === draft;
          const statusConfig = isDraft ? { color: "warning", text: "草稿" } : { color: "success", text: "已发布" };
          return (
            <Space size={6}>
              <Typography.Text>{value || "-"}</Typography.Text>
              <Badge status={statusConfig.color as "default" | "processing" | "success" | "error"} />
              <Typography.Text type="secondary" className="admin-matlab-version-status-text text-xs">{statusConfig.text}</Typography.Text>
            </Space>
          );
        },
      },
      {
        title: "Hash",
        dataIndex: "version_hash",
        key: "version_hash",
        width: 220,
        render: (hash: string) => <Typography.Text copyable={{ text: hash }}>{hash}</Typography.Text>,
      },
      {
        title: "变更日志",
        dataIndex: "changelog",
        key: "changelog",
        ellipsis: true,
        render: (text: string) => text || "-",
      },
      {
        title: "发布时间",
        dataIndex: "upload_time",
        key: "upload_time",
        width: 180,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "发布人",
        dataIndex: "uploaded_by_name",
        key: "uploaded_by_name",
        width: 120,
        render: (name: string, record: MatlabVersion) => name || record.uploaded_by || "-",
      },
      {
        title: "大小",
        dataIndex: "size_bytes",
        key: "size_bytes",
        width: 110,
        render: (size: number) => formatSize(size),
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right" as const,
        render: (_: unknown, record: MatlabVersion) => {
          const moreMenuItems: MenuProps["items"] = [
            ...(record === draft && canManage
              ? [
                  {
                    key: "publish",
                    label: "发布",
                    onClick: () => openPublishModal(),
                  },
                ]
              : []),
            {
              key: "preview",
              label: "查看文件列表",
              onClick: () => openPreview(`版本文件列表 (${record.version_tag || record.version_hash})`, record.file_list || []),
            },
            ...(canManage && record !== draft
              ? [
                  {
                    key: "rollback",
                    label: "回退",
                    danger: true,
                    onClick: () => {
                      Modal.confirm({
                        title: "回退到此版本",
                        content: "此操作将把该历史版本复制为新的草稿，需要重新发布后才会同步到 Worker。",
                        okText: "回退",
                        cancelText: "取消",
                        okButtonProps: { danger: true },
                        onOk: () => handleRollback(record),
                      });
                    },
                  },
                ]
              : []),
          ];

          return (
            <Space size={4}>
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            </Space>
          );
        },
      },
    ],
    [canManage, draft, handleRollback, openPublishModal],
  );

  const renderModuleCard = (item: MatlabModule) => {
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "edit",
        label: "编辑",
        icon: <EditOutlined />,
        onClick: () => openEditModule(item),
      },
      {
        key: "delete",
        label: "删除",
        icon: <DeleteOutlined />,
        danger: true,
        onClick: () => {
          Modal.confirm({
            title: `确认删除模块"${item.name}"吗？`,
            okText: "删除",
            cancelText: "取消",
            okButtonProps: { danger: true },
            onOk: () => deleteModule(item),
          });
        },
      },
    ];

    return (
      <Card
        key={item.slug}
        className="admin-matlab-module-card"
        size="small"
        hoverable
        onClick={() => setSelectedSlug(item.slug)}
      >
        <div className="flex flex-col">
          <div className="admin-matlab-module-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
            <DeploymentUnitOutlined className="text-base text-gray-500" />
            <Typography.Text strong className="truncate flex-1">{item.name}</Typography.Text>
            <Tag color="blue" className="flex-shrink-0 truncate max-w-[140px]">{item.slug}</Tag>
          </div>

          <div className="flex flex-col gap-2 px-4 py-3">
            <div className="flex items-center gap-2">
              <EditOutlined className="text-xs text-gray-500" />
              <Typography.Text type="secondary" className="text-xs">描述：{item.description || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <ApartmentOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">部署路径：{item.worker_deploy_path || "-"}</Typography.Text>
            </div>
            <div className="flex items-center gap-2">
              <InboxOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">必需文件：{(item.required_files || []).join(", ") || "-"}</Typography.Text>
            </div>
          </div>

          <div className="admin-matlab-module-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            <div />
            {canManage && (
              <Space size="small">
                <Tooltip title="编辑">
                  <Button
                    type="text"
                    size="small"
                    icon={<EditOutlined />}
                    onClick={(event) => {
                      event.stopPropagation();
                      openEditModule(item);
                    }}
                  />
                </Tooltip>
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    onClick={(event) => event.stopPropagation()}
                  />
                </Dropdown>
              </Space>
            )}
          </div>
        </div>
      </Card>
    );
  };

  // ---- Render left panel (module list) ----
  const renderLeftPanel = () => (
    <>
      <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
        <Card
          className="admin-matlab-tree-card"
          style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
          bodyStyle={{ flex: 1, padding: 0 }}
        >
          {canManage && (
            <div className="admin-matlab-sider-header">
              <div className="admin-matlab-sider-title">模块列表</div>
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreateModule}>
                新建模块
              </Button>
            </div>
          )}
          <div className="admin-matlab-sider-search">
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Input
                className="admin-matlab-search-input"
                placeholder="按模块名/标识/描述搜索"
                prefix={<SearchOutlined />}
                value={moduleKeywordInput}
                onChange={(e) => setModuleKeywordInput(e.target.value)}
                onPressEnter={handleModuleSearch}
                allowClear
              />
              <Button
                htmlType="button"
                icon={<SearchOutlined />}
                onClick={handleModuleSearch}
                block
                size="small"
              >
                搜索
              </Button>
            </Space>
          </div>
          <div className="admin-matlab-sider-menu">
            {modulesQuery.isLoading ? (
              <div className="admin-matlab-module-loading flex justify-center items-center py-12">
                <Spin tip="加载中..." />
              </div>
            ) : totalModules === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无模块数据" />
            ) : (
              <>
                {modulePageSlice.map((item) => (
                  <div
                    key={item.slug}
                    className={`admin-matlab-module-item ${selectedSlug === item.slug ? "admin-matlab-module-item--active" : ""}`}
                    onClick={() => setSelectedSlug(item.slug)}
                  >
                    <div className="admin-matlab-module-info">
                      <div className="admin-matlab-module-name">{item.name}</div>
                      <div className="admin-matlab-module-slug">{item.slug}</div>
                    </div>
                  </div>
                ))}
                <div className="admin-matlab-module-pagination">
                  <Pagination
                    current={modulePage}
                    pageSize={modulePageSize}
                    total={totalModules}
                    onChange={(page, pageSize) => {
                      setModulePage(page);
                      setModulePageSize(pageSize);
                    }}
                    showSizeChanger
                    showTotal={(total) => `共 ${total} 条`}
                  />
                </div>
              </>
            )}
          </div>
        </Card>
      </div>
      <div className="admin-matlab-resize-handle" onMouseDown={handleResizeStart}>
        <div className="admin-matlab-resize-handle-line" />
      </div>
    </>
  );

  // ---- Render right panel (version list) ----
  const renderRightPanel = () => {
    if (!selectedModule) {
      return (
        <div className="admin-matlab-main">
          <Card>
            <Typography.Text type="secondary">请在左侧选择一个模块查看详情。</Typography.Text>
          </Card>
        </div>
      );
    }

    return (
      <div className="admin-matlab-main">
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          {/* Title bar */}
          <div className="admin-matlab-header">
            <Space className="min-w-0" size={12}>
              <Typography.Text strong className="admin-matlab-header-title">
                {selectedModule.name}
              </Typography.Text>
              <Tag color="blue">{selectedModule.slug}</Tag>
            </Space>
            <Space size={8} wrap>
              <Button
                icon={<CloudSyncOutlined />}
                onClick={handleSync}
                loading={syncMutation.isPending}
                disabled={!canManage || syncMutation.isPending || !currentRelease}
              >
                同步到 Worker
              </Button>
              {canManage && (
                <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
                  上传新包
                </Button>
              )}
            </Space>
          </div>

          {/* Filter bar */}
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Input
                  allowClear
                  value={versionKeywordInput}
                  onChange={(event) => setVersionKeywordInput(event.currentTarget.value)}
                  placeholder="版本号 / Hash / 变更日志 / 发布人"
                  onPressEnter={() => handleVersionSearch()}
                />
              </Form.Item>
              <Form.Item label="状态" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                <Select<"draft" | "released">
                  value={versionStatus}
                  allowClear
                  placeholder="全部"
                  onChange={handleVersionStatusChange}
                  options={[
                    { value: "draft", label: "草稿" },
                    { value: "released", label: "已发布" },
                  ]}
                />
              </Form.Item>
              <Form.Item style={{ marginBottom: 0 }}>
                <Button
                  htmlType="button"
                  icon={<SearchOutlined />}
                  onClick={() => handleVersionSearch()}
                  className="admin-search-btn"
                >
                  查询
                </Button>
              </Form.Item>
            </Form>
            <Segmented
              value={viewMode}
              onChange={(value) => setViewMode(value as "table" | "card")}
              options={[
                { label: "卡片视图", value: "card" },
                { label: "列表视图", value: "table" },
              ]}
            />
          </div>

          {apiError && messageApi.error(apiError.message || "加载失败")}

          {viewMode === "table" ? (
            <div
              ref={tableScrollAnchorRef}
              className="admin-matlab-table-anchor"
              style={{ "--admin-matlab-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
            >
              <Table<MatlabVersion>
                rowKey="version_hash"
                dataSource={filteredVersions}
                columns={columns}
                loading={versionsQuery.isFetching}
                tableLayout="fixed"
                sticky
                scroll={{ y: tableScrollY }}
                locale={{
                  emptyText: (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无版本数据" />
                  ),
                }}
              />
            </div>
              ) : (
                <div className="admin-matlab-card-view">
                  {versionsQuery.isLoading && filteredVersions.length === 0 ? (
                    <div className="admin-matlab-card-view-state">
                      <Spin tip="加载中..." />
                    </div>
                  ) : filteredVersions.length === 0 ? (
                    <div className="admin-matlab-card-view-state">
                      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到符合筛选条件的版本。" />
                    </div>
                  ) : (
                    <>
                      <div className="admin-matlab-card-view-content">
                        <Row gutter={[12, 12]}>
                          {filteredVersions
                            .slice((pagination.current - 1) * pagination.pageSize, pagination.current * pagination.pageSize)
                            .map((item) => (
                              <Col
                                key={`${item.version_hash}-${item === draft ? "draft" : "release"}`}
                                xs={24}
                                sm={24}
                                md={12}
                                lg={8}
                                xl={6}
                              >
                                {renderVersionCard(item)}
                              </Col>
                            ))}
                        </Row>
                      </div>
                      <div className="admin-matlab-card-pagination">
                        <Pagination
                          current={pagination.current}
                          pageSize={pagination.pageSize}
                          total={filteredVersions.length}
                          onChange={(page, pageSize) => {
                            setPagination({ current: page, pageSize });
                          }}
                          showSizeChanger
                          showTotal={(total) => `共 ${total} 条`}
                        />
                      </div>
                    </>
                  )}
                </div>
              )}
        </Space>
      </div>
    );
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        defaultActiveKey="list"
        className="admin-matlab-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModule}>
              新建模块
            </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: <span className="admin-matlab-tab-title">MATLAB 引擎管理</span>,
            closable: false,
            children: (
              <div className="admin-matlab-list-pane">
                <div ref={containerRef} className="admin-matlab-page-body">
                  {!isMobile ? renderLeftPanel() : null}
                  {renderRightPanel()}
                </div>
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={editingModule ? `编辑模块：${editingModule.name}` : "新建模块"}
        open={moduleModalOpen}
        onCancel={closeModuleModal}
        onOk={() => saveModule()}
        confirmLoading={false}
        okText={editingModule ? "保存" : "创建"}
        cancelText="取消"
        destroyOnClose
        width={760}
      >
        <Form<ModuleFormValues>
          form={form}
          layout="vertical"
          initialValues={DEFAULT_MODULE_FORM_VALUES}
          preserve={false}
        >
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="模块名称" name="name" rules={[{ required: true, message: "请输入模块名称" }]}>
                <Input placeholder="模块显示名称" />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="标识" name="slug" rules={[{ required: true, message: "请输入模块标识" }]}>
                <Input placeholder="waveform_diagnosis" disabled={Boolean(editingModule)} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="描述" name="description">
                <Input.TextArea placeholder="模块用途说明" rows={2} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label="Worker 部署路径" name="worker_deploy_path">
                <Input placeholder="/opt/worker/matlab/{module}/" />
              </Form.Item>
            </Col>
            <Col xs={24} md={24}>
              <Form.Item label="必需文件" name="required_files">
                <Input.TextArea placeholder="每行一个文件名" rows={2} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title="上传 MATLAB 引擎"
        open={uploadModalOpen}
        onCancel={() => {
          setUploadModalOpen(false);
          setFileList([]);
        }}
        onOk={() => handleUpload()}
        okText="上传"
        cancelText="取消"
      >
        <Upload.Dragger
          accept=".zip"
          maxCount={1}
          fileList={fileList}
          beforeUpload={() => false}
          onChange={({ fileList: newFileList }) => setFileList(newFileList)}
        >
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽 ZIP 文件到此处</p>
          <p className="ant-upload-hint">
            ZIP 包必须包含 {(selectedModule?.required_files || []).join(", ") || "必需文件"}
          </p>
        </Upload.Dragger>
      </Modal>

      <Modal
        title="发布版本"
        open={publishModalOpen}
        onCancel={() => setPublishModalOpen(false)}
        onOk={() => handlePublish()}
        okText="发布"
        cancelText="取消"
        destroyOnClose
      >
        <Form<PublishFormValues>
          form={publishForm}
          layout="vertical"
          initialValues={DEFAULT_PUBLISH_FORM_VALUES}
          preserve={false}
        >
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label="版本号" name="version_tag" rules={[{ required: true, message: "请输入版本号" }]}>
                <Input placeholder="版本号，如 v1.0.0" />
              </Form.Item>
            </Col>
            <Col xs={24} md={24}>
              <Form.Item label="变更日志" name="changelog">
                <Input.TextArea placeholder="本次变更说明" rows={3} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal
        title={previewTitle}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={640}
      >
        {previewFiles.length === 0 ? (
          <Typography.Text type="secondary">无文件记录</Typography.Text>
        ) : (
          <List
            size="small"
            bordered
            dataSource={previewFiles}
            renderItem={(item) => (
              <List.Item>
                <Typography.Text code>{item}</Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  );
}