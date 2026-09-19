"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Empty, Spin, Table, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { AtpModelTestPanel } from "@/components/atp-models/atp-model-test-panel";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary, AtpAssetFileListResponse } from "@/types/auth";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatSize(bytes: number | "-"): string {
  if (bytes === "-") return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

function ATPAssetDetailPage() {
  const params = useParams();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const assetId = params.id as string;

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

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user) {
    return (
      <div className="p-6">
        <Alert type="warning" showIcon message="请先登录后查看 ATP 模型详情。" />
      </div>
    );
  }

  if (!canRead) {
    return (
      <div className="p-6">
        <Alert type="error" showIcon message="当前账号缺少 ATP 模型读取权限（需要 atp.read / atp.run / atp.manage）。" />
      </div>
    );
  }

  const fileItemRow = (file: AtpAssetFileListResponse["items"][number]) => ({
    key: file.relative_path,
    name: file.name,
    size: file.is_dir ? "-" : file.size,
    modified: file.is_dir ? "-" : file.modified_at,
    is_dir: file.is_dir,
  });

  return (
    <div className="admin-atp-models-detail-pane">
      {assetQuery.isLoading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Spin />
        </div>
      ) : assetQuery.isError ? (
        <Alert type="error" showIcon message="加载 ATP 模型失败" description={assetQuery.error instanceof Error ? assetQuery.error.message : ""} />
      ) : asset ? (
        <div>
          <Typography.Title level={5}>基本信息</Typography.Title>
          <Descriptions
            bordered
            size="small"
            column={2}
            className="admin-atp-models-meta-table"
            items={[
              { key: "code", label: "编码", children: asset.code },
              { key: "name", label: "名称", children: asset.name },
              { key: "voltage", label: "电压等级", children: asset.voltage_level || "-" },
              { key: "tower", label: "塔型", children: asset.tower_type || "-" },
              { key: "scene", label: "场景", children: asset.scene_type || "-" },
              { key: "arrester", label: "避雷器组合", children: asset.arrester_config || "-" },
              { key: "run_count", label: "运行次数", children: asset.run_count },
              { key: "last_run", label: "最近运行", children: asset.last_run_status ? `${asset.last_run_status} · ${formatDateTime(asset.last_run_date)}` : "-" },
              { key: "storage", label: "存储挂载", children: asset.storage_mount_code || "-" },
              { key: "create_date", label: "创建时间", children: formatDateTime(asset.create_date) },
            ]}
          />
        </div>
      ) : null}

      {asset ? <AtpModelTestPanel asset={asset} /> : null}

      <div>
        <Typography.Title level={5}>文件列表 ({files.length})</Typography.Title>
        {files.length === 0 && !filesQuery.isLoading ? (
          <div style={{ padding: "24px 0" }}>
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件" />
          </div>
        ) : (
          <Table
            rowKey="key"
            loading={filesQuery.isLoading}
            dataSource={files.map(fileItemRow)}
            pagination={false}
            className="admin-atp-models-files-table"
            columns={[
              { title: "文件名", dataIndex: "name", key: "name" },
              { title: "文件大小", dataIndex: "size", key: "size", width: 120, render: (v: number | "-") => formatSize(v) },
              { title: "更新时间", dataIndex: "modified", key: "modified", width: 180, render: (v: string | "-") => (v === "-" ? "-" : formatDateTime(v)) },
            ]}
          />
        )}
      </div>
    </div>
  );
}

export default ATPAssetDetailPage;
