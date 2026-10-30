"use client";

import { useRef, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Form,
  InputNumber,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { CheckCircleOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { getApiBaseUrl, readApiError } from "@/lib/api";
import type {
  FaultRecurrenceAnalyzeResponse,
  FaultRecurrenceDataPoint,
  FaultRecurrenceStrokeMode,
  FaultRecurrenceTempUploadResponse,
} from "@/types/auth";

type FaultRecurrenceFormValues = {
  curve_no: number;
  stroke_mode: FaultRecurrenceStrokeMode;
  withstand_level_ka: number;
};

const CURVE_OPTIONS: Array<{
  value: FaultRecurrenceFormValues["curve_no"];
  label: string;
}> = [
  { value: 1, label: "Heidler" },
  { value: 2, label: "双斜角" },
  { value: 3, label: "双指数" },
];

const STROKE_OPTIONS: Array<{
  value: FaultRecurrenceFormValues["stroke_mode"];
  label: string;
}> = [
  { value: "counterstroke", label: "反击" },
  { value: "shielding", label: "绕击" },
];

function formatNumber(value: number | null | undefined, digits = 6): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return "-";
  }
  return value.toFixed(digits).replace(/\.?0+$/, "");
}


function formatSourceMode(sourceMode: string, t: (s: string) => string = (s) => s): string {
  if (sourceMode === "legacy-sections") {
    return t("源端分段文本");
  }
  if (sourceMode === "plain-csv") {
    return t("普通 CSV/TXT");
  }
  return sourceMode || "-";
}


function resultTagColor(status: FaultRecurrenceAnalyzeResponse["result"]["status"]): string {
  if (status === "no_need") {
    return "green";
  }
  return "blue";
}

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};


