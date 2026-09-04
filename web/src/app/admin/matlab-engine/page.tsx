"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  App,
  Badge,
  Button,
  Card,
  Col,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Row,
  Select,
  Skeleton,
  Spin,
  Space,
  Tabs,
  Table,
  Tag,
  Tooltip,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
  type TableColumnsType,
} from "antd";
import {
  ClockCircleOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileTextOutlined,
  InboxOutlined,
  MoreOutlined,
  PlusOutlined,
  RocketOutlined,
  SearchOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import type { UploadFile } from "antd/es/upload";
import type { ComponentType, RefAttributes } from "react";

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { ApiError } from "@/lib/api";
import {
  createMatlabModule,
  deleteMatlabModule,
  deleteMatlabVersion,
  downloadMatlabPackage,
  fetchMatlabModuleVersions,
  fetchMatlabModules,
  syncMatlabVersion,
  updateMatlabModule,
  uploadMatlabRelease,
} from "@/lib/matlab-engine-api";
import type { MatlabModule, MatlabUploadPayload, MatlabVersion } from "@/types/matlab-engine";

type ModuleFormValues = {
  name: string;
  slug?: string;
  description?: string;
  worker_deploy_path?: string;
  required_files?: string;
};

const DEFAULT_MODULE_FORM_VALUES: ModuleFormValues = {
  name: "",
  slug: "",
  description: "",
  worker_deploy_path: "",
  required_files: "",
};

const DEFAULT_UPLOAD_FORM_VALUES: MatlabUploadPayload = {
  version_tag: "",
  changelog: "",
};

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const MATLAB_TABLE_MIN_SCROLL_Y = 180;
const MATLAB_TABLE_VIEWPORT_GAP = 40;
const MATLAB_TABLE_FALLBACK_RESERVE = 232;
const MATLAB_TABLE_EXTRA_HEIGHT = 14;

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
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hours = String(parsed.getHours()).padStart(2, "0");
  const minutes = String(parsed.getMinutes()).padStart(2, "0");
  const seconds = String(parsed.getSeconds()).padStart(2, "0");
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
}

