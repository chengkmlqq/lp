"use client";

import {
  CloudSyncOutlined,
  EyeOutlined,
  InboxOutlined,
  MoreOutlined,
  EditOutlined,
  PlusOutlined,
  RollbackOutlined,
  SearchOutlined,
  UploadOutlined,
  DeleteOutlined,
} from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Dropdown,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Popconfirm,
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
import type { UploadFile } from "antd/es/upload";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
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

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

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
const TABLE_VIEWPORT_GAP = 40;
const TABLE_FALLBACK_RESERVE = 220;

function formatSize(bytes: number): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString();
}

export default function AdminMatlabEnginePage() {
  const { user, initializing, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [form] = Form.useForm<ModuleFormValues>();
  const [publishForm] = Form.useForm<PublishFormValues>();

  const [apiError, setApiError] = useState<ApiError | null>(null);
  const [successMessage, setSuccessMessage] = useState("");
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const [moduleModalOpen, setModuleModalOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<MatlabModule | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("文件列表");
  const [previewFiles, setPreviewFiles] = useState<string[]>([]);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  // Left panel: module keyword (real-time filter)
  const [moduleKeyword, setModuleKeyword] = useState("");
  // Right panel: version filter (keyword + status, applied on 查询)
  const [versionKeywordInput, setVersionKeywordInput] = useState("");
  const [versionKeyword, setVersionKeyword] = useState("");
  const [versionStatus, setVersionStatus] = useState<"draft" | "released" | undefined>(undefined);

  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const isResizing = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
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
    onMutate: () => {
      setApiError(null);
      setSuccessMessage("");
    },
    onSuccess: (_data, slug) => {
      setSuccessMessage("同步任务已提交，请等待 Worker 处理");
      void queryClient.invalidateQueries({ queryKey: ["admin.matlab.versions", slug] });
    },
    onError: (candidate) => {
      setSuccessMessage("");
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "同步失败"));
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
          setSuccessMessage("同步完成");
        }
        if (event.name === "engine.sync_failed") {
          setApiError(new ApiError((payload?.error as string | undefined) ?? "同步失败"));
        }
        if (event.name === "engine.draft_uploaded") {
          setSuccessMessage("上传成功");
        }
        if (event.name === "engine.published") {
          setSuccessMessage("发布成功");
        }
        if (event.name === "engine.rollbacked") {
          setSuccessMessage("已回退");
        }
      },
      [modulesQuery, refetchCurrent, selectedSlug],
    ),
  );

  useToastFeedback({
    errorMessage: apiError,
    successMessage,
    clearError: () => setApiError(null),
    clearSuccess: () => setSuccessMessage(""),
  });

  const modules = useMemo(() => {
    const keyword = moduleKeyword.trim().toLowerCase();
    const items = modulesQuery.data ?? [];
    if (!keyword) return items;
    return items.filter((item) => {
      const text = `${item.name} ${item.slug} ${item.description ?? ""}`.toLowerCase();
      return text.includes(keyword);
    });
  }, [modulesQuery.data, moduleKeyword]);

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
    try {
      const values = await form.validateFields();
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
        setSuccessMessage("模块已更新");
      } else {
        const created = await createMatlabModule(payload);
        setSelectedSlug(created.slug);
        setSuccessMessage("模块已创建");
      }
      closeModuleModal();
      void modulesQuery.refetch();
    } catch (candidate) {
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "保存失败"));
    }
  }, [closeModuleModal, editingModule, form, modulesQuery]);

  const deleteModule = useCallback(
    async (item: MatlabModule) => {
      try {
        await deleteMatlabModule(item.slug);
        setSuccessMessage("模块已删除");
        await modulesQuery.refetch();
        if (selectedSlug === item.slug) {
          const remaining = modulesQuery.data?.filter((m) => m.slug !== item.slug) ?? [];
          setSelectedSlug(remaining[0]?.slug ?? null);
        }
      } catch (candidate) {
        setApiError(new ApiError(candidate instanceof Error ? candidate.message : "删除失败"));
      }
    },
    [modulesQuery, selectedSlug],
  );

  const handleUpload = useCallback(async () => {
    const raw = fileList[0]?.originFileObj;
    if (!raw) {
      setApiError(new ApiError("请先选择 ZIP 文件"));
      return;
    }
    if (!selectedSlug) {
      setApiError(new ApiError("请先选择模块"));
      return;
    }
    try {
      await uploadMatlabDraft(selectedSlug, raw);
      setSuccessMessage("上传成功");
      setUploadModalOpen(false);
      setFileList([]);
      void versionsQuery.refetch();
    } catch (candidate) {
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "上传失败"));
    }
  }, [fileList, selectedSlug, versionsQuery]);

  const openPublishModal = useCallback(() => {
    publishForm.setFieldsValue(DEFAULT_PUBLISH_FORM_VALUES);
    setPublishModalOpen(true);
  }, [publishForm]);

  const handlePublish = useCallback(async () => {
    try {
      const values = await publishForm.validateFields();
      if (!selectedSlug || !draft) {
        setApiError(new ApiError("当前没有草稿版本"));
        return;
      }
      await publishMatlabDraft(selectedSlug, {
        version_tag: values.version_tag.trim(),
        changelog: values.changelog?.trim() || "",
      });
      setSuccessMessage("发布成功");
      setPublishModalOpen(false);
      publishForm.resetFields();
      void versionsQuery.refetch();
    } catch (candidate) {
      if (
        candidate
        && typeof candidate === "object"
        && "errorFields" in candidate
        && Array.isArray((candidate as { errorFields?: unknown }).errorFields)
      ) {
        return;
      }
      setApiError(new ApiError(candidate instanceof Error ? candidate.message : "发布失败"));
    }
  }, [draft, publishForm, selectedSlug, versionsQuery]);

  const handleRollback = useCallback(
    async (version: MatlabVersion) => {
      if (!selectedSlug) return;
      try {
        await rollbackMatlabVersion(selectedSlug, version.version_hash);
        setSuccessMessage("已回退为新草稿，请重新发布");
        void versionsQuery.refetch();
      } catch (candidate) {
        setApiError(new ApiError(candidate instanceof Error ? candidate.message : "回退失败"));
      }
    },
    [selectedSlug, versionsQuery],
  );

  const handleSync = useCallback(async () => {
    if (!selectedSlug) return;
    try {
      await syncMutation.mutateAsync(selectedSlug);
    } catch {
      // toast handled by mutation onError
    }
  }, [selectedSlug, syncMutation]);

  const handleVersionSearch = useCallback(() => {
    setVersionKeyword(versionKeywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, [versionKeywordInput]);

  const handleVersionStatusChange = useCallback((value: "draft" | "released" | undefined) => {
    setVersionStatus(value);
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const anchorTop = anchor.getBoundingClientRect().top;
    const tableWrapper = anchor.querySelector<HTMLElement>(".ant-table-wrapper");
    const tableBody = anchor.querySelector<HTMLElement>(".ant-table-body");
    let nextHeight = Math.floor(window.innerHeight - anchorTop - TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - TABLE_VIEWPORT_GAP);
    }
    const clampedHeight = Math.max(TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    window.requestAnimationFrame(updateTableScrollY);
  }, [filteredVersions.length, versionsQuery.isFetching, updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };
    window.addEventListener("resize", onViewportChange);
    return () => window.removeEventListener("resize", onViewportChange);
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") return;
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) return;
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
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
      <Card title="MATLAB 程序管理">
        <Typography.Text type="secondary">
          {!user ? "请先登录后访问。" : "当前账号无权限（需要 line.read）。"}
        </Typography.Text>
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
    const moreMenuItems: MenuProps["items"] = [
      {
        key: "preview",
        label: isDraft ? "查看文件列表" : "查看文件",
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
      <AntCard
        key={`${item.version_hash}-${isDraft ? "draft" : "release"}`}
        className="admin-matlab-version-card"
        size="small"
        hoverable
        onClick={() => openPreview(`版本文件列表 (${item.version_tag || item.version_hash})`, item.file_list || [])}
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong>{item.version_tag || "未命名版本"}</Typography.Text>
            <Tag color={isDraft ? "warning" : "success"}>{isDraft ? "草稿" : "已发布"}</Tag>
          </Space>
        }
        extra={
          <Space size={4}>
            {isDraft && canManage && (
              <Tooltip title="发布">
                <Button
                  type="primary"
                  size="small"
                  onClick={(event) => {
                    event.stopPropagation();
                    openPublishModal();
                  }}
                >
                  发布
                </Button>
              </Tooltip>
            )}
            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                onClick={(event) => event.stopPropagation()}
              />
            </Dropdown>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">Hash</Typography.Text>
            <Typography.Text copyable={{ text: item.version_hash }}>{item.version_hash}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">变更日志</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: item.changelog || "-" }}>{item.changelog || "-"}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">发布时间</Typography.Text>
            <Typography.Text>{formatDateTime(item.upload_time)}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">发布人</Typography.Text>
            <Typography.Text>{item.uploaded_by_name || item.uploaded_by || "-"}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">大小</Typography.Text>
            <Typography.Text>{formatSize(item.size_bytes)}</Typography.Text>
          </div>
        </Space>
      </AntCard>
    );
  };

  const columns = useMemo(
    () => [
      {
        title: "版本号",
        dataIndex: "version_tag",
        key: "version_tag",
        width: 140,
        render: (value: string, record: MatlabVersion) => (
          <Space size={6}>
            <Typography.Text>{value || "-"}</Typography.Text>
            {record === draft && <Tag color="warning">草稿</Tag>}
          </Space>
        ),
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
        width: 180,
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
            <Space wrap>
              <Tooltip title="查看文件">
                <Button
                  size="small"
                  icon={<EyeOutlined />}
                  onClick={() => openPreview(`版本文件列表 (${record.version_tag || record.version_hash})`, record.file_list || [])}
                />
              </Tooltip>
              {canManage && record !== draft && (
                <Tooltip title="回退">
                  <Popconfirm
                    title="回退到此版本"
                    description="此操作将把该历史版本复制为新的草稿，需要重新发布后才会同步到 Worker。"
                    onConfirm={() => handleRollback(record)}
                    okText="回退"
                    cancelText="取消"
                  >
                    <Button size="small" icon={<RollbackOutlined />} />
                  </Popconfirm>
                </Tooltip>
              )}
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
      <AntCard
        key={item.slug}
        className="admin-matlab-module-card"
        size="small"
        hoverable
        onClick={() => setSelectedSlug(item.slug)}
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong className="truncate">{item.name}</Typography.Text>
            <Tag color="blue" className="truncate">{item.slug}</Tag>
          </Space>
        }
        extra={
          canManage ? (
            <Space size={4}>
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
          ) : null
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">描述</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: item.description || "-" }}>{item.description || "-"}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">Worker 部署路径</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: item.worker_deploy_path || "-" }}>{item.worker_deploy_path || "-"}</Typography.Text>
          </div>
          <div className="admin-matlab-version-field">
            <Typography.Text type="secondary">必需文件</Typography.Text>
            <Typography.Text ellipsis={{ tooltip: (item.required_files || []).join(", ") || "-" }}>{(item.required_files || []).join(", ") || "-"}</Typography.Text>
          </div>
        </Space>
      </AntCard>
    );
  };

  // ---- Render left panel (module list) ----
  const renderLeftPanel = () => (
    <>
      <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
        <AntCard
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
            <Input
              className="admin-matlab-search-input"
              placeholder="按模块名/标识/描述筛选"
              prefix={<SearchOutlined />}
              value={moduleKeyword}
              onChange={(e) => setModuleKeyword(e.target.value)}
              allowClear
            />
          </div>
          <div className="admin-matlab-sider-menu">
            {modulesQuery.isLoading ? (
              <div className="admin-matlab-module-loading flex justify-center items-center py-12">
                <Spin tip="加载中..." />
              </div>
            ) : modules.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无模块数据" />
            ) : (
              modules.map((item) => (
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
              ))
            )}
          </div>
        </AntCard>
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

          {/* Filter bar (mirrors menus page) */}
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
          </div>

          {/* View toggle */}
          <div className="admin-matlab-view-bar">
            <Space size={8}>
              <Button
                size="small"
                type={viewMode === "table" ? "primary" : "default"}
                onClick={() => setViewMode("table")}
                disabled={viewMode === "table"}
              >
                表格
              </Button>
              <Button
                size="small"
                type={viewMode === "card" ? "primary" : "default"}
                onClick={() => setViewMode("card")}
                disabled={viewMode === "card"}
              >
                卡片
              </Button>
            </Space>
          </div>

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
                scroll={{ y: tableScrollY }}
                pagination={{
                  current: pagination.current,
                  pageSize: pagination.pageSize,
                  total: Math.max(filteredVersions.length, 1),
                  showSizeChanger: true,
                  pageSizeOptions: [10, 20, 50, 100],
                  showTotal: () => `共 ${filteredVersions.length} 条`,
                  hideOnSinglePage: false,
                  style: { marginBottom: 0 },
                  onChange: (page, pageSize) => {
                    setPagination({ current: page, pageSize });
                  },
                }}
                locale={{
                  emptyText: (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到符合筛选条件的版本。" />
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
                <div className="admin-matlab-card-view-content">
                  <Row gutter={[12, 12]}>
                    {filteredVersions.map((item) => (
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
            <Button type="primary" onClick={openCreateModule}>
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