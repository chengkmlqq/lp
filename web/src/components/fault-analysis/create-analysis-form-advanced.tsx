import { Form, Input, Select, Upload, Button, FormInstance, Space, Divider, message } from "antd";
import { UploadOutlined, FileTextOutlined, TableOutlined, LineChartOutlined, CameraOutlined, DownloadOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd";
import type { CreateFaultAnalysisFormValues } from "./types";
import { parseExcelFile, generateImportTemplate } from "@/lib/excel-import-utils";

interface CreateAnalysisFormAdvancedProps {
  form: FormInstance<CreateFaultAnalysisFormValues>;
  lines: Array<{ id: string; name: string; code: string }>;
  linesLoading?: boolean;
  onSubmit: (values: CreateFaultAnalysisFormValues) => void;
}

export function CreateAnalysisFormAdvanced({ form, lines, linesLoading, onSubmit }: CreateAnalysisFormAdvancedProps) {
  // 处理Excel导入
  const handleExcelImport = async (file: File) => {
    try {
      const data = await parseExcelFile(file);

      // 将解析的数据填充到表单
      form.setFieldsValue(data as any);

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
    } catch (error) {
      message.error('模板下载失败');
    }
  };

  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onSubmit}
      className="max-h-[70vh] overflow-y-auto"
    >
      {/* 第一步：故障线路 */}
      <div className="mb-6">
        <div className="fault-analysis-step-header px-5 py-3.5 rounded-md mb-4 flex items-center gap-2">
          <span className="font-semibold">①</span>
          <span className="font-semibold">故障线路</span>
        </div>
        <div className="px-5">
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

      {/* 第二步：故障信息 */}
      <div className="mb-6">
        <div className="fault-analysis-step-header px-5 py-3.5 rounded-md mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-semibold">②</span>
            <span className="font-semibold">故障信息</span>
          </div>
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
        <div className="px-5 space-y-4">
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
              rules={[{ required: true, message: "请输入故障持续时间" }]}
            >
              <Input placeholder="64" type="number" />
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
              <Input placeholder="37.04" type="number" />
            </Form.Item>
            <Form.Item
              label="故障相电流(A)"
              name="fault_current"
              className="mb-0"
            >
              <Input placeholder="1.3" type="number" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="最大零序电流(A)"
              name="max_zero_current"
              className="mb-0"
            >
              <Input placeholder="1.45" type="number" />
            </Form.Item>
            <Form.Item
              label="零序补偿系数K"
              name="zero_compensation"
              className="mb-0"
            >
              <Input placeholder="0.52" type="number" />
            </Form.Item>
            <Form.Item
              label="故障电阻Rm(Ω)"
              name="fault_resistance"
              className="mb-0"
            >
              <Input placeholder="0.883" type="number" />
            </Form.Item>
          </div>

          <div className="grid grid-cols-3 gap-5">
            <Form.Item
              label="线路总长度L(km)"
              name="line_length"
              className="mb-0"
            >
              <Input placeholder="89.77" type="number" />
            </Form.Item>
            <Form.Item
              label="线路正序灵敏角(°)"
              name="line_angle"
              className="mb-0"
            >
              <Input placeholder="85" type="number" />
            </Form.Item>
            <Form.Item
              label="线路正序阻抗定值(Ω)"
              name="line_impedance"
              className="mb-0"
            >
              <Input placeholder="28.520" type="number" />
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
              <Input placeholder="无/114.50476" type="number" />
            </Form.Item>
            <Form.Item
              label="雷电定位纬度(°)"
              name="lightning_latitude"
              className="mb-0"
            >
              <Input placeholder="无/23.79996" type="number" />
            </Form.Item>
          </div>

          <Space.Compact className="w-full">
            <Form.Item
              label="录波测距(km)"
              name="wave_distance"
              className="flex-1 mb-0"
            >
              <Input placeholder="16.022" type="number" />
            </Form.Item>
            <div className="w-5" />
            <Form.Item
              label="行波测距(km)"
              name="traveling_wave_distance"
              className="flex-1 mb-0"
            >
              <Input placeholder="16.51" type="number" />
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

      {/* 第三步：分析数据 */}
      <div className="mb-6">
        <div className="fault-analysis-step-header px-5 py-3.5 rounded-md mb-4 flex items-center gap-2">
          <span className="font-semibold">③</span>
          <span className="font-semibold">分析数据</span>
        </div>
        <div className="px-5">
          <div className="grid grid-cols-2 gap-4">
            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <FileTextOutlined className="text-4xl text-blue-600" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">录波数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .txt 格式</div>
              </div>
              <Form.Item name="wave_data_file" className="mb-0">
                <Upload maxCount={1}>
                  <Button icon={<UploadOutlined />} size="small">选择文件</Button>
                </Upload>
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <TableOutlined className="text-4xl text-blue-600" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">雷电定位数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .xls/.xlsx 格式</div>
              </div>
              <Form.Item name="lightning_data_file" className="mb-0">
                <Upload maxCount={1}>
                  <Button icon={<UploadOutlined />} size="small">选择文件</Button>
                </Upload>
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <LineChartOutlined className="text-4xl text-blue-600" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">分布式行波数据</div>
                <div className="text-xs text-gray-500 mb-3">支持 .csv/.dat 格式</div>
              </div>
              <Form.Item name="traveling_wave_file" className="mb-0">
                <Upload maxCount={1}>
                  <Button icon={<UploadOutlined />} size="small">选择文件</Button>
                </Upload>
              </Form.Item>
            </div>

            <div className="border border-gray-300 rounded-lg p-4 flex flex-col items-center justify-center gap-3 bg-gray-50 min-h-[160px]">
              <CameraOutlined className="text-4xl text-blue-600" />
              <div className="text-center">
                <div className="font-semibold text-sm mb-1">光学监控数据</div>
                <div className="text-xs text-gray-500 mb-3">支持图片或视频格式</div>
              </div>
              <Form.Item name="optical_data_file" className="mb-0">
                <Upload maxCount={1}>
                  <Button icon={<UploadOutlined />} size="small">选择文件</Button>
                </Upload>
              </Form.Item>
            </div>
          </div>
        </div>
      </div>
    </Form>
  );
}
