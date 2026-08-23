import { Badge, Button, Progress, Space, Typography } from "antd";
import { ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, EyeOutlined, EditOutlined, DeleteOutlined, ThunderboltOutlined, DeploymentUnitOutlined, FileTextOutlined, DownloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { Card } from "@/components/ui-antd";
import type { FaultAnalysis } from "./types";

const { Text } = Typography;

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}

interface AnalysisCardProps {
  analysis: FaultAnalysis;
  selected?: boolean;
  onView?: () => void;
  onProcess?: () => void;
  onArtifacts?: () => void;
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

export function AnalysisCard({ analysis, selected, onView, onProcess, onArtifacts, onEdit, onDelete }: AnalysisCardProps) {
  const status = statusConfig[analysis.status];
  const confidenceColor = getConfidenceColor(analysis.confidence);
  const confidenceIcon = getConfidenceIcon(analysis.confidence);

  return (
    <Card
      size="small"
      hoverable
      className={`admin-fault-analysis-card${selected ? " selected" : ""}`}
      onClick={onView}
    >
      <div className="flex flex-col">
        <div className="admin-fault-analysis-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <DeploymentUnitOutlined className="text-base text-gray-500" />
          <div className="flex flex-1 min-w-0 items-center justify-between gap-2">
            <div className="flex flex-1 min-w-0 flex-col">
              <Text strong className="truncate">{analysis.line_name}</Text>
              <Text type="secondary" className="truncate text-xs">{analysis.title}</Text>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Badge status={status.color} />
              <Text type="secondary" className="text-xs">{status.text}</Text>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="text-gray-500">📍</span>
            <Text type="secondary" className="text-xs">{analysis.line_name}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">{formatDateTime(analysis.fault_time)}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">{analysis.fault_type}</Text>
          </div>
          <Text
            style={{ color: confidenceColor }}
            className="text-xs font-medium"
          >
            综合置信度 S={analysis.confidence}% {confidenceIcon}
          </Text>
        </div>

        <div className="admin-fault-analysis-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          {analysis.status === "processing" ? (
            <Progress percent={Math.round(analysis.progress)} size="small" className="flex-1 max-w-40" />
          ) : (
            <div />
          )}
          <Space size="small" className="flex-wrap">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onView?.();
              }}
            />
            <Button
              type="text"
              size="small"
              icon={<FileTextOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onProcess?.();
              }}
            >
              计算过程
            </Button>
            <Button
              type="text"
              size="small"
              icon={<DownloadOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onArtifacts?.();
              }}
            >
              产物
            </Button>
            {onEdit && (
              <Button
                type="text"
                size="small"
                icon={<EditOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  onEdit?.();
                }}
              />
            )}
            {onDelete && (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete?.();
                }}
              />
            )}
          </Space>
        </div>
      </div>
    </Card>
  );
}
