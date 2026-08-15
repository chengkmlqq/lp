import { Badge, Button, Space, Typography } from "antd";
import { ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, EyeOutlined, EditOutlined, DeleteOutlined, ThunderboltOutlined } from "@ant-design/icons";
import { Card } from "@/components/ui-antd";
import type { FaultAnalysis } from "./types";

const { Text } = Typography;

interface AnalysisCardProps {
  analysis: FaultAnalysis;
  selected?: boolean;
  onView?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
}

const statusConfig = {
  pending: { text: "待处理", icon: ClockCircleOutlined, color: "default" as const },
  processing: { text: "处理中", icon: ClockCircleOutlined, color: "processing" as const },
  completed: { text: "已完成", icon: CheckCircleOutlined, color: "success" as const },
  failed: { text: "失败", icon: CloseCircleOutlined, color: "error" as const },
};

const getConfidenceColor = (confidence: number) => {
  if (confidence >= 90) return "#22C55E";
  if (confidence >= 70) return "#F97316";
  return "#EF4444";
};

const getConfidenceIcon = (confidence: number) => {
  if (confidence >= 90) return "✅";
  if (confidence >= 70) return "⚠️";
  return "❌";
};

export function AnalysisCard({ analysis, selected, onView, onEdit, onDelete }: AnalysisCardProps) {
  const status = statusConfig[analysis.status];
  const confidenceColor = getConfidenceColor(analysis.confidence);
  const confidenceIcon = getConfidenceIcon(analysis.confidence);

  return (
    <Card
      size="small"
      hoverable
      className={`admin-fault-analysis-card${selected ? " selected" : ""}`}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <Text strong className="truncate">{analysis.title}</Text>
          </div>
          <div className="flex items-center gap-2">
            <Badge status={status.color} />
            <Text type="secondary" className="text-xs">{status.text}</Text>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <span className="text-gray-500">📍</span>
            <Text type="secondary" className="text-xs">{analysis.line_name}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">{analysis.fault_time}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">{analysis.fault_type}</Text>
          </div>
        </div>

        <Text
          style={{ color: confidenceColor }}
          className="text-xs font-medium"
        >
          综合置信度 S={analysis.confidence}% {confidenceIcon}
        </Text>

        <div className="flex justify-end pt-2 border-t border-gray-200">
          <Space size="small">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              onClick={onView}
            />
            {onEdit && (
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={onEdit}
              />
            )}
            {onDelete && (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={onDelete}
              />
            )}
          </Space>
        </div>
      </div>
    </Card>
  );
}
