"use client";

import { ReloadOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card as AntdCard,
  Col,
  Form,
  Image,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Tag,
  Typography,
  Upload,
  type CardProps,
  type UploadFile,
} from "antd";
import type { ComponentType, RefAttributes } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";

// ── Types ───────────────────────────────────────────────────────────

type TravelingWaveStatusResponse = {
  python_available: boolean;
  numpy_available: boolean;
  scipy_available: boolean;
  matplotlib_available: boolean;
  missing_components: string[];
  error: string | null;
};

type TravelingWaveParseResult = {
  wave_batch_id: string;
  vo_level: string;
  sample_frequency: number;
  head_time: string;
  head_time_parsed: string | null;
  left_dist_ohl: number;
  right_dist_ohl: number;
  data_len: number;
  line_name: string;
};

type TravelingWaveAnalyzeResponse = {
  id: string;
  status: "pending" | "running" | "success" | "failed";
  created_at: string | null;
  finished_at: string | null;
  phase_a_info: TravelingWaveParseResult | null;
  phase_b_info: TravelingWaveParseResult | null;
  phase_c_info: TravelingWaveParseResult | null;
  sample_rate_hz: number;
  vo_level: string;
  line_name: string;
  left_dist_ohl: number;
  right_dist_ohl: number;
  tower_no: string | null;
  fault_distance_km: number | null;
  three_phase_chart: string | null;
  zero_sequence_chart: string | null;
  error_message: string | null;
  log_text: string | null;
};

type AnalyzeFormValues = {
  input_mode: "upload" | "path";
  file_a?: UploadFile[];
  file_b?: UploadFile[];
  file_c?: UploadFile[];
  path_a?: string;
  path_b?: string;
  path_c?: string;
  sample_rate_hz: number;
  fault_distance_km?: number | null;
  tower_no?: string;
};

// ── Helpers ─────────────────────────────────────────────────────────

const Card = AntdCard as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

const DEFAULT_FORM_VALUES: AnalyzeFormValues = {
  input_mode: "upload",
  sample_rate_hz: 1_000_000,
};

function formatStatusTag(status: TravelingWaveAnalyzeResponse["status"] | null | undefined) {
  if (status === "success") return <Tag color="success">成功</Tag>;
  if (status === "running") return <Tag color="processing">运行中</Tag>;
  if (status === "failed") return <Tag color="error">失败</Tag>;
  if (status === "pending") return <Tag color="blue">排队中</Tag>;
  return <Tag>-</Tag>;
}

function formatInfoRow(label: string, value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return `${label}: ${value}`;
}

function getMissingComponents(status: TravelingWaveStatusResponse | null): string[] {
  if (!status) return [];
  if (Array.isArray(status.missing_components) && status.missing_components.length > 0) {
    return status.missing_components;
  }
  // Fallback: derive from available booleans (older backend without structured field)
  const missing: string[] = [];
  if (!status.python_available) missing.push("python");
  if (!status.numpy_available) missing.push("numpy");
  if (!status.scipy_available) missing.push("scipy");
  if (!status.matplotlib_available) missing.push("matplotlib");
  return missing;
}

function formatMissingComponents(missing: string[]): string {
  if (missing.length === 0) return "";
  const labels: Record<string, string> = {
    python: "Python",
    numpy: "numpy",
    scipy: "scipy",
    matplotlib: "matplotlib",
  };
  const names = missing.map((name) => labels[name] || name);
  return names.join("、");
}

function buildParseInfoBlock(label: string, info: TravelingWaveParseResult | null): string {
  if (!info) return `${label}: 未提供`;
  return [
    `${label}:`,
    `  BatchID: ${info.wave_batch_id || "-"}`,
    `  采样率: ${info.sample_frequency} Hz`,
    `  HeadTime: ${info.head_time || "-"}`,
    `  数据点数: ${info.data_len}`,
    `  电压等级: ${info.vo_level || "-"}`,
  ].join("\n");
}

// ── Component ───────────────────────────────────────────────────────

