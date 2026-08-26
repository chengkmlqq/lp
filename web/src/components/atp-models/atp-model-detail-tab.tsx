"use client";

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Tabs, Table, Tag, Typography } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useMemo } from "react";

import { useAuth } from "@/components/auth-provider";
import AtpCircuitPreview from "@/components/atp-circuit-preview";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary, AtpAssetFileListResponse, AtpAssetRunListResponse } from "@/types/auth";

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function formatNumber(value: number | null | undefined): string {
  if (value == null) return "-";
  return value.toLocaleString("zh-CN");
}

const RUN_COLUMNS = [
  { title: "状态", dataIndex: "status", key: "status", width: 110, render: (v: string) => <Tag color={v === "success" ? "green" : v === "failed" ? "red" : "blue"}>{v}</Tag> },
  { title: "引擎", dataIndex: "engine_mode", key: "engine_mode", width: 90 },
  { title: "退出码", dataIndex: "exit_code", key: "exit_code", width: 90, render: (v: number | null) => (v == null ? "-" : v) },
  { title: "耗时(ms)", dataIndex: "duration_ms", key: "duration_ms", width: 110, render: (v: number | null) => (v == null ? "-" : formatNumber(v)) },
  { title: "开始时间", dataIndex: "started_at", key: "started_at", width: 170, render: (v: string | null) => formatDateTime(v) },
];

interface AtpModelDetailTabProps {
  assetId: string;
  onNavigateBack?: () => void;
}

export function AtpModelDetailTab({ assetId, onNavigateBack }: AtpModelDetailTabProps) {
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

  const runsQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "runs"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/runs?limit=100`);
      if (!response.ok) {
        return { items: [], total: 0 } satisfies AtpAssetRunListResponse;
      }
      return (await response.json()) as AtpAssetRunListResponse;
    },
  });

  const asset = assetQuery.data;
  const files = filesQuery.data?.items ?? [];
  const runs = runsQuery.data?.items ?? [];

  const tabs = useMemo(
    () => [
      {
        key: "topology",
        label: "电路预览",
        children: <AtpCircuitPreview assetId={assetId} height={520} />,
      },
      {
        key: "files",
        label: `文件 (${files.length})`,
        children: files.length === 0 && !filesQuery.isLoading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无文件" />
        ) : (
          <Table
            rowKey="path"
            loading={filesQuery.isLoading}
            dataSource={files.map((file) => ({
              key: file.relative_path,
              name: file.name,
              path: file.relative_path,
              size: file.is_dir ? "-" : file.size,
              role: file.file_role || "-",
              is_dir: file.is_dir,
            }))}
            pagination={false}
            columns={[
              { title: "名称", dataIndex: "name", key: "name", width: 220 },
              { title: "路径", dataIndex: "path", key: "path" },
              { title: "大小(字节)", dataIndex: "size", key: "size", width: 120 },
              { title: "角色", dataIndex: "role", key: "role", width: 120 },
            ]}
          />
        ),
      },
      {
        key: "runs",
        label: `运行记录 (${runs.length})`,
        children: runs.length === 0 && !runsQuery.isLoading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无运行记录" />
        ) : (
          <Table
            rowKey="id"
            loading={runsQuery.isLoading}
            columns={RUN_COLUMNS}
            dataSource={runs}
            pagination={runs.length > 10 ? { pageSize: 10, showTotal: (t) => `共 ${t} 条` } : false}
          />
        ),
      },
    ],
    [assetId, files, runs, filesQuery.isLoading, runsQuery.isLoading],
  );

  if (initializing) {
    return <Card><div style={{ textAlign: "center", padding: "40px 0" }}><Spin tip="加载中..." /></div></Card>;
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
      {onNavigateBack && (
        <Button icon={<ArrowLeftOutlined />} onClick={onNavigateBack}>
          返回
        </Button>
      )}
      <Typography.Title level={4} style={{ margin: 0 }}>
        ATP 模型详情
      </Typography.Title>
      {asset && (
        <Tag color={asset.status === "enabled" ? "green" : asset.status === "disabled" ? "default" : "orange"}>
          {asset.status}
        </Tag>
      )}
    </Space>
  );

  const assetSection = assetQuery.isLoading ? (
    <Card>
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin tip="加载中..." />
      </div>
    </Card>
  ) : assetQuery.isError ? (
    <Card>
      <Alert type="error" showIcon message="加载 ATP 模型失败" description={assetQuery.error instanceof Error ? assetQuery.error.message : ""} />
    </Card>
  ) : asset ? (
    <Card size="small">
      <Descriptions
        size="small"
        column={{ xs: 1, sm: 2, md: 3 }}
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
    </Card>
  ) : null;

  return (
    <Card>
      <div className="flex flex-col gap-4">
        {header}
        {assetSection}
        <Card size="small" styles={{ body: { padding: 0 } }}>
          <Tabs items={tabs} />
        </Card>
      </div>
    </Card>
  );
}