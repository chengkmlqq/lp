"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Empty, Space, Spin, Tabs, Table, Tag, Typography } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import AtpCircuitPreview from "@/components/atp-circuit-preview";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary, AtpAssetFileListResponse, AtpAssetReleaseListResponse, AtpAssetRunListResponse } from "@/types/auth";

const { Text } = Typography;

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

const RELEASE_COLUMNS = [
  { title: "版本号", dataIndex: "release_no", key: "release_no", width: 90 },
  { title: "标签", dataIndex: "release_tag", key: "release_tag", width: 120, render: (v: string | null) => v || "-" },
  {
    title: "状态",
    dataIndex: "status",
    key: "status",
    width: 100,
    render: (v: string) => {
      const color = v === "released" ? "green" : v === "draft" ? "blue" : "default";
      return <Tag color={color}>{v}</Tag>;
    },
  },
  { title: "入口文件", dataIndex: "entry_file", key: "entry_file", render: (v: string | null) => v || "-" },
  {
    title: "激活",
    dataIndex: "is_active",
    key: "is_active",
    width: 90,
    render: (v: boolean) => (v ? <Tag color="gold">激活</Tag> : <Tag>未激活</Tag>),
  },
  { title: "创建时间", dataIndex: "create_date", key: "create_date", width: 170, render: (v: string) => formatDateTime(v) },
];

const RUN_COLUMNS = [
  { title: "状态", dataIndex: "status", key: "status", width: 110, render: (v: string) => <Tag color={v === "success" ? "green" : v === "failed" ? "red" : "blue"}>{v}</Tag> },
  { title: "版本号", dataIndex: "release_no", key: "release_no", width: 90 },
  { title: "引擎", dataIndex: "engine_mode", key: "engine_mode", width: 90 },
  { title: "退出码", dataIndex: "exit_code", key: "exit_code", width: 90, render: (v: number | null) => (v == null ? "-" : v) },
  { title: "耗时(ms)", dataIndex: "duration_ms", key: "duration_ms", width: 110, render: (v: number | null) => (v == null ? "-" : formatNumber(v)) },
  { title: "开始时间", dataIndex: "started_at", key: "started_at", width: 170, render: (v: string | null) => formatDateTime(v) },
];

function ATPAssetDetailPage() {
  const params = useParams();
  const router = useRouter();
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

  const releasesQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "releases"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}/releases?limit=200`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpAssetReleaseListResponse;
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
          release_id: null,
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
    queryKey: ["/api/v1/atp/assets", assetId, "releases", "runs"],
    enabled: Boolean(user && canRead && assetId),
    queryFn: async () => {
      const allRuns: AtpAssetRunListResponse["items"] = [];
      // 遍历所有 release 拉取运行记录（每 release 最多 100 条）
      const releases = releasesQuery.data?.items ?? [];
      for (const release of releases.slice(0, 10)) {
        const response = await fetchWithAuth(`/api/v1/atp/releases/${release.id}/runs?limit=100`);
        if (response.ok) {
          const data = (await response.json()) as AtpAssetRunListResponse;
          allRuns.push(...data.items);
        }
      }
      // 去重 + 按创建时间倒序
      const seen = new Set<string>();
      const unique = allRuns.filter((run) => {
        if (seen.has(run.id)) return false;
        seen.add(run.id);
        return true;
      });
      unique.sort((a, b) => new Date(b.create_date).getTime() - new Date(a.create_date).getTime());
      return { items: unique, total: unique.length } satisfies AtpAssetRunListResponse;
    },
  });

  const asset = assetQuery.data;
  const releases = releasesQuery.data?.items ?? [];
  const files = filesQuery.data?.items ?? [];
  const runs = runsQuery.data?.items ?? [];

  if (initializing) {
    return <AdminPageLoading tip="加载 ATP 模型详情中..." minHeightClassName="min-h-[280px]" />;
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
    path: file.relative_path,
    size: file.is_dir ? "-" : file.size,
    role: file.file_role || "-",
    is_dir: file.is_dir,
  });

  return (
    <div className="flex flex-col gap-4">
      <Space align="center" size={8}>
        <Button icon={<ArrowLeftOutlined />} onClick={() => router.push("/admin/atp-models")}>
          返回
        </Button>
        <Typography.Title level={4} style={{ margin: 0 }}>
          ATP 模型详情
        </Typography.Title>
        {asset && (
          <Tag color={asset.status === "enabled" ? "green" : asset.status === "disabled" ? "default" : "orange"}>
            {asset.status}
          </Tag>
        )}
      </Space>

      {assetQuery.isLoading ? (
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
              {
                key: "active_release",
                label: "激活版本",
                children: asset.active_release_tag ? `v${asset.active_release_no} (${asset.active_release_tag})` : asset.active_release_no ? `v${asset.active_release_no}` : "-",
              },
              { key: "release_count", label: "版本数", children: asset.release_count },
              { key: "run_count", label: "运行次数", children: asset.run_count },
              { key: "last_run", label: "最近运行", children: asset.last_run_status ? `${asset.last_run_status} · ${formatDateTime(asset.last_run_date)}` : "-" },
              { key: "storage", label: "存储挂载", children: asset.storage_mount_code || "-" },
              { key: "create_date", label: "创建时间", children: formatDateTime(asset.create_date) },
            ]}
          />
        </Card>
      ) : null}

      <Card size="small" styles={{ body: { padding: 0 } }}>
        <Tabs
          items={[
            {
              key: "topology",
              label: "电路预览",
              children: <AtpCircuitPreview assetId={assetId} height={520} />,
            },
            {
              key: "versions",
              label: `版本 (${releases.length})`,
              children: (
                <Table
                  rowKey="id"
                  columns={RELEASE_COLUMNS}
                  dataSource={releases}
                  loading={releasesQuery.isLoading}
                  pagination={releases.length > 10 ? { pageSize: 10, showTotal: (t) => `共 ${t} 条` } : false}
                />
              ),
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
                  dataSource={files.map(fileItemRow)}
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
                  columns={RUN_COLUMNS}
                  dataSource={runs}
                  loading={runsQuery.isLoading}
                  pagination={runs.length > 10 ? { pageSize: 10, showTotal: (t) => `共 ${t} 条` } : false}
                />
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}

export default ATPAssetDetailPage;