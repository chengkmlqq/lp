"use client";
import { useI18n } from "@/lib/i18n";

import { useMemo, type ReactNode } from "react";
import { Alert, Button, Empty, Spin, Table, Tag, Typography } from "antd";
import type { ColumnsType } from "antd/es/table";

import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatRiskLevel,
  readCurrentRisk,
  readCurrentScore,
  readObject,
  readOptionalNumber,
  readOptionalString,
  readSelectedCase,
  readString,
  riskColor,
} from "./types";

type ResultTableProps = {
  selectedJob: FlAnalysisJobSummary | null;
  selectedWaveformJobType: "normal" | "tongtiao" | null;
  rows: FlAnalysisTowerResultSummary[];
  loading: boolean;
  error: unknown;
  onOpenDetail: (row: FlAnalysisTowerResultSummary) => void;
  /** 表格右上方附加操作区（如导出结果按钮） */
  headerExtra?: ReactNode;
};

export function ResultTable({
  selectedJob,
  selectedWaveformJobType,
  rows,
  loading,
  error,
  onOpenDetail,
  headerExtra,
}: ResultTableProps) {
  const { t } = useI18n();
  const columns = useMemo<ColumnsType<FlAnalysisTowerResultSummary>>(() => {
    const resultColumns: ColumnsType<FlAnalysisTowerResultSummary> = [
      {
        title: t("序号"),
        dataIndex: "seq_no",
        width: 80,
      },
      {
        title: t("杆塔号"),
        dataIndex: "tower_no",
        width: 120,
      },
      {
        title: t("塔型"),
        dataIndex: "tower_type",
        width: 100,
        render: (value: string | null) => value || "-",
      },
    ];

    if (selectedJob?.job_type === "mitigation") {
      resultColumns.push(
        {
          title: t("当前风险"),
          key: "current_risk_level",
          width: 110,
          render: (_value, row) => <Tag color={riskColor(readCurrentRisk(row))}>{formatRiskLevel(readCurrentRisk(row), t)}</Tag>,
        },
        {
          title: t("预期风险"),
          dataIndex: "risk_level",
          width: 110,
          render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>,
        },
      );
    } else {
      resultColumns.push({
        title: t("风险等级"),
        dataIndex: "risk_level",
        width: 120,
        render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>,
      });
    }

    // ⚠️ 2026-09-30 成因分析并入防雷计算详情：读 result_json.cause_analysis
    resultColumns.push({
      title: t("原因分析"),
      key: "cause_analysis",
      width: 260,
      ellipsis: { showTitle: true },
      render: (_value, row) => {
        const cause = readObject(row.result_json).cause_analysis;
        if (typeof cause === "string" && cause.trim()) {
          return <Typography.Text style={{ fontSize: 12 }}>{cause}</Typography.Text>;
        }
        return <Typography.Text type="secondary">-</Typography.Text>;
      },
    });

    if (selectedWaveformJobType === "normal" || selectedWaveformJobType === "tongtiao") {
      resultColumns.push(
        {
          title: t("最不利点(μs)"),
          key: "selected_case",
          width: 160,
          render: (_value, row) => {
            const selectedCase = readSelectedCase(row);
            const head = selectedCase.head_time_us;
            const tail = selectedCase.tail_time_us;
            if (typeof head !== "number" || typeof tail !== "number") {
              return "-";
            }
            return `${head}/${tail}`;
          },
        },
      );
    }

    if (selectedWaveformJobType === "normal") {
      resultColumns.push(
        {
          title: t("反击耐雷水平(kA)"),
          key: "counterstrike_withstand_ka",
          width: 140,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_withstand_ka") ?? "-",
        },
        {
          title: t("反击跳闸率"),
          key: "counterstrike_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_trip_rate") ?? "-",
        },
        {
          title: t("绕击耐雷水平(kA)"),
          key: "shielding_withstand_ka",
          width: 140,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "shielding_withstand_ka") ?? "-",
        },
        {
          title: t("绕击跳闸率"),
          key: "shielding_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "shielding_trip_rate") ?? "-",
        },
      );
    }

    if (selectedWaveformJobType === "tongtiao") {
      resultColumns.push(
        {
          title: t("主导相组"),
          key: "dominant_phase_set",
          width: 120,
          render: (_value, row) => readOptionalString(readObject(row.result_json), "dominant_phase_set") ?? "-",
        },
        {
          title: t("闪络相"),
          key: "flashover_phase",
          width: 160,
          render: (_value, row) => readOptionalString(readObject(row.result_json), "flashover_phase") ?? "-",
        },
        {
          title: t("同跳跳闸率"),
          key: "counterstrike_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_trip_rate") ?? "-",
        },
      );
    }

    if (selectedJob?.job_type === "mitigation") {
      resultColumns.push(
        {
          title: t("改造结论"),
          key: "recommendation_result",
          width: 140,
          render: (_value, row) => readString(readObject(row.result_json), "recommendation_result"),
        },
        {
          title: t("当前得分"),
          key: "current_score",
          width: 100,
          render: (_value, row) => {
            const value = readCurrentScore(row);
            return value === null ? "-" : String(value);
          },
        },
      );
    }

    resultColumns.push(
      {
        title: t("详情"),
        key: "actions",
        width: 110,
        render: (_value, row) => (
          <Button
            size="small"
            onClick={() => {
              onOpenDetail(row);
            }}
          >
            查看详情
          </Button>
        ),
      },
    );

    return resultColumns;
  }, [onOpenDetail, selectedJob?.job_type, selectedWaveformJobType]);

  if (loading) {
    return (
      <div className="flex w-full items-center justify-center py-8">
        <Spin />
      </div>
    );
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error instanceof Error ? error.message : t("结果表加载失败")}
      />
    );
  }

  if (rows.length === 0) {
    return <Empty description={t("当前任务暂无分级结果")} />;
  }

  return (
    <>
      {headerExtra ? (
        <div className="flex items-center justify-between mb-3">
          <div className="fl-create-form-block-title" style={{ marginBottom: 0 }}>{t("杆塔明细")}</div>
          {headerExtra}
        </div>
      ) : null}
      <Table<FlAnalysisTowerResultSummary>
        rowKey="id"
        columns={columns}
        dataSource={rows}
        pagination={false}
        scroll={{ x: "max-content" }}
      />
    </>
  );
}
