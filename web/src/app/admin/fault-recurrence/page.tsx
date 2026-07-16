"use client";

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Descriptions,
  Empty,
  Form,
  InputNumber,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { readApiError } from "@/lib/api";
import type {
  FaultRecurrenceAnalyzeResponse,
  FaultRecurrenceDataPoint,
  FaultRecurrenceStrokeMode,
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


function formatSourceMode(sourceMode: string): string {
  if (sourceMode === "legacy-sections") {
    return "源端分段文本";
  }
  if (sourceMode === "plain-csv") {
    return "普通 CSV/TXT";
  }
  return sourceMode || "-";
}


function resultTagColor(status: FaultRecurrenceAnalyzeResponse["result"]["status"]): string {
  if (status === "no_need") {
    return "green";
  }
  return "blue";
}


export default function AdminFaultRecurrencePage() {
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const [form] = Form.useForm<FaultRecurrenceFormValues>();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [result, setResult] = useState<FaultRecurrenceAnalyzeResponse | null>(null);
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
    mutationFn: async (file: File) => {
      if (!canRead) {
        throw new Error("缺少 line/tower 相关读取权限");
      }

      const values = await form.validateFields();
      const formData = new FormData();
      formData.append("file", file);
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
      setResult(payload);
      setError("");
      messageApi.success("故障复现计算完成");
    },
    onError: (mutationError) => {
      setResult(null);
      setError(mutationError instanceof Error ? mutationError.message : "故障复现计算失败");
    },
  });

  const columns: ColumnsType<FaultRecurrenceDataPoint> = [
    {
      title: "波头时间 / μs",
      dataIndex: "head_time_us",
      render: (value: number) => formatNumber(value, 4),
      width: 140,
    },
    {
      title: "波尾时间 / μs",
      dataIndex: "tail_time_us",
      render: (value: number) => formatNumber(value, 4),
      width: 140,
    },
    {
      title: "反击耐雷水平 / kA",
      dataIndex: "counterstroke_withstand_ka",
      render: (value: number) => formatNumber(value, 4),
      width: 180,
    },
    {
      title: "绕击耐雷水平 / kA",
      dataIndex: "shielding_withstand_ka",
      render: (value: number) => formatNumber(value, 4),
      width: 180,
    },
  ];

  const handleAnalyze = async () => {
    if (!selectedFile) {
      setError("请先选择基础数据文件");
      return;
    }
    setError("");
    await analyzeMutation.mutateAsync(selectedFile);
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextFile = event.target.files?.[0] ?? null;
    setSelectedFile(nextFile);
    setError("");
    if (nextFile) {
      setResult(null);
    }
    event.target.value = "";
  };

  const handleReset = () => {
    setError("");
    setResult(null);
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
          message="暂无访问权限"
          description="故障复现工具依赖线路/杆塔读取权限，请联系管理员授权 line.read 或 tower.read。"
        />
      </Card>
    );
  }

  return (
    <>
      {contextHolder}
      <Space direction="vertical" size={16} className="w-full">
        <Card title="故障复现" className="surface-card">
          <Space direction="vertical" size={16} className="w-full">
            <Typography.Paragraph type="secondary" className="!mb-0">
              迁移自源端 `FuXian` 工具：上传基础数据文件后，按波形、类型和耐雷水平计算最可能的波头/波尾组合。
            </Typography.Paragraph>
            <Alert
              type="info"
              showIcon
              message="输入口径"
              description="支持源端 <TGanTa>/<XianLu> 分段文本，以及包含“波头时间/μs、波尾时间/μs、反击耐雷水平kA、绕击耐雷水平kA”列的普通 CSV/TXT。"
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
                  label="雷电流波形"
                  name="curve_no"
                  rules={[{ required: true, message: "请选择雷电流波形" }]}
                  className="mb-0 min-w-[160px]"
                >
                  <Select options={CURVE_OPTIONS} />
                </Form.Item>
                <Form.Item<FaultRecurrenceFormValues>
                  label="类型"
                  name="stroke_mode"
                  rules={[{ required: true, message: "请选择类型" }]}
                  className="mb-0 min-w-[160px]"
                >
                  <Select options={STROKE_OPTIONS} />
                </Form.Item>
                <Form.Item<FaultRecurrenceFormValues>
                  label="耐雷水平 / kA"
                  name="withstand_level_ka"
                  rules={[{ required: true, message: "请输入耐雷水平" }]}
                  className="mb-0 min-w-[180px]"
                >
                  <InputNumber min={0.0001} precision={4} className="w-full" />
                </Form.Item>
                <div className="flex min-w-[260px] flex-col gap-2">
                  <Typography.Text strong>基础数据文件</Typography.Text>
                  <Space wrap>
                    <Button onClick={() => fileInputRef.current?.click()}>
                      选择文件
                    </Button>
                    <Typography.Text type={selectedFile ? undefined : "secondary"}>
                      {selectedFile?.name || "未选择文件"}
                    </Typography.Text>
                  </Space>
                </div>
                <Space wrap>
                  <Button
                    type="primary"
                    loading={analyzeMutation.isPending}
                    disabled={!selectedFile}
                    onClick={() => {
                      void handleAnalyze();
                    }}
                  >
                    开始复现
                  </Button>
                  <Button onClick={handleReset}>
                    清空结果
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
            message="计算失败"
            description={error}
          />
        ) : null}

        <Card title="复现结果" className="surface-card">
          {!result ? (
            <Empty description="选择基础数据文件并执行一次复现计算后，将在这里展示结果。" />
          ) : (
            <Space direction="vertical" size={16} className="w-full">
              <Descriptions bordered column={{ xs: 1, sm: 1, md: 2, lg: 3 }}>
                <Descriptions.Item label="结果状态">
                  <Tag color={resultTagColor(result.result.status)}>
                    {result.result.status === "no_need" ? "No need" : "已匹配"}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="波形">
                  {result.curve_label}
                </Descriptions.Item>
                <Descriptions.Item label="类型">
                  {result.stroke_label}
                </Descriptions.Item>
                <Descriptions.Item label="耐雷水平 / kA">
                  {formatNumber(result.withstand_level_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label="输入文件">
                  {result.source_file_name}
                </Descriptions.Item>
                <Descriptions.Item label="输入格式">
                  {formatSourceMode(result.source_mode)}
                </Descriptions.Item>
                <Descriptions.Item label="基准点(反击) / kA">
                  {formatNumber(result.reference_counterstroke_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label="基准点(绕击) / kA">
                  {formatNumber(result.reference_shielding_ka, 4)}
                </Descriptions.Item>
                <Descriptions.Item label="有效数据条数">
                  {result.point_count}
                </Descriptions.Item>
                <Descriptions.Item label="匹配波头 / μs">
                  {formatNumber(result.result.head_time_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label="匹配波尾 / μs">
                  {formatNumber(result.result.tail_time_us, 6)}
                </Descriptions.Item>
                <Descriptions.Item label="概率密度">
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
                  message="未命中 2.6/50 基准点"
                  description="按源端逻辑，当前结果已回退为首条基础数据作为基准。"
                />
              ) : null}
              {result.warnings.length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  message="解析提醒"
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
          )}
        </Card>

        {result ? (
          <Card title={`基础数据预览 (${result.point_count} 条)`} className="surface-card">
            <Table<FaultRecurrenceDataPoint>
              rowKey={(record, index) => `${record.head_time_us}-${record.tail_time_us}-${index ?? 0}`}
              columns={columns}
              dataSource={result.data_points}
              pagination={{ pageSize: 10, hideOnSinglePage: false }}
              scroll={{ x: 720 }}
            />
          </Card>
        ) : null}
      </Space>
    </>
  );
}
