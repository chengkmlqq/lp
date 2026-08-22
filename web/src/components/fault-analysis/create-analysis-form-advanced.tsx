import { Form, Input, Select, Upload, Button, FormInstance, Space, message, Modal } from "antd";
import { UploadOutlined, FileTextOutlined, TableOutlined, LineChartOutlined, CameraOutlined, DownloadOutlined } from "@ant-design/icons";
import type { CreateFaultAnalysisFormValues } from "./types";
import { TempFileUpload } from "./temp-file-upload";
import type { FaultAnalysisTempFile } from "./types";
import { parseExcelFile, generateImportTemplate, generateWaveDataTemplate, generateLightningTemplate, generateWaveTemplate, generateOpticalTemplate } from "@/lib/excel-import-utils";

interface CreateAnalysisFormAdvancedProps {
  form: FormInstance<CreateFaultAnalysisFormValues>;
  lines: Array<{ id: string; name: string; code: string }>;
  linesLoading?: boolean;
  onSubmit: (values: CreateFaultAnalysisFormValues) => void;
  submitText?: string;
  submitting?: boolean;
}

export function CreateAnalysisFormAdvanced({ form, lines, linesLoading, onSubmit, submitText = "提交分析", submitting }: CreateAnalysisFormAdvancedProps) {
  // 处理Excel导入
  const handleExcelImport = async (file: File) => {
    try {
      const data = await parseExcelFile(file);

      // 将解析的数据填充到表单
      form.setFieldsValue(data as Partial<CreateFaultAnalysisFormValues>);

      message.success('Excel数据导入成功');
    } catch (error) {
      message.error(`导入失败: ${error instanceof Error ? error.message : '未知错误'}`);
    }

    // 阻止自动上传
    return false;
  };

  // 下载导入模板
  const handleDownloadTemplate = () => {
    try {
      generateImportTemplate();
      message.success('模板下载成功');
    } catch {
      message.error('模板下载失败');
    }
  };

  // 下载录波数据模板
  const handleDownloadWaveDataTemplate = () => {
    try {
      generateWaveDataTemplate();
      message.success('录波数据模板下载成功');
    } catch {
      message.error('录波数据模板下载失败');
    }
  };

  // 下载雷电定位数据模板
  const handleDownloadLightningTemplate = () => {
    try {
      generateLightningTemplate();
      message.success('雷电定位数据模板下载成功');
    } catch {
      message.error('雷电定位数据模板下载失败');
    }
  };

  // 下载行波数据模板
  const handleDownloadWaveTemplate = () => {
    try {
      generateWaveTemplate();
      message.success('行波数据模板下载成功');
    } catch {
      message.error('行波数据模板下载失败');
    }
  };

  // 下载光学监控数据模板
  const handleDownloadOpticalTemplate = () => {
    try {
      generateOpticalTemplate();
      message.success('光学监控数据模板下载成功');
    } catch {
      message.error('光学监控数据模板下载失败');
    }
  };

  // LP-420：文件字段 + 对应 previewKind 映射
  const FILE_KIND_MAP: Array<{
    field: keyof Pick<
      CreateFaultAnalysisFormValues,
      "wave_data_file" | "lightning_data_file" | "ledger_data_file" | "traveling_wave_file" | "optical_data_file"
    >;
    kind: "wave_data" | "lightning_data" | "ledger_data" | "traveling_wave" | "optical_data";
    label: string;
  }> = [
    { field: "wave_data_file", kind: "wave_data", label: "录波数据" },
    { field: "lightning_data_file", kind: "lightning_data", label: "雷电定位数据" },
    { field: "ledger_data_file", kind: "ledger_data", label: "判别台账" },
    { field: "traveling_wave_file", kind: "traveling_wave", label: "分布式行波数据" },
    { field: "optical_data_file", kind: "optical_data", label: "光学监控数据" },
  ];

  // LP-420：提交前置内容校验汇总
  const handleFinish = (values: CreateFaultAnalysisFormValues) => {
    const allErrors: string[] = [];
    const allWarnings: string[] = [];
    const pendingChecks: Array<{ files: FaultAnalysisTempFile[]; label: string }> = [];

    for (const { field, label } of FILE_KIND_MAP) {
      const files = values[field] ?? [];
      if (files.length === 0) {
        continue;
      }
      const filesWithPreview = files.filter((f) => !!f.preview);
      const filesWithoutPreview = files.filter((f) => !f.preview);
      if (filesWithoutPreview.length > 0) {
        pendingChecks.push({ files, label });
        continue;
      }
      for (const file of filesWithPreview) {
        for (const err of file.preview?.errors ?? []) {
          allErrors.push(`【${label}】${file.name}：${err}`);
        }
        for (const warn of file.preview?.warnings ?? []) {
          allWarnings.push(`【${label}】${file.name}：${warn}`);
        }
      }
    }

    if (pendingChecks.length > 0) {
      Modal.confirm({
        title: "部分文件尚未完成内容校验",
        content: `${pendingChecks.map((p) => p.label).join("、")} 仍有文件在解析中或尚未校验，确定要提交吗？`,
        okText: "仍要提交",
        cancelText: "等待校验",
        onOk: () => onSubmit(values),
      });
      return;
    }

    if (allErrors.length > 0) {
      Modal.confirm({
        title: "以下文件存在格式错误，无法参与判别",
        content: (
          <div className="max-h-[300px] overflow-y-auto">
            {allErrors.map((err, i) => (
              <div key={i} className="mb-1 text-red-600">
                {err}
              </div>
            ))}
            <div className="mt-2 text-gray-500">请移除对应文件后重新提交。</div>
          </div>
        ),
        okText: "我知道了",
        cancelButtonProps: { style: { display: "none" } },
        onOk: () => {},
      });
      return;
    }

    if (allWarnings.length > 0) {
      Modal.confirm({
        title: "部分文件疑似缺少字段",
        content: (
          <div className="max-h-[300px] overflow-y-auto">
            {allWarnings.slice(0, 10).map((w, i) => (
              <div key={i} className="mb-1 text-yellow-600">
                {w}
              </div>
            ))}
            {allWarnings.length > 10 && <div className="mt-1 text-gray-500">...等共 {allWarnings.length} 条提示</div>}
            <div className="mt-2 text-gray-500">仍要提交吗？</div>
          </div>
        ),
        okText: "仍要提交",
        cancelText: "返回修改",
        onOk: () => onSubmit(values),
      });
      return;
    }

    onSubmit(values);
  };

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={handleFinish}
      className="admin-fault-analysis-form-tabs"
    >
      {/* 上：故障线路 */}
      <div className="admin-fault-analysis-form-section">
        <div className="admin-fault-analysis-form-section-title">故障线路</div>
        <div className="px-1">
          <Form.Item
            label="请选择故障线路名称"
            name="line_id"
            rules={[{ required: true, message: "请选择故障线路" }]}
          >
            <Select
              placeholder="请选择故障线路名称"
              loading={linesLoading}
              showSearch
              optionFilterProp="children"
              filterOption={(input, option) =>
                (option?.label ?? "").toLowerCase().includes(input.toLowerCase())
              }
              options={lines.map((line) => ({
                value: line.id,
                label: `${line.name} (${line.code})`,
              }))}
            />
          </Form.Item>
        </div>
      </div>

      {/* 中：故障信息 */}
      <div className="admin-fault-analysis-form-section">
        <div className="admin-fault-analysis-form-section-title">故障信息</div>
        <div className="space-y-4 px-1">
          <div className="flex items-center justify-between">
            <div />
            <Space size="small">
              <Button
                size="small"
                icon={<DownloadOutlined />}
                className="fault-analysis-step-button"
                onClick={handleDownloadTemplate}
              >
                下载模板
              </Button>
              <Upload
                accept=".xlsx,.xls"
                showUploadList={false}
                beforeUpload={handleExcelImport}
              >
                <Button size="small" icon={<UploadOutlined />} className="fault-analysis-step-button">
                  Excel导入
                </Button>
              </Upload>
            </Space>
          </div>

          <Form.Item
            label="录波记录厂站"
            name="station_name"
            rules={[{ required: true, message: "请输入录波记录厂站" }]}
          >
            <Input placeholder="广东河源500kV上寨变" />
          </Form.Item>

          <Space.Compact className="w-full">
            <Form.Item
              label="故障时刻"
              name="fault_time"
              className="flex-1 mb-0"
              rules={[{ required: true, message: "请输入故障时刻" }]}
            >
              <Input placeholder="2023-03-27 20:20:31.939" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label="故障线路名称"
              name="fault_line_name"
              className="flex-1 mb-0"
              rules={[{ required: true, message: "请输入故障线路名称" }]}
            >
              <Input placeholder="220kV 龙和线" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact className="w-full">
            <Form.Item
              label="故障相"
              name="fault_phase"
              className="flex-1 mb-0"
              rules={[{ required: true, message: "请选择故障相" }]}
            >
              <Select
                placeholder="A/B/C/AN/BN/CN/AB/BC/AC/ABC/ABN/BCN/ACN"
                options={[
                  { value: "A", label: "A" },
                  { value: "B", label: "B" },
                  { value: "C", label: "C" },
                  { value: "AN", label: "AN" },
                  { value: "BN", label: "BN" },
                  { value: "CN", label: "CN" },
                  { value: "AB", label: "AB" },
                  { value: "BC", label: "BC" },
                  { value: "AC", label: "AC" },
                  { value: "ABC", label: "ABC" },
                  { value: "ABN", label: "ABN" },
                  { value: "BCN", label: "BCN" },
                  { value: "ACN", label: "ACN" },
                ]}
              />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label="故障持续时间(ms)"
              name="fault_duration"
              className="flex-1 mb-0"
              rules={[]}
            >
              <Input type="number" placeholder="64" />
            </Form.Item>
          </Space.Compact>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="重合闸情况"
              name="reclosure_status"
              className="mb-0"
              rules={[{ required: true, message: "请选择重合闸情况" }]}
            >
              <Select
                placeholder="成功"
                options={[
                  { value: "success", label: "成功" },
                  { value: "failed", label: "失败" },
                  { value: "not_applicable", label: "不适用" },
                ]}
              />
            </Form.Item>
            <Form.Item
              label="故障相电压(V)"
              name="fault_voltage"
              className="mb-0"
            >
              <Input type="number" placeholder="37.04" />
            </Form.Item>
            <Form.Item
              label="故障相电流(A)"
              name="fault_current"
              className="mb-0"
            >
              <Input type="number" placeholder="1.3" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="最大零序电流(A)"
              name="max_zero_current"
              className="mb-0"
            >
              <Input type="number" placeholder="1.45" />
            </Form.Item>
            <Form.Item
              label="零序补偿系数K"
              name="zero_compensation"
              className="mb-0"
            >
              <Input type="number" placeholder="0.52" />
            </Form.Item>
            <Form.Item
              label="故障电阻Rm(Ω)"
              name="fault_resistance"
              className="mb-0"
            >
              <Input type="number" placeholder="0.883" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="线路总长度L(km)"
              name="line_length"
              className="mb-0"
            >
              <Input type="number" placeholder="89.77" />
            </Form.Item>
            <Form.Item
              label="线路正序灵敏角(°)"
              name="line_angle"
              className="mb-0"
            >
              <Input type="number" placeholder="85" />
            </Form.Item>
            <Form.Item
              label="线路正序阻抗定值(Ω)"
              name="line_impedance"
              className="mb-0"
            >
              <Input type="number" placeholder="28.520" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="雷电流幅值I(kA)"
              name="lightning_current"
              className="mb-0"
            >
              <Input placeholder="无/20.3kA" />
            </Form.Item>
            <Form.Item
              label="雷电定位经度(°)"
              name="lightning_longitude"
              className="mb-0"
            >
              <Input type="number" placeholder="无/114.50476" />
            </Form.Item>
            <Form.Item
              label="雷电定位纬度(°)"
              name="lightning_latitude"
              className="mb-0"
            >
              <Input type="number" placeholder="无/23.79996" />
            </Form.Item>
          </div>

          <Space.Compact className="w-full">
            <Form.Item
              label="录波测距(km)"
              name="wave_distance"
              className="flex-1 mb-0"
            >
              <Input type="number" placeholder="16.022" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label="行波测距(km)"
              name="traveling_wave_distance"
              className="flex-1 mb-0"
            >
              <Input type="number" placeholder="16.51" />
            </Form.Item>
          </Space.Compact>

          <Space.Compact className="w-full">
            <Form.Item
              label="光学接闪位置(绕击/反击/分叉)"
              name="optical_position"
              className="flex-1 mb-0"
            >
              <Input placeholder="无/A/B/C/G/AB/BC/AC/AG/BG/CG/AN/BN/CN" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label="光学设备安装位置"
              name="optical_device_location"
              className="flex-1 mb-0"
            >
              <Input placeholder="65#" />
            </Form.Item>
          </Space.Compact>
        </div>
      </div>

      {/* 下：分析数据 */}
      <div className="admin-fault-analysis-form-section">
        <div className="admin-fault-analysis-form-section-title">分析数据</div>
        <div className="px-1 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <div className="flex items-center justify-between w-full mb-1">
                <FileTextOutlined className="text-4xl text-blue-600" />
                <DownloadOutlined className="text-lg cursor-pointer" size={24} onClick={handleDownloadWaveDataTemplate} title="下载模板" />
              </div>
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">录波数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .txt/.json/.csv/.pdf/.xlsx 格式</div>
              </div>
              <Form.Item name="wave_data_file" className="mb-0">
                <TempFileUpload accept=".txt,.json,.csv,.pdf,.xlsx" maxSizeMb={50} buttonLabel="选择文件" previewKind="wave_data" />
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <div className="flex items-center justify-between w-full mb-1">
                <TableOutlined className="text-4xl text-blue-600" />
                <DownloadOutlined className="text-lg cursor-pointer" size={24} onClick={handleDownloadLightningTemplate} title="下载模板" />
              </div>
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">雷电定位数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .xls/.xlsx/.csv 格式</div>
              </div>
              <Form.Item name="lightning_data_file" className="mb-0">
                <TempFileUpload accept=".xls,.xlsx,.csv" maxSizeMb={50} buttonLabel="选择文件" previewKind="lightning_data" />
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <div className="flex items-center justify-between w-full mb-1">
                <LineChartOutlined className="text-4xl text-blue-600" />
                <DownloadOutlined className="text-lg cursor-pointer" size={24} onClick={handleDownloadWaveTemplate} title="下载模板" />
              </div>
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">分布式行波数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .csv/.dat/.txt/.json 格式</div>
              </div>
              <Form.Item name="traveling_wave_file" className="mb-0">
                <TempFileUpload accept=".csv,.dat,.txt,.json" maxSizeMb={50} buttonLabel="选择文件" previewKind="traveling_wave" />
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <div className="flex items-center justify-between w-full mb-1">
                <CameraOutlined className="text-4xl text-blue-600" />
                <DownloadOutlined className="text-lg cursor-pointer" size={24} onClick={handleDownloadOpticalTemplate} title="下载模板" />
              </div>
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">光学监控数据</div>
                <div className="text-xs text-gray-500 mb-3">支持图片或视频格式</div>
              </div>
              <Form.Item name="optical_data_file" className="mb-0">
                <TempFileUpload accept="image/*,video/*" maxSizeMb={50} buttonLabel="选择文件" previewKind="optical_data" />
              </Form.Item>
            </div>

          </div>
        </div>
      </div>

      <div className="admin-fault-analysis-form-actions">
        <Button type="primary" htmlType="submit" loading={submitting}>
          {submitText}
        </Button>
      </div>
    </Form>
  );
}
