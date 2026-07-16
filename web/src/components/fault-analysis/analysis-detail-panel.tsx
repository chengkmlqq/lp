import { Descriptions, Spin, Alert, Typography, Tag, Space, Button } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import type { FaultAnalysis, FaultAnalysisDetail } from "./types";

const { Title } = Typography;

interface AnalysisDetailPanelProps {
  analysis: FaultAnalysis | null;
  detail: FaultAnalysisDetail | null;
  loading?: boolean;
  error?: Error | null;
  onViewFullReport?: (id: string) => void;
}

const statusConfig = {
  pending: { text: "待处理", color: "default" as const },
  processing: { text: "处理中", color: "processing" as const },
  completed: { text: "已完成", color: "success" as const },
  failed: { text: "失败", color: "error" as const },
};

const riskConfig = {
  low: { text: "低风险", color: "success" as const },
  medium: { text: "中风险", color: "warning" as const },
  high: { text: "高风险", color: "error" as const },
  critical: { text: "严重", color: "error" as const },
};

export function AnalysisDetailPanel({ analysis, detail, loading, error, onViewFullReport }: AnalysisDetailPanelProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin size="large" />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载失败"
        description={error.message}
      />
    );
  }

  if (!analysis) {
    return (
      <Alert
        type="info"
        showIcon
        message="请选择一个故障分析记录查看详情"
      />
    );
  }

  const displayData = detail || analysis;
  const status = statusConfig[displayData.status];
  const risk = riskConfig[displayData.risk_level];

  return (
    <Space direction="vertical" size={16} className="w-full">
      <div className="flex items-start justify-between">
        <div>
          <Title level={4}>{displayData.title}</Title>
          <Space size={8}>
            <Tag color={status.color}>{status.text}</Tag>
            <Tag color={risk.color}>{risk.text}</Tag>
          </Space>
        </div>
        {onViewFullReport && (
          <Button
            type="primary"
            icon={<EyeOutlined />}
            onClick={() => onViewFullReport(displayData.id)}
          >
            查看完整报告
          </Button>
        )}
      </div>

      <Descriptions column={2} bordered>
        <Descriptions.Item label="线路名称">
          {displayData.line_name}
        </Descriptions.Item>
        <Descriptions.Item label="杆塔数量">
          {displayData.tower_count}
        </Descriptions.Item>
        <Descriptions.Item label="创建时间">
          {new Date(displayData.created_at).toLocaleString("zh-CN")}
        </Descriptions.Item>
        <Descriptions.Item label="更新时间">
          {new Date(displayData.updated_at).toLocaleString("zh-CN")}
        </Descriptions.Item>
        {displayData.created_by && (
          <Descriptions.Item label="创建人" span={2}>
            {displayData.created_by}
          </Descriptions.Item>
        )}
        {displayData.description && (
          <Descriptions.Item label="描述" span={2}>
            {displayData.description}
          </Descriptions.Item>
        )}
      </Descriptions>

      {detail?.parameters && Object.keys(detail.parameters).length > 0 && (
        <div>
          <Title level={5}>分析参数</Title>
          <pre className="bg-gray-50 p-4 rounded overflow-auto">
            {JSON.stringify(detail.parameters, null, 2)}
          </pre>
        </div>
      )}

      {detail?.results && Object.keys(detail.results).length > 0 && (
        <div>
          <Title level={5}>分析结果</Title>
          <pre className="bg-gray-50 p-4 rounded overflow-auto">
            {JSON.stringify(detail.results, null, 2)}
          </pre>
        </div>
      )}
    </Space>
  );
}
