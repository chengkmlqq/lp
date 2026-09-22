"use client";

import { Button, Card, Dropdown, Modal, Progress, Space, Tooltip, Typography } from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";

import type { AtpAssetSummary } from "@/types/auth";

const { Text } = Typography;

interface AtpModelCardProps {
  asset: AtpAssetSummary;
  canManage: boolean;
  canTest: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  onTest: (asset: AtpAssetSummary) => void;
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

export function AtpModelCard({ asset, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, dimensionLabelMap }: AtpModelCardProps) {
  const rowBusy = deleteLoading;

  const handleView = useCallback(() => {
    onView(asset);
  }, [onView, asset]);

  const handleEdit = useCallback(() => {
    onEdit(asset);
  }, [onEdit, asset]);

  const handleTest = useCallback(() => {
    onTest(asset);
  }, [onTest, asset]);

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
      <div className="flex flex-col">
        <div className="admin-atp-models-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <Typography.Text strong className="truncate" style={{ flex: 1 }}>
            {asset.name}
          </Typography.Text>
        </div>

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

        <div className="admin-atp-models-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
        {asset.status === "processing" ? (
          <Progress percent={asset.progress ?? 0} size="small" className="flex-1 max-w-40" />
        ) : (
          <div />
        )}
        <Space size="small" className="shrink-0">
          <Tooltip title={canTest ? "模型测试" : "缺少测试权限（需要 atp.run / atp.manage）"}>
            <Button
              type="text"
              size="small"
              icon={<ExperimentOutlined />}
              disabled={!canTest}
              onClick={(event) => {
                event.stopPropagation();
                handleTest();
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
                  onClick: (info) => {
                    info.domEvent?.stopPropagation();
                    handleDelete();
                  },
                },
              ],
            }}
            trigger={["click"]}
          >
            <Tooltip title="更多">
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                onClick={(event) => event.stopPropagation()}
              />
            </Tooltip>
          </Dropdown>
        </Space>
        </div>
      </div>
    </Card>
  );
}
