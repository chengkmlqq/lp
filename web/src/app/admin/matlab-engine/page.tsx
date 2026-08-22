"use client";

import {
  CloudSyncOutlined,
  InboxOutlined,
  PlusOutlined,
  RollbackOutlined,
  UploadOutlined,
} from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Input,
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
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import {
  createMatlabModule,
  deleteMatlabModule,
  fetchMatlabModuleVersions,
  fetchMatlabModules,
  publishMatlabDraft,
  rollbackMatlabVersion,
  syncMatlabModule,
  updateMatlabModule,
  uploadMatlabDraft,
} from "@/lib/matlab-engine-api";
import type { MatlabModule, MatlabVersion } from "@/types/matlab-engine";

function formatSize(bytes: number): string {
  if (!bytes) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "-";
  return parsed.toLocaleString();
}

export default function AdminMatlabEnginePage() {
  const { user, initializing, hasPermission } = useAuth();
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);
  const [syncTaskId, setSyncTaskId] = useState<string | null>(null);
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null);

  const [moduleModalOpen, setModuleModalOpen] = useState(false);
  const [editingModule, setEditingModule] = useState<MatlabModule | null>(null);
  const [moduleName, setModuleName] = useState("");
  const [moduleSlug, setModuleSlug] = useState("");
  const [moduleDescription, setModuleDescription] = useState("");
  const [moduleDeployPath, setModuleDeployPath] = useState("");
  const [moduleRequiredFiles, setModuleRequiredFiles] = useState("");

  const [uploadModalOpen, setUploadModalOpen] = useState(false);
  const [fileList, setFileList] = useState<UploadFile[]>([]);

  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [publishTag, setPublishTag] = useState("");
  const [publishChangelog, setPublishChangelog] = useState("");

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTitle, setPreviewTitle] = useState("文件列表");
  const [previewFiles, setPreviewFiles] = useState<string[]>([]);

  const canManage = hasPermission("line.manage");
  const canRead = hasPermission("line.read") || canManage;

  const modulesQuery = useQuery({
    queryKey: ["matlab-modules"],
    enabled: canRead,
    queryFn: async () => fetchMatlabModules(),
  });

  const versionsQuery = useQuery({
    queryKey: ["matlab-versions", selectedSlug],
    enabled: Boolean(canRead && selectedSlug),
    queryFn: async () => {
      if (!selectedSlug) return { draft: null, releases: [] };
      return fetchMatlabModuleVersions(selectedSlug);
    },
  });

  const refetchCurrent = useCallback(() => {
    void modulesQuery.refetch();
    if (selectedSlug) {
      void versionsQuery.refetch();
    }
  }, [modulesQuery, selectedSlug, versionsQuery]);

  useTopicSubscription("admin.matlab-engine", useCallback((event) => {
    const payload = event.payload as Record<string, unknown> | undefined;
    const slug = (payload?.slug as string | undefined) ?? null;
    if (slug === null || slug === selectedSlug) {
      refetchCurrent();
    } else {
      void modulesQuery.refetch();
    }
    if (event.name === "engine.sync_completed") {
      setSyncing(false);
      setSyncTaskId(null);
      message.success("同步完成");
    }
    if (event.name === "engine.sync_failed") {
      setSyncing(false);
      setSyncTaskId(null);
      message.error(`同步失败: ${payload?.error ?? "未知错误"}`);
    }
    if (event.name === "engine.draft_uploaded") {
      message.success("上传成功");
    }
    if (event.name === "engine.published") {
      message.success("发布成功");
    }
    if (event.name === "engine.rollbacked") {
      message.success("已回退");
    }
  }, [refetchCurrent, selectedSlug]));

  useEffect(() => {
    if (error) {
      message.error(error);
      setError("");
    }
  }, [error]);

  useEffect(() => {
    if (modulesQuery.data?.length && !selectedSlug) {
      setSelectedSlug(modulesQuery.data[0].slug);
    }
  }, [modulesQuery.data, selectedSlug]);

  const selectedModule = useMemo(
    () => modulesQuery.data?.find((item) => item.slug === selectedSlug) ?? null,
    [modulesQuery.data, selectedSlug],
  );

  const draft = versionsQuery.data?.draft ?? null;
  const releases = versionsQuery.data?.releases ?? [];
  const currentRelease = releases[0] ?? null;
  const hasVersions = Boolean(draft || releases.length > 0);

  const openCreateModal = useCallback(() => {
    setEditingModule(null);
    setModuleName("");
    setModuleSlug("");
    setModuleDescription("");
    setModuleDeployPath("");
    setModuleRequiredFiles("RunWaveAnalysisModule\nrun_RunWaveAnalysisModule.sh");
    setModuleModalOpen(true);
  }, []);

  const openEditModal = useCallback((item: MatlabModule) => {
    setEditingModule(item);
    setModuleName(item.name);
    setModuleSlug(item.slug);
    setModuleDescription(item.description || "");
    setModuleDeployPath(item.worker_deploy_path || "");
    setModuleRequiredFiles((item.required_files || []).join("\n"));
    setModuleModalOpen(true);
  }, []);

  const handleSaveModule = async () => {
    if (!moduleName.trim()) {
      message.warning("请输入模块名称");
      return;
    }
    const payload = {
      name: moduleName.trim(),
      slug: moduleSlug.trim() || moduleName.trim(),
      description: moduleDescription.trim(),
      worker_deploy_path: moduleDeployPath.trim(),
      required_files: moduleRequiredFiles
        .split(/[\n,，]+/)
        .map((item) => item.trim())
        .filter(Boolean),
    };
    try {
      if (editingModule) {
        await updateMatlabModule(editingModule.slug, payload);
        message.success("模块已更新");
      } else {
        const created = await createMatlabModule(payload);
        setSelectedSlug(created.slug);
        message.success("模块已创建");
      }
      setModuleModalOpen(false);
      setEditingModule(null);
      void modulesQuery.refetch();
    } catch (candidate) {
      message.error(candidate instanceof Error ? candidate.message : "保存失败");
    }
  };

  const handleDeleteModule = async (item: MatlabModule) => {
    try {
      await deleteMatlabModule(item.slug);
      message.success("模块已删除");
      await modulesQuery.refetch();
      if (selectedSlug === item.slug) {
        const remaining = modulesQuery.data?.filter((m) => m.slug !== item.slug) ?? [];
        setSelectedSlug(remaining[0]?.slug ?? null);
      }
    } catch (candidate) {
      message.error(candidate instanceof Error ? candidate.message : "删除失败");
    }
  };

  const handleUpload = async () => {
    const raw = fileList[0]?.originFileObj;
    if (!raw) {
      message.warning("请先选择 ZIP 文件");
      return;
    }
    if (!selectedSlug) {
      message.warning("请先选择模块");
      return;
    }
    try {
      await uploadMatlabDraft(selectedSlug, raw);
      message.success("上传成功");
      setUploadModalOpen(false);
      setFileList([]);
      void versionsQuery.refetch();
    } catch (candidate) {
      message.error(candidate instanceof Error ? candidate.message : "上传失败");
    }
  };

  const handlePublish = async () => {
    const tag = publishTag.trim();
    if (!tag) {
      message.warning("请输入版本号");
      return;
    }
    if (!selectedSlug || !draft) {
      message.warning("当前没有草稿版本");
      return;
    }
    try {
      await publishMatlabDraft(selectedSlug, { version_tag: tag, changelog: publishChangelog.trim() });
      message.success("发布成功");
      setPublishModalOpen(false);
      setPublishTag("");
      setPublishChangelog("");
      void versionsQuery.refetch();
    } catch (candidate) {
      message.error(candidate instanceof Error ? candidate.message : "发布失败");
    }
  };

  const handleRollback = async (version: MatlabVersion) => {
    if (!selectedSlug) return;
    try {
      await rollbackMatlabVersion(selectedSlug, version.version_hash);
      message.success("已回退为新草稿，请重新发布");
      void versionsQuery.refetch();
    } catch (candidate) {
      message.error(candidate instanceof Error ? candidate.message : "回退失败");
    }
  };

  const handleSync = async () => {
    if (!selectedSlug) return;
    try {
      setSyncing(true);
      const data = await syncMatlabModule(selectedSlug);
      setSyncTaskId(data.task_id);
      message.info("同步任务已提交，请等待 Worker 处理");
    } catch (candidate) {
      setSyncing(false);
      message.error(candidate instanceof Error ? candidate.message : "同步失败");
    }
  };

  if (initializing) {
    return <AdminPageLoading tip="加载 MATLAB 程序管理..." minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <Card title="MATLAB 程序管理">
        <Typography.Text type="secondary">
          {!user ? "请先登录后访问。" : "当前账号无权限（需要 line.read）。"}
        </Typography.Text>
      </Card>
    );
  }

  const modules = modulesQuery.data ?? [];

  return (
    <div className="flex min-h-0 flex-1">
      <Col className="h-full" style={{ width: 260, minWidth: 240 }}>
        <div className="flex h-full flex-col rounded-lg border border-gray-200 bg-white">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <div className="text-sm font-medium text-gray-900">模块列表</div>
            {canManage && (
              <Button size="small" type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
                新建模块
              </Button>
            )}
          </div>
          <div className="flex-1 overflow-auto">
            {modules.length === 0 ? (
              <div className="px-3 py-4 text-center text-xs text-gray-400">暂无模块</div>
            ) : (
              modules.map((item) => (
                <div
                  key={item.slug}
                  className={`flex cursor-pointer items-center justify-between px-3 py-2 text-sm hover:bg-gray-50 ${
                    selectedSlug === item.slug ? "bg-blue-50 text-blue-700" : "text-gray-800"
                  }`}
                  onClick={() => setSelectedSlug(item.slug)}
                >
                  <div className="min-w-0 flex-1 truncate">
                    <div className="font-medium">{item.name}</div>
                    <div className="truncate text-xs text-gray-500">{item.slug}</div>
                  </div>
                  {canManage && (
                    <div className="ml-2 flex gap-1">
                      <Button
                        size="small"
                        type="text"
                        onClick={(event) => {
                          event.stopPropagation();
                          openEditModal(item);
                        }}
                      >
                        编辑
                      </Button>
                      <Popconfirm
                        title="删除模块"
                        description={`确认删除模块“${item.name}”吗？`}
                        onConfirm={() => void handleDeleteModule(item)}
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true }}
                      >
                        <Button size="small" type="text" danger onClick={(event) => event.stopPropagation()}>
                          删除
                        </Button>
                      </Popconfirm>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>
      </Col>

      <Col className="h-full flex-1 overflow-auto" style={{ minWidth: 0 }}>
        {!selectedModule ? (
          <Card>
            <Typography.Text type="secondary">请在左侧选择一个模块查看详情。</Typography.Text>
          </Card>
        ) : (
          <Card
            title={
              <Space>
                <Typography.Text strong>MATLAB 程序管理</Typography.Text>
                <Tag color="blue">{selectedModule.name}</Tag>
              </Space>
            }
            extra={
              <Space>
                <Button
                  icon={<CloudSyncOutlined />}
                  onClick={() => void handleSync()}
                  loading={syncing}
                  disabled={!canManage || syncing || !currentRelease}
                >
                  同步到 Worker
                </Button>
                {canManage && (
                  <Button type="primary" icon={<UploadOutlined />} onClick={() => setUploadModalOpen(true)}>
                    上传新包
                  </Button>
                )}
              </Space>
            }
          >
            <Descriptions column={2} size="small" className="mb-4">
              <Descriptions.Item label="名称">{selectedModule.name}</Descriptions.Item>
              <Descriptions.Item label="标识">{selectedModule.slug}</Descriptions.Item>
              <Descriptions.Item label="描述">{selectedModule.description || "-"}</Descriptions.Item>
              <Descriptions.Item label="部署路径">{selectedModule.worker_deploy_path || "-"}</Descriptions.Item>
              <Descriptions.Item label="必需文件" span={2}>
                {(selectedModule.required_files || []).join(", ") || "-"}
              </Descriptions.Item>
            </Descriptions>

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

            {hasVersions ? (
              <Row gutter={16}>
                <Col span={24}>
                  <Card type="inner" title="草稿版本" style={{ marginBottom: 16 }}>
                    {draft ? (
                      <Space direction="vertical" className="w-full">
                        <Descriptions column={3} size="small">
                          <Descriptions.Item label="版本 Hash">
                            <Typography.Text copyable>{draft.version_hash}</Typography.Text>
                          </Descriptions.Item>
                          <Descriptions.Item label="上传时间">
                            {formatDateTime(draft.upload_time)}
                          </Descriptions.Item>
                          <Descriptions.Item label="上传人">
                            {draft.uploaded_by_name || draft.uploaded_by || "-"}
                          </Descriptions.Item>
                          <Descriptions.Item label="大小">{formatSize(draft.size_bytes)}</Descriptions.Item>
                          <Descriptions.Item label="文件数">{draft.file_list?.length ?? 0}</Descriptions.Item>
                        </Descriptions>
                        <Space wrap>
                          <Button type="primary" onClick={() => {
                            setPublishTag("");
                            setPublishChangelog("");
                            setPublishModalOpen(true);
                          }} disabled={!canManage}>
                            发布
                          </Button>
                          <Button onClick={() => {
                            setPreviewTitle(`草稿文件列表 (${draft.version_hash})`);
                            setPreviewFiles(draft.file_list || []);
                            setPreviewOpen(true);
                          }}>
                            查看文件列表
                          </Button>
                        </Space>
                      </Space>
                    ) : (
                      <Typography.Text type="secondary">当前没有草稿，请上传新包。</Typography.Text>
                    )}
                  </Card>
                </Col>
                <Col span={24}>
                  <Card type="inner" title="历史版本">
                    <Table<MatlabVersion>
                      dataSource={releases}
                      rowKey="version_hash"
                      size="small"
                      pagination={false}
                      locale={{ emptyText: "暂无历史版本" }}
                      columns={[
                        {
                          title: "版本号",
                          dataIndex: "version_tag",
                          key: "version_tag",
                        },
                        {
                          title: "版本 Hash",
                          dataIndex: "version_hash",
                          key: "version_hash",
                          render: (hash: string) => (
                            <Typography.Text copyable={{ text: hash }}>{hash}</Typography.Text>
                          ),
                        },
                        {
                          title: "变更日志",
                          dataIndex: "changelog",
                          key: "changelog",
                          render: (text: string) => (text ? text : "-"),
                        },
                        {
                          title: "发布时间",
                          dataIndex: "upload_time",
                          key: "upload_time",
                          render: (t: string) => formatDateTime(t),
                        },
                        {
                          title: "发布人",
                          dataIndex: "uploaded_by_name",
                          key: "uploaded_by_name",
                          render: (name: string, record: MatlabVersion) => name || record.uploaded_by || "-",
                        },
                        {
                          title: "大小",
                          dataIndex: "size_bytes",
                          key: "size_bytes",
                          render: (size: number) => formatSize(size),
                        },
                        {
                          title: "操作",
                          key: "actions",
                          render: (_: unknown, record: MatlabVersion) => (
                            <Space>
                              <Button
                                size="small"
                                onClick={() => {
                                  setPreviewTitle(`版本文件列表 (${record.version_tag || record.version_hash})`);
                                  setPreviewFiles(record.file_list || []);
                                  setPreviewOpen(true);
                                }}
                              >
                                查看文件
                              </Button>
                              {canManage && (
                                <Popconfirm
                                  title="回退到此版本"
                                  description="此操作将把该历史版本复制为新的草稿，需要重新发布后才会同步到 Worker。"
                                  onConfirm={() => void handleRollback(record)}
                                  okText="回退"
                                  cancelText="取消"
                                >
                                  <Button size="small" icon={<RollbackOutlined />}>
                                    回退
                                  </Button>
                                </Popconfirm>
                              )}
                            </Space>
                          ),
                        },
                      ]}
                    />
                  </Card>
                </Col>
              </Row>
            ) : (
              <Alert
                type="warning"
                showIcon
                message="暂无版本"
                description="请上传引擎 ZIP 包并发布。"
                style={{ marginBottom: 16 }}
              />
            )}
          </Card>
        )}
      </Col>

      <Modal
        title={editingModule ? "编辑模块" : "新建模块"}
        open={moduleModalOpen}
        onOk={() => void handleSaveModule()}
        onCancel={() => {
          setModuleModalOpen(false);
          setEditingModule(null);
        }}
        okText="保存"
        cancelText="取消"
      >
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-sm text-gray-700">名称</div>
            <Input
              placeholder="模块显示名称"
              value={moduleName}
              onChange={(event) => setModuleName(event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1 text-sm text-gray-700">标识</div>
            <Input
              placeholder="waveform_diagnosis"
              value={moduleSlug}
              disabled={Boolean(editingModule)}
              onChange={(event) => setModuleSlug(event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1 text-sm text-gray-700">描述</div>
            <Input.TextArea
              placeholder="模块用途说明"
              rows={2}
              value={moduleDescription}
              onChange={(event) => setModuleDescription(event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1 text-sm text-gray-700">Worker 部署路径</div>
            <Input
              placeholder="/opt/worker/matlab/{module}/"
              value={moduleDeployPath}
              onChange={(event) => setModuleDeployPath(event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1 text-sm text-gray-700">必需文件</div>
            <Input.TextArea
              placeholder="每行一个文件名"
              rows={2}
              value={moduleRequiredFiles}
              onChange={(event) => setModuleRequiredFiles(event.target.value)}
            />
          </div>
        </div>
      </Modal>

      <Modal
        title="上传 MATLAB 引擎"
        open={uploadModalOpen}
        onCancel={() => {
          setUploadModalOpen(false);
          setFileList([]);
        }}
        onOk={() => void handleUpload()}
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
            ZIP 包必须包含 {(selectedModule?.required_files || []).join(", ") || "必需文件"}
          </p>
        </Upload.Dragger>
      </Modal>

      <Modal
        title="发布版本"
        open={publishModalOpen}
        onOk={() => void handlePublish()}
        onCancel={() => setPublishModalOpen(false)}
        okText="发布"
        cancelText="取消"
      >
        <div className="flex flex-col gap-3">
          <div>
            <div className="mb-1 text-sm text-gray-700">版本号</div>
            <Input
              placeholder="版本号，如 v1.0.0"
              value={publishTag}
              onChange={(event) => setPublishTag(event.target.value)}
            />
          </div>
          <div>
            <div className="mb-1 text-sm text-gray-700">变更日志</div>
            <Input.TextArea
              placeholder="本次变更说明"
              rows={3}
              value={publishChangelog}
              onChange={(event) => setPublishChangelog(event.target.value)}
            />
          </div>
        </div>
      </Modal>

      <Modal
        title={previewTitle}
        open={previewOpen}
        onCancel={() => setPreviewOpen(false)}
        footer={null}
        width={640}
      >
        {previewFiles.length === 0 ? (
          <Typography.Text type="secondary">无文件记录</Typography.Text>
        ) : (
          <List
            size="small"
            bordered
            dataSource={previewFiles}
            renderItem={(item) => (
              <List.Item>
                <Typography.Text code>{item}</Typography.Text>
              </List.Item>
            )}
          />
        )}
      </Modal>
    </div>
  );
}
