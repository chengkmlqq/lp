"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Empty,
  Input,
  Modal,
  Popconfirm,
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
  type UploadFile,
} from "antd";
import {
  CloudUploadOutlined,
  ClusterOutlined,
  DiffOutlined,
  FolderOutlined,
  ReloadOutlined,
  SearchOutlined,
  SwapOutlined,
} from "@ant-design/icons";
import { useMemo, useState } from "react";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { readApiError } from "@/lib/api";
import { packModelFilesZip } from "@/lib/atp-model-pack";
import { publishStateMeta, resolvePublishState } from "@/lib/atp-model-state";
import type {
  AtpAssetFileListResponse,
  AtpAssetRunStatus,
  AtpAssetStatus,
  AtpAssetSummary,
  AtpAssetVersionCompareResponse,
  AtpAssetVersionListResponse,
  AtpAssetVersionSummary,
} from "@/types/auth";
import { AtpDatDetailView } from "./atp-dat-detail-view";
import { AtpFileContentViewer } from "./atp-file-content-viewer";
import { AtpModelSlotsPanel } from "./atp-model-slots-panel";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function formatSize(bytes: number | "-"): string {
  if (bytes === "-") return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

/** 资产状态的展示文案与色调（enabled 正常态不显示） */
function statusMeta(status: AtpAssetStatus, t: (s: string) => string): { text: string; chipClass: string } | null {
  switch (status) {
    case "processing":
      return { text: t("处理中"), chipClass: "is-processing" };
    case "disabled":
      return { text: t("已停用"), chipClass: "is-danger" };
    case "archived":
      return { text: t("已归档"), chipClass: "is-warning" };
    case "draft":
      return { text: t("草稿"), chipClass: "is-muted" };
    default:
      return null;
  }
}

function runStatusMeta(status: AtpAssetRunStatus | null, t: (s: string) => string): { text: string; className: string } {
  switch (status) {
    case "success":
      return { text: t("成功"), className: "is-success" };
    case "failed":
      return { text: t("失败"), className: "is-danger" };
    case "running":
      return { text: t("运行中"), className: "is-running" };
    case "pending":
      return { text: t("排队中"), className: "is-running" };
    default:
      return { text: t("未运行"), className: "is-muted" };
  }
}

/**
 * ATP 模型详情（2026-11-07 版式重做，参考 DataAtlas 详情页）：
 *
 * 旧版是「基本信息 Descriptions 表 + 文件列表」从上到下平铺，信息没有层级，
 * bordered 表格的竖线也显得重。
 *
 * 新版按「概览带 → 分区 Tabs → 干净表格」重排：
 * - 顶部概览带：图标锚点 + 模型名/编码 + 语义 chip（发布/状态）+ 刷新；
 *   下方一行紧凑读数（文件数）；
 * - 内容用 Tabs 分区：「基本信息」是无边框属性网格 + 参数槽位；「文件列表 (n)」
 *   带文件名筛选与分页，对齐知识构建页「概览 + 表格」的阅读节奏；
 * - 属性网格沿用卡片的两列 dl 视觉（标签灰 12px / 值深 13px），详情页放宽为四列。
 *
 * 2026-11-12 精简（信息过载反馈）：撤掉概览带里的「测试次数 / 最近结果」两格读数与
 * 形态 chip，统计行只留「文件数」并收敛为紧凑单格；「基本信息」去掉「模型形态 / 存储挂载」
 * 两项。形态与预检提示仍由「模型检查」Alert 呈现，最近运行结果保留在「基本信息」里。
 */
export function AtpModelDetailTab({
  assetId,
  onOpenAsset,
}: {
  assetId: string;
  /** 覆盖上传派生「变更版本」后，用新版本 id 打开详情（父级负责开新 tab） */
  onOpenAsset?: (assetId: string) => void;
}) {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [fileKeyword, setFileKeyword] = useState("");
  const [datDetail, setDatDetail] = useState<{ path: string; name: string } | null>(null);
  // 通用文件在线查看：所有非目录文件均可打开（dat 另有结构化「查看详情」）
  const [previewFile, setPreviewFile] = useState<{ path: string; name: string } | null>(null);
  // ===== 重新上传覆盖（2026-11-10）=====
  const [replaceOpen, setReplaceOpen] = useState(false);
  const [replaceFiles, setReplaceFiles] = useState<UploadFile[]>([]);
  const [replaceUploading, setReplaceUploading] = useState(false);
  // ===== 版本对比（2026-11-10）=====
  const [compareTarget, setCompareTarget] = useState<AtpAssetVersionSummary | null>(null);
  const [compareOtherId, setCompareOtherId] = useState<string | undefined>(undefined);
  const [diffFilter, setDiffFilter] = useState<"all" | "changed" | "added" | "removed" | "same">("all");
  // ===== 版本切换（2026-11-10）：把某个已发布版本设为同维度组内的生效版本 =====
  const [activatingId, setActivatingId] = useState<string | null>(null);
  // ===== 发布 / 下线（2026-11-10）：详情页直接完成「变更 → 重新发布」 =====
  const [publishOpen, setPublishOpen] = useState(false);
  const [publishNotes, setPublishNotes] = useState("");
  const [publishSetActive, setPublishSetActive] = useState(true);
  const [publishBusy, setPublishBusy] = useState(false);

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("atp.manage");

  const assetQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetSummary;
    },
    // 后台分析（形态 + 槽位）进行中时轮询，出终态自动停
    refetchInterval: (query) => {
      const status = (query.state.data as AtpAssetSummary | undefined)?.analysis_status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });

  const filesQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "files"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/files`);
      if (!response.ok) {
        return {
          asset_id: assetId,
          storage_mount_code: "",
          storage_root_path: "",
          items: [],
          total: 0,
        } satisfies AtpAssetFileListResponse;
      }
      return (await response.json()) as AtpAssetFileListResponse;
    },
  });

  const asset = assetQuery.data;
  const files = useMemo(() => filesQuery.data?.items ?? [], [filesQuery.data?.items]);

  // ===== 版本历史（2026-11-10）：同维度组合的全部版本，含发布状态/描述/文件数 =====
  const versionsQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "versions"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/versions`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetVersionListResponse;
    },
  });
  const versions = useMemo(() => versionsQuery.data?.items ?? [], [versionsQuery.data?.items]);

  // ===== 版本对比（2026-11-10）：当前版本 vs 选定版本，按「相对路径+大小」判定文件差异 =====
  const compareQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "versions", "compare", compareOtherId],
    enabled: Boolean(compareTarget && compareOtherId && compareOtherId !== assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/atp/assets/${assetId}/versions/compare?other_id=${encodeURIComponent(compareOtherId ?? "")}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetVersionCompareResponse;
    },
  });

  const filteredFiles = useMemo(() => {
    const keyword = fileKeyword.trim().toLowerCase();
    if (!keyword) return files;
    return files.filter(
      (file) =>
        file.name.toLowerCase().includes(keyword) ||
        file.relative_path.toLowerCase().includes(keyword),
    );
  }, [files, fileKeyword]);

  const handleRefresh = () => {
    assetQuery.refetch();
    filesQuery.refetch();
    versionsQuery.refetch();
  };

  // ===== 重新上传覆盖（2026-11-10）：打包 zip → 临时上传 → replace=true 提交 =====
  const handleReplaceUpload = async () => {
    if (replaceFiles.length === 0) return;
    setReplaceUploading(true);
    try {
      const rawFiles = replaceFiles
        .map((item) => item.originFileObj)
        .filter((file): file is NonNullable<typeof file> => Boolean(file)) as File[];
      if (rawFiles.length === 0) {
        throw new Error(t("请先选择要上传的模型文件"));
      }
      const zipBlob = await packModelFilesZip(rawFiles);
      const tempForm = new FormData();
      tempForm.append("file", zipBlob, "model.zip");
      const tempResponse = await fetchWithAuth("/api/v1/uploads/temp", {
        method: "POST",
        body: tempForm,
      });
      if (!tempResponse.ok) {
        throw new Error(await readApiError(tempResponse));
      }
      const tempPayload = (await tempResponse.json()) as { temp_file_id: string };
      const filesForm = new FormData();
      filesForm.append("temp_file_id", tempPayload.temp_file_id);
      const uploadResponse = await fetchWithAuth(
        `/api/v1/atp/assets/${assetId}/files?replace=true`,
        { method: "POST", body: filesForm },
      );
      if (!uploadResponse.ok) {
        throw new Error(await readApiError(uploadResponse));
      }
      const uploaded = (await uploadResponse.json()) as AtpAssetSummary;
      setReplaceOpen(false);
      setReplaceFiles([]);
      // 已发布模型的文件变更会派生成「变更」新版本（后端行为，2026-11-10）：
      // 旧版本文件保持在线继续参与仿真，新文件落在新版本里等重新发布。
      if (uploaded.id && uploaded.id !== assetId) {
        Modal.success({
          title: t("已生成变更版本"),
          content: t("原已发布版本继续参与仿真；新文件已存为变更版本 {version}，验证通过后重新发布即可上线。").replace(
            "{version}",
            uploaded.version || "-",
          ),
        });
        onOpenAsset?.(uploaded.id);
        return;
      }
      Modal.success({
        title: t("模型文件已覆盖"),
        content: t("旧文件已清理，测试结论已重置；后台正在重新检测模型形态与槽位。"),
      });
      handleRefresh();
    } catch (error) {
      Modal.error({
        title: t("覆盖上传失败"),
        content: error instanceof Error ? error.message : t("请稍后重试"),
      });
    } finally {
      setReplaceUploading(false);
    }
  };

  /**
   * 发布当前版本（2026-11-10）：新建 → 已发布、变更 → 已发布、下线 → 重新上线
   * 都走这一个入口。可选同时设为生效版本（同维度组内唯一）。
   */
  const handlePublish = async () => {
    setPublishBusy(true);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/publish`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          release_notes: publishNotes.trim() || null,
          set_active: publishSetActive,
        }),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      setPublishOpen(false);
      Modal.success({
        title: t("版本已发布"),
        content: publishSetActive ? t("该版本已设为生效版本") : undefined,
      });
      handleRefresh();
    } catch (error) {
      Modal.error({
        title: t("发布失败"),
        content: error instanceof Error ? error.message : t("请稍后重试"),
      });
    } finally {
      setPublishBusy(false);
    }
  };

  const handleUnpublish = async () => {
    setPublishBusy(true);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/unpublish`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      Modal.success({ title: t("版本已下线") });
      handleRefresh();
    } catch (error) {
      Modal.error({
        title: t("下线失败"),
        content: error instanceof Error ? error.message : t("请稍后重试"),
      });
    } finally {
      setPublishBusy(false);
    }
  };

  /**
   * 版本切换（2026-11-10）：把某个已发布版本设为同维度组内的生效版本。
   * 只允许切到已发布版本（后端也会拒），切换后旧版本自动失效——防雷计算随后
   * 就用这个版本的文件，所以给一次确认，避免误点。
   */
  const handleActivateVersion = (item: AtpAssetVersionSummary) => {
    Modal.confirm({
      title: t("切换生效版本"),
      content: t(
        "将 {version} 设为生效版本后，同维度组合内其他版本自动失效，防雷计算会改用该版本的文件。",
      ).replace("{version}", item.version || "-"),
      okText: t("切换"),
      cancelText: t("取消"),
      onOk: async () => {
        setActivatingId(item.id);
        try {
          const response = await fetchWithAuth(`/api/v1/atp/assets/${item.id}/activate`, {
            method: "POST",
          });
          if (!response.ok) {
            throw new Error(await readApiError(response));
          }
          Modal.success({
            title: t("已切换生效版本"),
            content: t("当前生效版本：{version}").replace("{version}", item.version || "-"),
          });
          handleRefresh();
        } catch (error) {
          Modal.error({
            title: t("切换失败"),
            content: error instanceof Error ? error.message : t("请稍后重试"),
          });
        } finally {
          setActivatingId(null);
        }
      },
    });
  };

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <div className="p-6">
        <Alert type="warning" showIcon message={t("请先登录后查看 ATP 模型详情。")} />
      </div>
    );
  }

  if (!canRead) {
    return (
      <div className="p-6">
        <Alert type="error" showIcon message={t("当前账号缺少 ATP 模型读取权限（需要 atp.read / atp.run / atp.manage）。")} />
      </div>
    );
  }

  // 后台形态 / 槽位分析进行中：预检提示（checkIssues）待分析结束后再展示。
  const analysisRunning = asset?.analysis_status === "pending" || asset?.analysis_status === "running";
  const checkIssues = asset?.format_check?.issues ?? [];
  const abnormal = asset ? statusMeta(asset.status, t) : null;
  // 发布生命周期四态（2026-11-10）：新建 / 变更 / 已发布 / 下线
  const publishState = asset ? resolvePublishState(asset) : "new";
  const publishMeta = publishStateMeta(publishState, t);
  const runStatus = runStatusMeta(asset?.last_run_status ?? null, t);

  const fileColumns: ColumnsType<AtpAssetFileListResponse["items"][number]> = [
    {
      title: t("文件名"),
      dataIndex: "name",
      key: "name",
      render: (_value, file) =>
        file.is_dir ? (
          <span className="admin-atp-models-file-dir">
            <FolderOutlined />
            {file.name}
          </span>
        ) : (
          <span title={file.relative_path}>{file.name}</span>
        ),
    },
    {
      title: t("文件大小"),
      dataIndex: "size",
      key: "size",
      width: 110,
      render: (value: number | "-") => formatSize(value),
    },
    {
      title: t("更新时间"),
      dataIndex: "modified_at",
      key: "modified_at",
      width: 170,
      render: (value: string | "-") => (value === "-" ? "-" : formatDateTime(value)),
    },
    {
      title: t("操作"),
      key: "operation",
      width: 160,
      align: "right",
      render: (_value, file) =>
        !file.is_dir ? (
          <Space size={4}>
            {file.relative_path.toLowerCase().endsWith(".dat") ? (
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                onClick={(event) => {
                  event.stopPropagation();
                  setDatDetail({ path: file.relative_path, name: file.name });
                }}
              >
                {t("查看详情")}
              </Button>
            ) : null}
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              onClick={(event) => {
                event.stopPropagation();
                setPreviewFile({ path: file.relative_path, name: file.name });
              }}
            >
              {t("查看")}
            </Button>
          </Space>
        ) : (
          <span className="admin-atp-models-file-none">-</span>
        ),
    },
  ];

  // 版本历史表列（2026-11-10）
  const versionColumns: ColumnsType<AtpAssetVersionSummary> = [
    {
      title: t("版本"),
      dataIndex: "version",
      key: "version",
      width: 110,
      render: (_value, item) => (
        <Space size={4}>
          <span style={{ fontWeight: item.id === assetId ? 600 : 400 }}>{item.version || "-"}</span>
          {item.id === assetId ? <Tag color="blue">{t("当前")}</Tag> : null}
          {item.is_active ? <Tag color="green">{t("生效")}</Tag> : null}
        </Space>
      ),
    },
    {
      title: t("发布状态"),
      dataIndex: "is_published",
      key: "is_published",
      width: 110,
      render: (_value: boolean, item) => {
        // 四态（2026-11-10）：新建 / 变更 / 已发布 / 下线
        const meta = publishStateMeta(resolvePublishState(item), t);
        return (
          <Tooltip title={item.published_date ? `${t("发布时间")} ${formatDateTime(item.published_date)}` : meta.hint}>
            <span className={`admin-atp-models-state-chip ${meta.className}`}>{meta.text}</span>
          </Tooltip>
        );
      },
    },
    {
      title: t("标签"),
      dataIndex: "tags",
      key: "tags",
      width: 160,
      render: (value: string[] | undefined) =>
        value && value.length > 0 ? (
          <Space size={2} wrap>
            {value.map((tag) => (
              <Tag key={tag} className="admin-atp-models-card-tag" title={tag}>
                {tag}
              </Tag>
            ))}
          </Space>
        ) : (
          <span className="admin-atp-models-file-none">-</span>
        ),
    },
    {
      title: t("版本描述"),
      dataIndex: "release_notes",
      key: "release_notes",
      ellipsis: true,
      render: (value: string | null) => value || <span className="admin-atp-models-file-none">-</span>,
    },
    {
      title: t("测试结论"),
      dataIndex: "test_status",
      key: "test_status",
      width: 100,
      render: (value: AtpAssetSummary["test_status"], item) => {
        if (value === "passed") return <span className="admin-atp-models-state-chip is-active">{t("通过")}</span>;
        if (value === "failed") return <span className="admin-atp-models-state-chip is-danger">{t("未通过")}</span>;
        if (value === "suspect") return <span className="admin-atp-models-state-chip is-warning">{t("可疑")}</span>;
        return (
          <Tooltip title={item.test_message || undefined}>
            <span className="admin-atp-models-state-chip is-muted">{t("未测试")}</span>
          </Tooltip>
        );
      },
    },
    {
      title: t("文件"),
      key: "files",
      width: 140,
      render: (_value, item) =>
        item.file_count === null ? (
          "-"
        ) : (
          <span>
            {item.file_count} {t("个")} · {formatSize(item.total_size ?? 0)}
          </span>
        ),
    },
    {
      title: t("创建时间"),
      dataIndex: "create_date",
      key: "create_date",
      width: 150,
      render: (value: string) => formatDateTime(value),
    },
    {
      title: t("操作"),
      key: "operation",
      width: 220,
      align: "right",
      render: (_value, item) => (
        <Space size={4}>
          {/* 版本切换（2026-11-10）：只有已发布且当前未生效的版本可以切过去 */}
          {canManage && item.is_published && !item.is_active ? (
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<SwapOutlined />}
              loading={activatingId === item.id}
              onClick={() => handleActivateVersion(item)}
            >
              {t("切换生效")}
            </Button>
          ) : null}
          {item.id !== assetId ? (
            <>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                icon={<DiffOutlined />}
                onClick={() => {
                  setCompareTarget(item);
                  setCompareOtherId(item.id);
                  setDiffFilter("all");
                }}
              >
                {t("对比")}
              </Button>
              <Button
                type="link"
                size="small"
                style={{ padding: 0 }}
                href={`/admin/atp-models/${item.id}`}
              >
                {t("查看详情")}
              </Button>
            </>
          ) : null}
          {item.id === assetId && !(canManage && item.is_published && !item.is_active) ? (
            <span className="admin-atp-models-file-none">-</span>
          ) : null}
        </Space>
      ),
    },
  ];

  // 对比结果表列（按文件路径 + 大小判定）
  const diffColumns: ColumnsType<AtpAssetVersionCompareResponse["files"][number]> = [
    {
      title: t("文件"),
      dataIndex: "relative_path",
      key: "relative_path",
      ellipsis: true,
    },
    {
      title: t("差异"),
      dataIndex: "status",
      key: "status",
      width: 90,
      render: (value: string) => {
        if (value === "changed") return <Tag color="orange">{t("变更")}</Tag>;
        if (value === "added") return <Tag color="green">{t("新增")}</Tag>;
        if (value === "removed") return <Tag color="red">{t("删除")}</Tag>;
        return <Tag>{t("相同")}</Tag>;
      },
    },
    {
      title: t("本版本"),
      key: "size_a",
      width: 110,
      align: "right",
      render: (_value, item) => (item.size_a === null ? "-" : formatSize(item.size_a)),
    },
    {
      title: t("对比版本"),
      key: "size_b",
      width: 110,
      align: "right",
      render: (_value, item) => (item.size_b === null ? "-" : formatSize(item.size_b)),
    },
  ];

  const diffRows = useMemo(() => {
    const rows = compareQuery.data?.files ?? [];
    if (diffFilter === "all") return rows;
    return rows.filter((row) => row.status === diffFilter);
  }, [compareQuery.data?.files, diffFilter]);

  return (
    <div className="admin-atp-models-detail-pane modo-page-card">
      {assetQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Spin />
        </div>
      ) : assetQuery.isError ? (
        <Alert type="error" showIcon message={t("加载 ATP 模型失败")} description={assetQuery.error instanceof Error ? assetQuery.error.message : ""} />
      ) : asset ? (
        <>
          {/* 概览带：图标锚点 + 名称/编码 + 发布状态 chip + 刷新；下方紧凑单格读数 */}
          <div className="admin-atp-models-detail-hero">
            <div className="admin-atp-models-detail-hero-head">
              <span className="admin-atp-models-card-tile admin-atp-models-detail-tile" aria-hidden>
                <ClusterOutlined />
              </span>
              <div className="admin-atp-models-detail-headline">
                <div className="admin-atp-models-detail-name">
                  <span className="admin-atp-models-detail-name-text" title={asset.name || asset.code}>
                    {asset.name || asset.code}
                  </span>
                  <Tooltip title={publishMeta.hint}>
                    <span className={`admin-atp-models-state-chip ${publishMeta.className}`}>
                      {publishState === "published" ? <span className="admin-atp-models-state-chip-dot" /> : null}
                      {publishMeta.text}
                    </span>
                  </Tooltip>
                </div>
                <div className="admin-atp-models-detail-subline">
                  <span title={asset.code}>{asset.code}</span>
                  <span className="admin-atp-models-detail-subline-dot">·</span>
                  <span>
                    {t("版本")} {asset.version || "-"}
                  </span>
                  <span className="admin-atp-models-detail-subline-dot">·</span>
                  <span>
                    {t("创建于")} {formatDateTime(asset.create_date)}
                  </span>
                  {abnormal ? (
                    <span className={`admin-atp-models-state-chip ${abnormal.chipClass}`}>{abnormal.text}</span>
                  ) : null}
                </div>
              </div>
              <Space size={6} className="shrink-0">
                {/* 发布 / 下线（2026-11-10）：详情页也能走完「变更 → 重新发布」，
                    不必退回列表卡片操作 */}
                {canManage ? (
                  publishState === "published" ? (
                    <Popconfirm
                      title={t("下线该版本？")}
                      description={t("下线后不参与仿真定位，文件与运行记录保留，可随时重新发布上线。")}
                      okText={t("下线")}
                      cancelText={t("取消")}
                      onConfirm={() => void handleUnpublish()}
                    >
                      <Button danger loading={publishBusy}>
                        {t("下线")}
                      </Button>
                    </Popconfirm>
                  ) : (
                    <Button
                      type="primary"
                      onClick={() => {
                        setPublishNotes(asset.release_notes ?? "");
                        setPublishSetActive(true);
                        setPublishOpen(true);
                      }}
                    >
                      {publishState === "new" ? t("发布") : t("重新发布")}
                    </Button>
                  )
                ) : null}
                <Tooltip title={t("刷新")}>
                  <Button
                    icon={<ReloadOutlined />}
                    onClick={handleRefresh}
                    loading={assetQuery.isFetching || filesQuery.isFetching}
                  />
                </Tooltip>
              </Space>
            </div>

            {/* 顶部统计行收敛为紧凑单格：只保留文件数（概览页仍复用同一套多格视觉） */}
            <div className="admin-atp-models-detail-stats is-compact">
              <div className="admin-atp-models-detail-stat">
                <span className="admin-atp-models-detail-stat-value">{files.length}</span>
                <span className="admin-atp-models-detail-stat-label">{t("文件数")}</span>
              </div>
            </div>
          </div>

          {/* 后台检测失败：单独一条 warning，说明重传可再次触发 */}
          {asset.analysis_status === "failed" ? (
            <Alert
              type="warning"
              showIcon
              message={t("后台检测失败（形态识别 / 槽位扫描）")}
              description={asset.analysis_error || t("重新上传模型文件可再次触发检测；若提示目录为空，请先上传模型文件。")}
            />
          ) : null}

          {/* 上传预检：error 级已在后端 400 拦掉，这里只剩「能跑但建议人工确认」的项 */}
          {checkIssues.length > 0 && !analysisRunning ? (
            <Alert
              type="warning"
              showIcon
              message={t("模型检查：{n} 条提示（不影响仿真，建议人工确认）").replace("{n}", String(checkIssues.length))}
              description={
                <div className="flex flex-col gap-2">
                  {checkIssues.map((issue) => (
                    <div key={issue.code} style={{ fontSize: 12 }}>
                      <Typography.Text strong>[{issue.code}]</Typography.Text> {issue.message}
                      {issue.file ? (
                        <Typography.Text type="secondary">（{issue.file}）</Typography.Text>
                      ) : null}
                      <div className="text-gray-500" style={{ marginTop: 2 }}>
                        → {issue.fix_hint}
                      </div>
                    </div>
                  ))}
                </div>
              }
            />
          ) : null}

          <Tabs
            className="admin-atp-models-detail-tabs"
            items={[
              {
                key: "info",
                label: t("基本信息"),
                children: (
                  <div className="admin-atp-models-detail-section">
                    <dl className="admin-atp-models-detail-meta">
                      <div>
                        <dt>{t("编码")}</dt>
                        <dd title={asset.code}>{asset.code}</dd>
                      </div>
                      <div>
                        <dt>{t("版本")}</dt>
                        <dd>{asset.version || "-"}</dd>
                      </div>
                      <div>
                        <dt>{t("电压等级")}</dt>
                        <dd>{asset.voltage_level_label || asset.voltage_level || "-"}</dd>
                      </div>
                      <div>
                        <dt>{t("塔型")}</dt>
                        <dd>{asset.tower_type_label || asset.tower_type || "-"}</dd>
                      </div>
                      <div>
                        <dt>{t("场景")}</dt>
                        <dd>{asset.scene_type_label || asset.scene_type || "-"}</dd>
                      </div>
                      <div>
                        <dt>{t("避雷器组合")}</dt>
                        <dd>{asset.arrester_config_label || asset.arrester_config || "-"}</dd>
                      </div>
                      <div>
                        <dt>{t("避雷线")}</dt>
                        <dd>{asset.shield_wire === "without" ? t("无避雷线") : t("有避雷线")}</dd>
                      </div>
                      <div>
                        <dt>{t("最近运行")}</dt>
                        <dd>
                          {asset.last_run_status
                            ? `${runStatus.text} · ${formatDateTime(asset.last_run_date)}`
                            : "-"}
                        </dd>
                      </div>
                      <div>
                        <dt>{t("创建时间")}</dt>
                        <dd>{formatDateTime(asset.create_date)}</dd>
                      </div>
                      <div>
                        <dt>{t("更新时间")}</dt>
                        <dd>{formatDateTime(asset.update_date)}</dd>
                      </div>
                    </dl>

                    <div className="admin-atp-models-detail-slots">
                      <AtpModelSlotsPanel assetId={assetId} />
                    </div>
                  </div>
                ),
              },
              {
                key: "files",
                label: `${t("文件列表")} (${files.length})`,
                children: (
                  <div className="admin-atp-models-detail-section">
                    <div className="admin-atp-models-detail-toolbar">
                      <Input
                        allowClear
                        value={fileKeyword}
                        onChange={(event) => setFileKeyword(event.target.value)}
                        prefix={<SearchOutlined style={{ color: "var(--fquiz-theme-text-muted)" }} />}
                        placeholder={t("搜索文件名")}
                        className="admin-atp-models-detail-search"
                      />
                      <span className="admin-atp-models-detail-toolbar-note">
                        {t("共 {n} 个文件").replace("{n}", String(filteredFiles.length))}
                      </span>
                      {canManage ? (
                        <Button
                          icon={<CloudUploadOutlined />}
                          onClick={() => {
                            setReplaceFiles([]);
                            setReplaceOpen(true);
                          }}
                        >
                          {t("重新上传覆盖")}
                        </Button>
                      ) : null}
                    </div>
                    {filteredFiles.length === 0 && !filesQuery.isLoading ? (
                      <div style={{ padding: "24px 0" }}>
                        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无文件")} />
                      </div>
                    ) : (
                      <Table
                        rowKey="relative_path"
                        loading={filesQuery.isFetching}
                        dataSource={filteredFiles}
                        pagination={{
                          pageSize: 20,
                          showSizeChanger: false,
                          showTotal: (total) => t("共 {n} 个文件").replace("{n}", String(total)),
                        }}
                        className="admin-atp-models-files-table"
                        columns={fileColumns}
                      />
                    )}
                  </div>
                ),
              },
              {
                key: "versions",
                label: `${t("版本历史")} (${versions.length})`,
                children: (
                  <div className="admin-atp-models-detail-section">
                    <div className="admin-atp-models-detail-toolbar">
                      <span className="admin-atp-models-detail-toolbar-note">
                        {t("同维度组合下的全部版本；发布时填写的版本描述在此追溯")}
                      </span>
                      <Button icon={<ReloadOutlined />} onClick={() => versionsQuery.refetch()} loading={versionsQuery.isFetching} />
                    </div>
                    <Table
                      rowKey="id"
                      loading={versionsQuery.isFetching}
                      dataSource={versions}
                      pagination={{ pageSize: 10, showSizeChanger: false }}
                      columns={versionColumns}
                    />
                  </div>
                ),
              },
            ]}
          />
        </>
      ) : null}

      <Modal
        open={Boolean(datDetail)}
        title={`${t("DAT 文件详情")}：${datDetail?.name ?? ""}`}
        width={900}
        footer={null}
        onCancel={() => setDatDetail(null)}
      >
        {datDetail ? <AtpDatDetailView assetId={assetId} relativePath={datDetail.path} /> : null}
      </Modal>

      <Drawer
        open={Boolean(previewFile)}
        title={`${t("文件内容")}：${previewFile?.name ?? ""}`}
        width={800}
        destroyOnHidden
        styles={{ body: { height: "75vh", overflow: "hidden", display: "flex", flexDirection: "column", padding: 16 } }}
        onClose={() => setPreviewFile(null)}
      >
        {previewFile ? (
          <AtpFileContentViewer assetId={assetId} relativePath={previewFile.path} name={previewFile.name} />
        ) : null}
      </Drawer>

      {/* 重新上传覆盖（2026-11-10）：清空该版本目录后写入新文件，测试结论重置 */}
      <Modal
        open={replaceOpen}
        title={publishState === "published" ? t("上传变更文件") : t("重新上传覆盖")}
        okText={t("覆盖上传")}
        cancelText={t("取消")}
        okButtonProps={{
          disabled: replaceFiles.length === 0,
          loading: replaceUploading,
        }}
        onOk={() => {
          void handleReplaceUpload();
        }}
        onCancel={() => {
          if (!replaceUploading) {
            setReplaceOpen(false);
            setReplaceFiles([]);
          }
        }}
        destroyOnHidden
      >
        <div className="flex flex-col gap-3">
          <Alert
            type={publishState === "published" ? "info" : "warning"}
            showIcon
            message={
              publishState === "published"
                ? t("已发布模型：新文件会存为「变更版本」")
                : t("将清空该版本的现有模型文件并写入新文件")
            }
            description={
              publishState === "published"
                ? t("当前已发布版本的文件保持不变、继续参与仿真；新文件另存为一个变更版本，验证通过后重新发布即可上线。")
                : t("旧文件不可恢复；上传后测试结论会重置，后台将自动重新检测模型形态与槽位。")
            }
          />
          <Upload.Dragger
            multiple
            directory
            fileList={replaceFiles}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setReplaceFiles(next)}
            accept=".zip,.atp,.dat,.acp"
          >
            <p className="ant-upload-drag-icon">
              <CloudUploadOutlined />
            </p>
            <p className="ant-upload-text">{t("选择模型文件夹或文件（支持 zip 整包）")}</p>
            <p className="ant-upload-hint">{t("上传后自动按原有目录结构打包覆盖")}</p>
          </Upload.Dragger>
        </div>
      </Modal>

      {/* 发布 / 重新发布（2026-11-10）：新建 → 已发布、变更 → 已发布、下线 → 重新上线 */}
      <Modal
        open={publishOpen}
        title={publishState === "new" ? t("发布版本") : t("重新发布")}
        okText={t("发布")}
        cancelText={t("取消")}
        okButtonProps={{ loading: publishBusy }}
        onOk={() => void handlePublish()}
        onCancel={() => {
          if (!publishBusy) setPublishOpen(false);
        }}
        destroyOnHidden
      >
        <div className="flex flex-col gap-3">
          <Alert
            type="info"
            showIcon
            message={
              publishState === "changed"
                ? t("发布后该版本将取代上一个已发布版本")
                : publishState === "offline"
                  ? t("发布后重新参与仿真定位")
                  : t("发布后该版本参与仿真定位")
            }
            description={`${t("模型")}：${asset?.name || asset?.code || "-"} · ${t("版本")} ${asset?.version || "-"}`}
          />
          <div>
            <div style={{ marginBottom: 6 }}>{t("版本描述")}</div>
            <Input.TextArea
              rows={4}
              maxLength={1000}
              showCount
              value={publishNotes}
              onChange={(event) => setPublishNotes(event.target.value)}
              placeholder={t("如：修正上字塔横担斜材坡度，几何与 115 线路实测一致")}
            />
          </div>
          <Checkbox checked={publishSetActive} onChange={(event) => setPublishSetActive(event.target.checked)}>
            {t("同时设为生效版本")}
          </Checkbox>
          <div className="admin-atp-models-detail-toolbar-note">
            {t("同维度组合内只能有一个生效版本；发布后旧版本自动失效，可在版本历史里随时切回")}
          </div>
        </div>
      </Modal>

      {/* 版本对比（2026-11-10）：元数据并排 + 文件级差异 */}
      <Modal
        open={Boolean(compareTarget)}
        title={t("版本对比")}
        width={860}
        footer={
          <Button
            type="primary"
            onClick={() => {
              setCompareTarget(null);
              setCompareOtherId(undefined);
            }}
          >
            {t("关闭")}
          </Button>
        }
        onCancel={() => {
          setCompareTarget(null);
          setCompareOtherId(undefined);
        }}
        destroyOnHidden
      >
        <div className="flex flex-col gap-3">
          <Space wrap size={8}>
            <span>{t("对比版本")}</span>
            <Select
              style={{ minWidth: 260 }}
              value={compareOtherId}
              onChange={(value) => setCompareOtherId(value)}
              options={versions
                .filter((item) => item.id !== assetId)
                .map((item) => ({
                  value: item.id,
                  label: `${item.version} · ${publishStateMeta(resolvePublishState(item), t).text}`,
                }))}
              placeholder={t("选择要对比的版本")}
            />
            {compareQuery.data ? (
              <span className="admin-atp-models-detail-toolbar-note">
                {t("相同 {a} · 变更 {b} · 新增 {c} · 删除 {d}")
                  .replace("{a}", String(compareQuery.data.summary.same ?? 0))
                  .replace("{b}", String(compareQuery.data.summary.changed ?? 0))
                  .replace("{c}", String(compareQuery.data.summary.added ?? 0))
                  .replace("{d}", String(compareQuery.data.summary.removed ?? 0))}
              </span>
            ) : null}
          </Space>

          {compareQuery.data ? (
            <>
              <Table
                rowKey="key"
                size="small"
                pagination={false}
                dataSource={[
                  { key: "version", label: t("版本号"), a: compareQuery.data.asset_a.version, b: compareQuery.data.asset_b.version },
                  {
                    key: "published",
                    label: t("发布状态"),
                    a: publishStateMeta(resolvePublishState(compareQuery.data.asset_a), t).text,
                    b: publishStateMeta(resolvePublishState(compareQuery.data.asset_b), t).text,
                  },
                  {
                    key: "release_notes",
                    label: t("版本描述"),
                    a: compareQuery.data.asset_a.release_notes || "-",
                    b: compareQuery.data.asset_b.release_notes || "-",
                  },
                  {
                    key: "files",
                    label: t("文件数/大小"),
                    a:
                      compareQuery.data.asset_a.file_count === null
                        ? "-"
                        : `${compareQuery.data.asset_a.file_count} · ${formatSize(compareQuery.data.asset_a.total_size ?? 0)}`,
                    b:
                      compareQuery.data.asset_b.file_count === null
                        ? "-"
                        : `${compareQuery.data.asset_b.file_count} · ${formatSize(compareQuery.data.asset_b.total_size ?? 0)}`,
                  },
                  {
                    key: "test_status",
                    label: t("测试结论"),
                    a: compareQuery.data.asset_a.test_status || t("未测试"),
                    b: compareQuery.data.asset_b.test_status || t("未测试"),
                  },
                  {
                    key: "update_date",
                    label: t("更新时间"),
                    a: formatDateTime(compareQuery.data.asset_a.update_date),
                    b: formatDateTime(compareQuery.data.asset_b.update_date),
                  },
                ]}
                columns={[
                  { title: t("项目"), dataIndex: "label", key: "label", width: 120 },
                  {
                    title: t("本版本"),
                    dataIndex: "a",
                    key: "a",
                    width: 320,
                    ellipsis: true,
                  },
                  {
                    title: t("对比版本"),
                    dataIndex: "b",
                    key: "b",
                    width: 320,
                    ellipsis: true,
                  },
                ]}
              />
              <Segmented
                value={diffFilter}
                onChange={(value) => setDiffFilter(value as typeof diffFilter)}
                options={[
                  { value: "all", label: t("全部") },
                  { value: "changed", label: `${t("变更")} ${compareQuery.data.summary.changed ?? 0}` },
                  { value: "added", label: `${t("新增")} ${compareQuery.data.summary.added ?? 0}` },
                  { value: "removed", label: `${t("删除")} ${compareQuery.data.summary.removed ?? 0}` },
                  { value: "same", label: `${t("相同")} ${compareQuery.data.summary.same ?? 0}` },
                ]}
              />
              <Table
                rowKey="relative_path"
                size="small"
                loading={compareQuery.isFetching}
                dataSource={diffRows}
                pagination={{ pageSize: 10, showSizeChanger: false }}
                columns={diffColumns}
              />
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {t("文件差异按「相对路径 + 文件大小」判定；内容相同但大小一致的文件视为相同。")}
              </Typography.Text>
            </>
          ) : (
            <div style={{ textAlign: "center", padding: "24px 0" }}>
              <Spin />
            </div>
          )}
        </div>
      </Modal>
    </div>
  );
}
