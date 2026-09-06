"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Card, Descriptions, Empty, Space, Spin, Table, Typography } from "antd";
import { useMemo } from "react";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary, AtpAssetFileListResponse } from "@/types/auth";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

interface AtpModelDetailTabProps {
  assetId: string;
}

export function AtpModelDetailTab({ assetId }: AtpModelDetailTabProps) {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();

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
    () => (filesQuery.data?.items ?? []).map((file) => ({
      key: file.relative_path,
      name: file.name,
      path: file.relative_path,
      size: file.is_dir ? "-" : file.size,
      role: file.file_role || "-",
      is_dir: file.is_dir,
    })),
    [filesQuery.data?.items],
  );

  if (initializing) {
    return <Card><div style={{ textAlign: "center", padding: "40px 0" }}><Spin /></div></Card>;
  }

  if (!user) {
    return (
      <Card>
        <Alert type="warning" showIcon message="请先登录后查看 ATP 模型详情。" />
      </Card>
    );
  }

  if (!canRead) {
    return (
      <Card>
        <Alert type="error" showIcon message="当前账号缺少 ATP 模型读取权限（需要 atp.read / atp.run / atp.manage）。" />
      </Card>
    );
  }

  const header = (
    <Space align="center" size={8}>
      <Typography.Title level={4} style={{ margin: 0 }}>
        ATP 模型详情
      </Typography.Title>
    </Space>
  );

  const assetSection = assetQuery.isLoading ? (
    <Card>
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin />
      </div>
    </Card>
  ) : assetQuery.isError ? (
    <Card>
      <Alert type="error" showIcon message="加载 ATP 模型失败" description={assetQuery.error instanceof Error ? assetQuery.error.message : ""} />
    </Card>
  ) : asset ? (
    <Card size="small">
      <div className="flex flex-col gap-2">
        <Typography.Title level={5} style={{ margin: 0 }}>基本信息</Typography.Title>
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
    </Card>
  ) : null;

  return (
    <Card>
      <div className="flex flex-col gap-4">
        {header}
        {assetSection}
        <Card size="small" styles={{ body: { padding: 0 } }}>
          <div className="flex flex-col">
            <div className="px-4 py-3 border-b border-gray-200">
              <Typography.Title level={5} style={{ margin: 0 }}>
                文件列表 ({files.length})
              </Typography.Title>
            </div>
            {files.length === 0 && !filesQuery.isLoading ? (
              <div style={{ padding: "24px 0" }}>
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件" />
              </div>
            ) : (
              <Table
                rowKey="key"
                loading={filesQuery.isLoading}
                dataSource={fileRows}
                pagination={false}
                columns={[
                  { title: "名称", dataIndex: "name", key: "name", width: 220 },
                  { title: "路径", dataIndex: "path", key: "path" },
                  { title: "大小(字节)", dataIndex: "size", key: "size", width: 120 },
                  { title: "角色", dataIndex: "role", key: "role", width: 120 },
                ]}
              />
            )}
          </div>
        </Card>
      </div>
    </Card>
  );
}