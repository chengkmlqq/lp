"use client";

import { Button, Dropdown, Modal, Progress, Space, Tooltip, Typography } from "antd";
import { Card } from "@/components/ui-antd";
import {
  ApartmentOutlined,
  DeleteOutlined,
  DisconnectOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  SafetyOutlined,
  SendOutlined,
  SyncOutlined,
  ThunderboltOutlined,
  AppstoreOutlined,
  BlockOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import { useCallback } from "react";
import type { ReactNode } from "react";

import { useI18n } from "@/lib/i18n";
import type { AtpAssetStatus, AtpAssetSummary } from "@/types/auth";
import { checkWarningCount } from "@/lib/atp-model-format";
import { resolveFormatMeta } from "./atp-model-format-tag";

/** 右下角最多平铺几个操作按钮，其余收进「更多」 */
const MAX_VISIBLE_ACTIONS = 2;

interface AtpModelCardProps {
  asset: AtpAssetSummary;
  canManage: boolean;
  canTest: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  onTest: (asset: AtpAssetSummary) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  /** 按存储里的真实 work.atp 重判形态（存量资产默认值不被当成结论） */
  onRecheckFormat: (id: string) => void;
  recheckBusy: boolean;
  publishBusy: boolean;
}

interface CardAction {
  key: string;
  label: string;
  icon: ReactNode;
  tooltip: string;
  disabled?: boolean;
  danger?: boolean;
  run: () => void;
}

/**
 * 维度显示文本：优先用后台已转换好的中文 label（voltage_level_label 等），
 * 无 label 时回落原始 code。后台在 serialize_asset 时一次性批量转换好随数据下发，
 * 前端不需要再拉维度字典接口做转换。
 */
function formatDimension(value: string | null, label: string | null | undefined): string | null {
  if (!value) return null;
  return label || value;
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
 * 模型卡片（2026-11-05 再调整）：
 * - 发布状态移到右上角，「生效/失效」随发布上线而取消（发布即生效，下线即退出仿真定位）；
 * - 形态（新版/老版/检测中…）不再用标签，改为卡片上的一枚水印式印章；
 * - 右下角最多两个按钮（发布|下线 → 测试），其余收进「更多」。
 */
export function AtpModelCard({
  asset,
  canManage,
  canTest,
  deleteLoading,
  onView,
  onEdit,
  onDelete,
  onTest,
  onPublish,
  onUnpublish,
  onRecheckFormat,
  recheckBusy,
  publishBusy,
}: AtpModelCardProps) {
  const { t } = useI18n();
  const rowBusy = deleteLoading || publishBusy;

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

  const voltageText = formatDimension(asset.voltage_level, asset.voltage_level_label) || "-";
  const towerText = formatDimension(asset.tower_type, asset.tower_type_label) || "-";
  const sceneText = formatDimension(asset.scene_type, asset.scene_type_label) || "-";
  const arresterText =
    [formatDimension(asset.arrester_config, asset.arrester_config_label), asset.shield_wire === "without" ? t("无避雷线") : null]
      .filter(Boolean)
      .join(" · ") || "-";

  const abnormal = statusMeta(asset.status, t);
  const updateTime = formatDateShort(asset.update_date);
  const published = asset.is_published !== false;

  // 形态印章：继承原形态 pill 的判定（检测中/检测失败/待检测/新版/老版…）
  const formatMeta = resolveFormatMeta(asset);
  const formatWarnCount = asset.analysis_status === "failed" ? 0 : checkWarningCount(asset.format_check);
  const formatHint =
    formatWarnCount > 0
      ? `${formatMeta.hint}（${t("另有")} ${formatWarnCount} ${t("条预检提示，详情页可查看")}）`
      : formatMeta.hint;

  // 动作清单：顺序即优先级，前 MAX_VISIBLE_ACTIONS 个平铺在右下角，其余进「更多」。
  // 「详情」点卡片本身即可进入，故排在两位常用操作之后。
  const actions: CardAction[] = [];
  if (canManage) {
    if (published) {
      actions.push({
        key: "unpublish",
        label: t("下线"),
        icon: <DisconnectOutlined />,
        tooltip: t("下线该版本（下线后不参与仿真定位）"),
        disabled: rowBusy,
        run: () => onUnpublish(asset.id),
      });
    } else {
      actions.push({
        key: "publish",
        label: t("发布"),
        icon: <SendOutlined />,
        tooltip: t("发布该版本（发布后参与仿真定位）"),
        disabled: rowBusy,
        run: () => onPublish(asset.id),
      });
    }
  }
  actions.push({
    key: "test",
    label: t("测试"),
    icon: <ExperimentOutlined />,
    tooltip: canTest ? t("模型测试") : t("缺少测试权限（需要 atp.run / atp.manage）"),
    disabled: !canTest,
    run: handleTest,
  });
  actions.push({
    key: "detail",
    label: t("详情"),
    icon: <EyeOutlined />,
    tooltip: t("详情"),
    run: handleView,
  });
  if (canManage) {
    actions.push({
      key: "edit",
      label: t("编辑"),
      icon: <EditOutlined />,
      tooltip: t("编辑"),
      run: handleEdit,
    });
    actions.push({
      key: "recheck-format",
      label: t("重新检测形态"),
      icon: <SyncOutlined spin={recheckBusy} />,
      tooltip: t("重新检测形态"),
      disabled: recheckBusy,
      run: () => onRecheckFormat(asset.id),
    });
    actions.push({
      key: "delete",
      label: t("删除"),
      icon: <DeleteOutlined />,
      tooltip: t("删除"),
      danger: true,
      disabled: rowBusy,
      run: handleDelete,
    });
  }

  const visibleActions = actions.slice(0, MAX_VISIBLE_ACTIONS);
  const overflowActions = actions.slice(MAX_VISIBLE_ACTIONS);

  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-models-card"
      onClick={handleView}
      styles={{ body: { padding: 0 } }}
    >
      <div className="relative flex h-full flex-col">
        {/* 形态印章：水印式盖在卡片右侧（替代原右上角形态标签） */}
        <Tooltip title={formatHint}>
          <div
            className="admin-atp-models-stamp"
            data-tone={formatMeta.tone}
            style={{ color: formatMeta.color }}
            onClick={(event) => event.stopPropagation()}
          >
            <span className="admin-atp-models-stamp-text">{formatMeta.label}</span>
            {formatWarnCount > 0 ? (
              <span className="admin-atp-models-stamp-warn">
                <WarningOutlined />
                {formatWarnCount}
              </span>
            ) : null}
          </div>
        </Tooltip>

        {/* 标题栏：图标 + 名称 + 右上角发布状态 */}
        <div className="admin-atp-models-card-title flex items-center gap-2 border-b border-gray-200 px-4 py-3">
          <BlockOutlined className="text-base text-gray-500" />
          <Typography.Text strong ellipsis className="admin-atp-models-card-name min-w-0 flex-1">
            {asset.name || asset.code}
          </Typography.Text>
          <div className="flex shrink-0 items-center gap-1.5">
            {published ? (
              <span className="admin-atp-models-state-chip is-published">
                <span className="admin-atp-models-state-chip-dot" />
                {t("已发布")}
              </span>
            ) : (
              <span className="admin-atp-models-state-chip is-muted">{t("未发布")}</span>
            )}
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

          {/* 元信息行：异常状态 + 版本 + 更新时间（发布状态已在右上角） */}
          <div className="mt-auto flex min-h-5 items-center gap-2 text-xs">
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

        {/* 动作栏：左侧处理进度（与线路管理页卡片一致），右侧最多两个按钮 + 更多 */}
        <div className="admin-atp-models-card-actions flex items-center justify-between gap-2 border-t border-gray-200 px-4 py-2">
          {asset.status === "processing" ? (
            <Progress percent={asset.progress ?? 0} size="small" className="max-w-40 flex-1" />
          ) : (
            <div />
          )}
          <Space size="small" className="shrink-0">
            {visibleActions.map((action) => (
              <Tooltip key={action.key} title={action.tooltip}>
                <Button
                  type="text"
                  size="small"
                  danger={action.danger}
                  icon={action.icon}
                  disabled={action.disabled}
                  onClick={(event) => {
                    event.stopPropagation();
                    action.run();
                  }}
                />
              </Tooltip>
            ))}
            {overflowActions.length > 0 ? (
              <Dropdown
                menu={{
                  items: overflowActions.map((action) => ({
                    key: action.key,
                    danger: action.danger,
                    disabled: action.disabled,
                    label: (
                      <span className="inline-flex items-center gap-1.5">
                        {action.icon}
                        {action.label}
                      </span>
                    ),
                    onClick: (event: { domEvent: { stopPropagation: () => void } }) => {
                      event.domEvent.stopPropagation();
                      action.run();
                    },
                  })),
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
            ) : null}
          </Space>
        </div>
      </div>
    </Card>
  );
}
