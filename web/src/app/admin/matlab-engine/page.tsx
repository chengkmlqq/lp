"use client";

import { CloudSyncOutlined, DeleteOutlined, InboxOutlined, UploadOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  List,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
  message,
} from "antd";
import type { UploadFile } from "antd/es/upload";
import { useCallback, useEffect, useRef, useState } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type { WsEventEnvelope } from "@/types/ws";

type EngineVersion = {
  version_hash: string;
  upload_time: string;
  uploaded_by: string;
  uploaded_by_name: string;
  file_list: string[];
  size_bytes: number;
  is_active?: boolean;
};

type VersionsResponse = {
  items: EngineVersion[];
  current_version: string;
};

type SyncResponse = {
  task_id: string;
  status: string;
};

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function AdminMatlabEnginePage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncTaskId, setSyncTaskId] = useState<string | null>(null);
  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const canManage = hasPermission("line.manage");
  const canRead = hasPermission("line.read") || canManage;

  const versionsQuery = useQuery({
    queryKey: ["/api/v1/fault-matlab/versions"],
    enabled: canRead,
    queryFn: async () => {
      const res = await fetchWithAuth("/api/v1/fault-matlab/versions");
      if (!res.ok) throw new Error(await readApiError(res));
      return (await res.json()) as VersionsResponse;
    },
    refetchInterval: syncing ? 3000 : false,
  });

  useTopicSubscription("admin.matlab-engine", useCallback((event: WsEventEnvelope) => {
    if (
      event.name === "engine.sync_completed" ||
      event.name === "engine.sync_failed"
    ) {
      setSyncing(false);
      setSyncTaskId(null);
      void versionsQuery.refetch();
      if (event.name === "engine.sync_completed") {
        message.success("同步完成");
      } else {
        message.error(`同步失败: ${(event.payload as Record<string, unknown>)?.error ?? "未知错误"}`);
      }
    }
    if (event.name === "engine.version_uploaded" || event.name === "engine.version_activated") {
      void versionsQuery.refetch();
    }
  }, [versionsQuery]));

  useEffect(() => {
    if (error) {
      message.error(error);
      setError("");
    }
  }, [error]);

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetchWithAuth("/api/v1/fault-matlab/upload", {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: () => {
      message.success("上传成功");
      setUploadModalOpen(false);
      setFileList([]);
      void versionsQuery.refetch();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "上传失败");
    },
  });

  const activateMutation = useMutation({
    mutationFn: async (versionHash: string) => {
      const res = await fetchWithAuth(`/api/v1/fault-matlab/activate/${versionHash}`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: () => {
      message.success("已激活");
      void versionsQuery.refetch();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "激活失败");
    },
  });

  const handleSync = async () => {
    try {
      setSyncing(true);
      const res = await fetchWithAuth("/api/v1/fault-matlab/sync", { method: "POST" });
      if (!res.ok) throw new Error(await readApiError(res));
      const data = (await res.json()) as SyncResponse;
      setSyncTaskId(data.task_id);
      message.info("同步任务已提交，请等待 Worker 处理");
    } catch (candidate) {
      setSyncing(false);
      setError(candidate instanceof Error ? candidate.message : "同步失败");
    }
  };

  const handleUpload = async () => {
    if (fileList.length === 0) {
      message.warning("请先选择 ZIP 文件");
      return;
    }
    const raw = fileList[0].originFileObj;
    if (!raw) {
      message.warning("文件无效");
      return;
    }
    await uploadMutation.mutateAsync(raw);
  };

  if (initializing) {
    return <AdminPageLoading tip="加载 MATLAB 引擎管理..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <Card title="MATLAB 引擎管理">
        <Typography.Text type="secondary">
          {!user ? "请先登录后访问。" : "当前账号无权限（需要 line.read）。"}
        </Typography.Text>
      </Card>
    );
  }

  const versions = versionsQuery.data?.items ?? [];
  const currentVersion = versionsQuery.data?.current_version ?? "";
  const activeVersion = versions.find((v) => v.version_hash === currentVersion);

  const versionColumns = [
    {
      title: "版本 Hash",
      dataIndex: "version_hash",
      key: "version_hash",
      render: (hash: string) => <Typography.Text copyable={{ text: hash }}>{hash}</Typography.Text>,
    },
    {
      title: "上传时间",
      dataIndex: "upload_time",
      key: "upload_time",
      render: (t: string) => (t ? new Date(t).toLocaleString() : "-"),
    },
    {
      title: "上传人",
      dataIndex: "uploaded_by_name",
      key: "uploaded_by_name",
      render: (name: string, record: EngineVersion) => name || record.uploaded_by || "-",
    },
    {
      title: "大小",
      dataIndex: "size_bytes",
      key: "size_bytes",
      render: (size: number) => formatSize(size),
    },
    {
      title: "状态",
      key: "status",
      render: (_: unknown, record: EngineVersion) =>
        record.version_hash === currentVersion ? (
          <Tag color="success">当前激活</Tag>
        ) : (
          <Tag>未激活</Tag>
        ),
    },
    {
      title: "操作",
      key: "actions",
      render: (_: unknown, record: EngineVersion) => (
        <Space>
          {record.version_hash !== currentVersion && canManage && (
            <Button
              size="small"
              type="primary"
              onClick={() => void activateMutation.mutateAsync(record.version_hash)}
              loading={activateMutation.isPending}
            >
              激活
            </Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Card
        title="MATLAB 引擎管理"
        extra={
          <Space>
            <Button
              icon={<CloudSyncOutlined />}
              onClick={() => void handleSync()}
              loading={syncing}
              disabled={!canManage || syncing || !currentVersion}
            >
              同步到 Worker
            </Button>
            {canManage && (
              <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
                上传引擎
              </Button>
            )}
          </Space>
        }
      >
        {activeVersion ? (
          <Card type="inner" title="当前激活版本" style={{ marginBottom: 16 }}>
            <Descriptions column={2} size="small">
              <Descriptions.Item label="版本 Hash">
                <Typography.Text copyable>{activeVersion.version_hash}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="上传时间">
                {activeVersion.upload_time ? new Date(activeVersion.upload_time).toLocaleString() : "-"}
              </Descriptions.Item>
              <Descriptions.Item label="上传人">
                {activeVersion.uploaded_by_name || activeVersion.uploaded_by || "-"}
              </Descriptions.Item>
              <Descriptions.Item label="大小">
                {formatSize(activeVersion.size_bytes)}
              </Descriptions.Item>
            </Descriptions>
            {activeVersion.file_list?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Typography.Text type="secondary">文件清单：</Typography.Text>
                <Typography.Text style={{ marginLeft: 4 }}>
                  {activeVersion.file_list.join(", ")}
                </Typography.Text>
              </div>
            )}
          </Card>
        ) : (
          <Alert
            type="warning"
            showIcon
            message="当前没有激活版本"
            description="请上传引擎 ZIP 包并激活一个版本。首次上传将自动激活。"
            style={{ marginBottom: 16 }}
          />
        )}

        {syncing && (
          <Alert
            type="info"
            showIcon
            icon={<CloudSyncOutlined spin />}
            message="正在同步引擎到 Worker..."
            description={syncTaskId ? `Task ID: ${syncTaskId}` : "请等待..."}
            style={{ marginBottom: 16 }}
          />
        )}

        <Table
          dataSource={versions}
          columns={versionColumns}
          rowKey="version_hash"
          size="small"
          pagination={false}
          locale={{ emptyText: "暂无版本记录" }}
        />
      </Card>

      <Modal
        title="上传 MATLAB 引擎"
        open={uploadModalOpen}
        onCancel={() => {
          setUploadModalOpen(false);
          setFileList([]);
        }}
        onOk={() => void handleUpload()}
        confirmLoading={uploadMutation.isPending}
        okText="上传"
        cancelText="取消"
      >
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
            ZIP 包必须包含 RunWaveAnalysisModule 可执行文件和 run_RunWaveAnalysisModule.sh
          </p>
        </Upload.Dragger>
      </Modal>
    </div>
  );
}
