import { Badge, Button, Dropdown, Progress, Space, Tooltip, Typography, type MenuProps } from "antd";
import { ClockCircleOutlined, CheckCircleOutlined, CloseCircleOutlined, EyeOutlined, FileTextOutlined, ThunderboltOutlined, DeploymentUnitOutlined, MoreOutlined, ApartmentOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useI18n } from "@/lib/i18n";
import { Card } from "@/components/ui-antd";
import { RECLOSURE_LABELS } from "./types";
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
  onDelete?: () => void;
  onLog?: () => void;
}

const statusConfig = {
  pending: { text: "待处理", icon: ClockCircleOutlined, color: "default" as const },
  processing: { text: "处理中", icon: ClockCircleOutlined, color: "processing" as const },
  completed: { text: "已完成", icon: CheckCircleOutlined, color: "success" as const },
  failed: { text: "失败", icon: CloseCircleOutlined, color: "error" as const },
};

export function AnalysisCard({ analysis, selected, onView, onDelete, onLog }: AnalysisCardProps) {
  const { t } = useI18n();
  const status = statusConfig[analysis.status];
  // 对齐雷电流幅值统计页：详情/分析日志平铺为两个图标按钮，其余操作收进 ⋯ 三点下拉
  const moreMenuItems: MenuProps["items"] = [
    ...(onDelete
      ? [
          {
            key: "delete",
            label: t("删除"),
            danger: true,
            onClick: (info) => {
              info.domEvent?.stopPropagation();
              onDelete();
            },
          },
        ]
      : []),
  ];

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
              <Text strong className="truncate">{analysis.title}</Text>
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
              <Badge status={status.color} />
              <Text type="secondary" className="text-xs">{status.text}</Text>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <ApartmentOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">故障线路：{analysis.line_name || '-'}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">故障时刻：{formatDateTime(analysis.fault_time)}</Text>
          </div>

          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">故障项：{analysis.fault_phase || '-'}</Text>
          </div>

          <div className="flex items-center gap-2">
            <DeploymentUnitOutlined className="text-gray-500 text-xs" />
            <Text type="secondary" className="text-xs">重合闸：{analysis.reclosure_status ? (RECLOSURE_LABELS[analysis.reclosure_status] ?? analysis.reclosure_status) : '-'}</Text>
          </div>
        </div>

        <div className="admin-fault-analysis-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          {analysis.status === "processing" ? (
            <Progress percent={Math.round(analysis.progress)} size="small" className="flex-1 max-w-40" />
          ) : (
            <div />
          )}
          <Space size="small" className="shrink-0">
            <Tooltip title={t("详情")}>
              <Button
                type="text"
                size="small"
                icon={<EyeOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  onView?.();
                }}
              />
            </Tooltip>
            {onLog ? (
              <Tooltip title={t("分析日志")}>
                <Button
                  type="text"
                  size="small"
                  icon={<FileTextOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                    onLog();
                  }}
                />
              </Tooltip>
            ) : null}
            {moreMenuItems.length > 0 ? (
              <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
                <Tooltip title={t("更多")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<MoreOutlined />}
                    onClick={(event) => event.stopPropagation()}
                  />
                </Tooltip>
              </Dropdown>
            ) : null}
          </Space>
        </div>
      </div>
    </Card>
  );
}
