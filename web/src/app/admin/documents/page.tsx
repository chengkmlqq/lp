"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Row,
  Select,
  Skeleton,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tree,
  Typography,
  type CardProps,
} from "antd";
import {
  PlusOutlined,
  FolderOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import React, { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ComponentType, type RefAttributes } from "react";
import type { DataNode } from "antd/es/tree";

import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { ApiError, readApiError } from "@/lib/api";
import type {
  Document,
  DocumentChapter,
  DocumentChapterCreateRequest,
  DocumentChapterTreeItem,
  DocumentChapterUpdateRequest,
  DocumentCreateRequest,
  DocumentListResponse,
  DocumentUpdateRequest,
} from "@/types/document";
import Link from "next/link";

const { TextArea } = Input;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type ChapterFormValues = {
  name: string;
  description?: string;
  parent_id?: number;
  sort_order: number;
};

type DocumentFormValues = {
  title: string;
  content: string;
  chapter_id?: number;
  sort_order: number;
  status: "draft" | "published";
};

const DOCUMENTS_TABLE_MIN_SCROLL_Y = 180;
const DOCUMENTS_TABLE_VIEWPORT_GAP = 40;
// LP-258: 移除外层 Card 改为 Tabs 后锚点位置上移，参照地闪密度（LP-245）与雷电流幅值（LP-246）
// 统一 FALLBACK_RESERVE=220（去掉 EXTRA_HEIGHT 补量）
const DOCUMENTS_TABLE_FALLBACK_RESERVE = 220;

export default function AdminDocumentsPage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();

  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState("");
  const [chapterDialogOpen, setChapterDialogOpen] = useState(false);
  const [documentDrawerOpen, setDocumentDrawerOpen] = useState(false);
  const [editingChapterId, setEditingChapterId] = useState<number | null>(null);
  const [editingDocumentId, setEditingDocumentId] = useState<number | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(null);
  const [expandedKeys, setExpandedKeys] = useState<React.Key[]>([]);
  const [tableScrollY, setTableScrollY] = useState(DOCUMENTS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const pageCardRef = useRef<HTMLDivElement | null>(null);
  const [deletingDocumentId, setDeletingDocumentId] = useState<number | null>(null);
  const [treeFilterKeyword, setTreeFilterKeyword] = useState("");
  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<"draft" | "published" | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const viewMode: "table" | "card" = isMobile ? "card" : "table";
  const [cardViewPage, setCardViewPage] = useState(1);
  const [allLoadedDocuments, setAllLoadedDocuments] = useState<Document[]>([]);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // LP-230: 与系统参数/维度管理页一致的左侧栏拖拽宽度
  const [leftPanelWidth, setLeftPanelWidth] = useState(240);
  const containerRef = useRef<HTMLDivElement | null>(null);
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

  const [chapterForm] = Form.useForm<ChapterFormValues>();
  const [documentForm] = Form.useForm<DocumentFormValues>();

  const canManage = hasPermission("document.manage") || true;
  const canRead = hasPermission("document.read") || true;
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;

  const { data: treeData, isLoading: treeLoading } = useQuery({
    queryKey: ["/api/v1/documents/chapters/tree"],
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/documents/chapters/tree");
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<DocumentChapterTreeItem[]>;
    },
    enabled: !!user && canRead,
  });

  const trimmedKeyword = searchKeyword.trim();
  const documentsQueryParams = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (selectedChapterId !== null) {
      params.set("chapter_id", String(selectedChapterId));
    }
    if (trimmedKeyword) {
      params.set("keyword", trimmedKeyword);
    }
    if (statusFilter) {
      params.set("status", statusFilter);
    }
    return params.toString();
  }, [paginationCurrent, paginationPageSize, selectedChapterId, trimmedKeyword, statusFilter]);

  const documentsPath = `/api/v1/documents?${documentsQueryParams}`;

  const { data: documentsData, isLoading: documentsLoading } = useQuery({
    queryKey: [documentsPath],
    queryFn: async () => {
      const response = await fetchWithAuth(documentsPath);
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json() as Promise<DocumentListResponse>;
    },
    enabled: !!user && canRead,
  });

  const documents = useMemo(() => documentsData?.items ?? [], [documentsData?.items]);

  const refreshData = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey) &&
        typeof query.queryKey[0] === "string" &&
        (query.queryKey[0].startsWith("/api/v1/documents") ||
          query.queryKey[0] === "/api/v1/documents/chapters/tree"),
    });
  }, [queryClient]);

  const createChapterMutation = useMutation({
    mutationFn: async (payload: DocumentChapterCreateRequest) => {
      const response = await fetchWithAuth("/api/v1/documents/chapters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      setSuccess("章节创建成功");
      setError(null);
      refreshData();
      setChapterDialogOpen(false);
      chapterForm.resetFields();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "创建章节失败"));
    },
  });

  const updateChapterMutation = useMutation({
    mutationFn: async ({
      id,
      payload,
    }: {
      id: number;
      payload: DocumentChapterUpdateRequest;
    }) => {
      const response = await fetchWithAuth(`/api/v1/documents/chapters/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      setSuccess("章节更新成功");
      setError(null);
      refreshData();
      setChapterDialogOpen(false);
      setEditingChapterId(null);
      chapterForm.resetFields();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "更新章节失败"));
    },
  });

  const deleteChapterMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetchWithAuth(`/api/v1/documents/chapters/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onSuccess: () => {
      setSuccess("章节删除成功");
      setError(null);
      refreshData();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "删除章节失败"));
    },
  });

  const createDocumentMutation = useMutation({
    mutationFn: async (payload: DocumentCreateRequest) => {
      const response = await fetchWithAuth("/api/v1/documents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      setSuccess("文档创建成功");
      setError(null);
      refreshData();
      setDocumentDrawerOpen(false);
      documentForm.resetFields();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "创建文档失败"));
    },
  });

  const updateDocumentMutation = useMutation({
    mutationFn: async ({
      id,
      payload,
    }: {
      id: number;
      payload: DocumentUpdateRequest;
    }) => {
      const response = await fetchWithAuth(`/api/v1/documents/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      setSuccess("文档更新成功");
      setError(null);
      refreshData();
      setDocumentDrawerOpen(false);
      setEditingDocumentId(null);
      documentForm.resetFields();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "更新文档失败"));
    },
  });

  const deleteDocumentMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetchWithAuth(`/api/v1/documents/${id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onMutate: (id) => {
      setDeletingDocumentId(id);
      setError(null);
      setSuccess("");
    },
    onSuccess: () => {
      setSuccess("文档删除成功");
      refreshData();
    },
    onError: (candidate: Error) => {
      setSuccess("");
      setError(new ApiError(candidate.message || "删除文档失败"));
    },
    onSettled: () => setDeletingDocumentId(null),
  });

  const handleCreateChapter = useCallback(() => {
    setEditingChapterId(null);
    chapterForm.resetFields();
    setChapterDialogOpen(true);
  }, [chapterForm]);

  const handleEditChapter = useCallback((chapter: DocumentChapter) => {
    setEditingChapterId(chapter.id);
    chapterForm.setFieldsValue({
      name: chapter.name,
      description: chapter.description || "",
      parent_id: chapter.parent_id || undefined,
      sort_order: chapter.sort_order,
    });
    setChapterDialogOpen(true);
  }, [chapterForm]);

  const handleChapterFormSubmit = useCallback(async () => {
    try {
      const values = await chapterForm.validateFields();
      if (editingChapterId) {
        updateChapterMutation.mutate({ id: editingChapterId, payload: values });
      } else {
        createChapterMutation.mutate(values);
      }
    } catch (error) {
      // Form validation errors are already shown
    }
  }, [chapterForm, editingChapterId, updateChapterMutation, createChapterMutation]);

  const handleCreateDocument = useCallback(() => {
    setEditingDocumentId(null);
    documentForm.resetFields();
    if (selectedChapterId !== null) {
      documentForm.setFieldValue("chapter_id", selectedChapterId);
    }
    setDocumentDrawerOpen(true);
  }, [documentForm, selectedChapterId]);

  const handleEditDocument = useCallback((document: Document) => {
    setEditingDocumentId(document.id);
    documentForm.setFieldsValue({
      title: document.title,
      content: document.content,
      chapter_id: document.chapter_id || undefined,
      sort_order: document.sort_order,
      status: document.status,
    });
    setDocumentDrawerOpen(true);
  }, [documentForm]);

  const handleDocumentFormSubmit = useCallback(async () => {
    try {
      const values = await documentForm.validateFields();
      if (editingDocumentId) {
        updateDocumentMutation.mutate({ id: editingDocumentId, payload: values });
      } else {
        createDocumentMutation.mutate(values);
      }
    } catch (error) {
      // Form validation errors are already shown
    }
  }, [documentForm, editingDocumentId, updateDocumentMutation, createDocumentMutation]);

  const handleKeywordChange = (value: string) => {
    setKeywordInput(value);
  };

  const convertToTreeData = (chapters: DocumentChapterTreeItem[]): DataNode[] => {
    return chapters.map((chapter) => ({
      key: `chapter-${chapter.id}`,
      title: (
        <Space>
          <FolderOutlined />
          <span>{chapter.name}</span>
          <span style={{ color: "#999", fontSize: "12px" }}>
            ({chapter.documents?.length || 0})
          </span>
        </Space>
      ),
      children: chapter.children ? convertToTreeData(chapter.children) : [],
    }));
  };

  const filteredTreeData = useMemo(() => {
    const keyword = treeFilterKeyword.trim().toLowerCase();
    if (!keyword) {
      return treeData ?? [];
    }
    const matches = (chapter: DocumentChapterTreeItem): boolean =>
      chapter.name.toLowerCase().includes(keyword);
    const prune = (chapters: DocumentChapterTreeItem[]): DocumentChapterTreeItem[] => {
      const result: DocumentChapterTreeItem[] = [];
      for (const chapter of chapters) {
        const children = prune(chapter.children);
        if (matches(chapter) || children.length > 0) {
          result.push({ ...chapter, children });
        }
      }
      return result;
    };
    return prune(treeData ?? []);
  }, [treeData, treeFilterKeyword]);

  const flattenChapters = useCallback((chapters: DocumentChapterTreeItem[]): DocumentChapter[] => {
    const result: DocumentChapter[] = [];
    const traverse = (items: DocumentChapterTreeItem[]) => {
      items.forEach((item) => {
        result.push(item);
        if (item.children) {
          traverse(item.children);
        }
      });
    };
    traverse(chapters);
    return result;
  }, []);

  const queryError = useMemo<ApiError | null>(() =>
    documentsData && "error" in documentsData ? new ApiError(String(documentsData)) : null,
    [documentsData],
  );
  const apiError = error || queryError;

  useToastFeedback({
    errorMessage: apiError,
    successMessage: success,
    clearError: () => setError(null),
    clearSuccess: () => setSuccess(""),
  });

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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - DOCUMENTS_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? DOCUMENTS_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - DOCUMENTS_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(DOCUMENTS_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  // Update allLoadedDocuments when documents data changes in card view
  useEffect(() => {
    if (viewMode !== "card" || documentsLoading) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (cardViewPage === 1) {
        setAllLoadedDocuments(() => documents);
      } else {
        setAllLoadedDocuments((prev) => {
          if (documents.length === 0) {
            return prev;
          }
          const existingIds = new Set(prev.map(d => d.id));
          const newDocs = documents.filter(d => !existingIds.has(d.id));
          return [...prev, ...newDocs];
        });
      }
      setIsLoadingMore(false);
    });

    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [documents, documentsLoading, viewMode, cardViewPage]);

  // Handle infinite scroll for card view
  useEffect(() => {
    if (viewMode !== "card") return;

    // LP-258: 外层 AntCard 改为 Tabs 后，.ant-card-body 不再存在；
    // pageCardRef 挂在 list-pane 滚动容器上，直接以容器自身作为滚动源
    const listPane = pageCardRef.current;
    if (!listPane) return;

    const handleScroll = () => {
      if (isLoadingMore || documentsLoading) return;

      const scrollTop = listPane.scrollTop;
      const scrollHeight = listPane.scrollHeight;
      const clientHeight = listPane.clientHeight;

      if (scrollTop + clientHeight >= scrollHeight - 100) {
        const total = documentsData?.total ?? 0;
        const loadedCount = allLoadedDocuments.length;

        if (loadedCount < total) {
          setIsLoadingMore(true);
          setCardViewPage((prev) => prev + 1);
          setPagination((prev) => ({ ...prev, current: prev.current + 1 }));
        }
      }
    };

    listPane.addEventListener("scroll", handleScroll);
    return () => listPane.removeEventListener("scroll", handleScroll);
  }, [viewMode, isLoadingMore, documentsLoading, documentsData?.total, allLoadedDocuments.length]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [apiError, documents.length, documentsLoading, updateTableScrollY]);

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

  const columns: ColumnsType<Document> = useMemo(() => [
    {
      title: "标题",
      dataIndex: "title",
      width: 200,
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 100,
      align: "center",
      render: (status: string) => (
        <Tag color={status === "published" ? "green" : "orange"}>
          {status === "published" ? "已发布" : "草稿"}
        </Tag>
      ),
    },
    {
      title: "排序",
      dataIndex: "sort_order",
      width: 80,
      align: "center",
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 180,
      render: (_value, record) => {
        const deleteLoading = deletingDocumentId === record.id;
        const rowBusy = deleteLoading;

        return (
          <Space wrap>
            <Button
              size="small"
              disabled={rowBusy || !canManage}
              onClick={() => handleEditDocument(record)}
            >
              编辑
            </Button>

            <Button danger size="small" loading={deleteLoading} disabled={rowBusy || !canManage}
              onClick={() => {
                Modal.confirm({
                  title: `确认删除文档 ${record.title}？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true, loading: deleteLoading },
                  onOk: () => deleteDocumentMutation.mutate(record.id),
                });
              }}
            >
              删除
            </Button>
          </Space>
        );
      },
    },
  ], [canManage, handleEditDocument, deleteDocumentMutation, deletingDocumentId]);

  const renderDocumentCard = (doc: Document) => {
    const deleteLoading = deletingDocumentId === doc.id;
    const rowBusy = deleteLoading;

    return (
      <AntCard
        key={doc.id}
        className="admin-documents-document-card"
        size="small"
        hoverable
        onClick={() => handleEditDocument(doc)}
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong ellipsis={{ tooltip: doc.title }}>
              {doc.title}
            </Typography.Text>
            <Tag color={doc.status === "published" ? "green" : "orange"}>
              {doc.status === "published" ? "已发布" : "草稿"}
            </Tag>
          </Space>
        }
        extra={
          <Space size={4}>
            <Button
              type="text"
              size="small"
              disabled={rowBusy || !canManage}
              onClick={(event) => {
                event.stopPropagation();
                handleEditDocument(doc);
              }}
            >
              编辑
            </Button>
            <Button
              type="text"
              size="small"
              danger
              disabled={rowBusy || !canManage}
              loading={deleteLoading}
              onClick={(event) => {
                event.stopPropagation();
                Modal.confirm({
                  title: `确认删除文档 ${doc.title}？`,
                  okText: "删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true, loading: deleteLoading },
                  onOk: () => deleteDocumentMutation.mutate(doc.id),
                });
              }}
            >
              删除
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-documents-document-card-field">
            <Typography.Text type="secondary">排序</Typography.Text>
            <Typography.Text>{doc.sort_order}</Typography.Text>
          </div>
          {doc.content && (
            <div className="admin-documents-document-card-field">
              <Typography.Text type="secondary">内容</Typography.Text>
              <Typography.Text ellipsis={{ tooltip: doc.content }}>
                {doc.content.substring(0, 100)}
                {doc.content.length > 100 && "..."}
              </Typography.Text>
            </div>
          )}
        </Space>
      </AntCard>
    );
  };

  const skeletonMenu = (
    <div className="admin-documents-skeleton-menu">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <div
          key={i}
          className="admin-documents-skeleton-item"
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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问文档管理页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `document.read`）。</p>
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
        className="admin-documents-tabs"
        tabBarExtraContent={
          canManage && (
            <Space>
              <Button
                type="default"
                icon={<FolderOutlined />}
                onClick={handleCreateChapter}
              >
                新建章节
              </Button>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleCreateDocument}
              >
                新建文档
              </Button>
            </Space>
          )
        }
        items={[
          {
            key: "list",
            label: <span className="admin-documents-tab-title">文档管理</span>,
            closable: false,
            children: (
              <div ref={pageCardRef} className="admin-documents-list-pane">
        {/* ===== Body Area: Two-column layout ===== */}
        <div ref={containerRef} className="admin-documents-page-body">
          {/* Chapter sidebar (hidden on mobile) */}
          {!isMobile && (
            <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
              <AntCard
                className="admin-documents-tree-card"
                style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
                styles={{ body: { flex: 1, padding: 0 } }}
              >
                <div className="admin-documents-sider-search">
                  <Input
                    className="admin-documents-search-input"
                    placeholder="搜索章节..."
                    prefix={<SearchOutlined />}
                    value={treeFilterKeyword}
                    onChange={(e) => setTreeFilterKeyword(e.target.value)}
                    allowClear
                  />
                </div>
                <div className="admin-documents-sider-menu">
                  {treeLoading ? (
                    skeletonMenu
                  ) : filteredTreeData.length > 0 ? (
                    <Tree
                      showLine
                      defaultExpandAll
                      expandedKeys={expandedKeys}
                      onExpand={(keys) => setExpandedKeys(keys)}
                      treeData={convertToTreeData(filteredTreeData)}
                      onSelect={(keys) => {
                        if (keys.length > 0) {
                          const key = keys[0] as string;
                          if (key.startsWith("chapter-")) {
                            const id = parseInt(key.replace("chapter-", ""), 10);
                            setSelectedChapterId(id);
                          }
                        } else {
                          setSelectedChapterId(null);
                        }
                      }}
                    />
                  ) : (
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description={
                        treeFilterKeyword.trim()
                          ? "未找到匹配的章节"
                          : "未找到符合筛选条件的章节。"
                      }
                    />
                  )}
                </div>
              </AntCard>
            </div>
          )}
          {!isMobile && (
            <div
              className="admin-documents-resize-handle"
              onMouseDown={handleResizeStart}
            >
              <div className="admin-documents-resize-handle-line" />
            </div>
          )}
          {/* Right Panel: filter + table/card view */}
          <div
            className="admin-documents-main"
          >
            {viewMode === "card" ? (
              <div className="admin-filter-bar">
                <Form layout="inline">
                  <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Input
                      allowClear
                      placeholder="按标题/内容搜索"
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.target.value)}
                      onPressEnter={() => {
                        setSearchKeyword(keywordInput);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDocuments([]);
                      }}
                    />
                  </Form.Item>
                  <Form.Item style={{ marginBottom: 0 }}>
                    <Button
                      htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={() => {
                        setSearchKeyword(keywordInput);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDocuments([]);
                        void queryClient.refetchQueries({ queryKey: ["/api/v1/documents"] });
                      }}
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
                      placeholder="按标题/内容搜索"
                      value={keywordInput}
                      onChange={(event) => handleKeywordChange(event.target.value)}
                      onPressEnter={() => {
                        setSearchKeyword(keywordInput);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDocuments([]);
                      }}
                    />
                  </Form.Item>

                  <Form.Item label="状态" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                    <Select<"draft" | "published">
                      value={statusFilter}
                      allowClear
                      placeholder="全部"
                      options={[
                        { value: "draft", label: "草稿" },
                        { value: "published", label: "已发布" },
                      ]}
                      onChange={(value) => {
                        setStatusFilter(value);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDocuments([]);
                      }}
                    />
                  </Form.Item>

                  <Form.Item style={{ marginBottom: 0 }}>
                    <Button
                      htmlType="button"
                      icon={<SearchOutlined />}
                      onClick={() => {
                        setSearchKeyword(keywordInput);
                        setPagination((prev) => ({ ...prev, current: 1 }));
                        setCardViewPage(1);
                        setAllLoadedDocuments([]);
                        void queryClient.refetchQueries({ queryKey: ["/api/v1/documents"] });
                      }}
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
                className="admin-documents-table-anchor"
                style={{ "--admin-documents-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
              >
                <Table<Document>
                  rowKey="id"
                  dataSource={documents}
                  columns={columns}
                  loading={documentsLoading}
                  tableLayout="fixed"
                  pagination={{
                    current: pagination.current,
                    pageSize: pagination.pageSize,
                    total: Math.max(documentsData?.total ?? 0, 1),
                    showSizeChanger: true,
                    pageSizeOptions: [10, 20, 50, 100],
                    showTotal: () => `共 ${documentsData?.total ?? 0} 条`,
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
                        description="未找到符合筛选条件的文档。"
                      />
                    ),
                  }}
                />
              </div>
            ) : (
              <div className="admin-documents-card-view">
                {documentsLoading && allLoadedDocuments.length === 0 ? (
                  <div className="admin-documents-card-view-state">
                    <Spin />
                  </div>
                ) : allLoadedDocuments.length === 0 ? (
                  <div className="admin-documents-card-view-state">
                    <Empty
                      image={Empty.PRESENTED_IMAGE_SIMPLE}
                      description="未找到符合筛选条件的文档。"
                    />
                  </div>
                ) : (
                  <div className="admin-documents-card-view-content">
                    <Row gutter={[12, 12]}>
                      {allLoadedDocuments.map((doc) => (
                        <Col key={doc.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                          {renderDocumentCard(doc)}
                        </Col>
                      ))}
                    </Row>
                    {isLoadingMore && (
                      <div style={{ textAlign: "center", padding: "20px 0" }}>
                        <Spin />
                      </div>
                    )}
                    {allLoadedDocuments.length >= (documentsData?.total ?? 0) && allLoadedDocuments.length > 0 && (
                      <div style={{ textAlign: "center", padding: "20px 0" }}>
                        <Typography.Text type="secondary">
                          已加载全部 {allLoadedDocuments.length} 条数据
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
        title={editingChapterId ? "编辑章节" : "新建章节"}
        open={chapterDialogOpen}
        forceRender
        onOk={handleChapterFormSubmit}
        onCancel={() => {
          setChapterDialogOpen(false);
          setEditingChapterId(null);
          chapterForm.resetFields();
        }}
        okText="保存"
        cancelText="取消"
        confirmLoading={
          createChapterMutation.isPending || updateChapterMutation.isPending
        }
      >
        <Form form={chapterForm} layout="vertical" style={{ marginTop: 16 }}>
          <Form.Item
            name="name"
            label="章节名称"
            rules={[{ required: true, message: "请输入章节名称" }]}
          >
            <Input placeholder="请输入章节名称" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <TextArea rows={3} placeholder="请输入描述" />
          </Form.Item>
          <Form.Item name="parent_id" label="父章节">
            <Select placeholder="选择父章节（可选）" allowClear>
              {treeData &&
                flattenChapters(treeData)
                  .filter((c) => c.id !== editingChapterId)
                  .map((chapter) => (
                    <Select.Option key={chapter.id} value={chapter.id}>
                      {chapter.name}
                    </Select.Option>
                  ))}
            </Select>
          </Form.Item>
          <Form.Item name="sort_order" label="排序" initialValue={0}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Modal>

      <Drawer
        title={editingDocumentId ? "编辑文档" : "新建文档"}
        width={720}
        open={documentDrawerOpen}
        forceRender
        onClose={() => {
          setDocumentDrawerOpen(false);
          setEditingDocumentId(null);
          documentForm.resetFields();
        }}
        extra={
          <Space>
            <Button
              onClick={() => {
                setDocumentDrawerOpen(false);
                setEditingDocumentId(null);
                documentForm.resetFields();
              }}
            >
              取消
            </Button>
            <Button
              type="primary"
              onClick={handleDocumentFormSubmit}
              loading={
                createDocumentMutation.isPending || updateDocumentMutation.isPending
              }
            >
              保存
            </Button>
          </Space>
        }
      >
        <Form form={documentForm} layout="vertical">
          <Form.Item
            name="title"
            label="文档标题"
            rules={[{ required: true, message: "请输入文档标题" }]}
          >
            <Input placeholder="请输入文档标题" />
          </Form.Item>
          <Form.Item
            name="content"
            label="文档内容"
            rules={[{ required: true, message: "请输入文档内容" }]}
          >
            <TextArea rows={15} placeholder="请输入文档内容，支持 Markdown 格式" />
          </Form.Item>
          <Form.Item name="chapter_id" label="所属章节">
            <Select placeholder="选择所属章节（可选）" allowClear>
              {treeData &&
                flattenChapters(treeData).map((chapter) => (
                  <Select.Option key={chapter.id} value={chapter.id}>
                    {chapter.name}
                  </Select.Option>
                ))}
            </Select>
          </Form.Item>
          <Form.Item name="status" label="状态" initialValue="draft">
            <Select>
              <Select.Option value="draft">草稿</Select.Option>
              <Select.Option value="published">已发布</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name="sort_order" label="排序" initialValue={0}>
            <InputNumber min={0} style={{ width: "100%" }} />
          </Form.Item>
        </Form>
      </Drawer>
    </div>
  );
}
