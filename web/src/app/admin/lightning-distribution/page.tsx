"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
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
import { MoreOutlined, QuestionCircleOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type ComponentType, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode, type RefAttributes } from "react";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

import { useAuth } from "@/components/auth-provider";
import { TaskLogViewerModal } from "@/components/task-log-viewer";
import { TowerDensityView } from "@/components/lightning-tower-density-view";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  LightningDistributionImportResponse,
  LightningDistributionRecord,
  LightningDistributionListResponse,
  LightningDistributionStatusResponse,
  LightningLpDrawResponse,
  LightningLinkedLineSummary,
  LightningLinkedLinesResponse,
  LineSummary,
  LineListResponse,
} from "@/types/auth";
import { CHINESE_CITIES, type CityOption } from "@/data/chinese-cities";

type ImportFormValues = {
  event_year: number;
  region_id: string;
  city: string;
  notes: string;
  line_id: string | null;
};

const INITIAL_IMPORT_VALUES: ImportFormValues = {
  event_year: new Date().getFullYear(),
  region_id: "",
  city: "",
  notes: "",
  line_id: null,
};

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "处理中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
};

const LIGHTNING_TABLE_MIN_SCROLL_Y = 180;
const LIGHTNING_TABLE_VIEWPORT_GAP = 40;
const LIGHTNING_TABLE_FALLBACK_RESERVE = 220;

const FIELD_HELP_TOOLTIPS = {
  overallNg: "地闪密度：区域内单位面积、单位时间内的落雷次数，即有效落雷数 ÷（面积 km² × 统计年数），单位为 次/(km²·年)。数值越高表示该区域雷击活动越频繁。",
  maxCurrent: "区域内落雷电流绝对值的最大值（kA），反映该区域最强一次雷击的电流强度。",
  avgCurrent: "区域内落雷电流绝对值的平均值（kA），反映该区域雷击电流的总体强度水平。",
} as const;

function FieldHelpTooltip({ content }: { content: string }) {
  return (
    <Tooltip title={content}>
      <QuestionCircleOutlined style={{ color: "#999", fontSize: "12px", marginLeft: 4 }} />
    </Tooltip>
  );
}

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return "-";
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function truncateFileName(name: string, maxLength = 20): string {
  if (!name) {
    return "未命名";
  }
  return name.length > maxLength ? `${name.slice(0, maxLength)}…` : name;
}

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