export default function AdminTravelingWavePage() {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const [form] = Form.useForm<AnalyzeFormValues>();
  const [status, setStatus] = useState<TravelingWaveStatusResponse | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [lastValues, setLastValues] = useState<AnalyzeFormValues | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const canRead = hasPermission("traveling_wave.read") || hasPermission("traveling_wave.manage");
  const canManage = hasPermission("traveling_wave.manage");

  useToastFeedback({
    errorMessage: error,
    successMessage: success,
    errorTitle: "分析失败",
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });

  // ── Status check ────────────────────────────────────────────────

  const loadStatus = useCallback(async () => {
    if (!user || !canRead) return;
    setStatusLoading(true);
    setError("");
    try {
      const response = await fetchWithAuth("/api/v1/traveling-wave/status");
      if (!response.ok) throw new Error(await readApiError(response));
      const payload = (await response.json()) as TravelingWaveStatusResponse;
      setStatus(payload);
    } catch (candidate) {
      setError(candidate instanceof Error ? candidate.message : "行波分析状态检测失败");
    } finally {
      setStatusLoading(false);
    }
  }, [canRead, fetchWithAuth, user]);

  useEffect(() => {
    queueMicrotask(() => {
      void loadStatus();
    });
  }, [loadStatus]);

  // ── Submission ──────────────────────────────────────────────────

  const analyzeMutation = useMutation({
    mutationFn: async (values: AnalyzeFormValues) => {
      if (values.input_mode === "upload") {
        // Upload mode: use FormData
        const formData = new FormData();
        if (values.file_a?.[0]?.originFileObj) {
          formData.append("file_a", values.file_a[0].originFileObj as Blob);
        }
        if (values.file_b?.[0]?.originFileObj) {
          formData.append("file_b", values.file_b[0].originFileObj as Blob);
        }
        if (values.file_c?.[0]?.originFileObj) {
          formData.append("file_c", values.file_c[0].originFileObj as Blob);
        }
        formData.append("sample_rate_hz", String(values.sample_rate_hz));
        if (values.fault_distance_km) {
          formData.append("fault_distance_km", String(values.fault_distance_km));
        }
        if (values.tower_no) {
          formData.append("tower_no", values.tower_no);
        }

        const response = await fetchWithAuth("/api/v1/traveling-wave/analyze/upload", {
          method: "POST",
          body: formData,
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return (await response.json()) as TravelingWaveAnalyzeResponse;
      }

      // Path mode: JSON payload
      const response = await fetchWithAuth("/api/v1/traveling-wave/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          file_a: values.path_a?.trim() || null,
          file_b: values.path_b?.trim() || null,
          file_c: values.path_c?.trim() || null,
          sample_rate_hz: values.sample_rate_hz,
          fault_distance_km: values.fault_distance_km ?? null,
          tower_no: values.tower_no?.trim() || null,
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as TravelingWaveAnalyzeResponse;
    },
    onSuccess: (payload) => {
      setActiveJobId(payload.id);
      setError("");
      setSuccess(
        payload.status === "success"
          ? "分析完成"
          : payload.status === "failed"
            ? "分析失败"
            : "分析任务已提交",
      );
    },
    onError: (candidate) => {
      setSuccess("");
      setError(candidate instanceof Error ? candidate.message : "分析提交失败");
    },
  });

  // ── Result polling ──────────────────────────────────────────────

  const resultQuery = useQuery({
    queryKey: ["traveling-wave-result", activeJobId],
    enabled: Boolean(activeJobId) && canRead,
    queryFn: async () => {
      if (!activeJobId) throw new Error("分析记录不存在");
      const response = await fetchWithAuth(`/api/v1/traveling-wave/analyze/${activeJobId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as TravelingWaveAnalyzeResponse;
    },
    refetchInterval: (query) => {
      const detail = query.state.data as TravelingWaveAnalyzeResponse | undefined;
      return detail && (detail.status === "pending" || detail.status === "running") ? 2000 : false;
    },
  });

  // ── Handlers ────────────────────────────────────────────────────

  const handleAnalyze = async (values: AnalyzeFormValues) => {
    if (!canManage) {
      setError("缺少 traveling_wave.manage 权限");
      return;
    }
    setError("");
    setSuccess("");
    setLastValues(values);
    await analyzeMutation.mutateAsync(values);
  };

  const handleReset = () => {
    setActiveJobId(null);
    form.resetFields();
  };

  const handleRetry = async () => {
    if (!canManage) {
      setError("缺少 traveling_wave.manage 权限");
      return;
    }
    if (!lastValues) return;
    setError("");
    setSuccess("");
    await analyzeMutation.mutateAsync(lastValues);
  };

  const handleCheckEnvironment = () => {
    void loadStatus();
  };

  const result = resultQuery.data;

  const missingComponents = useMemo(() => getMissingComponents(status), [status]);
  const missingComponentsText = useMemo(() => formatMissingComponents(missingComponents), [missingComponents]);

  // ── Derived info block ──────────────────────────────────────────

  const parsedInfoText = useMemo(() => {
    if (!result) return "";
    const parts = [
      `分析 ID: ${result.id}`,
      buildParseInfoBlock("A相", result.phase_a_info),
      buildParseInfoBlock("B相", result.phase_b_info),
      buildParseInfoBlock("C相", result.phase_c_info),
      "",
      `电压等级: ${result.vo_level || "-"}`,
      `线路名称: ${result.line_name || "-"}`,
      `左档距: ${result.left_dist_ohl} m`,
      `右档距: ${result.right_dist_ohl} m`,
    ];
    if (result.tower_no) parts.push(`杆塔号: ${result.tower_no}`);
    if (result.fault_distance_km) parts.push(`故障距离: ${result.fault_distance_km} km`);
    return parts.join("\n");
  }, [result]);

  // ── Render ──────────────────────────────────────────────────────

  if (initializing) {
    return <AdminPageLoading tip="加载行波分析中..." minHeightClassName="min-h-[280px]" />;
  }
  if (!user) {
    return (
      <Card title="行波分析">
        <Typography.Text type="secondary">请先登录后访问行波分析页面。</Typography.Text>
      </Card>
    );
  }
  if (!canRead) {
    return (
      <Card title="行波分析">
        <Typography.Text type="secondary">你没有访问该页面的权限（需要 traveling_wave.read）。</Typography.Text>
      </Card>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Card
        className="admin-traveling-wave-page-card"
        title="行波分析"
        extra={
          <Space>
            <Tag color={status?.python_available ? "success" : "error"}>
              Python {status?.python_available ? "可用" : "不可用"}
            </Tag>
            <Button icon={<ReloadOutlined />} loading={statusLoading} onClick={() => void loadStatus()}>
              检测
            </Button>
          </Space>
        }
      >
        <div className="admin-traveling-wave-layout">
          {/* Left: Analysis Form */}
          <div className="admin-traveling-wave-form">
            <Typography.Title level={5} style={{ marginTop: 0 }}>分析参数</Typography.Title>
            <Form<AnalyzeFormValues>
              form={form}
              layout="vertical"
              initialValues={DEFAULT_FORM_VALUES}
              onFinish={(values) => {
                void handleAnalyze(values);
              }}
            >
              {/* Input mode switch */}
              <Form.Item name="input_mode" label="输入方式">
                <Select>
                  <Select.Option value="upload">文件上传</Select.Option>
                  <Select.Option value="path">服务端文件路径</Select.Option>
                </Select>
              </Form.Item>

              {/* File upload mode */}
              <Form.Item noStyle shouldUpdate={(prev, cur) => prev.input_mode !== cur.input_mode}>
                {({ getFieldValue }) =>
                  getFieldValue("input_mode") === "upload" ? (
                    <>
                      <Row gutter={12}>
                        <Col xs={24} md={8}>
                          <Form.Item name="file_a" label="A 相数据文件">
                            <Upload maxCount={1} accept=".txt" beforeUpload={() => false}>
                              <Button>选择文件</Button>
                            </Upload>
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                          <Form.Item name="file_b" label="B 相数据文件">
                            <Upload maxCount={1} accept=".txt" beforeUpload={() => false}>
                              <Button>选择文件</Button>
                            </Upload>
                          </Form.Item>
                        </Col>
                        <Col xs={24} md={8}>
                          <Form.Item name="file_c" label="C 相数据文件">
                            <Upload maxCount={1} accept=".txt" beforeUpload={() => false}>
                              <Button>选择文件</Button>
                            </Upload>
                          </Form.Item>
                        </Col>
                      </Row>
                    </>
                  ) : (
                    <>
                      <Form.Item name="path_a" label="A 相文件路径">
                        <Input placeholder="/path/to/A相.txt" />
                      </Form.Item>
                      <Form.Item name="path_b" label="B 相文件路径">
                        <Input placeholder="/path/to/B相.txt" />
                      </Form.Item>
                      <Form.Item name="path_c" label="C 相文件路径">
                        <Input placeholder="/path/to/C相.txt" />
                      </Form.Item>
                    </>
                  )
                }
              </Form.Item>

              {/* Parameters */}
              <Row gutter={12}>
                <Col xs={24} md={8}>
                  <Form.Item
                    name="sample_rate_hz"
                    label="采样率 (Hz)"
                    rules={[{ required: true, message: "请输入采样率" }]}
                  >
                    <InputNumber min={1000} max={100_000_000} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item name="fault_distance_km" label="故障距离 (km)">
                    <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
                  </Form.Item>
                </Col>
                <Col xs={24} md={8}>
                  <Form.Item name="tower_no" label="杆塔号">
                    <Input placeholder="如: 39号" />
                  </Form.Item>
                </Col>
              </Row>

              {/* Environment warning in submit area */}
              {missingComponents.length > 0 && (
                <Alert
                  type="warning"
                  showIcon
                  style={{ marginBottom: 16 }}
                  message="分析服务环境不完整"
                  description={`缺少依赖组件：${missingComponentsText}。任务仍可提交，但分析可能失败（由 worker 兜底报错），建议先修复服务端环境。`}
                />
              )}

              {/* Actions */}
              <Space wrap>
                <Button
                  type="primary"
                  htmlType="submit"
                  icon={<ThunderboltOutlined />}
                  disabled={!canManage || analyzeMutation.isPending}
                  loading={analyzeMutation.isPending}
                >
                  开始分析
                </Button>
                <Button onClick={handleReset}>重置</Button>
                {activeJobId && (
                  <Typography.Text type="secondary">当前分析 ID: {activeJobId}</Typography.Text>
                )}
              </Space>
            </Form>

            {/* Environment status details */}
            <div className="admin-traveling-wave-status">
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                依赖库状态：
                <Tag color={status?.numpy_available ? "success" : "error"} style={{ marginInlineStart: 6 }}>
                  numpy
                </Tag>
                <Tag color={status?.scipy_available ? "success" : "error"}>
                  scipy
                </Tag>
                <Tag color={status?.matplotlib_available ? "success" : "error"}>
                  matplotlib
                </Tag>
              </Typography.Text>
              {status?.error && (
                <Typography.Text type="danger" style={{ fontSize: 12 }}>
                  {status.error}
                </Typography.Text>
              )}
              {!status && !statusLoading && (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  尚未检测
                </Typography.Text>
              )}
            </div>
          </div>

          {/* Right: Results */}
          <div className="admin-traveling-wave-result">
            <Typography.Title level={5} style={{ marginTop: 0 }}>分析结果</Typography.Title>
            {!result && (
              <div className="admin-traveling-wave-result-empty">
                <Typography.Text type="secondary">
                  {resultQuery.isLoading ? "正在加载分析详情..." : "提交分析任务后在此查看结果。"}
                </Typography.Text>
              </div>
            )}
            {result && (
              <Space direction="vertical" size={12} style={{ width: "100%", flex: 1, minHeight: 0, display: "flex" }}>
                {/* Status */}
                <Space wrap>
                  <Typography.Text strong>状态</Typography.Text>
                  {formatStatusTag(result.status)}
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    分析 ID: {result.id}
                  </Typography.Text>
                </Space>
                {result.error_message && (
                  <Alert
                    type="error"
                    showIcon
                    message="分析失败"
                    description={result.error_message}
                    action={
                      <Space direction="vertical" size={4}>
                        {canManage && (
                          <Button
                            type="primary"
                            ghost
                            size="small"
                            icon={<ThunderboltOutlined />}
                            loading={analyzeMutation.isPending}
                            disabled={!lastValues}
                            onClick={() => void handleRetry()}
                          >
                            重试
                          </Button>
                        )}
                        <Button size="small" icon={<ReloadOutlined />} loading={statusLoading} onClick={handleCheckEnvironment}>
                          环境检测
                        </Button>
                      </Space>
                    }
                  />
                )}

                {/* Parsed Info */}
                {(result.phase_a_info || result.phase_b_info || result.phase_c_info) && (
                  <pre className="admin-traveling-wave-pre admin-traveling-wave-info">
                    {parsedInfoText}
                  </pre>
                )}

                {/* Charts */}
                {result.three_phase_chart && (
                  <div style={{ textAlign: "center" }}>
                    <Typography.Text strong>三相行波波形 + 零序分量</Typography.Text>
                    <br />
                    <Image
                      src={`data:image/png;base64,${result.three_phase_chart}`}
                      alt="三相行波波形图"
                      style={{ maxWidth: "100%", marginTop: 8 }}
                    />
                  </div>
                )}

                {/* Analysis Log */}
                <Typography.Text strong style={{ marginTop: 4 }}>分析日志</Typography.Text>
                <pre className="admin-traveling-wave-pre admin-traveling-wave-log">
                  {result.log_text || "无日志"}
                </pre>
              </Space>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
