"use client";

// ATP 模型 dat(线路几何模板)详情查看:把 LCC 线路常数输入文件
// 翻译成运维人员可读的结构化表格。
// dat 是固定列宽的 ATP 文本:头部(JMARTI/LINE CONSTANTS/METRIC)
// + 导体卡(每根导线: 相序/半径/单位电阻/水平位置/高度)
// + 频率卡(土壤电阻率/频率采样点)。
import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Spin, Table, Typography } from "antd";
import { useMemo } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

export interface AtpDatDetailProps {
  assetId: string;
  relativePath: string;
}

interface AtpFileContentResponse {
  asset_id: string;
  relative_path: string;
  name: string;
  size: number;
  mime_type: string | null;
  content_type: "text" | "binary" | "not-found";
  content: string;
  preview_lines: string[];
}

interface ConductorRow {
  key: string;
  index: number;
  node: string;
  kind: string; // 相线 / 避雷线 / 未知
  radius: string;
  resistance: string; // Ω/km
  x: string; // 水平位置 m
  y: string; // 高度 m
  raw: string;
}

const PHASE_MARKERS: Array<{ re: RegExp; label: string }> = [
  { re: /[ABC]/, label: "相线" },
  { re: /[DEFG]/, label: "避雷线" },
];

function parseConductors(lines: string[]): { rows: ConductorRow[]; nodes: string[]; metric: boolean } {
  const rows: ConductorRow[] = [];
  const nodes: string[] = [];
  let metric = false;
  let inConductor = false;

  for (const line of lines) {
    const up = line.toUpperCase();
    if (!metric && up.includes("METRIC")) {
      metric = true;
      inConductor = true;
      continue;
    }
    if (up.includes("ENDING CONDUCTOR")) {
      inConductor = false;
      break;
    }
    // BRANCH 行: 节点名 IN___AOUT__A 形式 → 提取相别字符
    const branchMatch = line.match(/(IN___)([A-Za-z0-9])(OUT__)([A-Za-z0-9])/g);
    if (branchMatch) {
      for (const m of branchMatch) {
        const nm = m.replace("IN___", "").replace(/OUT__.*/, "");
        if (nm && !nodes.includes(nm)) nodes.push(nm);
      }
      continue;
    }
    if (inConductor) {
      const trimmed = line.trim();
      if (!trimmed || /^C\s/.test(up) || /^C$/.test(trimmed)) continue;
      // 导体卡: 相序号开头, 后续为数值字段(空白或固定列宽分隔)
      const idxMatch = trimmed.match(/^(\d+)/);
      if (!idxMatch) continue;
      const idx = Number(idxMatch[1]);
      const tokens = trimmed.split(/\s+/).filter(Boolean);
      const node = nodes[idx - 1] || "";
      const phase = PHASE_MARKERS.find((p) => p.re.test(node));
      rows.push({
        key: `cond-${idx}`,
        index: idx,
        node,
        kind: phase?.label ?? (idx > 3 ? "避雷线" : "相线"),
        // 常见 LCC 导体卡(METRIC): 相序 半径(m) 单位电阻(Ω/km) 分裂数 水平位置 高度 ...
        radius: tokens[1] ?? "-",
        resistance: tokens[2] ?? "-",
        x: tokens[4] ?? "-",
        y: tokens[5] ?? "-",
        raw: trimmed.slice(0, 90),
      });
    }
  }
  return { rows, nodes, metric };
}

export function AtpDatDetailView({ assetId, relativePath }: AtpDatDetailProps) {
  const { t } = useI18n();
  const { user, fetchWithAuth } = useAuth();

  const contentQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "files", "content", relativePath],
    enabled: Boolean(user && assetId && relativePath),
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/atp/assets/${assetId}/files/content?path=${encodeURIComponent(relativePath)}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpFileContentResponse;
    },
  });

  const parsed = useMemo(() => {
    const data = contentQuery.data;
    if (!data || data.content_type !== "text") return null;
    const lines = (data.preview_lines?.length ? data.preview_lines : data.content.split("\n")) as string[];
    return parseConductors(lines);
  }, [contentQuery.data]);

  if (contentQuery.isLoading) {
    return (
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin />
      </div>
    );
  }

  if (contentQuery.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("读取文件失败")}
        description={contentQuery.error instanceof Error ? contentQuery.error.message : ""}
      />
    );
  }

  const data = contentQuery.data;
  if (!data) return null;
  if (data.content_type === "binary") {
    return <Alert type="warning" showIcon message={t("该文件是二进制格式，无法预览文本内容。")} />;
  }
  if (data.content_type === "not-found") {
    return <Alert type="warning" showIcon message={t("文件不存在。")} />;
  }

  return (
    <div>
      <Descriptions
        bordered
        size="small"
        column={3}
        items={[
          { key: "name", label: t("文件名"), children: data.name || "-" },
          { key: "size", label: t("文件大小"), children: `${data.size} B` },
          { key: "model", label: t("线路模型"), children: "JMARTI(频率相关) / LCC 线路常数" },
          { key: "unit", label: t("单位制"), children: parsed?.metric ? "公制(METRIC)" : "-" },
          { key: "conductor_count", label: t("导体数"), children: String(parsed?.rows.length ?? "-") },
          {
            key: "ground_wire",
            label: t("避雷线"),
            children: String(parsed?.rows.filter((r) => r.kind === "避雷线").length ?? "-"),
          },
        ]}
      />
      <Typography.Title level={5} style={{ marginTop: 16, fontSize: 14 }}>
        导线布置(运维可读)
      </Typography.Title>
      <Table
        rowKey="key"
        size="small"
        pagination={false}
        dataSource={parsed?.rows ?? []}
        columns={[
          { title: t("序号"), dataIndex: "index", width: 60 },
          { title: t("节点"), dataIndex: "node", width: 90 },
          { title: t("类型"), dataIndex: "kind", width: 90 },
          { title: t("半径(m)"), dataIndex: "radius", width: 100 },
          { title: t("单位电阻(Ω/km)"), dataIndex: "resistance", width: 130 },
          { title: t("水平位置(m)"), dataIndex: "x", width: 110 },
          { title: t("高度(m)"), dataIndex: "y", width: 100 },
          { title: t("原始行"), dataIndex: "raw", ellipsis: true },
        ]}
      />
      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", color: "#888", fontSize: 12 }}>{t("查看 dat 原始内容")}</summary>
        <pre
          style={{
            marginTop: 8,
            maxHeight: 240,
            overflow: "auto",
            background: "#fafafa",
            padding: 8,
            fontSize: 11,
            lineHeight: 1.5,
            whiteSpace: "pre",
          }}
        >
          {data.content || (data.preview_lines || []).join("\n")}
        </pre>
      </details>
    </div>
  );
}