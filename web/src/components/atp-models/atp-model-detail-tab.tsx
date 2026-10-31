"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Drawer, Empty, Modal, Space, Spin, Table, Typography } from "antd";
import { useMemo, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary, AtpAssetFileListResponse } from "@/types/auth";
import { AtpDatDetailView } from "./atp-dat-detail-view";
import { AtpFileContentViewer } from "./atp-file-content-viewer";
import { AtpSceneViewer } from "./atp-scene-viewer";
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

interface AtpModelDetailTabProps {
  assetId: string;
}

// 「场景拓扑预览」显示开关：按用户要求屏蔽该区块（拓扑图暂不可用/不展示）。
// 组件 AtpSceneViewer 及其接口调用均保留，将此常量改回 true 即可恢复显示。
const SHOW_SCENE_TOPOLOGY_PREVIEW = false;

export function AtpModelDetailTab({ assetId }: AtpModelDetailTabProps) {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [datDetail, setDatDetail] = useState<{ path: string; name: string } | null>(null);
  // 通用文件在线查看：所有非目录文件均可打开（dat 另有结构化「查看详情」）
  const [previewFile, setPreviewFile] = useState<{ path: string; name: string } | null>(null);

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

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
  const files = filesQuery.data?.items ?? [];

  const fileRows = useMemo(
    () =>
      (filesQuery.data?.items ?? []).map((file) => ({
        key: file.relative_path,
        path: file.relative_path,
        name: file.name,
        size: file.is_dir ? "-" : file.size,
        modified: file.is_dir ? "-" : file.modified_at,
        is_dir: file.is_dir,
      })),
    [filesQuery.data?.items],
  );

  if (initializing) {
    return <div style={{ textAlign: "center", padding: "40px 0" }}><Spin /></div>;
  }

  if (!user) {
    return <Alert type="warning" showIcon message={t("请先登录后查看 ATP 模型详情。")} />;
  }

  if (!canRead) {
    return <Alert type="error" showIcon message={t("当前账号缺少 ATP 模型读取权限（需要 atp.read / atp.run / atp.manage）。")} />;
  }

  return (
    <div className="admin-atp-models-detail-pane modo-page-card">
      {assetQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Spin />
        </div>
      ) : assetQuery.isError ? (
        <Alert type="error" showIcon message={t("加载 ATP 模型失败")} description={assetQuery.error instanceof Error ? assetQuery.error.message : ""} />
      ) : asset ? (
        <div>
          <Typography.Title level={5}>{t("基本信息")}</Typography.Title>
          <Descriptions
            bordered
            size="small"
            column={2}
            className="admin-atp-models-meta-table"
            items={[
              { key: "code", label: t("编码"), children: asset.code },
              { key: "name", label: t("名称"), children: asset.name },
              { key: "voltage", label: t("电压等级"), children: asset.voltage_level || "-" },
              { key: "tower", label: t("塔型"), children: asset.tower_type || "-" },
              { key: "scene", label: t("场景"), children: asset.scene_type || "-" },
              { key: "arrester", label: t("避雷器组合"), children: asset.arrester_config || "-" },
              { key: "run_count", label: t("运行次数"), children: asset.run_count },
              { key: "last_run", label: t("最近运行"), children: asset.last_run_status ? `${asset.last_run_status} · ${formatDateTime(asset.last_run_date)}` : "-" },
              { key: "storage", label: t("存储挂载"), children: asset.storage_mount_code || "-" },
              { key: "create_date", label: t("创建时间"), children: formatDateTime(asset.create_date) },
            ]}
          />
        </div>
      ) : null}

      {SHOW_SCENE_TOPOLOGY_PREVIEW ? (
        <div style={{ marginTop: 16 }}>
          <AtpSceneViewer assetId={assetId} />
        </div>
      ) : null}

      <div style={{ marginTop: 16 }}>
        <AtpModelSlotsPanel assetId={assetId} />
      </div>

      <div>
        <Typography.Title level={5}>文件列表 ({files.length})</Typography.Title>
        {files.length === 0 && !filesQuery.isLoading ? (
          <div style={{ padding: "24px 0" }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无文件")} />
          </div>
        ) : (
          <Table
            rowKey="key"
            loading={filesQuery.isLoading}
            dataSource={fileRows}
            pagination={false}
            className="admin-atp-models-files-table"
            columns={[
              { title: t("文件名"), dataIndex: "name", key: "name" },
              { title: t("文件大小"), dataIndex: "size", key: "size", width: 120, render: (v: number | "-") => formatSize(v) },
              { title: t("更新时间"), dataIndex: "modified", key: "modified", width: 180, render: (v: string | "-") => (v === "-" ? "-" : formatDateTime(v)) },
              {
                title: t("操作"),
                key: "operation",
                width: 170,
                align: "right" as const,
                render: (_value, row: { path: string; name: string; is_dir: boolean }) =>
                  !row.is_dir ? (
                    <Space size={4}>
                      {row.path.toLowerCase().endsWith(".dat") ? (
                        <Button
                          type="link"
                          size="small"
                          style={{ padding: 0 }}
                          onClick={(event) => {
                            event.stopPropagation();
                            setDatDetail({ path: row.path, name: row.name });
                          }}
                        >
                          查看详情
                        </Button>
                      ) : null}
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        onClick={(event) => {
                          event.stopPropagation();
                          setPreviewFile({ path: row.path, name: row.name });
                        }}
                      >
                        查看
                      </Button>
                    </Space>
                  ) : (
                    <span style={{ color: "#bbb", fontSize: 12 }}>-</span>
                  ),
              },
            ]}
          />
        )}
      </div>

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
    </div>
  );
}
