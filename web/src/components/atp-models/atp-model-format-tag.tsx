"use client";

import { LoadingOutlined, WarningOutlined } from "@ant-design/icons";
import { Tooltip } from "antd";

import {
  checkWarningCount,
  describeModelFormat,
  MODEL_ANALYZING_META,
  type ModelFormatMeta,
} from "@/lib/atp-model-format";
import { useI18n } from "@/lib/i18n";
import type { AtpAssetSummary } from "@/types/auth";

/** 检测失败态（analysis_status = failed）：结果不可信，需要人工重试 */
const MODEL_ANALYSIS_FAILED_META: ModelFormatMeta = {
  label: "检测失败",
  short: "检测失败",
  color: "#b91c1c",
  background: "#fef2f2",
  tone: "other",
  hint: "后台分析失败。悬停可看原因，或点「更多 → 重新检测形态」重试。",
};

/**
 * 解析模型当前的形态展示元数据（卡片/表格共用）。
 *
 * 优先级：分析进行中 > 分析失败 > 预检报告（无报告显示「待检测」，
 * 不能把存量行的 legacy 列默认值冒充判定结论，2026-11-03 生产事故）。
 */
export function resolveFormatMeta(asset: AtpAssetSummary): ModelFormatMeta {
  const analysisRunning = asset.analysis_status === "pending" || asset.analysis_status === "running";
  if (analysisRunning) {
    return MODEL_ANALYZING_META;
  }
  if (asset.analysis_status === "failed") {
    return {
      ...MODEL_ANALYSIS_FAILED_META,
      hint: asset.analysis_error?.trim() ? asset.analysis_error : MODEL_ANALYSIS_FAILED_META.hint,
    };
  }
  const formatChecked = Boolean(asset.format_check?.model_format);
  return describeModelFormat(asset.model_format, formatChecked);
}

interface AtpModelFormatTagProps {
  asset: AtpAssetSummary;
  /** true = 极短标签（表格列），false = 完整标签（卡片） */
  compact?: boolean;
}

/**
 * 形态标记 + 检测状态 + 预检警告数的统一 pill：
 * - 检测中 / 检测失败 / 待检测 / 新版 / 老版 / 内嵌 / 无线路 一个位置说完；
 * - 预检有 warning 时在 tag 内追加黄色计数，悬停可看形态说明。
 */
export function AtpModelFormatTag({ asset, compact = false }: AtpModelFormatTagProps) {
  const { t } = useI18n();
  const meta = resolveFormatMeta(asset);
  const warnCount = asset.analysis_status === "failed" ? 0 : checkWarningCount(asset.format_check);

  const hint = warnCount > 0
    ? `${meta.hint}（${t("另有")} ${warnCount} ${t("条预检提示，详情页可查看")}）`
    : meta.hint;

  return (
    <Tooltip title={hint}>
      <span
        className="admin-atp-models-format-tag"
        style={{ color: meta.color, backgroundColor: meta.background, borderColor: `${meta.color}33` }}
      >
        {asset.analysis_status === "pending" || asset.analysis_status === "running" ? (
          <LoadingOutlined spin className="admin-atp-models-format-tag-icon" />
        ) : null}
        {compact ? meta.short : meta.label}
        {warnCount > 0 ? (
          <span className="admin-atp-models-format-tag-warn">
            <WarningOutlined />
            {warnCount}
          </span>
        ) : null}
      </span>
    </Tooltip>
  );
}
