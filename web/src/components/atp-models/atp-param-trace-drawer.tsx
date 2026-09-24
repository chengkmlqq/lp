"use client";

// ATP 模型测试「参数溯源」抽屉：展示本次测试最终接受的全部参数，
// 每个槽位的值 + 来源分类（模板规则 / 系统默认 / 模板默认值 / 缺变量 / 关闭），
// 以及命中链、用默认值补全的变量、未解析槽位。
import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Drawer, Spin, Table, Tag, Typography } from "antd";
import { useMemo } from "react";

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

interface ComparePayload {
  params_source?: string;
  params_diagnostics?: ParamsDiagnostics;
  atp_params?: Record<string, unknown>;
}

export interface AtpParamTraceDrawerProps {
  runId: string;
  open: boolean;
  onClose: () => void;
}

type SourceKind = "template" | "system" | "default" | "unresolved" | "disabled" | "else" | "unknown";

function classifySource(source: string): { kind: SourceKind; label: string } {
  const s = source || "";
  if (s.includes("缺")) return { kind: "unresolved", label: "缺变量" };
  if (s.includes("默认值")) return { kind: "default", label: "模板默认值" };
  if (s.includes("全局")) return { kind: "system", label: "系统默认" };
  if (s.includes("else")) return { kind: "else", label: "规则 else" };
  if (s.includes("关闭")) return { kind: "disabled", label: "本级关闭" };
  if (s && s !== "全局参数") return { kind: "template", label: "模板规则" };
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

  const rows = useMemo(() => {
    const diag = compareQuery.data?.params_diagnostics;
    if (!diag) return [];
    const sources = diag.sources ?? {};
    const resolved = diag.resolved ?? {};
    const keys = new Set<string>([...Object.keys(sources), ...Object.keys(resolved)]);
    return [...keys].sort().map((slot) => {
      const sourceText = sources[slot] ?? "-";
      const cls = classifySource(sourceText);
      return {
        key: slot,
        slot,
        value: resolved[slot] ?? compareQuery.data?.atp_params?.[slot] ?? "-",
        sourceText,
        kind: cls.kind,
        kindLabel: cls.label,
      };
    });
  }, [compareQuery.data]);

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
        message="读取参数溯源失败"
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
            label: "参数来源",
            children:
              paramSource === "tower" ? (
                <Tag color="purple">手工杆塔数据（base_tower / profile）</Tag>
              ) : (
                <Tag color="blue">参数模板默认值（无杆塔）</Tag>
              ),
          },
          {
            key: "tower",
            label: "命中塔型",
            children: diag?.tower_kind ? <Tag>{diag.tower_kind}</Tag> : "-",
          },
          {
            key: "unresolved",
            label: "未解析槽位",
            children: unresolvedCount > 0 ? <Tag color="red">{unresolvedCount} 个</Tag> : <Tag color="green">无</Tag>,
          },
        ]}
      />

      {chain.length > 0 ? (
        <div style={{ marginBottom: 10 }}>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            命中链（粗 → 细）：
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
        columns={[
          { title: "槽位", dataIndex: "slot", width: 130, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
          {
            title: "值",
            dataIndex: "value",
            width: 130,
            render: (v: string) => <Typography.Text strong>{v}</Typography.Text>,
          },
          {
            title: "来源分类",
            dataIndex: "kind",
            width: 110,
            render: (kind: SourceKind, row: { kindLabel: string }) => <Tag color={KIND_COLOR[kind]}>{row.kindLabel}</Tag>,
          },
          { title: "原始来源", dataIndex: "sourceText", render: (v: string) => <Typography.Text type="secondary" style={{ fontSize: 12 }}>{v}</Typography.Text> },
        ]}
      />

      {defaultsApplied.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <Typography.Text strong style={{ fontSize: 12 }}>
            已用模板默认值补全的变量（{defaultsApplied.length}）：
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
            槽位命中默认值（{defaultsUsedCount}）：
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
          message={`${unresolvedCount} 个槽位取不到值（已按 C# 口径填 "1." 占位）`}
          description={Object.entries(unresolved)
            .map(([slot, names]) => `${slot} ← 缺 ${names.join("/")}`)
            .join("；")}
        />
      ) : null}
    </div>
  );
}

export function AtpParamTraceDrawer({ runId, open, onClose }: AtpParamTraceDrawerProps) {
  return (
    <Drawer open={open} title={`参数溯源：run ${runId.slice(0, 8)}`} width={760} onClose={onClose} destroyOnClose>
      <ParamsTraceBody runId={runId} />
    </Drawer>
  );
}