export default function AdminLightningDistributionPage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [importForm] = Form.useForm<ImportFormValues>();

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [lpDrawRow, setLpDrawRow] = useState<LightningDistributionRecord | null>(null);
  const [linkedLinesRow, setLinkedLinesRow] = useState<LightningDistributionRecord | null>(null);
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeImportId, setActiveImportId] = useState<string | null>(null);
  const [tableScrollY, setTableScrollY] = useState(LIGHTNING_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  // ---- 任务日志弹窗 ----
  const [logModalOpen, setLogModalOpen] = useState(false);
  const [logModalTaskId, setLogModalTaskId] = useState<string | null>(null);
  const [logModalTitle, setLogModalTitle] = useState("任务执行日志");

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");
  const canReadLogs = hasPermission("celery.read") || hasPermission("celery.manage");

  const openLogViewer = (taskId: string | null | undefined, label: string, fileName: string) => {
    if (!taskId || !canReadLogs) {
      return;
    }
    setLogModalTaskId(taskId);
    setLogModalTitle(`${label} - ${fileName}`);
    setLogModalOpen(true);
  };

  // ---- 地闪分布列表 ----
  const trimmedKeyword = searchKeyword.trim();
  const distributionsPath = useMemo(() => {
    const params = new URLSearchParams();
    if (trimmedKeyword) params.set("keyword", trimmedKeyword);
    params.set("limit", "100");
    params.set("offset", "0");
    return `/api/v1/lightning-currents/distributions?${params.toString()}`;
  }, [trimmedKeyword]);

  const distributionsQuery = useQuery({
    queryKey: [distributionsPath],
    enabled: !!user && canRead,
    // 列表不再单点依赖 WebSocket：存在 pending/processing 记录时按 ~5s 轮询，
    // 保证 WS 断开/403 时进度也能推进到最终态；全部完成后停止轮询。
    refetchInterval: (query) => {
      const items = (query.state.data as LightningDistributionListResponse | undefined)?.items ?? [];
      const hasActive = items.some((row) => row.status === "pending" || row.status === "processing");
      return hasActive ? 5000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(distributionsPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionListResponse;
    },
  });

  const records = useMemo(() => distributionsQuery.data?.items ?? [], [distributionsQuery.data?.items]);
  const listError = distributionsQuery.error instanceof Error ? distributionsQuery.error.message : "";

  // ---- 导入任务进度轮询 ----
  const importStatusPath = activeImportId
    ? `/api/v1/lightning-currents/distributions/${activeImportId}/status`
    : null;
  const importStatusQuery = useQuery({
    queryKey: [importStatusPath],
    enabled: !!importStatusPath,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed") return false;
      return 5000;
    },
    queryFn: async () => {
      if (!importStatusPath) return null;
      const response = await fetchWithAuth(importStatusPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionStatusResponse;
    },
  });

  const activeRecord = importStatusQuery.data?.record ?? null;
  const activeStatus = importStatusQuery.data?.status;

  useToastFeedback({
    errorMessage: error || listError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  const refreshAll = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lightning-currents"),
    });
  }, [queryClient]);

  useTopicSubscription(
    "admin.lightning-distribution",
    useCallback((event) => {
      const name = event.name;
      const payload = event.payload as {
        distribution_id?: string;
        stage?: string;
        progress?: number;
        status?: string;
        error?: string;
      };
      if (name === "distribution.import_started") {
        if (payload?.distribution_id) setActiveImportId(payload.distribution_id);
        void refreshAll();
      } else if (name === "distribution.import_progress") {
        void refreshAll();
      } else if (name === "distribution.import_completed") {
        setActiveImportId(null);
        void refreshAll();
      } else if (name === "distribution.import_failed") {
        setActiveImportId(null);
        setError(payload?.error || "分布导入失败，请查看记录详情后重试");
        void refreshAll();
      } else if (name === "distribution.lp_draw_completed") {
        setError("");
        setSuccess("LP 分区密度图绘制完成，可在详情弹窗查看。");
        void refreshAll();
      } else if (name === "distribution.lp_draw_failed") {
        setError(payload?.error || "LP 分区密度图绘制失败");
        void refreshAll();
      }
    }, [refreshAll]),
  );

  // ---- 导入 ----
  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const values = importForm.getFieldsValue(true);
      const formData = new FormData();
      formData.append("file", file);
      formData.append("event_year", String(values.event_year));
      formData.append("region_id", values.region_id.trim());
      formData.append("city", values.city.trim());
      if (values.notes?.trim()) formData.append("notes", values.notes.trim());
      if (values.line_id) formData.append("line_id", values.line_id);

      const response = await fetchWithAuth("/api/v1/lightning-currents/import-distribution", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionImportResponse;
    },
    onSuccess: async (payload) => {
      setError("");
      setSuccess("分布导入已提交，正在后台解析统计…");
      setActiveImportId(payload.distribution_id);
      setImportModalOpen(false);
      importForm.resetFields();
      setSelectedFile(null);
      // 自动打开导入任务日志弹窗（有 celery 权限时）
      if (canReadLogs && payload.task_id) {
        const fileName = selectedFile?.name || "导入";
        setLogModalTaskId(payload.task_id);
        setLogModalTitle(`导入日志 - ${fileName}`);
        setLogModalOpen(true);
      }
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "分布导入失败");
    },
  });

  // 导入任务完成/失败时的反馈
  useEffect(() => {
    if (!activeImportId) return;
    if (activeStatus === "completed") {
      if (activeRecord) {
        setSuccess(
          `导入完成：有效 ${activeRecord.valid_count} 条，跳过 ${activeRecord.skipped_count} 条，`
          + `Ng=${formatNumber(activeRecord.overall_ng, 4)}，Imax=${formatNumber(activeRecord.max_abs_current, 2)}kA`,
        );
      } else {
        setSuccess("分布导入完成");
      }
      setActiveImportId(null);
    } else if (activeStatus === "failed") {
      setError(activeRecord?.error_message || "分布导入失败，请查看记录详情后重试");
      setActiveImportId(null);
    }
  }, [activeStatus, activeImportId, activeRecord]);

  // ---- 删除 ----
  const deleteMutation = useMutation({
    mutationFn: async (record: LightningDistributionRecord) => {
      if (!canManage) {
        throw new Error("缺少 lightning.manage 权限");
      }
      const response = await fetchWithAuth(
        `/api/v1/lightning-currents/distributions/${record.id}`,
        { method: "DELETE" },
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return response.json();
    },
    onSuccess: async (data: { success?: boolean }) => {
      if (data?.success === false) {
        setSuccess("");
        setError("删除失败：记录不存在");
        return;
      }
      setError("");
      setSuccess("分布记录已删除");
      await refreshAll();
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const openDetail = useCallback((record: LightningDistributionRecord) => {
    const key = record.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        return previous;
      }
      const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };
      return [
        ...previous,
        {
          key,
          label: (
            <Space size={6}>
              <span>{truncateFileName(record.source_file_name)}</span>
              <Tag color={meta.color}>{meta.label}</Tag>
            </Space>
          ),
          closable: true,
          children: (
            <DistributionDetailView
              record={record}
              fetchWithAuth={fetchWithAuth}
              canReadLogs={canReadLogs}
              onOpenLog={openLogViewer}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth, canReadLogs, openLogViewer]);

  // 打开「杆塔数据」Tab（key 前缀 `towers-<id>` 去重，避免重复点击叠加 Tab）
  const openTowerTab = useCallback((record: LightningDistributionRecord) => {
    const tabKey = `towers-${record.id}`;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === tabKey)) {
        return previous;
      }
      return [
        ...previous,
        {
          key: tabKey,
          label: (
            <Space size={6}>
              <span>杆塔数据</span>
              <Tag>{truncateFileName(record.source_file_name)}</Tag>
            </Space>
          ),
          closable: true,
          children: (
            <TowerDensityView
              distributionId={record.id}
              fetchWithAuth={fetchWithAuth}
            />
          ),
        },
      ];
    });
    setActiveTabKey(tabKey);
  }, [fetchWithAuth]);

  const handleTabsEdit = useCallback((targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey]);

  const openLpDrawModal = (record: LightningDistributionRecord) => {
    setLpDrawRow(record);
  };

  const openLinkedLinesModal = useCallback((record: LightningDistributionRecord) => {
    setLinkedLinesRow(record);
  }, []);

  const closeImportModal = () => {
    setImportModalOpen(false);
    importForm.resetFields();
    setSelectedFile(null);
  };

  const handleImportConfirm = async () => {
    try {
      await importForm.validateFields();
      if (selectedFile) {
        importMutation.mutate(selectedFile);
      }
    } catch {
      // 表单校验失败时不触发导入
    }
  };

  const handleSearch = () => {
    setSearchKeyword(keywordInput);
    void queryClient.refetchQueries({ queryKey: [distributionsPath] });
  };

  // ---- 表格高度自适应（参考用户管理页）----
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

    let nextHeight = Math.floor(window.innerHeight - anchorTop - LIGHTNING_TABLE_FALLBACK_RESERVE);
    if (tableWrapper) {
      const wrapperRect = tableWrapper.getBoundingClientRect();
      const bodyHeight = tableBody?.getBoundingClientRect().height ?? LIGHTNING_TABLE_MIN_SCROLL_Y;
      const nonBodyHeight = Math.max(0, wrapperRect.height - bodyHeight);
      const topGap = Math.max(0, wrapperRect.top - anchorTop);
      nextHeight = Math.floor(window.innerHeight - anchorTop - topGap - nonBodyHeight - LIGHTNING_TABLE_VIEWPORT_GAP);
    }

    const clampedHeight = Math.max(LIGHTNING_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [records.length, distributionsQuery.isFetching, updateTableScrollY]);

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

  // ---- 表格列 ----
  const columns = useMemo<ColumnsType<LightningDistributionRecord>>(
    () => [
      {
        title: "文件名",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string) => value || "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 160,
        render: (_: unknown, row) => {
          const meta = STATUS_META[row.status] ?? { color: "default", label: row.status };
          return (
            <Space size={6}>
              <Tag color={meta.color}>{meta.label}</Tag>
              {row.status === "processing" && (
                <Progress percent={row.progress} size="small" style={{ width: 80 }} />
              )}
            </Space>
          );
        },
      },
      {
        title: "有效点数",
        dataIndex: "valid_count",
        width: 90,
        render: (value: number) => value,
      },
      {
        title: (
          <span>
            整体Ng
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.overallNg} />
          </span>
        ),
        dataIndex: "overall_ng",
        width: 130,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: (
          <span style={{ whiteSpace: "nowrap" }}>
            最大电流(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.maxCurrent} />
          </span>
        ),
        dataIndex: "max_abs_current",
        width: 130,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: (
          <span style={{ whiteSpace: "nowrap" }}>
            平均电流(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.avgCurrent} />
          </span>
        ),
        dataIndex: "avg_abs_current",
        width: 130,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "关联线路",
        key: "linked_lines",
        width: 110,
        render: (_: unknown, row) => (
          <Button
            type="link"
            size="small"
            style={{ padding: 0 }}
            onClick={() => openLinkedLinesModal(row)}
          >
            {row.linked_line_count ?? 0} 条
          </Button>
        ),
      },
      {
        title: "操作",
        key: "actions",
        width: 200,
        fixed: "right",
        render: (_: unknown, row) => {
          const moreMenuItems: MenuProps["items"] = [
            {
              key: "tower-data",
              label: "杆塔数据",
              onClick: () => openTowerTab(row),
            },
            ...(canReadLogs && row.task_id
              ? [
                  {
                    key: "import-log",
                    label: "导入日志",
                    onClick: () => openLogViewer(row.task_id, "导入日志", row.source_file_name),
                  },
                ]
              : []),
            ...(canReadLogs && row.lp_draw_task_id
              ? [
                  {
                    key: "draw-log",
                    label: "绘图日志",
                    onClick: () => openLogViewer(row.lp_draw_task_id, "绘图日志", row.source_file_name),
                  },
                ]
              : []),
            ...(canManage
              ? [
                  {
                    key: "draw-lp",
                    label: "绘图",
                    onClick: () => openLpDrawModal(row),
                  },
                ]
              : []),
          ];

          return (
            <Space wrap>
              <Button size="small" onClick={() => openDetail(row)}>
                详情
              </Button>
              {canManage && (
                <Button
                  size="small"
                  danger
                  loading={deleteMutation.isPending}
                  onClick={() => {
                    Modal.confirm({
                      title: "确认删除该地闪分布记录？",
                      content: "将同时删除 MinIO 上的原始文件与密度图，此操作不可恢复。",
                      onOk: () => deleteMutation.mutate(row),
                      okText: "确认删除",
                      cancelText: "取消",
                      okButtonProps: { danger: true },
                    });
                  }}
                >
                  删除
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
      },
    ],
    [canManage, deleteMutation, openDetail, openTowerTab, openLinkedLinesModal, openLogViewer, canReadLogs],
  );

  const renderRecordCard = (record: LightningDistributionRecord) => {
    const dropdownItems: MenuProps["items"] = [
      {
        key: "image",
        label: "详情",
        onClick: () => openDetail(record),
      },
      ...(canReadLogs && record.task_id
        ? [
            {
              key: "import-log",
              label: "导入日志",
              onClick: () => openLogViewer(record.task_id, "导入日志", record.source_file_name),
            },
          ]
        : []),
      ...(canReadLogs && record.lp_draw_task_id
        ? [
            {
              key: "draw-log",
              label: "绘图日志",
              onClick: () => openLogViewer(record.lp_draw_task_id, "绘图日志", record.source_file_name),
            },
          ]
        : []),
      ...(canManage
        ? [
            {
              key: "draw-lp",
              label: "绘图",
              onClick: () => openLpDrawModal(record),
            },
            {
              key: "delete",
              label: "删除",
              danger: true as const,
              onClick: () => {
                Modal.confirm({
                  title: "确认删除",
                  content: "确认删除该地闪分布记录？此操作不可恢复。",
                  okText: "确认删除",
                  cancelText: "取消",
                  okButtonProps: { danger: true },
                  onOk: () => deleteMutation.mutate(record),
                });
              },
            },
          ]
        : []),
    ];

    const meta = STATUS_META[record.status] ?? { color: "default", label: record.status };

    return (
      <AntCard
        key={record.id}
        className="admin-lightning-distribution-batch-card"
        size="small"
        title={
          <Space className="min-w-0" size={8}>
            <Typography.Text strong>{record.source_file_name || "未命名文件"}</Typography.Text>
            <Tag color={meta.color}>{meta.label}</Tag>
          </Space>
        }
        extra={
          <Dropdown menu={{ items: dropdownItems }}>
            <Button type="text" size="small" icon={<MoreOutlined />} />
          </Dropdown>
        }
      >
        <Space direction="vertical" size={10} style={{ width: "100%" }}>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">城市</Typography.Text>
            <Typography.Text>{record.city || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">地点标签</Typography.Text>
            <Typography.Text>{record.location_tag || "-"}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">导入时间</Typography.Text>
            <Typography.Text>
              {formatDateTime(record.create_date)}
            </Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">有效点数</Typography.Text>
            <Typography.Text>{record.valid_count}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">
              整体 Ng
              <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.overallNg} />
            </Typography.Text>
            <Typography.Text>{formatNumber(record.overall_ng, 4)}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">
              最大电流
              <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.maxCurrent} />
            </Typography.Text>
            <Typography.Text>
              {formatNumber(record.max_abs_current, 2)} kA
            </Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">
              平均电流
              <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.avgCurrent} />
            </Typography.Text>
            <Typography.Text>
              {formatNumber(record.avg_abs_current, 2)} kA
            </Typography.Text>
          </div>
          {record.status === "processing" && (
            <Progress percent={record.progress} size="small" />
          )}
        </Space>
      </AntCard>
    );
  };

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
        <p className="text-sm text-[var(--gray-11)]">请先登录后再访问地闪密度统计页面。</p>
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
        <p className="text-sm text-[var(--gray-11)]">你没有访问该页面的权限（需要 `lightning.read`）。</p>
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
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="admin-lightning-distribution-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" onClick={() => setImportModalOpen(true)}>
              导入
            </Button>
          ) : null
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-lightning-distribution-tab-title">地闪密度统计</span>,
            closable: false,
            children: (
              <div className="admin-lightning-distribution-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label="关键词" className="admin-filter-keyword-item">
                      <Input
                        allowClear
                        placeholder="按地点/标签/文件名筛选"
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item>
                      <Button htmlType="button" icon={<SearchOutlined />} onClick={handleSearch} className="admin-search-btn">
                        查询
                      </Button>
                    </Form.Item>
                  </Form>
                </div>

                {isMobile ? (
                  <div className="admin-lightning-distribution-card-view">
                    {distributionsQuery.isLoading && records.length === 0 ? (
                      <div className="admin-lightning-distribution-card-view-state">
                        <Spin tip="加载中..." />
                      </div>
                    ) : records.length === 0 ? (
                      <div className="admin-lightning-distribution-card-view-state">
                        <Empty
                          image={Empty.PRESENTED_IMAGE_SIMPLE}
                          description="未找到符合筛选条件的地闪分布记录。"
                        />
                      </div>
                    ) : (
                      <div className="admin-lightning-distribution-card-view-content">
                        <Row gutter={[12, 12]}>
                          {records.map((record) => (
                            <Col key={record.id} xs={24} sm={24} md={12} lg={8} xl={6}>
                              {renderRecordCard(record)}
                            </Col>
                          ))}
                        </Row>
                      </div>
                    )}
                  </div>
                ) : (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-lightning-distribution-table-anchor"
                    style={{ "--admin-lightning-distribution-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<LightningDistributionRecord>
                      rowKey="id"
                      columns={columns}
                      dataSource={records}
                      loading={distributionsQuery.isFetching}
                      tableLayout="fixed"
                      pagination={{
                        pageSize: 20,
                        showSizeChanger: true,
                        pageSizeOptions: [10, 20, 50, 100],
                        showTotal: (total) => `共 ${records.length} 条`,
                      }}
                      scroll={{ x: 1000, y: tableScrollY }}
                      locale={{
                        emptyText: (
                          <Empty
                            image={Empty.PRESENTED_IMAGE_SIMPLE}
                            description="未找到符合筛选条件的地闪分布记录。"
                          />
                        ),
                      }}
                    />
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <ImportModal
        open={importModalOpen}
        onClose={closeImportModal}
        importForm={importForm}
        initialValues={INITIAL_IMPORT_VALUES}
        selectedFile={selectedFile}
        setSelectedFile={setSelectedFile}
        loading={importMutation.isPending}
        onConfirm={handleImportConfirm}
      />

      <LinkedLinesModal
        open={!!linkedLinesRow}
        data={linkedLinesRow}
        onClose={() => setLinkedLinesRow(null)}
        fetchWithAuth={fetchWithAuth}
      />

      {canManage && (
        <DrawLpModal
          open={!!lpDrawRow}
          data={lpDrawRow}
          onClose={() => setLpDrawRow(null)}
          fetchWithAuth={fetchWithAuth}
          onSubmitted={(taskId, fileName) => {
            if (canReadLogs && taskId) {
              setLogModalTaskId(taskId);
              setLogModalTitle(`绘图日志 - ${fileName}`);
              setLogModalOpen(true);
            }
          }}
        />
      )}

      <TaskLogViewerModal
        taskId={logModalTaskId}
        title={logModalTitle}
        open={logModalOpen}
        onClose={() => setLogModalOpen(false)}
      />
    </div>
  );
}

function ImportModal({
  open,
  onClose,
  importForm,
  initialValues,
  selectedFile,
  setSelectedFile,
  loading,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  importForm: ReturnType<typeof Form.useForm<ImportFormValues>>[0];
  initialValues: ImportFormValues;
  selectedFile: File | null;
  setSelectedFile: (file: File | null) => void;
  loading: boolean;
  onConfirm: () => void;
}) {
  const { fetchWithAuth } = useAuth();
  const [lineSearchText, setLineSearchText] = useState("");

  const linesQuery = useQuery({
    queryKey: ["/api/v1/lines", lineSearchText],
    enabled: open,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "200");
      params.set("offset", "0");
      if (lineSearchText.trim()) params.set("keyword", lineSearchText.trim());
      const response = await fetchWithAuth(`/api/v1/lines?${params.toString()}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  const lineOptions = useMemo(() => {
    const items = linesQuery.data?.items ?? [];
    return items.map((line: LineSummary) => ({
      label: `${line.code} - ${line.name}${line.voltage_kv ? ` (${line.voltage_kv}kV)` : ""}`,
      value: line.id,
    }));
  }, [linesQuery.data]);

  return (
    <Modal
      title="导入地闪密度数据"
      open={open}
      onCancel={onClose}
      footer={null}
      width={640}
      destroyOnClose
    >
      <Form<ImportFormValues> form={importForm} layout="vertical" initialValues={initialValues}>
        <div className="grid gap-3 md:grid-cols-2">
          <Form.Item name="city" label="城市" rules={[{ required: true, message: "请选择城市" }]}>
            <Select
              showSearch
              allowClear
              placeholder="请搜索选择城市"
              filterOption={(input, option) => {
                const keyword = input.toLowerCase().trim();
                const data = option?.["data-data"] as CityOption | undefined;
                if (!data) return false;
                return (
                  data.label.includes(input)
                  || data.pinyin.includes(keyword)
                  || data.initials.includes(keyword)
                );
              }}
              options={CHINESE_CITIES.map((item) => ({
                label: item.label,
                value: item.label,
                "data-data": item,
              }))}
            />
          </Form.Item>
          <Form.Item name="region_id" label="事件发生地点" rules={[{ required: true, message: "请填写事件发生地点" }]}>
            <Input placeholder="例如 XX变电站、XX区域（闪电事件发生地点）" />
          </Form.Item>
          <Form.Item name="event_year" label="数据年份" rules={[{ required: true, message: "请填写年份" }]}>
            <InputNumber className="w-full" min={1900} max={2100} />
          </Form.Item>
          <Form.Item name="notes" label="数据说明">
            <Input placeholder="可填写数据来源、采集说明等" />
          </Form.Item>
        </div>

        <div className="grid gap-3 md:grid-cols-1" style={{ marginBottom: 16 }}>
          <Form.Item name="line_id" label="关联线路">
            <Select
              showSearch
              allowClear
              placeholder="选择关联线路（可选，用于线路密度回填）"
              filterOption={false}
              onSearch={setLineSearchText}
              notFoundContent={linesQuery.isLoading ? <Spin size="small" /> : undefined}
              options={lineOptions}
            />
          </Form.Item>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Form.Item label="数据文件" required>
            <Upload.Dragger
              accept=".txt,.csv,text/plain,text/csv"
              showUploadList={false}
              beforeUpload={(file) => {
                setSelectedFile(file);
                return false;
              }}
              onRemove={() => setSelectedFile(null)}
            >
              {selectedFile ? (
                <p className="ant-upload-text">{selectedFile.name}</p>
              ) : (
                <>
                  <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                    点击或拖拽文件到此区域上传
                  </p>
                  <Typography.Text type="secondary">
                    支持包含经纬度和电流的 CSV 或 TXT 文件。原始文件将存入 MinIO。
                  </Typography.Text>
                </>
              )}
            </Upload.Dragger>
          </Form.Item>
        </div>
        <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
          <Button
            type="primary"
            disabled={!selectedFile}
            loading={loading}
            onClick={onConfirm}
          >
            确认导入
          </Button>
        </div>
      </Form>
    </Modal>
  );
}

function DistributionDetailView({
  record,
  fetchWithAuth,
  canReadLogs,
  onOpenLog,
}: {
  record: LightningDistributionRecord;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  canReadLogs: boolean;
  onOpenLog: (taskId: string | null | undefined, label: string, fileName: string) => void;
}) {
  const imageQuery = useQuery({
    queryKey: ["/api/v1/lightning-currents/distributions", record.id, "image"],
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/distributions/${record.id}/image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      if (blob.size === 0) return null;
      return URL.createObjectURL(blob);
    },
  });

  const lpImageQuery = useQuery({
    queryKey: ["/api/v1/lightning-currents/distributions", record.id, "lp-image"],
    enabled: !!record.has_lp_image,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lightning-currents/distributions/${record.id}/lp-image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      if (blob.size === 0) return null;
      return URL.createObjectURL(blob);
    },
  });

  useEffect(() => {
    const objectUrl = imageQuery.data;
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [imageQuery.data]);

  useEffect(() => {
    const objectUrl = lpImageQuery.data;
    if (!objectUrl) return;
    return () => URL.revokeObjectURL(objectUrl);
  }, [lpImageQuery.data]);

  const imageUrl = imageQuery.data ?? null;

  return (
    <Space direction="vertical" size={16} className="w-full">
      <Descriptions bordered size="small" column={3}>
        <Descriptions.Item label="城市">{record.city || "-"}</Descriptions.Item>
        <Descriptions.Item label="地点标签">{record.location_tag || "-"}</Descriptions.Item>
        <Descriptions.Item label="年份">{record.event_year ?? "-"}</Descriptions.Item>
        <Descriptions.Item label="有效点数">{record.valid_count}</Descriptions.Item>
        <Descriptions.Item label="面积(km²)">{formatNumber(record.area_km2, 3)}</Descriptions.Item>
        <Descriptions.Item label="统计年限">{formatNumber(record.data_years, 3)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            整体 Ng
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.overallNg} />
          </span>
        }>{formatNumber(record.overall_ng, 4)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            Imax(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.maxCurrent} />
          </span>
        }>{formatNumber(record.max_abs_current, 2)}</Descriptions.Item>
        <Descriptions.Item label={
          <span>
            Iavg(kA)
            <FieldHelpTooltip content={FIELD_HELP_TOOLTIPS.avgCurrent} />
          </span>
        }>{formatNumber(record.avg_abs_current, 2)}</Descriptions.Item>
        <Descriptions.Item label="正极数量">{record.positive_count}</Descriptions.Item>
        <Descriptions.Item label="负极数量">{record.negative_count}</Descriptions.Item>
        <Descriptions.Item label="未知极性">{record.unknown_count}</Descriptions.Item>
      </Descriptions>

      <Tabs
        defaultActiveKey="grid"
        items={[
          {
            key: "grid",
            label: "均匀网格图",
            children: (
              <div style={{ textAlign: "center", minHeight: 200 }}>
                {imageQuery.isLoading ? (
                  <Spin tip="加载图片中..." />
                ) : imageUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={imageUrl}
                    alt="地闪密度图"
                    style={{ maxWidth: "100%", border: "1px solid #f0f0f0", borderRadius: 6 }}
                  />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无密度图（导入失败或仍在处理中）" />
                )}
              </div>
            ),
          },
          ...(record.has_lp_image
            ? [
                {
                  key: "lp",
                  label: "LP 分区图",
                  children: (
                    <div style={{ textAlign: "center", minHeight: 200 }}>
                      {lpImageQuery.isLoading ? (
                        <Spin tip="加载 LP 分区图中..." />
                      ) : lpImageQuery.data ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          src={lpImageQuery.data}
                          alt="LP 分区密度图"
                          style={{ maxWidth: "100%", border: "1px solid #f0f0f0", borderRadius: 6 }}
                        />
                      ) : (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无 LP 分区图" />
                      )}
                    </div>
                  ),
                },
              ]
            : []),
          ...(canReadLogs && (record.task_id || record.lp_draw_task_id)
            ? [
                {
                  key: "logs",
                  label: "处理日志",
                  children: (
                    <Space direction="vertical" size={12} style={{ width: "100%", minHeight: 120 }}>
                      {record.task_id && (
                        <Button onClick={() => onOpenLog(record.task_id, "导入日志", record.source_file_name)}>
                          查看导入日志
                        </Button>
                      )}
                      {record.lp_draw_task_id && (
                        <Button onClick={() => onOpenLog(record.lp_draw_task_id, "绘图日志", record.source_file_name)}>
                          查看绘图日志
                        </Button>
                      )}
                      {!record.task_id && !record.lp_draw_task_id && (
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无可查看的处理日志" />
                      )}
                    </Space>
                  ),
                },
              ]
            : []),
        ]}
      />
    </Space>
  );
}

function LinkedLinesModal({
  open,
  data,
  onClose,
  fetchWithAuth,
}: {
  open: boolean;
  data: LightningDistributionRecord | null;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
}) {
  const linkedLinesPath = data
    ? `/api/v1/lightning-currents/distributions/${data.id}/linked-lines`
    : null;
  const linkedLinesQuery = useQuery({
    queryKey: [linkedLinesPath],
    enabled: !!linkedLinesPath,
    queryFn: async () => {
      if (!linkedLinesPath) {
        return { items: [], total: 0 } satisfies LightningLinkedLinesResponse;
      }
      const response = await fetchWithAuth(linkedLinesPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningLinkedLinesResponse;
    },
  });

  const linkedLines = useMemo(
    () => linkedLinesQuery.data?.items ?? [],
    [linkedLinesQuery.data],
  );

  const linkedColumns = useMemo<ColumnsType<LightningLinkedLineSummary>>(
    () => [
      {
        title: "线路编号",
        dataIndex: "line_code",
        width: 120,
        render: (value: string | null) => value || "-",
      },
      {
        title: "线路名称",
        dataIndex: "line_name",
        width: 150,
        render: (value: string | null) => value || "-",
      },
      {
        title: "电压等级",
        dataIndex: "voltage_kv",
        width: 90,
        render: (value: number | null) =>
          value === null || value === undefined ? "-" : `${value}kV`,
      },
      {
        title: "引用杆塔数",
        dataIndex: "tower_count",
        width: 90,
        render: (value: number) => value,
      },
      {
        title: "最近回填时间",
        dataIndex: "prepared_at",
        width: 150,
        render: (value: string | null) => (value ? formatDateTime(value) : "-"),
      },
    ],
    [],
  );

  return (
    <Modal
      title={`关联线路 - ${data?.source_file_name ?? ""}`}
      open={open}
      onCancel={onClose}
      footer={null}
      width={600}
      destroyOnClose
    >
      <Table<LightningLinkedLineSummary>
        rowKey="line_id"
        size="small"
        columns={linkedColumns}
        dataSource={linkedLines}
        loading={linkedLinesQuery.isFetching}
        pagination={false}
        locale={{
          emptyText: linkedLinesQuery.isLoading ? (
            <Spin size="small" />
          ) : (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该分布尚未回填任何线路" />
          ),
        }}
      />
    </Modal>
  );
}

function DrawLpModal({
  open,
  data,
  onClose,
  fetchWithAuth,
  onSubmitted,
}: {
  open: boolean;
  data: LightningDistributionRecord | null;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onSubmitted: (taskId: string, fileName: string) => void;
}) {
  return (
    <Modal title="绘制 LP 分区地闪密度图" open={open} onCancel={onClose} footer={null} width={560} destroyOnClose>
      {/* key 随分布记录变化强制重挂载，避免残留上一分布选中的线路 / 提交结果 */}
      <DrawLpBody key={data?.id ?? "empty"} open={open} data={data} fetchWithAuth={fetchWithAuth} onSubmitted={onSubmitted} />
    </Modal>
  );
}

function DrawLpBody({
  open,
  data,
  fetchWithAuth,
  onSubmitted,
}: {
  open: boolean;
  data: LightningDistributionRecord | null;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  onSubmitted: (taskId: string, fileName: string) => void;
}) {
  const [lineSearchText, setLineSearchText] = useState("");
  const [lineId, setLineId] = useState<string | null>(null);
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  // 当前分布记录 stats_json 中的落雷经纬度范围；历史记录可能无 bbox（降级为不传 bbox 参数）。
  const bboxParam = useMemo(() => {
    const bbox = data?.stats_json?.bbox;
    if (!bbox || typeof bbox !== "object") return null;
    const { min_lat, max_lat, min_lon, max_lon } = bbox as Record<string, unknown>;
    if (
      typeof min_lat !== "number" ||
      typeof max_lat !== "number" ||
      typeof min_lon !== "number" ||
      typeof max_lon !== "number"
    ) {
      return null;
    }
    return `${min_lat},${min_lon},${max_lat},${max_lon}`;
  }, [data?.stats_json]);

  const linesQuery = useQuery({
    queryKey: ["/api/v1/lines", lineSearchText, bboxParam],
    enabled: open,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "200");
      params.set("offset", "0");
      if (lineSearchText.trim()) params.set("keyword", lineSearchText.trim());
      if (bboxParam) params.set("bbox", bboxParam);
      const resp = await fetchWithAuth(`/api/v1/lines?${params.toString()}`);
      if (!resp.ok) throw new Error(await readApiError(resp));
      return (await resp.json()) as LineListResponse;
    },
  });

  const lineOptions = useMemo(() =>
    (linesQuery.data?.items ?? []).map((l: LineSummary) => ({
      label: `${l.code} - ${l.name}${l.voltage_kv ? ` (${l.voltage_kv}kV)` : ""}`,
      value: l.id,
    })),
    [linesQuery.data],
  );

  const drawMutation = useMutation({
    mutationFn: async () => {
      if (!lineId) throw new Error("请先选择线路");
      const body: Record<string, unknown> = { line_id: lineId };
      const resp = await fetchWithAuth(
        `/api/v1/lightning-currents/distributions/${data?.id}/draw-lp`,
        { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) },
      );
      if (!resp.ok) throw new Error(await readApiError(resp));
      return (await resp.json()) as LightningLpDrawResponse;
    },
    onSuccess: (p) => {
      setError("");
      setSuccess(`LP 绘图任务已提交（任务ID: ${p.task_id}）。完成后请在详情弹窗查看。`);
      onSubmitted(p.task_id, data?.source_file_name || "绘图");
    },
    onError: (e) => {
      setSuccess("");
      setError(e instanceof Error ? e.message : "绘图任务提交失败");
    },
  });

  return (
    <>
      <Form layout="vertical">
        <Form.Item
          required
          label={(
            <Space size={4}>
              选择线路
              <Tooltip title="仅展示与当前地闪密度数据区域有重叠的线路；未覆盖区域的线路绘图无有效数据，故不展示">
                <QuestionCircleOutlined style={{ color: "var(--ant-color-text-quaternary)" }} />
              </Tooltip>
            </Space>
          )}
        >
          <Select
            showSearch
            placeholder="选择线路（按该线路杆塔分组绘图）"
            filterOption={false}
            onSearch={setLineSearchText}
            notFoundContent={
              linesQuery.isLoading
                ? <Spin size="small" />
                : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="无可用线路" />
            }
            value={lineId}
            onChange={setLineId}
            options={lineOptions}
          />
        </Form.Item>
      </Form>
      <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
        <Button type="primary" loading={drawMutation.isPending} onClick={() => drawMutation.mutate()}>
          提交绘图
        </Button>
      </div>
      {success && <Typography.Paragraph type="success" style={{ marginTop: 12 }}>{success}</Typography.Paragraph>}
      {error && <Typography.Paragraph type="danger" style={{ marginTop: 12 }}>{error}</Typography.Paragraph>}
    </>
  );
}
