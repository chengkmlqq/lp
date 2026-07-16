import { Form, Input, Select, FormInstance } from "antd";
import type { CreateFaultAnalysisFormValues } from "./types";

interface CreateAnalysisFormProps {
  form: FormInstance<CreateFaultAnalysisFormValues>;
  lines: Array<{ id: string; name: string; code: string }>;
  linesLoading?: boolean;
  onSubmit: (values: CreateFaultAnalysisFormValues) => void;
}

const analysisTypes = [
  { value: "lightning", label: "雷击故障分析" },
  { value: "insulation", label: "绝缘故障分析" },
  { value: "conductor", label: "导线故障分析" },
  { value: "tower", label: "杆塔故障分析" },
  { value: "comprehensive", label: "综合故障分析" },
];

export function CreateAnalysisForm({ form, lines, linesLoading, onSubmit }: CreateAnalysisFormProps) {
  return (
    <Form
      form={form}
      layout="vertical"
      onFinish={onSubmit}
      initialValues={{
        analysis_type: "comprehensive",
      }}
    >
      <Form.Item
        label="分析名称"
        name="title"
        rules={[
          { required: true, message: "请输入分析名称" },
          { max: 100, message: "名称不能超过100个字符" },
        ]}
      >
        <Input placeholder="例如：XX线路故障分析" />
      </Form.Item>

      <Form.Item
        label="线路"
        name="line_id"
        rules={[{ required: true, message: "请选择线路" }]}
      >
        <Select
          placeholder="请选择线路"
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

      <Form.Item
        label="分析类型"
        name="analysis_type"
        rules={[{ required: true, message: "请选择分析类型" }]}
      >
        <Select
          placeholder="请选择分析类型"
          options={analysisTypes}
        />
      </Form.Item>

      <Form.Item
        label="描述"
        name="description"
        rules={[{ max: 500, message: "描述不能超过500个字符" }]}
      >
        <Input.TextArea
          placeholder="请输入分析描述（可选）"
          rows={4}
        />
      </Form.Item>
    </Form>
  );
}
