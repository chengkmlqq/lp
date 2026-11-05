"use client";

import { Button, Dropdown, Modal, Progress, Space, Tooltip, Typography } from "antd";
import { Card } from "@/components/ui-antd";
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  DisconnectOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  SafetyOutlined,
  SendOutlined,
  StopOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  AppstoreOutlined,
  BlockOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";

import { useI18n } from "@/lib/i18n";
import type { AtpAssetStatus, AtpAssetSummary } from "@/types/auth";
import { AtpModelFormatTag } from "./atp-model-format-tag";

interface AtpModelCardProps {
  asset: AtpAssetSummary;
  canManage: boolean;
  canTest: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  onTest: (asset: AtpAssetSummary) => void;
  onActivate: (id: string) => void;
  onDeactivate: (id: string) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  /** 按存储里的真实 work.atp 重判形态（存量资产默认值不被当成结论） */
  onRecheckFormat: (id: string) => void;
  recheckBusy: boolean;
  activeBusy: boolean;
  publishBusy: boolean;
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

function formatDimension(value: string | null, map: Map<string, string> | undefined): string | null {
  if (!value) return null;
  return map?.get(value) ?? value;
}

function formatDateShort(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** 资产运行状态的展示文案与色调（enabled 正常态不显示，避免每张卡片都挂着「正常」） */
function statusMeta(status: AtpAssetStatus, t: (s: string) => string): { text: string; className: string } | null {
  switch (status) {
    case "processing":
      return { text: t("处理中"), className: "admin-atp-models-state-chip is-processing" };
    case "disabled":
      return { text: t("已停用"), className: "admin-atp-models-state-chip is-danger" };
    case "archived":
      return { text: t("已归档"), className: "admin-atp-models-state-chip is-warning" };
    case "draft":
      return { text: t("草稿"), className: "admin-atp-models-state-chip is-muted" };
    default:
      return null;
  }
}

/**
 * 模型卡片（2026-11-05 对齐线路管理页卡片重设计）：
 * 一行主信息（名称 + 形态标记），一行维度链，一行元信息（发布/生效/异常/时间），
 * 底部动作栏——操作按钮全部放右下角（测试/详情/发布|下线/更多），
 * 与线路管理页卡片同构：左侧留空（处理中时放进度条），右侧为按钮组。
 */
export function AtpModelCard({ asset, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, onActivate, onDeactivate, onPublish, onUnpublish, onRecheckFormat, recheckBusy, activeBusy, publishBusy, dimensionLabelMap }: AtpModelCardProps) {
  const { t } = useI18n();
  const rowBusy = deleteLoading || activeBusy || publishBusy;

  const handleView = useCallback(() => {
    onView(asset);
  }, [onView, asset]);

  const handleEdit = useCallback(() => {
    onEdit(asset);
  }, [onEdit, asset]);

  const handleTest = useCallback(() => {
    onTest(asset);
  }, [onTest, asset]);

  // 不用 useCallback：Modal.confirm 稳定，包一层 memo 反而触发 React Compiler
  // 的 preserve-manual-memoization 编译跳过（error）。
  const handleDelete = () => {
    Modal.confirm({
      title: t("删除模型"),
      content: t("这会同时删除其文件与运行记录。"),
      okText: t("删除"),
      cancelText: t("取消"),
      okButtonProps: { danger: true, loading: deleteLoading },
      onOk: () => onDelete(asset.id),
    });
  };

  const voltageText = formatDimension(asset.voltage_level, dimensionLabelMap?.voltage_level) || "-";
  const towerText = formatDimension(asset.tower_type, dimensionLabelMap?.tower_type) || "-";
  const sceneText = formatDimension(asset.scene_type, dimensionLabelMap?.scene_type) || "-";
  const arresterText =
    [formatDimension(asset.arrester_config, dimensionLabelMap?.arrester_config), asset.shield_wire === "without" ? t("无避雷线") : null]
      .filter(Boolean)
      .join(" · ") || "-";

  const abnormal = statusMeta(asset.status, t);
  const updateTime = formatDateShort(asset.update_date);
  const published = asset.is_published !== false;

  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-models-card"
      onClick={handleView}
      styles={{ body: { padding: 0 } }}
    >
      <div className="flex h-full flex-col">
        {/* 标题栏：与线路管理页卡片同构（图标 + 名称 + 右侧形态标记 + 底部分隔线） */}
        <div className="admin-atp-models-card-title flex items-center gap-2 border-b border-gray-200 px-4 py-3">
          <BlockOutlined className="text-base text-gray-500" />
          <Typography.Text strong ellipsis className="admin-atp-models-card-name min-w-0 flex-1">
            {asset.name || asset.code}
          </Typography.Text>
          <div className="flex shrink-0 items-center gap-1.5">
            <AtpModelFormatTag asset={asset} />
          </div>
        </div>

        {/* 字段区：逐行「小图标 + 标签：值」，与线路管理页卡片一致 */}
        <div className="flex flex-1 flex-col gap-2 px-4 py-3">
          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" ellipsis className="min-w-0 text-xs">
              {t("电压等级")}：{voltageText}
            </Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <ApartmentOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" ellipsis className="min-w-0 text-xs">
              {t("塔型")}：{towerText}
            </Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <AppstoreOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" ellipsis className="min-w-0 text-xs">
              {t("场景")}：{sceneText}
            </Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <SafetyOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" ellipsis className="min-w-0 text-xs">
              {t("避雷器")}：{arresterText}
            </Typography.Text>
          </div>

          {/* 元信息行：发布状态 + 生效状态 + 异常状态 + 版本 + 更新时间 */}
          <div className="mt-auto flex min-h-5 items-center gap-2 text-xs">
            {published ? (
              <span className="admin-atp-models-state-chip is-published">
                <span className="admin-atp-models-state-chip-dot" />
                {t("已发布")}
              </span>
            ) : (
              <span className="admin-atp-models-state-chip is-muted">{t("未发布")}</span>
            )}
            {asset.is_active ? (
              <span className="admin-atp-models-state-chip is-active">
                <span className="admin-atp-models-state-chip-dot" />
                {t("生效中")}
              </span>
            ) : null}
            {abnormal ? <span className={abnormal.className}>{abnormal.text}</span> : null}
            {asset.version ? (
              <Typography.Text type="secondary" className="text-xs">
                {asset.version}
              </Typography.Text>
            ) : null}
            {updateTime ? (
              <Typography.Text type="secondary" className="ml-auto text-xs">
                {updateTime}
              </Typography.Text>
            ) : null}
          </div>
        </div>

        {/* 动作栏：左侧处理进度（与线路管理页卡片一致），右侧操作按钮组（右下角） */}
        <div className="admin-atp-models-card-actions flex items-center justify-between gap-2 border-t border-gray-200 px-4 py-2">
          {asset.status === "processing" ? (
            <Progress percent={asset.progress ?? 0} size="small" className="max-w-40 flex-1" />
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
            {canManage ? (
              published ? (
                <Tooltip title={t("下线该版本（下线后不参与仿真定位）")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<DisconnectOutlined />}
                    disabled={rowBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onUnpublish(asset.id);
                    }}
                  />
                </Tooltip>
              ) : (
                <Tooltip title={t("发布该版本（发布后参与仿真定位）")}>
                  <Button
                    type="text"
                    size="small"
                    icon={<SendOutlined />}
                    disabled={rowBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onPublish(asset.id);
                    }}
                  />
                </Tooltip>
              )
            ) : null}
            <Dropdown
              menu={{
                items: [
                  {
                    key: "edit",
                    label: (
                      <span className="inline-flex items-center gap-1.5">
                        <EditOutlined />
                        {t("编辑")}
                      </span>
                    ),
                    disabled: !canManage,
                    onClick: (event) => {
                      event.domEvent.stopPropagation();
                      handleEdit();
                    },
                  },
                  ...(canManage
                    ? [
                        asset.is_active
                          ? {
                              key: "deactivate",
                              label: (
                                <span className="inline-flex items-center gap-1.5">
                                  <StopOutlined />
                                  {t("取消生效")}
                                </span>
                              ),
                              disabled: rowBusy,
                              onClick: (event: { domEvent: { stopPropagation: () => void } }) => {
                                event.domEvent.stopPropagation();
                                onDeactivate(asset.id);
                              },
                            }
                          : {
                              key: "activate",
                              label: (
                                <span className="inline-flex items-center gap-1.5">
                                  <CheckCircleOutlined />
                                  {t("设为生效")}
                                </span>
                              ),
                              disabled: rowBusy,
                              onClick: (event: { domEvent: { stopPropagation: () => void } }) => {
                                event.domEvent.stopPropagation();
                                onActivate(asset.id);
                              },
                            },
                        {
                          key: "recheck-format",
                          label: (
                            <span className="inline-flex items-center gap-1.5">
                              <SyncOutlined spin={recheckBusy} />
                              {t("重新检测形态")}
                            </span>
                          ),
                          disabled: recheckBusy,
                          onClick: (event: { domEvent: { stopPropagation: () => void } }) => {
                            event.domEvent.stopPropagation();
                            onRecheckFormat(asset.id);
                          },
                        },
                        { type: "divider" as const },
                        {
                          key: "delete",
                          label: (
                            <span className="inline-flex items-center gap-1.5">
                              <DeleteOutlined />
                              {t("删除")}
                            </span>
                          ),
                          danger: true,
                          disabled: rowBusy,
                          onClick: (event: { domEvent: { stopPropagation: () => void } }) => {
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
