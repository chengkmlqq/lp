"use client";

import { useMemo, type ReactNode } from "react";
import { Alert, Button, Empty, Spin, Table, Tag } from "antd";
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
  const columns = useMemo<ColumnsType<FlAnalysisTowerResultSummary>>(() => {
    const resultColumns: ColumnsType<FlAnalysisTowerResultSummary> = [
      {
        title: "序号",
        dataIndex: "seq_no",
        width: 80,
      },
      {
        title: "杆塔号",
        dataIndex: "tower_no",
        width: 120,
      },
      {
        title: "塔型",
        dataIndex: "tower_type",
        width: 100,
        render: (value: string | null) => value || "-",
      },
    ];

    if (selectedJob?.job_type === "mitigation") {
      resultColumns.push(
        {
          title: "当前风险",
          key: "current_risk_level",
          width: 110,
          render: (_value, row) => <Tag color={riskColor(readCurrentRisk(row))}>{formatRiskLevel(readCurrentRisk(row))}</Tag>,
        },
        {
          title: "预期风险",
          dataIndex: "risk_level",
          width: 110,
          render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value)}</Tag>,
        },
      );
    } else {
      resultColumns.push({
        title: "风险等级",
        dataIndex: "risk_level",
        width: 120,
        render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value)}</Tag>,
      });
    }

    if (selectedWaveformJobType === "normal" || selectedWaveformJobType === "tongtiao") {
      resultColumns.push(
        {
          title: "最不利点(μs)",
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
          title: "反击耐雷水平(kA)",
          key: "counterstrike_withstand_ka",
          width: 140,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_withstand_ka") ?? "-",
        },
        {
          title: "反击跳闸率",
          key: "counterstrike_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_trip_rate") ?? "-",
        },
        {
          title: "绕击耐雷水平(kA)",
          key: "shielding_withstand_ka",
          width: 140,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "shielding_withstand_ka") ?? "-",
        },
        {
          title: "绕击跳闸率",
          key: "shielding_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "shielding_trip_rate") ?? "-",
        },
      );
    }

    if (selectedWaveformJobType === "tongtiao") {
      resultColumns.push(
        {
          title: "主导相组",
          key: "dominant_phase_set",
          width: 120,
          render: (_value, row) => readOptionalString(readObject(row.result_json), "dominant_phase_set") ?? "-",
        },
        {
          title: "闪络相",
          key: "flashover_phase",
          width: 160,
          render: (_value, row) => readOptionalString(readObject(row.result_json), "flashover_phase") ?? "-",
        },
        {
          title: "同跳跳闸率",
          key: "counterstrike_trip_rate",
          width: 120,
          render: (_value, row) => readOptionalNumber(readObject(row.result_json), "counterstrike_trip_rate") ?? "-",
        },
      );
    }

    if (selectedJob?.job_type === "mitigation") {
      resultColumns.push(
        {
          title: "改造结论",
          key: "recommendation_result",
          width: 140,
          render: (_value, row) => readString(readObject(row.result_json), "recommendation_result"),
        },
        {
          title: "当前得分",
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
        title: "详情",
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
    return <Spin />;
  }

  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        message={error instanceof Error ? error.message : "结果表加载失败"}
      />
    );
  }

  if (rows.length === 0) {
    return <Empty description="当前任务暂无分级结果" />;
  }

  return (
    <>
      {headerExtra ? (
        <div className="flex items-center justify-between mb-3">
          <div className="fl-create-form-block-title" style={{ marginBottom: 0 }}>杆塔明细</div>
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
