"use client";

// ATP 模型测试「参数溯源」抽屉：展示本次测试最终接受的全部参数，
// 每个槽位的值 + 来源分类（模板规则 / 系统默认 / 模板默认值 / 缺变量 / 关闭），
// 以及命中链、用默认值补全的变量、未解析槽位。
import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Drawer, Spin, Table, Tag, Tooltip, Typography } from "antd";
import { useMemo } from "react";

import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

interface ParamsDiagnostics {
  chain?: string[];
  tower_kind?: string;
  defaults_applied?: string[];
  defaults_used?: Record<string, string>;
  unresolved?: Record<string, string[]>;
  sources?: Record<string, string>;
  resolved?: Record<string, string>;
}

interface RuntimeOverride {
  value?: number | string | null;
  written?: boolean;
  note?: string;
}

/** 行级去向（2026-11-03）：compare.json 的 params_trace，见 stage_materialize / trace_parameter_writes */
interface ParamTraceEntry {
  value?: string;
  source?: string | null;
  work_atp_line?: number;
  written?: string;
  runtime_override?: RuntimeOverride;
}

interface ComparePayload {
  params_source?: string;
  params_diagnostics?: ParamsDiagnostics;
  params_trace?: Record<string, ParamTraceEntry>;
  atp_params?: Record<string, unknown>;
}

export interface AtpParamTraceDrawerProps {
  runId: string;
  open: boolean;
  onClose: () => void;
}

interface TraceRow {
  key: string;
  slot: string;
  value: string;
  sourceText: string;
  kind: SourceKind;
  kindLabel: string;
  workAtpLine?: number;
  written?: string;
  overridden: boolean;
  overrideNote?: string;
  overrideWritten?: boolean;
}

type SourceKind = "template" | "system" | "default" | "unresolved" | "disabled" | "else" | "unknown";

function classifySource(source: string, t: (s: string) => string = (s) => s): { kind: SourceKind; label: string } {
  const s = source || "";
  if (s.includes("缺")) return { kind: "unresolved", label: t("缺变量") };
  if (s.includes("默认值")) return { kind: "default", label: t("模板默认值") };
  if (s.includes("全局")) return { kind: "system", label: t("系统默认") };
  if (s.includes("else")) return { kind: "else", label: t("规则 else") };
  if (s.includes("关闭")) return { kind: "disabled", label: t("本级关闭") };
  if (s && s !== "全局参数") return { kind: "template", label: t("模板规则") };
  return { kind: "unknown", label: s || "-" };
}

const KIND_COLOR: Record<SourceKind, string> = {
  template: "blue",
  system: "geekblue",
  default: "orange",
  unresolved: "red",
  disabled: "default",
  else: "purple",
  unknown: "default",
};

