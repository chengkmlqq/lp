"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
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
  WarningOutlined,
} from "@ant-design/icons";
import { useMemo, useState } from "react";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { readApiError } from "@/lib/api";
import { packModelFilesZip } from "@/lib/atp-model-pack";
import { checkWarningCount, describeModelFormat, MODEL_ANALYZING_META } from "@/lib/atp-model-format";
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
 * - 顶部概览带：图标锚点 + 模型名/编码 + 语义 chip（发布/形态/状态）+ 刷新；
 *   下方一行大数字统计（测试次数 / 最近结果 / 文件数），三秒读完使用情况；
 * - 内容用 Tabs 分区：「基本信息」是无边框属性网格 + 参数槽位；「文件列表 (n)」
 *   带文件名筛选与分页，对齐知识构建页「概览 + 表格」的阅读节奏；
 * - 属性网格沿用卡片的两列 dl 视觉（标签灰 12px / 值深 13px），详情页放宽为四列。
 */
export function AtpModelDetailTab({ assetId }: { assetId: string }) {
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
      Modal.success({
        title: t("模型文件已覆盖"),
        content: t("旧文件已清理，测试结论已重置；后台正在重新检测模型形态与槽位。"),
      });
      setReplaceOpen(false);
      setReplaceFiles([]);
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

  // 模型形态与上传预检：形态决定仿真走 lib 还是 pch 链路；warning 是
  // 「需要人工确认但不阻断仿真」的项。分析进行中时显示「检测中」。
  const analysisRunning = asset?.analysis_status === "pending" || asset?.analysis_status === "running";
  const formatMeta = analysisRunning
    ? MODEL_ANALYZING_META
    : describeModelFormat(asset?.model_format, Boolean(asset?.format_check?.model_format));
  const warnCount = checkWarningCount(asset?.format_check);
  const checkIssues = asset?.format_check?.issues ?? [];
  const abnormal = asset ? statusMeta(asset.status, t) : null;
  const published = asset?.is_published !== false;
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
      render: (value: boolean, item) =>
        value ? (
          <Tooltip title={item.published_date ? formatDateTime(item.published_date) : undefined}>
            <span className="admin-atp-models-state-chip is-published">{t("已发布")}</span>
          </Tooltip>
        ) : (
          <span className="admin-atp-models-state-chip is-muted">{t("未发布")}</span>
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
      width: 130,
      align: "right",
      render: (_value, item) =>
        item.id === assetId ? (
          <span className="admin-atp-models-file-none">-</span>
        ) : (
          <Space size={4}>
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
          {/* 概览带：图标锚点 + 名称/编码 + 语义 chips + 刷新；下方大数字统计行 */}
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
                  {published ? (
                    <span className="admin-atp-models-state-chip is-published">{t("已发布")}</span>
                  ) : (
                    <span className="admin-atp-models-state-chip is-muted">{t("未发布")}</span>
                  )}
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
                  <Tooltip title={t(formatMeta.hint)}>
                    <span
                      className="admin-atp-models-detail-chip"
                      style={{ color: formatMeta.color, background: formatMeta.background }}
                    >
                      {t(formatMeta.short)}
                      {warnCount > 0 && !analysisRunning ? (
                        <WarningOutlined style={{ fontSize: 11 }} />
                      ) : null}
                    </span>
                  </Tooltip>
                  {abnormal ? (
                    <span className={`admin-atp-models-state-chip ${abnormal.chipClass}`}>{abnormal.text}</span>
                  ) : null}
                </div>
              </div>
              <Tooltip title={t("刷新")}>
                <Button
                  icon={<ReloadOutlined />}
                  onClick={handleRefresh}
                  loading={assetQuery.isFetching || filesQuery.isFetching}
                />
              </Tooltip>
            </div>

            <div className="admin-atp-models-detail-stats">
              <div className="admin-atp-models-detail-stat">
                <span className="admin-atp-models-detail-stat-value">{asset.run_count ?? 0}</span>
                <span className="admin-atp-models-detail-stat-label">{t("测试次数")}</span>
              </div>
              <div className="admin-atp-models-detail-stat">
                <span className={`admin-atp-models-detail-stat-value ${runStatus.className}`}>{runStatus.text}</span>
                <span className="admin-atp-models-detail-stat-label">
                  {t("最近结果")}
                  {asset.last_run_date ? ` · ${formatDateTime(asset.last_run_date)}` : ""}
                </span>
              </div>
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
                        <dt>{t("模型形态")}</dt>
                        <dd>
                          <span style={{ color: formatMeta.color }}>{t(formatMeta.label)}</span>
                          {warnCount > 0 && !analysisRunning ? (
                            <Typography.Text type="warning" style={{ fontSize: 12, marginLeft: 6 }}>
                              {warnCount} {t("条提示")}
                            </Typography.Text>
                          ) : null}
                        </dd>
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
                        <dt>{t("存储挂载")}</dt>
                        <dd>{asset.storage_mount_code || "-"}</dd>
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
        title={t("重新上传覆盖")}
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
            type="warning"
            showIcon
            message={t("将清空该版本的现有模型文件并写入新文件")}
            description={t("旧文件不可恢复；上传后测试结论会重置，后台将自动重新检测模型形态与槽位。")}
          />
          <Upload.Dragger
            multiple
            directory
            fileList={replaceFiles}
            beforeUpload={() => false}
            onChange={({ fileList: next }) => setReplaceFiles(next)}
            accept=".zip,.atp,.dat,.lib,.pch"
          >
            <p className="ant-upload-drag-icon">
              <CloudUploadOutlined />
            </p>
            <p className="ant-upload-text">{t("选择模型文件夹或文件（支持 zip 整包）")}</p>
            <p className="ant-upload-hint">{t("上传后自动按原有目录结构打包覆盖")}</p>
          </Upload.Dragger>
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
                  label: `${item.version}${item.is_published ? ` · ${t("已发布")}` : ` · ${t("未发布")}`}`,
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
                    a: compareQuery.data.asset_a.is_published ? t("已发布") : t("未发布"),
                    b: compareQuery.data.asset_b.is_published ? t("已发布") : t("未发布"),
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
