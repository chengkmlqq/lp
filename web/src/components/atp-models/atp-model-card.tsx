"use client";

import { Badge, Button, Card, Dropdown, Modal, Progress, Space, Tooltip, Typography } from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DatabaseOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";

import { useI18n } from "@/lib/i18n";
import type { AtpAssetStatus, AtpAssetSummary } from "@/types/auth";

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

function assetBadgeStatus(status: AtpAssetStatus, t: (s: string) => string): { badge: "success" | "processing" | "error" | "warning" | "default"; text: string } {
  switch (status) {
    case "processing":
      return { badge: "processing", text: t("处理中") };
    case "disabled":
      return { badge: "error", text: t("已停用") };
    case "archived":
      return { badge: "warning", text: t("已归档") };
    case "draft":
      return { badge: "default", text: t("草稿") };
    default:
      return { badge: "success", text: t("正常") };
  }
}

export function AtpModelCard({ asset, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, dimensionLabelMap }: AtpModelCardProps) {
  const { t } = useI18n();
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
      title: t("删除模型"),
      content: t("这会同时删除其文件与运行记录。"),
      okText: t("删除"),
      cancelText: t("取消"),
      okButtonProps: { danger: true, loading: deleteLoading },
      onOk: () => onDelete(asset.id),
    });
  }, [deleteLoading, onDelete, asset.id]);

  const { badge: statusBadge, text: statusText } = assetBadgeStatus(asset.status, t);

  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-models-card"
      onClick={handleView}
    >
      <div className="flex flex-col">
        <div className="admin-atp-models-card-title flex items-center gap-2 px-4 py-3 border-b border-gray-200">
          <DatabaseOutlined className="text-base text-gray-500" />
          <Typography.Text strong className="truncate flex-1">{asset.name}</Typography.Text>
          <div className="flex flex-shrink-0 items-center gap-2">
            <Badge status={statusBadge} />
            <Typography.Text type="secondary" className="text-xs">
              {statusText}
            </Typography.Text>
          </div>
        </div>

        <div className="flex flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">电压等级：{formatDimension(asset.voltage_level, dimensionLabelMap?.voltage_level)}</Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <ApartmentOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">塔型：{formatDimension(asset.tower_type, dimensionLabelMap?.tower_type)}</Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">场景：{formatDimension(asset.scene_type, dimensionLabelMap?.scene_type)}</Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <EyeOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">避雷器组合：{formatDimension(asset.arrester_config, dimensionLabelMap?.arrester_config)}</Typography.Text>
          </div>
        </div>

        <div className="admin-atp-models-card-actions flex items-center justify-between px-4 py-2 border-t border-gray-200">
          {asset.status === "processing" ? (
            <Progress percent={asset.progress ?? 0} size="small" className="flex-1 max-w-40" />
          ) : (
            <div />
          )}
          <Space size="small" className="shrink-0">
            <Tooltip title={canTest ? t("模型测试") : t("缺少测试权限（需要 atp.run / atp.manage）")}>
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
            <Tooltip title={t("详情")}>
              <Button
                type="text"
                size="small"
                icon={<EyeOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                  handleView();
                }}
              />
            </Tooltip>
            <Dropdown
              menu={{
                items: [
                  {
                    key: "edit",
                    label: (
                      <Space size={4}>
                        <EditOutlined />
                        <span>{t("编辑")}</span>
                      </Space>
                    ),
                    onClick: (event) => {
                      event.domEvent.stopPropagation();
                      handleEdit();
                    },
                  },
                  ...(canManage
                    ? [
                        {
                          key: "delete",
                          label: (
                            <Space size={4}>
                              <DeleteOutlined />
                              <span>{t("删除")}</span>
                            </Space>
                          ),
                          danger: true,
                          disabled: rowBusy,
                          onClick: (event) => {
                            event.domEvent.stopPropagation();
                            handleDelete();
                          },
                        },
                      ]
                    : []),
                ],
              }}
              trigger={["click"]}
            >
              <Tooltip title={t("更多")}>
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
