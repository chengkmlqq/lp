"use client";

import { Button, Card, Dropdown, Modal, Progress, Tooltip, Typography } from "antd";
import {
  CheckCircleOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  StopOutlined,
  SyncOutlined,
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
  /** 按存储里的真实 work.atp 重判形态（存量资产默认值不被当成结论） */
  onRecheckFormat: (id: string) => void;
  recheckBusy: boolean;
  activeBusy: boolean;
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
 * 模型卡片（2026-11-03 重设计）：
 * 一行主信息（名称 + 形态标记 + 菜单），一行维度链，一行元信息（生效/异常/时间），
 * 底部动作行。原先四个维度各占一行加图标 label，卡片高近 300px、一屏放不下几张，
 * 属于信息堆砌 —— 维度本来就有左侧树做导航，卡片里合并成一条链即可。
 */
export function AtpModelCard({ asset, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, onActivate, onDeactivate, onRecheckFormat, recheckBusy, activeBusy, dimensionLabelMap }: AtpModelCardProps) {
  const { t } = useI18n();
  const rowBusy = deleteLoading || activeBusy;

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

  const dimensionText = [
    formatDimension(asset.voltage_level, dimensionLabelMap?.voltage_level),
    formatDimension(asset.tower_type, dimensionLabelMap?.tower_type),
    formatDimension(asset.scene_type, dimensionLabelMap?.scene_type),
    formatDimension(asset.arrester_config, dimensionLabelMap?.arrester_config),
    asset.shield_wire === "without" ? t("无避雷线") : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const abnormal = statusMeta(asset.status, t);
  const updateTime = formatDateShort(asset.update_date);

  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-models-card"
      onClick={handleView}
      styles={{ body: { padding: "12px 14px 10px", height: "100%" } }}
    >
      <div className="flex h-full flex-col gap-2">
        {/* 主行：名称 + 形态标记 + 菜单 */}
        <div className="flex items-start gap-2">
          <Typography.Text strong ellipsis className="admin-atp-models-card-name">
            {asset.name || asset.code}
          </Typography.Text>
          <div className="flex shrink-0 items-center gap-1.5">
            <AtpModelFormatTag asset={asset} />
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
              <Button
                type="text"
                size="small"
                icon={<MoreOutlined />}
                className="-mr-2"
                onClick={(event) => event.stopPropagation()}
              />
            </Dropdown>
          </div>
        </div>

        {/* 维度链：电压 · 塔型 · 场景 · 避雷器 · 避雷线（+ 版本） */}
        <Typography.Text type="secondary" ellipsis className="text-xs leading-5">
          {dimensionText || "-"}
          {asset.version ? ` · ${asset.version}` : ""}
        </Typography.Text>

        {/* 元信息行：生效状态 + 异常状态 + 更新时间 */}
        <div className="flex min-h-5 items-center gap-2 text-xs">
          {asset.is_active ? (
            <span className="admin-atp-models-state-chip is-active">
              <span className="admin-atp-models-state-chip-dot" />
              {t("生效中")}
            </span>
          ) : (
            <span className="admin-atp-models-state-chip is-muted">{t("未生效")}</span>
          )}
          {abnormal ? <span className={abnormal.className}>{abnormal.text}</span> : null}
          {updateTime ? (
            <Typography.Text type="secondary" className="ml-auto text-xs">
              {updateTime}
            </Typography.Text>
          ) : null}
        </div>

        {asset.status === "processing" ? (
          <Progress percent={asset.progress ?? 0} size="small" />
        ) : null}

        {/* 动作行 */}
        <div className="mt-auto flex items-center justify-end gap-1 border-t pt-2" style={{ borderColor: "color-mix(in srgb, var(--fquiz-theme-primary) 14%, var(--ant-color-border-secondary))" }}>
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
            >
              {t("测试")}
            </Button>
          </Tooltip>
          <Button
            type="text"
            size="small"
            icon={<EyeOutlined />}
            onClick={(event) => {
              event.stopPropagation();
              handleView();
            }}
          >
            {t("详情")}
          </Button>
        </div>
      </div>
    </Card>
  );
}