export default function AdminFaultRecurrencePage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth, getAccessToken } = useAuth();
  const [form] = Form.useForm<FaultRecurrenceFormValues>();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const tabSeqRef = useRef(0);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [resultTabs, setResultTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>("");
  const [error, setError] = useState("");
  const [messageApi, contextHolder] = message.useMessage();

  const canRead = hasPermission("line.read")
    || hasPermission("line.manage")
    || hasPermission("tower.read")
    || hasPermission("tower.manage");

  useToastFeedback({
    errorMessage: error,
    clearError: () => setError(""),
  });

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!canRead) {
        throw new Error(t("缺少 line/tower 相关读取权限"));
      }
      if (!tempFileId) {
        throw new Error(t("文件尚未上传完成，请先等待上传完成再开始复现"));
      }

      const values = await form.validateFields();
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      formData.append("curve_no", String(values.curve_no));
      formData.append("stroke_mode", values.stroke_mode);
      formData.append("withstand_level_ka", String(values.withstand_level_ka));

      const response = await fetchWithAuth("/api/v1/fault-recurrence/analyze", {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultRecurrenceAnalyzeResponse;
    },
    onSuccess: (payload) => {
      const tabKey = `result-${++tabSeqRef.current}`;
      setResultTabs((previous) => [
        ...previous,
        {
          key: tabKey,
          label: (
            <Space size={6}>
              <span>{payload.source_file_name || t("复现结果")}</span>
              <Tag color={resultTagColor(payload.result.status)}>
                {payload.result.status === "no_need" ? "No need" : t("已匹配")}
              </Tag>
            </Space>
          ),
          closable: true,
          children: (
            <FaultRecurrenceResultView result={payload} />
          ),
        },
      ]);
      setActiveTabKey(tabKey);
      setError("");
      messageApi.success(t("故障复现计算完成"));
    },
    onError: (mutationError) => {
      setError(mutationError instanceof Error ? mutationError.message : t("故障复现计算失败"));
    },
  });

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    event.target.value = "";
    if (!nextFile) {
      return;
    }
    handleTempUpload(nextFile);
  };

  const handleTempUpload = (file: File) => {
    setSelectedFile(file);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
    setError("");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${getApiBaseUrl()}/api/v1/fault-recurrence/upload-temp`);
    xhr.withCredentials = true;
    const token = getAccessToken();
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
      if (!event.lengthComputable || event.total <= 0) {
        return;
      }
      const percent = Math.min(99, Math.max(0, Math.round((event.loaded / event.total) * 100)));
      setUploadProgress(percent);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        setUploadProgress(100);
        try {
          const payload = JSON.parse(xhr.responseText) as FaultRecurrenceTempUploadResponse;
          setTempFileId(payload.temp_file_id);
        } catch {
          setUploadError(t("上传成功但响应解析失败，请重新选择文件"));
        }
        return;
      }
      let detail = `HTTP ${xhr.status}`;
      try {
        const parsed = JSON.parse(xhr.responseText) as { detail?: string };
        if (parsed?.detail?.trim()) {
          detail = parsed.detail;
        }
      } catch {
        // 忽略非 JSON 响应
      }
      setUploadError(detail);
    };
    xhr.onerror = () => setUploadError(t("网络异常，上传失败"));
    xhr.onabort = () => setUploadError(t("上传已取消"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  };

  const handleRemoveFile = () => {
    setSelectedFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
  };

  const handleAnalyze = async () => {
    if (!tempFileId) {
      setError(selectedFile ? t("文件尚未上传完成，请稍候或重新选择文件") : t("请先选择基础数据文件"));
      return;
    }
    setError("");
    await analyzeMutation.mutateAsync();
  };

  const handleTabsEdit = (targetKey: React.MouseEvent | React.KeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    const removedIndex = resultTabs.findIndex((tab) => tab.key === key);
    const next = resultTabs.filter((tab) => tab.key !== key);
    setResultTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? "";
      setActiveTabKey(fallback);
    }
  };

  const handleReset = () => {
    setError("");
    setResultTabs([]);
    setActiveTabKey("");
  };

  if (initializing) {
    return (
      <Card className="surface-card">
        <div className="flex min-h-64 items-center justify-center">
          <Spin size="large" />
        </div>
      </Card>
    );
  }

  if (!user || !canRead) {
    return (
      <Card className="surface-card">
        <Alert
          type="warning"
          showIcon
          message={t("暂无访问权限")}
          description={t("故障复现工具依赖线路/杆塔读取权限，请联系管理员授权 line.read 或 tower.read。")}
        />
      </Card>
    );
  }

  return (
    <>
      {contextHolder}
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        <Card title={t("故障复现")} className="surface-card">
          <Space direction="vertical" size={16} className="w-full">
            <Typography.Paragraph type="secondary" className="!mb-0">
              迁移自源端 `FuXian` 工具：上传基础数据文件后，按波形、类型和耐雷水平计算最可能的波头/波尾组合。
            </Typography.Paragraph>
            <Alert
              type="info"
              showIcon
              message={t("输入口径")}
              description={t("支持源端 <TGanTa>/<XianLu> 分段文本，以及包含“波头时间/μs、波尾时间/μs、反击耐雷水平kA、绕击耐雷水平kA”列的普通 CSV/TXT。")}
            />
            <Form<FaultRecurrenceFormValues>
              form={form}
              layout="vertical"
              initialValues={{
                curve_no: 1,
                stroke_mode: "counterstroke",
                withstand_level_ka: 10,
              }}
            >
              <div className="flex flex-wrap items-end gap-4">
                <Form.Item<FaultRecurrenceFormValues>
                  label={t("雷电流波形")}
                  name="curve_no"
                  rules={[{ required: true, message: t("请选择雷电流波形") }]}
                  className="mb-0 min-w-[160px]"
                >
                  <Select options={CURVE_OPTIONS.map((opt) => ({ ...opt, label: t(opt.label) }))} />
                </Form.Item>
                <Form.Item<FaultRecurrenceFormValues>
                  label={t("类型")}
                  name="stroke_mode"
                  rules={[{ required: true, message: t("请选择类型") }]}
                  className="mb-0 min-w-[160px]"
                >
                  <Select options={STROKE_OPTIONS.map((opt) => ({ ...opt, label: t(opt.label) }))} />
                </Form.Item>
                <Form.Item<FaultRecurrenceFormValues>
                  label={t("耐雷水平 / kA")}
                  name="withstand_level_ka"
                  rules={[{ required: true, message: t("请输入耐雷水平") }]}
                  className="mb-0 min-w-[180px]"
                >
                  <InputNumber min={0.0001} precision={4} className="w-full" />
                </Form.Item>
                <div className="flex min-w-[320px] flex-col gap-2">
                  <Typography.Text strong>{t("基础数据文件")}</Typography.Text>
                  <Space wrap>
                    <Button onClick={() => fileInputRef.current?.click()}>
                      选择文件
                    </Button>
                    <Typography.Text type={selectedFile ? undefined : "secondary"}>
                      {selectedFile?.name || t("未选择文件")}
                    </Typography.Text>
                    {selectedFile ? (
                      <Button size="small" type="text" onClick={handleRemoveFile}>
                        {t("移除")}
                      </Button>
                    ) : null}
                  </Space>
                  {selectedFile && uploadProgress > 0 && uploadProgress < 100 ? (
                    <Progress percent={uploadProgress} size="small" style={{ width: 220 }} />
                  ) : null}
                  {selectedFile && uploadProgress >= 100 && tempFileId && !uploadError ? (
                    <Typography.Text type="success">
                      <CheckCircleOutlined /> 上传完成，可以开始复现
                    </Typography.Text>
                  ) : null}
                  {selectedFile && uploadProgress >= 100 && !tempFileId && uploadError ? (
                    <Typography.Text type="danger">{uploadError}</Typography.Text>
                  ) : null}
                </div>
                <Space wrap>
                  <Button
                    type="primary"
                    loading={analyzeMutation.isPending}
                    disabled={!tempFileId}
                    onClick={() => {
                      void handleAnalyze();
                    }}
                  >
                    {t("开始复现")}
                  </Button>
                  <Button onClick={handleReset}>
                    {t("清空结果")}
                  </Button>
                </Space>
              </div>
            </Form>
            <input
              ref={fileInputRef}
              type="file"
              accept=".txt,.csv,text/plain,text/csv"
              hidden
              onChange={handleFileChange}
            />
          </Space>
        </Card>

        {error ? (
          <Alert
            type="error"
            showIcon
            message={t("计算失败")}
            description={error}
          />
        ) : null}

        <div className="flex min-h-0 flex-1 flex-col">
          <Tabs
            type="editable-card"
            hideAdd
            activeKey={activeTabKey}
            onChange={setActiveTabKey}
            onEdit={handleTabsEdit}
            className="admin-fault-recurrence-tabs"
            items={[
              {
                key: "result",
                label: <>{t("复现结果")}</>,
                closable: false,
                children: (
                  <div className="admin-fault-recurrence-result-pane">
                    {resultTabs.length === 0 ? (
                      <Empty description={t("选择基础数据文件并执行一次复现计算后，将在这里展示结果。")} />
                    ) : (
                      <Tabs
                        type="editable-card"
                        hideAdd
                        activeKey={activeTabKey}
                        onChange={setActiveTabKey}
                        onEdit={handleTabsEdit}
                        className="admin-fault-recurrence-result-tabs"
                        items={resultTabs}
                      />
                    )}
                  </div>
                ),
              },
            ]}
          />
        </div>
      </div>
    </>
  );
}

function FaultRecurrenceResultView({
  result,
}: {
  result: FaultRecurrenceAnalyzeResponse;
}) {
  const { t } = useI18n();
  const columns: ColumnsType<FaultRecurrenceDataPoint> = [
    {
      title: t("波头时间 / μs"),
      dataIndex: "head_time_us",
      render: (value: number) => formatNumber(value, 4),
      width: 140,
    },
    {
      title: t("波尾时间 / μs"),
      dataIndex: "tail_time_us",
      render: (value: number) => formatNumber(value, 4),
      width: 140,
    },
    {
      title: t("反击耐雷水平 / kA"),
      dataIndex: "counterstroke_withstand_ka",
      render: (value: number) => formatNumber(value, 4),
      width: 180,
    },
    {
      title: t("绕击耐雷水平 / kA"),
      dataIndex: "shielding_withstand_ka",
      render: (value: number) => formatNumber(value, 4),
      width: 180,
    },
  ];

  return (
    <ModoTabs
      defaultActiveKey="overview"
      items={[
        {
          key: "overview",
          label: t("结果概览"),
          children: (
            <Space direction="vertical" size={16} className="modo-page-tabs">
              <Descriptions bordered column={{ xs: 1, sm: 1, md: 2, lg: 3 }}>
                <Descriptions.Item label={t("结果状态")}>
                  <Tag color={resultTagColor(result.result.status)}>
                    {result.result.status === "no_need" ? "No need" : t("已匹配")}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label={t("波形")}>
                  {result.curve_label}
                </Descriptions.Item>
                <Descriptions.Item label={t("类型")}>
                  {result.stroke_label}
                </Descriptions.Item>
                <Descriptions.Item label={t("耐雷水平 / kA")}>
                  {formatNumber(result.withstand_level_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label={t("输入文件")}>
                  {result.source_file_name}
                </Descriptions.Item>
                <Descriptions.Item label={t("输入格式")}>
                  {formatSourceMode(result.source_mode, t)}
                </Descriptions.Item>
                <Descriptions.Item label={t("基准点(反击) / kA")}>
                  {formatNumber(result.reference_counterstroke_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label={t("基准点(绕击) / kA")}>
                  {formatNumber(result.reference_shielding_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label={t("有效数据条数")}>
                  {result.point_count}
                </Descriptions.Item>
                <Descriptions.Item label={t("匹配波头 / μs")}>
                  {formatNumber(result.result.head_time_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label={t("匹配波尾 / μs")}>
                  {formatNumber(result.result.tail_time_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label={t("概率密度")}>
                  {formatNumber(result.result.probability_density, 12)}
                </Descriptions.Item>
              </Descriptions>
              <Alert
                type={result.result.status === "no_need" ? "success" : "info"}
                showIcon
                message={result.result.message}
              />
              {!result.reference_point_found ? (
                <Alert
                  type="warning"
                  showIcon
                  message={t("未命中 2.6/50 基准点")}
                  description={t("按源端逻辑，当前结果已回退为首条基础数据作为基准。")}
                />
              ) : null}
              {result.warnings.length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  message={t("解析提醒")}
                  description={
                    <ul className="mb-0 list-disc pl-5">
                      {result.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  }
                />
              ) : null}
            </Space>
          ),
        },
        {
          key: "detail",
          label: t("详细数据"),
          children: (
            <Card title={`${t("基础数据预览")} (${result.point_count} 条)`} className="surface-card">
              <Table<FaultRecurrenceDataPoint>
                rowKey={(record, index) => `${record.head_time_us}-${record.tail_time_us}-${index ?? 0}`}
                columns={columns}
                dataSource={result.data_points}
                pagination={{ pageSize: 10, hideOnSinglePage: false }}
                scroll={{ x: 720 }}
              />
            </Card>
          ),
        },
      ]}
    />
  );
}
