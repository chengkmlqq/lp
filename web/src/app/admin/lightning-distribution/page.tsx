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
  Tag,
  Typography,
  Upload,
  type CardProps,
  type MenuProps,
} from "antd";
import { MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState, type ComponentType, type RefAttributes } from "react";

const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type {
  LightningDistributionImportResponse,
  LightningDistributionRecord,
  LightningDistributionListResponse,
  LightningDistributionStatusResponse,
  LightningDistributionImageResponse,
  LightningFillDensityResponse,
  LineSummary,
  LineListResponse,
} from "@/types/auth";

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

const STAGE_META: Record<string, string> = {
  parsing: "解析中",
  validating: "校验中",
  statistics: "统计中",
  rendering: "出图中",
};

function formatNumber(value: number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits);
}

export default function AdminLightningDistributionPage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();
  const isMobile = useMobileDetection();
  const [importForm] = Form.useForm<ImportFormValues>();

  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedForImage, setSelectedForImage] = useState<LightningDistributionRecord | null>(null);
  const [imageModalOpen, setImageModalOpen] = useState(false);
  const [fillModalOpen, setFillModalOpen] = useState(false);
  const [fillForm] = Form.useForm<{ line_id: string | null; region_id: string; years: number | null; radius_km: number | null }>();

  const [keywordInput, setKeywordInput] = useState("");
  const [searchKeyword, setSearchKeyword] = useState("");
  const [activeImportId, setActiveImportId] = useState<string | null>(null);

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");
  const canManage = hasPermission("lightning.manage");

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
    refetchInterval: 5000,
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
      return 2000;
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
    "admin.lightning-currents",
    useCallback(() => {
      void refreshAll();
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

  // 导入中弹窗展示进度
  const importProgressModalOpen = !!activeImportId && (activeStatus === "processing" || activeStatus === "pending");

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

  const openImageModal = (record: LightningDistributionRecord) => {
    setSelectedForImage(record);
    setImageModalOpen(true);
  };

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

  // ---- 表格列 ----
  const columns = useMemo<ColumnsType<LightningDistributionRecord>>(
    () => [
      {
        title: "城市",
        dataIndex: "city",
        width: 110,
        render: (value: string | null) => value || "-",
      },
      {
        title: "地点标签",
        dataIndex: "location_tag",
        width: 130,
        render: (value: string | null) => value || "-",
      },
      {
        title: "文件名",
        dataIndex: "source_file_name",
        width: 200,
        render: (value: string) => value || "-",
      },
      {
        title: "年份",
        dataIndex: "event_year",
        width: 70,
        render: (value: number | null) => value ?? "-",
      },
      {
        title: "导入时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => new Date(value).toLocaleString("zh-CN", { hour12: false }),
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
        title: "整体Ng",
        dataIndex: "overall_ng",
        width: 90,
        render: (value: number | null) => formatNumber(value, 4),
      },
      {
        title: "最大电流(kA)",
        dataIndex: "max_abs_current",
        width: 110,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "平均电流(kA)",
        dataIndex: "avg_abs_current",
        width: 110,
        render: (value: number | null) => formatNumber(value, 2),
      },
      {
        title: "操作",
        key: "actions",
        width: canManage ? 220 : 160,
        fixed: "right",
        render: (_: unknown, row) => (
          <Space wrap>
            <Button size="small" onClick={() => openImageModal(row)}>
              看图
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
          </Space>
        ),
      },
    ],
    [canManage, deleteMutation],
  );

  const renderRecordCard = (record: LightningDistributionRecord) => {
    const dropdownItems: MenuProps["items"] = [
      {
        key: "image",
        label: "查看密度图",
        onClick: () => openImageModal(record),
      },
      ...(canManage
        ? [
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
              {new Date(record.create_date).toLocaleString("zh-CN", { hour12: false })}
            </Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">有效点数</Typography.Text>
            <Typography.Text>{record.valid_count}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">整体 Ng</Typography.Text>
            <Typography.Text>{formatNumber(record.overall_ng, 4)}</Typography.Text>
          </div>
          <div className="admin-lightning-distribution-batch-card-field">
            <Typography.Text type="secondary">电流范围</Typography.Text>
            <Typography.Text>
              {formatNumber(record.max_abs_current, 2)} kA (最大)
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
      <AntCard
        className="admin-lightning-distribution-page-card"
        title="地闪密度统计"
        extra={
          <Space>
            {canManage && (
              <Button onClick={() => setFillModalOpen(true)}>线路密度填充</Button>
            )}
            {canManage && (
              <Button type="primary" onClick={() => setImportModalOpen(true)}>
                导入
              </Button>
            )}
          </Space>
        }
      >
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
            scroll={{ x: 1300 }}
            locale={{
              emptyText: (
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description="未找到符合筛选条件的地闪分布记录。"
                />
              ),
            }}
          />
        )}
      </AntCard>

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

      <ImageViewModal
        record={selectedForImage}
        open={imageModalOpen}
        onClose={() => {
          setImageModalOpen(false);
          setSelectedForImage(null);
        }}
        fetchWithAuth={fetchWithAuth}
      />

      {canManage && (
        <FillDensityModal
          open={fillModalOpen}
          onClose={() => {
            setFillModalOpen(false);
            fillForm.resetFields();
          }}
          fetchWithAuth={fetchWithAuth}
          form={fillForm}
        />
      )}

      <Modal
        title="导入处理中"
        open={importProgressModalOpen}
        footer={null}
        closable={false}
        width={420}
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Typography.Text>
            正在{activeRecord ? STAGE_META[activeRecord.stage] ?? activeRecord.stage : "解析"}文件…
          </Typography.Text>
          <Progress percent={activeRecord?.progress ?? 0} status={activeStatus === "failed" ? "exception" : "active"} />
        </Space>
      </Modal>
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
    queryKey: ["/api/v1/power-lines", lineSearchText],
    enabled: open,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "200");
      params.set("offset", "0");
      if (lineSearchText.trim()) params.set("keyword", lineSearchText.trim());
      const response = await fetchWithAuth(`/api/v1/power-lines?${params.toString()}`);
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
          <Form.Item name="city" label="城市/区域" rules={[{ required: true, message: "请填写城市/区域" }]}>
            <Input placeholder="例如 上海" />
          </Form.Item>
          <Form.Item name="region_id" label="区域标识" rules={[{ required: true, message: "请填写区域标识" }]}>
            <Input placeholder="例如 SH-001" />
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

function ImageViewModal({
  record,
  open,
  onClose,
  fetchWithAuth,
}: {
  record: LightningDistributionRecord | null;
  open: boolean;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
}) {
  const imageQuery = useQuery({
    queryKey: ["/api/v1/lightning-currents/distributions", record?.id, "image"],
    enabled: open && !!record,
    queryFn: async () => {
      if (!record) return null;
      const response = await fetchWithAuth(`/api/v1/lightning-currents/distributions/${record.id}/image`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningDistributionImageResponse;
    },
  });

  const imageUrl = imageQuery.data?.image_url ?? null;

  return (
    <Modal
      title={record ? `密度图 - ${record.source_file_name || "未命名"}` : "密度图"}
      open={open}
      onCancel={onClose}
      footer={null}
      width={900}
      destroyOnClose
    >
      {record && (
        <Space direction="vertical" size={16} className="w-full">
          <Descriptions bordered size="small" column={3}>
            <Descriptions.Item label="城市">{record.city || "-"}</Descriptions.Item>
            <Descriptions.Item label="地点标签">{record.location_tag || "-"}</Descriptions.Item>
            <Descriptions.Item label="年份">{record.event_year ?? "-"}</Descriptions.Item>
            <Descriptions.Item label="有效点数">{record.valid_count}</Descriptions.Item>
            <Descriptions.Item label="面积(km²)">{formatNumber(record.area_km2, 3)}</Descriptions.Item>
            <Descriptions.Item label="统计年限">{formatNumber(record.data_years, 3)}</Descriptions.Item>
            <Descriptions.Item label="整体 Ng">{formatNumber(record.overall_ng, 4)}</Descriptions.Item>
            <Descriptions.Item label="Imax(kA)">{formatNumber(record.max_abs_current, 2)}</Descriptions.Item>
            <Descriptions.Item label="Iavg(kA)">{formatNumber(record.avg_abs_current, 2)}</Descriptions.Item>
            <Descriptions.Item label="正极数量">{record.positive_count}</Descriptions.Item>
            <Descriptions.Item label="负极数量">{record.negative_count}</Descriptions.Item>
            <Descriptions.Item label="未知极性">{record.unknown_count}</Descriptions.Item>
          </Descriptions>

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
        </Space>
      )}
    </Modal>
  );
}

function FillDensityModal({
  open,
  onClose,
  fetchWithAuth,
  form,
}: {
  open: boolean;
  onClose: () => void;
  fetchWithAuth: (path: string, init?: RequestInit, retryOnUnauthorized?: boolean) => Promise<Response>;
  form: ReturnType<typeof Form.useForm<{ line_id: string | null; region_id: string; years: number | null; radius_km: number | null }>>[0];
}) {
  const [lineSearchText, setLineSearchText] = useState("");
  const [success, setSuccess] = useState("");
  const [error, setError] = useState("");

  const linesQuery = useQuery({
    queryKey: ["/api/v1/power-lines", lineSearchText],
    enabled: open,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", "200");
      params.set("offset", "0");
      if (lineSearchText.trim()) params.set("keyword", lineSearchText.trim());
      const response = await fetchWithAuth(`/api/v1/power-lines?${params.toString()}`);
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

  const fillMutation = useMutation({
    mutationFn: async () => {
      const values = form.getFieldsValue(true);
      if (!values.line_id) {
        throw new Error("请先选择线路");
      }
      const body: Record<string, unknown> = { line_id: values.line_id };
      if (values.region_id?.trim()) body.region_id = values.region_id.trim();
      if (values.years) body.years = values.years;
      if (values.radius_km) body.radius_km = values.radius_km;
      const response = await fetchWithAuth("/api/v1/lightning-currents/fill-density", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LightningFillDensityResponse;
    },
    onSuccess: (payload) => {
      setError("");
      setSuccess(`线路密度回填任务已提交（任务ID: ${payload.task_id}）。完成后请在线路管理页面刷新查看杆塔密度。`);
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "回填任务提交失败");
    },
  });

  return (
    <Modal
      title="线路密度填充"
      open={open}
      onCancel={onClose}
      footer={null}
      width={560}
      destroyOnClose
    >
      <Form form={form} layout="vertical">
        <Form.Item name="line_id" label="选择线路" rules={[{ required: true, message: "请选择线路" }]}>
          <Select
            showSearch
            placeholder="选择线路（按该线路关联的地闪分布计算）"
            filterOption={false}
            onSearch={setLineSearchText}
            notFoundContent={linesQuery.isLoading ? <Spin size="small" /> : undefined}
            options={lineOptions}
          />
        </Form.Item>
        <div className="grid gap-3 md:grid-cols-3">
          <Form.Item name="region_id" label="区域标识">
            <Input placeholder="可选" />
          </Form.Item>
          <Form.Item name="years" label="统计年数">
            <InputNumber className="w-full" min={0.1} step={0.5} placeholder="默认取分布记录" />
          </Form.Item>
          <Form.Item name="radius_km" label="缓冲半径(km)">
            <InputNumber className="w-full" min={0.05} max={50} step={0.5} placeholder="默认按电压等级" />
          </Form.Item>
        </div>
      </Form>
      <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
        <Button
          type="primary"
          loading={fillMutation.isPending}
          onClick={() => fillMutation.mutate()}
        >
          提交回填
        </Button>
      </div>
      {success && <Typography.Paragraph type="success" style={{ marginTop: 12 }}>{success}</Typography.Paragraph>}
      {error && <Typography.Paragraph type="danger" style={{ marginTop: 12 }}>{error}</Typography.Paragraph>}
    </Modal>
  );
}
