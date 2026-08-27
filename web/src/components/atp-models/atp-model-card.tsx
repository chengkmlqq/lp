"use client";

import { Badge, Button, Card, Dropdown, Modal, Progress, Space, Tooltip, Typography } from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  InfoCircleOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";

import type { AtpAssetSummary } from "@/types/auth";

const { Text } = Typography;

interface AtpModelCardProps {
  asset: AtpAssetSummary;
  canManage: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onPreview: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

function formatDimension(
  value: string | null,
  map: Map<string, string> | undefined,
): string {
  if (!value) return "-";
  return map?.get(value) ?? value;
}

const assetStatusConfig = {
  draft: { text: "草稿", color: "default" as const },
  enabled: { text: "启用", color: "success" as const },
  disabled: { text: "停用", color: "default" as const },
  archived: { text: "归档", color: "default" as const },
  processing: { text: "处理中", color: "processing" as const },
};

const getAssetStatus = (status: string) => assetStatusConfig[status as keyof typeof assetStatusConfig] ?? assetStatusConfig.draft;

export function AtpModelCard({ asset, canManage, deleteLoading, onView, onEdit, onPreview, onDelete, dimensionLabelMap }: AtpModelCardProps) {
  const rowBusy = deleteLoading;
  const status = getAssetStatus(asset.status);

  const handleView = useCallback(() => {
    onView(asset);
  }, [onView, asset]);

  const handleEdit = useCallback(() => {
    onEdit(asset);
  }, [onEdit, asset]);

  const handlePreview = useCallback(() => {
    onPreview(asset);
  }, [onPreview, asset]);

  const handleDelete = useCallback(() => {
    Modal.confirm({
      title: "删除模型",
      content: "这会同时删除其文件与运行记录。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true, loading: deleteLoading },
      onOk: () => onDelete(asset.id),
    });
  }, [deleteLoading, onDelete, asset.id]);

  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-models-card"
      onClick={handleView}
    >
      <div className="admin-atp-models-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
        <Typography.Text strong className="truncate" style={{ flex: 1 }}>
          {asset.name}
        </Typography.Text>
        <div className="flex flex-shrink-0 items-center gap-2">
          <Badge status={status.color} />
          <Text type="secondary" className="text-xs">{status.text}</Text>
        </div>
      </div>

      <div className="admin-atp-models-card-body">
        <div className="admin-atp-models-card-body">
        <div className="flex flex-col gap-2 px-4 py-3">
          <div className="admin-atp-models-card-field flex items-center gap-2">
            <ThunderboltOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">电压等级：{formatDimension(asset.voltage_level, dimensionLabelMap?.voltage_level)}</Text>
          </div>
          <div className="admin-atp-models-card-field flex items-center gap-2">
            <ApartmentOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">塔型：{formatDimension(asset.tower_type, dimensionLabelMap?.tower_type)}</Text>
          </div>
          <div className="admin-atp-models-card-field flex items-center gap-2">
            <ClockCircleOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">场景：{formatDimension(asset.scene_type, dimensionLabelMap?.scene_type)}</Text>
          </div>
          <div className="admin-atp-models-card-field flex items-center gap-2">
            <EyeOutlined className="text-xs text-gray-500" />
            <Text type="secondary" className="text-xs">避雷器组合：{formatDimension(asset.arrester_config, dimensionLabelMap?.arrester_config)}</Text>
          </div>
        </div>
      </div>

      <div className="admin-atp-models-card-actions flex items-center justify-between px-4 py-2">
        {asset.status === "processing" ? (
          <Progress percent={asset.progress ?? 0} size="small" className="flex-1 max-w-40" />
        ) : null}
        <Space size="small">
          <Tooltip title="预览">
            <Button
              type="text"
              size="small"
              icon={<InfoCircleOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                handlePreview();
              }}
            />
          </Tooltip>
          <Tooltip title="编辑">
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                handleEdit();
              }}
            />
          </Tooltip>
          <Dropdown
            menu={{
              items: [
                {
                  key: "delete",
                  label: "删除",
                  icon: <DeleteOutlined />,
                  danger: true,
                  disabled: !canManage || rowBusy,
                },
              ],
              onClick: () => {
                handleDelete();
              },
            }}
            trigger={["click"]}
          >
            <Button size="small" icon={<MoreOutlined />} onClick={(event) => event.stopPropagation()} />
          </Dropdown>
        </Space>
      </div>
    </Card>
  );
}
