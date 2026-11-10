"use client";

import { Button, Dropdown, Modal, Progress, Space, Tooltip } from "antd";
import { Card } from "@/components/ui-antd";
import {
  ClusterOutlined,
  DeleteOutlined,
  DisconnectOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  MoreOutlined,
  SendOutlined,
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
 * 模型卡片（2026-11-07 版式重做）：
 *
 * 旧版卡片的问题是把所有信息都摆成同等权重——每个字段前面挂一个图标、右上角水印式
 * 「新/旧」斜章、左下蓝色圆点徽章、卡片底色还带一层蓝渐变，元素互相抢视线，
 * 30 张卡排在一起时整页都是噪点，扫读无从下手。
 *
 * 新版按「一个锚点 + 安静的信息层」重排：
 * - 标题区只留模型名 + 编号，编号用小一号灰字，去掉装饰图标；发布状态收敛为一枚
 *   语义 chip（已发布=绿、未发布=灰），不再用红点；
 * - 四个维度改成两列「标签灰 / 值深」的属性网格，字段不再带图标，靠对齐形成节奏；
 * - 形态（新版/旧版/检测中…）从水印斜章收成页脚一行灰字，悬停看完整链路说明与
 *   预检提示数——信息不丢，噪音去掉；
 * - 卡片改纯白底 + 细边框，靠留白与对齐撑精致度，不靠装饰。
 *
 * 2026-11-07 二次调整（页面反馈「有点素」）：在不回到「什么都强调」的前提下补两处结构色——
 * ① 标题左侧一枚图标块（antd 原生 ClusterOutlined，统一用主题色，不按电压分档换色）；
 * ② 属性下方一条三格数据条（测试次数 / 最近结果 / 版本），浅底小块把使用情况压成可扫读的读数，
 *    最近结果用成功绿、失败红，其余保持灰。
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
  const published = asset.is_published !== false;

  // 形态说明：页脚那行灰字要给完整解释（决定仿真链路），预检 warning 数一并带出
  const formatMeta = resolveFormatMeta(asset);
  const formatWarnCount = asset.analysis_status === "failed" ? 0 : checkWarningCount(asset.format_check);
  const formatHint =
    formatWarnCount > 0
      ? `${t(formatMeta.hint)}（${t("另有")} ${formatWarnCount} ${t("条预检提示，详情页可查看")}）`
      : t(formatMeta.hint);

  const specs = [
    { key: "voltage", label: t("电压等级"), value: voltageText },
    { key: "tower", label: t("塔型"), value: towerText },
    { key: "scene", label: t("场景"), value: sceneText },
    { key: "arrester", label: t("避雷器"), value: arresterText },
  ];

  const runStatus =
    asset.last_run_status === "success"
      ? { text: t("成功"), className: "is-success" }
      : asset.last_run_status === "failed"
        ? { text: t("失败"), className: "is-danger" }
        : asset.last_run_status === "running"
          ? { text: t("运行中"), className: "is-running" }
          : asset.last_run_status === "pending"
            ? { text: t("排队中"), className: "is-running" }
            : { text: t("未运行"), className: "is-muted" };

  // 数据条：把「用得多不多、最近跑得怎么样」这类三秒钟就能读完的信息压成三格
  const stats = [
    { key: "runs", label: t("测试次数"), value: String(asset.run_count ?? 0), className: "" },
    { key: "last", label: t("最近结果"), value: runStatus.text, className: runStatus.className },
    { key: "version", label: t("版本"), value: asset.version || "-", className: "" },
  ];

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
      <div className="admin-atp-models-card-inner">
        {/* 标题区：电压分档色块（锚点）+ 模型名 + 编号，右侧只放一枚发布状态 chip */}
        <div className="admin-atp-models-card-head">
          <span className="admin-atp-models-card-tile" aria-hidden>
            <ClusterOutlined />
          </span>
          <div className="admin-atp-models-card-headline">
            <div className="admin-atp-models-card-name" title={asset.name || asset.code}>
              {asset.name || asset.code}
            </div>
            {asset.name && asset.code ? (
              <div className="admin-atp-models-card-code" title={asset.code}>
                {asset.code}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center gap-1">
            {published ? (
              <span className="admin-atp-models-state-chip is-published">{t("已发布")}</span>
            ) : (
              <span className="admin-atp-models-state-chip is-muted">{t("未发布")}</span>
            )}
          </div>
        </div>

        {/* 属性网格：两列「标签灰 / 值深」，字段不带图标，靠对齐形成扫读节奏 */}
        <dl className="admin-atp-models-card-specs">
          {specs.map((spec) => (
            <div key={spec.key} className="admin-atp-models-card-spec">
              <dt>{spec.label}</dt>
              <dd title={spec.value}>{spec.value}</dd>
            </div>
          ))}
        </dl>

        {/* 数据条：三格浅色小块，扫读节奏与首页统计卡一致 */}
        <div className="admin-atp-models-card-stats">
          {stats.map((stat) => (
            <div key={stat.key} className="admin-atp-models-stat">
              <span className="admin-atp-models-stat-label">{stat.label}</span>
              <span className={`admin-atp-models-stat-value${stat.className ? ` ${stat.className}` : ""}`} title={stat.value}>
                {stat.value}
              </span>
            </div>
          ))}
        </div>

        {/* 处理进度：只在运行中任务上出现，其余时候不占位置 */}
        {asset.status === "processing" ? (
          <Progress percent={asset.progress ?? 0} size="small" className="admin-atp-models-card-progress" />
        ) : null}

        {/* 页脚：左侧形态说明与异常状态（安静灰字），右侧操作 */}
        <div className="admin-atp-models-card-foot">
          <div className="admin-atp-models-card-foot-meta">
            <Tooltip title={formatHint}>
              <span
                className="admin-atp-models-format-note"
                data-tone={formatMeta.tone}
                onClick={(event) => event.stopPropagation()}
              >
                {t(formatMeta.short)}
                {formatWarnCount > 0 ? (
                  <span className="admin-atp-models-format-note-warn">
                    <WarningOutlined />
                    {formatWarnCount}
                  </span>
                ) : null}
              </span>
            </Tooltip>
            {abnormal ? <span className={abnormal.className}>{abnormal.text}</span> : null}
          </div>
          <Space size={2} className="shrink-0">
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