function ParamsTraceBody({ runId }: { runId: string }) {
  const { t } = useI18n();
  const { user, fetchWithAuth } = useAuth();

  const compareQuery = useQuery({
    queryKey: ["/api/v1/atp/test-runs", runId, "compare"],
    enabled: Boolean(user && runId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/test-runs/${runId}/compare`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as ComparePayload;
    },
  });

  const rows = useMemo<TraceRow[]>(() => {
    const trace = compareQuery.data?.params_trace ?? {};
    const diag = compareQuery.data?.params_diagnostics;
    const sources = diag?.sources ?? {};
    const resolved = diag?.resolved ?? {};
    const atpParams = compareQuery.data?.atp_params ?? {};
    const keys = new Set<string>([
      ...Object.keys(trace),
      ...Object.keys(sources),
      ...Object.keys(resolved),
      ...Object.keys(atpParams),
    ]);
    return [...keys].sort().map((slot) => {
      const entry = trace[slot];
      const sourceText = entry?.source ?? sources[slot] ?? "-";
      const cls = classifySource(sourceText, t);
      const override = entry?.runtime_override;
      return {
        key: slot,
        slot,
        value: entry?.value ?? resolved[slot] ?? atpParams[slot] ?? "-",
        sourceText,
        kind: cls.kind,
        kindLabel: cls.label,
        workAtpLine: entry?.work_atp_line,
        written: entry?.written,
        overridden: Boolean(override),
        overrideNote: override?.note,
        overrideWritten: override?.written,
      };
    });
  }, [compareQuery.data, t]);

  if (compareQuery.isLoading) {
    return (
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin />
      </div>
    );
  }

  if (compareQuery.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("读取参数溯源失败")}
        description={compareQuery.error instanceof Error ? compareQuery.error.message : ""}
      />
    );
  }

  const data = compareQuery.data;
  if (!data) return null;

  const diag = data.params_diagnostics;
  const chain = diag?.chain ?? [];
  const defaultsApplied = diag?.defaults_applied ?? [];
  const unresolved = diag?.unresolved ?? {};
  const unresolvedCount = Object.keys(unresolved).length;
  const defaultsUsed = diag?.defaults_used ?? {};
  const defaultsUsedCount = Object.keys(defaultsUsed).length;
  const paramSource = data.params_source;

  return (
    <div>
      <Descriptions
        bordered
        size="small"
        column={3}
        style={{ marginBottom: 12 }}
        items={[
          {
            key: "source",
            label: t("参数来源"),
            children:
              paramSource === "test_line" ? (
                <Tag color="green">{t("测试线路快照（唯一来源）")}</Tag>
              ) : paramSource === "tower" ? (
                <Tag color="purple">{t("手工杆塔数据（已弃用）")}</Tag>
              ) : (
                <Tag color="blue">{t("参数模板默认值（已弃用）")}</Tag>
              ),
          },
          {
            key: "tower",
            label: t("命中塔型"),
            children: diag?.tower_kind ? <Tag>{diag.tower_kind}</Tag> : "-",
          },
          {
            key: "unresolved",
            label: t("未解析槽位"),
            children: unresolvedCount > 0 ? <Tag color="red">{unresolvedCount} {t("个")}</Tag> : <Tag color="green">{t("无")}</Tag>,
          },
        ]}
      />

      {chain.length > 0 ? (
        <div style={{ marginBottom: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t("命中链（粗 → 细）：")}
          </Typography.Text>{" "}
          {chain.map((item, index) => (
            <Tag key={item} color={index === chain.length - 1 ? "blue" : "default"}>
              {item}
            </Tag>
          ))}
        </div>
      ) : null}

      <Table
        size="small"
        rowKey="key"
        pagination={false}
        scroll={{ y: 380 }}
        dataSource={rows}
        columns={(
          [
          { title: t("槽位"), dataIndex: "slot", width: 120, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
          {
            title: t("值"),
            dataIndex: "value",
            width: 110,
            render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
          },
          {
            title: t("来源分类"),
            dataIndex: "kind",
            width: 96,
            render: (kind: SourceKind, row: { kindLabel: string }) => <Tag color={KIND_COLOR[kind]}>{row.kindLabel}</Tag>,
          },
          {
            title: t("原始来源"),
            dataIndex: "sourceText",
            render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text>,
          },
          {
            title: t("去向（work.atp）"),
            width: 150,
            render: (_: unknown, row: { workAtpLine?: number; written?: string }) =>
              row.workAtpLine ? (
                <span>
                  <Typography.Text code style={{ fontSize: 12 }}>
                    #{row.workAtpLine}
                  </Typography.Text>{" "}
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {row.written ?? "-"}
                  </Typography.Text>
                </span>
              ) : (
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>-</Typography.Text>
              ),
          },
          {
            title: t("标记"),
            width: 96,
            render: (_: unknown, row: { overridden: boolean; overrideNote?: string; overrideWritten?: boolean }) =>
              row.overridden ? (
                <Tooltip title={row.overrideNote ?? t("运行期覆盖")}>
                  <Tag color="volcano">{t("运行期覆盖")}{row.overrideWritten === false ? t("（未落盘）") : ""}</Tag>
                </Tooltip>
              ) : null,
          },
        ] as ColumnsType<TraceRow>)}
      />

      {defaultsApplied.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <Typography.Text strong style={{ fontSize: 12 }}>
            {t("已用模板默认值补全的变量")}（{defaultsApplied.length}）：
          </Typography.Text>
          <div style={{ marginTop: 4 }}>
            {defaultsApplied.map((name) => (
              <Tag key={name} color="orange" style={{ marginBottom: 4 }}>
                {name}
              </Tag>
            ))}
          </div>
        </div>
      ) : null}

      {defaultsUsedCount > 0 ? (
        <div style={{ marginTop: 8 }}>
          <Typography.Text strong style={{ fontSize: 12 }}>
            {t("槽位命中默认值")}（{defaultsUsedCount}）：
          </Typography.Text>
          <div style={{ marginTop: 4 }}>
            {Object.entries(defaultsUsed).map(([slot, value]) => (
              <Tag key={slot} color="purple" style={{ marginBottom: 4 }}>
                {slot} = {value}
              </Tag>
            ))}
          </div>
        </div>
      ) : null}

      {unresolvedCount > 0 ? (
        <Alert
          style={{ marginTop: 12 }}
          type="warning"
          showIcon
          message={`${unresolvedCount} ${t("个槽位取不到值")}（${t("已按 C# 口径填")} "1." ${t("占位")}）`}
          description={Object.entries(unresolved)
            .map(([slot, names]) => `${slot} ← ${t("缺")} ${names.join("/")}`)
            .join("；")}
        />
      ) : null}
    </div>
  );
}

export function AtpParamTraceDrawer({ runId, open, onClose }: AtpParamTraceDrawerProps) {
  const { t } = useI18n();
  return (
    <Drawer open={open} title={`${t("参数溯源")}：run ${runId.slice(0, 8)}`} width={760} onClose={onClose} destroyOnClose>
      <ParamsTraceBody runId={runId} />
    </Drawer>
  );
}