export default function AdminMatlabEnginePage() {
  const { modal: modalApi } = App.useApp();
  const { user, initializing, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [form] = Form.useForm<ModuleFormValues>();
  const [uploadForm] = Form.useForm<MatlabUploadPayload>();

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  useToastFeedback({
    errorMessage: error,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const [moduleModalOpen, setModuleModalOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<MatlabModule | null>(null);
  const [detailModule, setDetailModule] = useState<MatlabModule | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("文件列表");
  const [previewFiles, setPreviewFiles] = useState<string[]>([]);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  // 版本筛选（仅关键词）
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  // 模块筛选（左侧栏）
  const [moduleKeywordInput, setModuleKeywordInput] = useState("");
  const [moduleKeyword, setModuleKeyword] = useState("");

  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(MATLAB_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedVersions, setAllLoadedVersions] = useState<MatlabVersion[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const containerRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);
  const [downloadingHash, setDownloadingHash] = useState<string | null>(null);
  const [syncingHash, setSyncingHash] = useState<string | null>(null);

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

  const canRead = hasPermission("line.read") || hasPermission("line.manage");
  const canManage = hasPermission("line.manage");

  // 切换模块时统一重置版本列表相关状态（卡片视图、分页）
  const selectModule = useCallback((slug: string | null) => {
    setSelectedSlug(slug);
    setCardViewPage(1);
    setAllLoadedVersions([]);
    setPagination((prev) => ({ ...prev, current: 1 }));
  }, []);

  const modulesQuery = useQuery({
    queryKey: ["admin.matlab.modules"],
    enabled: !!user && canRead,
    queryFn: async () => fetchMatlabModules(),
  });

  const modules = useMemo(() => modulesQuery.data ?? [], [modulesQuery.data]);
  // 当前生效的模块：优先用户显式选择，未选择时自动取第一个模块
  const effectiveSlug = selectedSlug ?? modules[0]?.slug ?? null;

  const versionsQuery = useQuery({
    queryKey: ["admin.matlab.versions", effectiveSlug],
    enabled: Boolean(user && canRead && effectiveSlug),
    queryFn: async () => {
      if (!effectiveSlug) return { slug: "", releases: [] };
      return fetchMatlabModuleVersions(effectiveSlug);
    },
  });

  const refreshCurrent = useCallback(async () => {
    await modulesQuery.refetch();
    if (effectiveSlug) {
      await versionsQuery.refetch();
    }
  }, [effectiveSlug, modulesQuery, versionsQuery]);

  useTopicSubscription(
    "admin.matlab-engine",
    useCallback(
      (event) => {
        if (!user || !canRead) return;
        const payload = event.payload as Record<string, unknown> | undefined;
        const slug = (payload?.slug as string | undefined) ?? null;
        if (slug === null || slug === effectiveSlug) {
          void refreshCurrent();
        } else {
          void modulesQuery.refetch();
        }

        if (event.name === "engine.sync_completed") {
          setSuccess("同步完成");
        }
        if (event.name === "engine.sync_failed") {
          setError((payload?.error as string | undefined) ?? "同步失败");
        }
        if (event.name === "engine.released") {
          setSuccess("上传成功");
        }
      },
      [canRead, effectiveSlug, modulesQuery, refreshCurrent, user],
    ),
  );

  const syncVersionMutation = useMutation({
    mutationFn: async (version: MatlabVersion) => {
      if (!effectiveSlug) return;
      await syncMatlabVersion(effectiveSlug, version.version_hash);
    },
    onSuccess: async () => {
      setSuccess("同步任务已提交，请等待 Worker 处理");
      if (effectiveSlug) {
        await queryClient.invalidateQueries({ queryKey: ["admin.matlab.versions", effectiveSlug] });
      }
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "同步失败");
    },
  });

  const deleteModuleMutation = useMutation({
    mutationFn: async (item: MatlabModule) => deleteMatlabModule(item.slug),
    onSuccess: async (_data, item) => {
      setSuccess("模块已删除");
      await modulesQuery.refetch();
      // 删除的正好是当前生效模块时，清空显式选择，回落到剩余模块中的第一个
      if (effectiveSlug === item.slug) {
        selectModule(null);
      }
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除失败");
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
    onSuccess: async ({ mode, module }) => {
      setSuccess(mode === "created" ? "模块已创建" : "模块已更新");
      setModuleModalOpen(false);
      setEditingModule(null);
      form.resetFields();
      await modulesQuery.refetch();
      if (mode === "created") {
        selectModule(module.slug);
      }
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
      setError(candidate instanceof Error ? candidate.message : "保存失败");
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (values: MatlabUploadPayload) => {
      const raw = fileList[0]?.originFileObj;
      if (!raw) {
        throw new ApiError("请先选择 ZIP 文件");
      }
      if (!effectiveSlug) {
        throw new ApiError("请先选择模块");
      }
      if (!values.version_tag?.trim()) {
        throw new ApiError("请输入版本号");
      }
      await uploadMatlabRelease(effectiveSlug, raw, {
        version_tag: values.version_tag.trim(),
        changelog: values.changelog?.trim() || "",
      });
    },
    onSuccess: async () => {
      setSuccess("上传成功");
      setUploadModalOpen(false);
      setFileList([]);
      uploadForm.resetFields();
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
      setError(candidate instanceof Error ? candidate.message : "上传失败");
    },
  });

  const deleteVersionMutation = useMutation({
    mutationFn: async (version: MatlabVersion) => {
      if (!effectiveSlug) return;
      await deleteMatlabVersion(effectiveSlug, version.version_hash);
    },
    onSuccess: async () => {
      setSuccess("版本已删除");
      await versionsQuery.refetch();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除版本失败");
    },
  });

  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const selectedModule = useMemo(
    () => modules.find((item) => item.slug === effectiveSlug) ?? null,
    [modules, effectiveSlug],
  );

  const filteredModules = useMemo(() => {
    const keyword = moduleKeyword.trim().toLowerCase();
    if (!keyword) return modules;
    return modules.filter((item) => {
      const text = `${item.name} ${item.slug} ${item.description ?? ""}`.toLowerCase();
      return text.includes(keyword);
    });
  }, [moduleKeyword, modules]);

  const releases = useMemo(() => versionsQuery.data?.releases ?? [], [versionsQuery.data]);
  const currentRelease = releases[0] ?? null;
  // 最近一次成功同步到 Worker 的版本（由后端在 engine.sync_completed 时标记）
  const activeRelease = useMemo(
    () => releases.find((item) => item.is_active) ?? null,
    [releases],
  );

  const allVersions = useMemo(() => {
    // 同一 hash 可能出现多条发布记录（历史回退后重新发布），按 hash 去重避免表格 rowKey 冲突。
    const items: MatlabVersion[] = [];
    const seen = new Set<string>();
    for (const item of releases) {
      if (seen.has(item.version_hash)) continue;
      seen.add(item.version_hash);
      items.push(item);
    }
    return items;
  }, [releases]);

  const filteredVersions = useMemo(() => {
    const keyword = searchKeyword.trim().toLowerCase();
    if (!keyword) return allVersions;
    return allVersions.filter((item) => {
      const text = `${item.version_tag ?? ""} ${item.version_hash} ${item.changelog ?? ""} ${item.uploaded_by_name ?? item.uploaded_by ?? ""}`.toLowerCase();
      return text.includes(keyword);
    });
  }, [allVersions, searchKeyword]);

  const pageVersions = useMemo(() => {
    const start = (paginationCurrent - 1) * paginationPageSize;
    return filteredVersions.slice(start, start + paginationPageSize);
  }, [filteredVersions, paginationCurrent, paginationPageSize]);

  useEffect(() => {
    if (viewMode !== "card" || versionsQuery.isLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedVersions(() => pageVersions);
      } else {
        setAllLoadedVersions((prev) => {
          if (pageVersions.length === 0) {
            return prev;
          }
          const existingHashes = new Set(prev.map((v) => v.version_hash));
          const newVersions = pageVersions.filter((v) => !existingHashes.has(v.version_hash));
          return [...prev, ...newVersions];
        });
      }
      setIsLoadingMore(() => false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [pageVersions, versionsQuery.isLoading, viewMode, cardViewPage]);

  useEffect(() => {
    if (viewMode !== "card") return;

    const scrollContainer = pageCardRef.current;
    if (!scrollContainer) return;

    const handleScroll = () => {
      if (isLoadingMore || versionsQuery.isLoading) return;

      const scrollTop = scrollContainer.scrollTop;
      const scrollHeight = scrollContainer.scrollHeight;
      const clientHeight = scrollContainer.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const loadedCount = allLoadedVersions.length;
        if (loadedCount < filteredVersions.length) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    scrollContainer.addEventListener("scroll", handleScroll);
    return () => scrollContainer.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, versionsQuery.isLoading, allLoadedVersions.length, filteredVersions.length]);

  const openPreview = (title: string, files: string[]) => {
    setPreviewTitle(title);
    setPreviewFiles(files);
    setPreviewOpen(true);
  };

  const openModuleDetail = useCallback((item: MatlabModule) => {
    setDetailModule(item);
    setDetailOpen(true);
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

  const getModuleMoreMenuItems = useCallback(
    (item: MatlabModule): MenuProps["items"] => [
      {
        key: "detail",
        label: "详情",
        icon: <EyeOutlined />,
        onClick: ({ domEvent }) => {
          domEvent.stopPropagation();
          openModuleDetail(item);
        },
      },
      ...(canManage
        ? [
            {
              key: "edit",
              label: "编辑",
              icon: <EditOutlined />,
              onClick: ({ domEvent }) => {
                domEvent.stopPropagation();
                openEditModule(item);
              },
            },
            {
              key: "delete",
              label: "删除",
              icon: <DeleteOutlined />,
              danger: true,
              onClick: ({ domEvent }) => {
                domEvent.stopPropagation();
                modalApi.confirm({
                  title: "删除模块",
                  content: `确认删除模块"${item.name}"吗？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => deleteModule(item),
                });
              },
            },
          ]
        : []),
    ],
    [canManage, deleteModule, modalApi, openEditModule, openModuleDetail],
  );

  const handleUpload = useCallback(async () => {
    const values = await uploadForm.validateFields();
    await uploadMutation.mutateAsync(values);
  }, [uploadForm, uploadMutation]);

  const handleSyncVersion = useCallback(
    async (version: MatlabVersion) => {
      if (!effectiveSlug) return;
      setSyncingHash(version.version_hash);
      try {
        await syncVersionMutation.mutateAsync(version);
      } finally {
        setSyncingHash(null);
      }
    },
    [effectiveSlug, syncVersionMutation],
  );

  const handleDownload = useCallback(
    async (version: MatlabVersion) => {
      if (!effectiveSlug) return;
      setDownloadingHash(version.version_hash);
      try {
        await downloadMatlabPackage(effectiveSlug, version.version_hash);
        setSuccess("下载开始");
      } catch (candidate) {
        setError(candidate instanceof Error ? candidate.message : "下载失败");
      } finally {
        setDownloadingHash(null);
      }
    },
    [effectiveSlug],
  );

  const handleQuery = useCallback(() => {
    // LP-545：关键词/分页都未变化时查询键不变，react-query 不会自动重新拉取；
    // 手动强制刷新，保证重复点击「查询」也会触发查询（如拉取新数据）。
    const keywordChanged = keywordInput.trim() !== searchKeyword.trim();
    const pageChanged = paginationCurrent !== 1;
    setSearchKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    setCardViewPage(1);
    setAllLoadedVersions([]);
    if (!keywordChanged && !pageChanged) {
      void queryClient.refetchQueries({ queryKey: ["admin.matlab.versions", effectiveSlug] });
    }
  }, [keywordInput, searchKeyword, paginationCurrent, queryClient, effectiveSlug]);

  const handleModuleSearch = useCallback(() => {
    setModuleKeyword(moduleKeywordInput);
  }, [moduleKeywordInput]);

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - MATLAB_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? MATLAB_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - MATLAB_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(MATLAB_TABLE_MIN_SCROLL_Y, nextHeight + MATLAB_TABLE_EXTRA_HEIGHT);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [paginationCurrent, paginationPageSize, pageVersions.length, versionsQuery.isFetching, updateTableScrollY]);

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
    <div className="admin-matlab-skeleton-menu">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="admin-matlab-skeleton-item"
          style={i % 3 === 0 ? {} : { paddingLeft: 20 }}
        >
          <Skeleton.Input active size="small" block style={{ width: `${50 + (i % 3) * 15}%` }} />
        </div>
      ))}
    </div>
  );

  const columns = useMemo<TableColumnsType<MatlabVersion>>(() => {
    const baseColumns: TableColumnsType<MatlabVersion> = [
      {
        title: "版本号",
        dataIndex: "version_tag",
        key: "version_tag",
        width: 150,
        render: (value: string) => <Typography.Text>{value || "-"}</Typography.Text>,
      },
      {
        title: "Worker 状态",
        key: "worker_status",
        width: 140,
        render: (_, record) => {
          if (record.is_active) {
            return (
              <Tooltip
                title={
                  record.deployed_at
                    ? `已部署到 Worker（${formatDateTime(record.deployed_at)}）`
                    : "已部署到 Worker"
                }
              >
                <Tag color="blue">Worker 已部署</Tag>
              </Tooltip>
            );
          }
          const isNewest = record === currentRelease;
          return (
            <Tooltip
              title={
                isNewest
                  ? "最新版本尚未生效；点击行内「生效」按钮部署到 Worker"
                  : "Worker 当前未部署该版本；点击行内「生效」按钮部署，带「Worker 已部署」标记的才是生效版本"
              }
            >
              <Tag>{isNewest ? "未生效" : "非当前"}</Tag>
            </Tooltip>
          );
        },
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
        width: 170,
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
        width: 100,
        render: (size: number) => formatSize(size),
      },
      {
        title: "文件数",
        dataIndex: "file_list",
        key: "file_count",
        width: 90,
        render: (list: string[] | undefined) => (list?.length ? `${list.length} 个` : "-"),
      },
    ];

    baseColumns.push({
      title: "操作",
      key: "actions",
      width: 240,
      fixed: "right",
      render: (_, record) => {
        const moreMenuItems: MenuProps["items"] = [
          ...(canManage
            ? [
                {
                  key: "delete",
                  label: "删除",
                  danger: true,
                  onClick: () => {
                    modalApi.confirm({
                      title: "删除版本",
                      content: `确认删除版本"${record.version_tag}"（${record.version_hash}）吗？删除后不可恢复。`,
                      okText: "删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                      onOk: () => deleteVersionMutation.mutateAsync(record),
                    });
                  },
                } as const,
              ]
            : []),
        ];

        return (
          <Space wrap>
            <Button
              size="small"
              onClick={() => openPreview(`版本文件列表 (${record.version_tag || record.version_hash})`, record.file_list || [])}
            >
              查看
            </Button>
            <Button
              size="small"
              loading={downloadingHash === record.version_hash}
              onClick={() => handleDownload(record)}
            >
              下载
            </Button>
            {canManage && (
              <Button
                size="small"
                type="primary"
                loading={syncingHash === record.version_hash}
                disabled={Boolean(record.is_active) || syncingHash === record.version_hash}
                onClick={() => handleSyncVersion(record)}
              >
                生效
              </Button>
            )}
            {moreMenuItems.length > 0 && (
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            )}
          </Space>
        );
      },
    });

    return baseColumns;
  }, [canManage, currentRelease, deleteVersionMutation, downloadingHash, handleDownload, handleSyncVersion, modalApi, syncingHash]);
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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问 MATLAB 引擎管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `line.read`）。</p>
        <Link
          href="/"
          className="inline-flex w-fit items-center justify-center rounded-md border border-[var(--gray-6)] bg-[var(--gray-a2)] px-4 py-2 text-sm font-medium text-[var(--gray-12)] transition hover:bg-[var(--gray-a3)]"
        >
          返回首页
        </Link>
      </main>
    );
  }

  const renderVersionCard = (item: MatlabVersion) => {
    const rowBusy = uploadMutation.isPending || deleteVersionMutation.isPending;

    const moreMenuItems: MenuProps["items"] = [
      ...(canManage
        ? [
            {
              key: "sync",
              label: "生效",
              icon: <RocketOutlined />,
              disabled: rowBusy || Boolean(item.is_active) || syncingHash === item.version_hash,
              onClick: (info) => {
                info.domEvent?.stopPropagation();
                handleSyncVersion(item);
              },
            } as const,
          ]
        : []),
      ...(canManage
        ? [
            {
              key: "delete",
              label: "删除",
              danger: true,
              onClick: (info) => {
                info.domEvent?.stopPropagation();
                modalApi.confirm({
                  title: "删除版本",
                  content: `确认删除版本"${item.version_tag}"（${item.version_hash}）吗？删除后不可恢复。`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => deleteVersionMutation.mutateAsync(item),
                });
              },
            } as const,
          ]
        : []),
    ];

    return (
      <Card
        key={item.version_hash}
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
              {item.is_active && (
                <>
                  <Badge status="success" />
                  <Typography.Text type="secondary" className="text-xs">Worker 已部署</Typography.Text>
                </>
              )}
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
            <div className="flex items-center gap-2">
              <FileTextOutlined className="text-xs text-gray-500" />
              <Typography.Text className="text-xs">文件数：{item.file_list?.length ?? 0}</Typography.Text>
            </div>
          </div>

          <div className="admin-matlab-version-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
            <div />
            <Space size="small" className="shrink-0">
              <Tooltip title="查看">
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
              <Tooltip title="下载">
                <Button
                  type="text"
                  size="small"
                  loading={downloadingHash === item.version_hash}
                  onClick={(event) => {
                    event.stopPropagation();
                    handleDownload(item);
                  }}
                >
                  下载
                </Button>
              </Tooltip>
              {moreMenuItems.length > 0 && (
                <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                  <Tooltip title="更多">
                    <Button
                      type="text"
                      size="small"
                      disabled={rowBusy}
                      icon={<MoreOutlined />}
                      onClick={(event) => event.stopPropagation()}
                    />
                  </Tooltip>
                </Dropdown>
              )}
            </Space>
          </div>
        </div>
      </Card>
    );
  };


  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="admin-matlab-tabs"
        tabBarExtraContent={
          <Space>
            {activeRelease && (
              <Tooltip
                title={
                  activeRelease.deployed_at
                    ? `部署时间：${formatDateTime(activeRelease.deployed_at)}`
                    : undefined
                }
              >
                <Typography.Text type="secondary" style={{ fontSize: 13 }}>
                  Worker 已部署：{activeRelease.version_tag || activeRelease.version_hash}
                </Typography.Text>
              </Tooltip>
            )}
            {canManage && (
              <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
                上传新包
              </Button>
            )}
          </Space>
        }
        items={[
          {
            key: "list",
            label: <span className="admin-matlab-tab-title">MATLAB 引擎管理</span>,
            closable: false,
            children: (
              <div className="admin-matlab-list-pane">
                {/* ===== Body Area: Two-column layout ===== */}
                <div ref={containerRef} className="admin-matlab-page-body">
                  {/* Module Sidebar */}
                  {!isMobile && (
                    <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
                      <AntCard
                        className="admin-matlab-tree-card"
                        style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
                        styles={{ body: { flex: 1, padding: 0 } }}
                        actions={canManage ? [
                          <Button
                            type="text"
                            key="add-module"
                            onClick={openCreateModule}
                            style={{ width: "100%", color: "var(--ant-color-primary)" }}
                          >
                            <PlusOutlined /> 新建模块
                          </Button>,
                        ] : undefined}
                      >
                        {modulesQuery.data && modulesQuery.data.length > 0 && (
                          <div className="admin-matlab-sider-search">
                            <Input
                              className="admin-matlab-search-input"
                              placeholder="搜索模块..."
                              prefix={<SearchOutlined />}
                              value={moduleKeywordInput}
                              onChange={(e) => setModuleKeywordInput(e.target.value)}
                              onPressEnter={handleModuleSearch}
                              allowClear
                            />
                          </div>
                        )}
                        {modulesQuery.isLoading ? (
                          skeletonMenu
                        ) : modulesQuery.data && modulesQuery.data.length > 0 ? (
                          <>
                            {moduleKeyword && (
                              <div className="admin-matlab-search-results-count">
                                {`找到 ${filteredModules.length} 个模块`}
                              </div>
                            )}
                            <div className="admin-matlab-sider-menu">
                              {filteredModules.map((item) => (
                                <div
                                  key={item.slug}
                                  className={`admin-matlab-module-item ${effectiveSlug === item.slug ? "admin-matlab-module-item--active" : ""}`}
                                  onClick={() => selectModule(item.slug)}
                                >
                                  <div className="admin-matlab-module-info">
                                    <div className="admin-matlab-module-name">{item.name}</div>
                                  </div>
                                  <Dropdown
                                    menu={{ items: getModuleMoreMenuItems(item) }}
                                    trigger={["click"]}
                                  >
                                    <span
                                        className="admin-matlab-module-item-more"
                                        role="button"
                                        onMouseDown={(e) => e.stopPropagation()}
                                        onDoubleClick={(e) => e.stopPropagation()}
                                        onClick={(e) => e.stopPropagation()}
                                      >
                                        <MoreOutlined />
                                      </span>
                                    </Dropdown>
                                </div>
                              ))}
                            </div>
                          </>
                        ) : (
                          <div className="admin-matlab-sider-empty">
                            <Empty description="暂无模块" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                          </div>
                        )}
                      </AntCard>
                    </div>
                  )}
                  {!isMobile && (
                    <div
                      className="admin-matlab-resize-handle"
                      onMouseDown={handleResizeStart}
                    >
                      <div className="admin-matlab-resize-handle-line" />
                    </div>
                  )}
                  {/* Right Panel: filter + table/card-view */}
                  <div
                    ref={isMobile ? pageCardRef : undefined}
                    className="admin-matlab-main"
                  >
                    <div className="admin-filter-bar">
                      <Form layout="inline">
                        {isMobile && (
                          <Form.Item label="模块" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                            <Select
                              value={effectiveSlug ?? undefined}
                              placeholder="请选择模块"
                              style={{ minWidth: 160 }}
                              options={modules.map((m) => ({ label: m.name, value: m.slug }))}
                              onChange={(value) => selectModule(value ?? null)}
                            />
                          </Form.Item>
                        )}
                        <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                          <Input
                            allowClear
                            placeholder="版本号 / Hash / 变更日志 / 发布人"
                            value={keywordInput}
                            onChange={(event) => setKeywordInput(event.target.value)}
                            onPressEnter={handleQuery}
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

                    {selectedModule && viewMode === "table" ? (
                      <div
                        ref={tableScrollAnchorRef}
                        className="admin-matlab-table-anchor"
                        style={{ "--admin-matlab-table-body-min-height": `${tableScrollY}px` } as React.CSSProperties}
                      >
                        <Table<MatlabVersion>
                          rowKey="version_hash"
                          dataSource={pageVersions}
                          columns={columns}
                          loading={versionsQuery.isFetching}
                          tableLayout="fixed"
                          pagination={{
                            current: pagination.current,
                            pageSize: pagination.pageSize,
                            total: filteredVersions.length,
                            showSizeChanger: true,
                            pageSizeOptions: [10, 20, 50, 100],
                            showTotal: () => `共 ${filteredVersions.length} 条`,
                            hideOnSinglePage: false,
                            style: { marginBottom: 0 },
                            onChange: (page, pageSize) => {
                              setPagination({ current: page, pageSize });
                            },
                          }}
                          scroll={{ x: 1080, y: tableScrollY }}
                          locale={{
                            emptyText: (
                              <Empty
                                image={Empty.PRESENTED_IMAGE_SIMPLE}
                                description="未找到符合筛选条件的版本。"
                              />
                            ),
                          }}
                        />
                      </div>
                    ) : selectedModule ? (
                      <div className="admin-matlab-card-view">
                        {versionsQuery.isLoading && allLoadedVersions.length === 0 ? (
                          <div className="admin-matlab-card-view-state">
                            <Spin />
                          </div>
                        ) : allLoadedVersions.length === 0 ? (
                          <div className="admin-matlab-card-view-state">
                            <Empty
                              image={Empty.PRESENTED_IMAGE_SIMPLE}
                              description="未找到符合筛选条件的版本。"
                            />
                          </div>
                        ) : (
                          <div className="admin-matlab-card-view-content">
                            <Row gutter={[12, 12]}>
                              {allLoadedVersions.map((item) => (
                                <Col key={item.version_hash} xs={24} sm={24} md={12} lg={8} xl={6}>
                                  {renderVersionCard(item)}
                                </Col>
                              ))}
                            </Row>
                            {isLoadingMore && (
                              <div style={{ textAlign: "center", padding: "20px 0" }}>
                                <Spin />
                              </div>
                            )}
                            {allLoadedVersions.length >= filteredVersions.length && allLoadedVersions.length > 0 && (
                              <div style={{ textAlign: "center", padding: "20px 0" }}>
                                <Typography.Text type="secondary">
                                  已加载全部 {allLoadedVersions.length} 条数据
                                </Typography.Text>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="admin-matlab-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description={
                            modules.length === 0
                              ? "暂无模块，请先新建模块。"
                              : "请在左侧选择一个模块查看版本。"
                          }
                        />
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ),
          },
        ]}
      />

      {canManage && (
        <Modal
          title={editingModule ? `编辑模块：${editingModule.name}` : "新建模块"}
          open={moduleModalOpen}
          onCancel={closeModuleModal}
          onOk={() => saveModule()}
          confirmLoading={saveModuleMutation.isPending}
          okText={editingModule ? "保存" : "创建"}
          cancelText="取消"
          destroyOnHidden
          forceRender
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
      )}

      {canManage && (
        <Modal
          title="上传 MATLAB 引擎"
          open={uploadModalOpen}
          onCancel={() => {
            setUploadModalOpen(false);
            setFileList([]);
            uploadForm.resetFields();
          }}
          onOk={() => handleUpload()}
          okText="上传"
          cancelText="取消"
          confirmLoading={uploadMutation.isPending}
          destroyOnHidden
          forceRender
        >
          <Form<MatlabUploadPayload>
            form={uploadForm}
            layout="vertical"
            initialValues={DEFAULT_UPLOAD_FORM_VALUES}
            preserve={false}
          >
            <Row gutter={12}>
              <Col xs={24} md={12}>
                <Form.Item
                  label="版本号"
                  name="version_tag"
                  rules={[{ required: true, message: "请输入版本号" }]}
                >
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
              ZIP 包必须包含 {(selectedModule?.required_files || []).join(", ") || "必需文件"}，上传成功后即为已发布版本
            </p>
          </Upload.Dragger>
        </Modal>
      )}

      <Modal
        title={previewTitle}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={640}
        destroyOnHidden
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

      <Modal
        title={`模块详情：${detailModule?.name ?? ""}`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        footer={null}
        width={560}
        destroyOnHidden
      >
        {detailModule && (
          <Descriptions column={1} bordered size="small" styles={{ label: { width: 130 } }}>
            <Descriptions.Item label="标识">
              <Typography.Text code>{detailModule.slug}</Typography.Text>
            </Descriptions.Item>
            <Descriptions.Item label="描述">{detailModule.description || "-"}</Descriptions.Item>
            <Descriptions.Item label="Worker 部署路径">
              {detailModule.worker_deploy_path || "-"}
            </Descriptions.Item>
            <Descriptions.Item label="必需文件">
              {detailModule.required_files && detailModule.required_files.length > 0 ? (
                <Space size={[4, 4]} wrap>
                  {detailModule.required_files.map((file) => (
                    <Tag key={file} style={{ marginRight: 0 }}>{file}</Tag>
                  ))}
                </Space>
              ) : (
                "-"
              )}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">{formatDateTime(detailModule.created_at)}</Descriptions.Item>
            <Descriptions.Item label="更新时间">{formatDateTime(detailModule.updated_at)}</Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </div>
  );
}
