"use client";

// ATP 测试产物查看组件:
//   - lib 文件:翻译 KARD/KARG 头部 + 解析分支头,输出可读的线路模型库摘要
//   - 日志(lis/log):识别特征点(闪络/Halt/KILL/ERROR/警告)并高亮
import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Spin, Table, Tag, Typography } from "antd";
import { useMemo } from "react";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

export interface AtpTestArtifactViewProps {
  runId: string;
  path: string; // long.lib / work.lis / long.dat ...
}

interface FileContentResponse {
  content_type: "text" | "binary" | "not-found";
  content: string;
  preview_lines: string[];
  size: number;
}

// ---- lib 解析 ----

interface LibBranch {
  key: string;
  index: number;
  nodeIn: string;
  nodeOut: string;
  dataPoints: number;
}

function parseLib(text: string): {
  kard: string[];
  karg: string[];
  kbeg: string[];
  kend: string[];
  branchCount: number;
  branches: LibBranch[];
} {
  const lines = text.split("\n");
  const kard: string[] = [];
  const karg: string[] = [];
  const kbeg: string[] = [];
  const kend: string[] = [];
  const branches: LibBranch[] = [];
  let branchCount = 0;
  let inBranch = false;

  for (const line of lines) {
    const t = line.trim();
    if (t.startsWith("KARD")) {
      kard.push(line);
      continue;
    }
    if (t.startsWith("KARG")) {
      karg.push(line);
      continue;
    }
    if (t.startsWith("KBEG")) {
      kbeg.push(line);
      continue;
    }
    if (t.startsWith("KEND")) {
      kend.push(line);
      continue;
    }
    if (t.startsWith("/BRANCH")) {
      inBranch = true;
      continue;
    }
    if (inBranch && /^-\d+[A-Za-z]/.test(t)) {
      // 分支头形如 -1IN___AOUT__A  2.  0.00  -2 8
      const m = t.match(/^-\d+([A-Za-z0-9_]+)([A-Za-z0-9_]+)\s/);
      branchCount += 1;
      const nodeIn = m ? m[1] : `BR${branchCount}`;
      const nodeOut = m ? m[2] : "";
      branches.push({
        key: `branch-${branchCount}`,
        index: branchCount,
        nodeIn,
        nodeOut,
        dataPoints: 0,
      });
      continue;
    }
  }

  // 数据点数:每个分支头之后的首行是点数(以数字开头)
  // 简化:分支数量已足够,点数在原始内容里可见
  return {
    kard,
    karg,
    kbeg,
    kend,
    branchCount,
    branches,
  };
}

// ---- 日志特征点 ----

const LOG_PATTERNS: Array<{ label: string; re: RegExp; color: string }> = [
  { label: "闪络", re: /flashover|Close switch|闪络/i, color: "volcano" },
  { label: "Halt", re: /\bHalt\b|Halt Code/i, color: "red" },
  { label: "KILL", re: /KILL\s*[=:]?\s*\d+|error stop/i, color: "red" },
  { label: "错误", re: /\bERROR\b|\bError\b|\bFATAL\b/i, color: "red" },
  { label: "警告", re: /\bWarning\b|警告/i, color: "orange" },
];

function findLogFeatures(lines: string[]): Array<{ lineNo: number; text: string; label: string; color: string }> {
  const hits: Array<{ lineNo: number; text: string; label: string; color: string }> = [];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    for (const p of LOG_PATTERNS) {
      if (p.re.test(line)) {
        hits.push({ lineNo: i + 1, text: line.trim().slice(0, 160), label: p.label, color: p.color });
        break; // 一行只标一个特征
      }
    }
  }
  return hits.slice(0, 200);
}

export function AtpTestArtifactView({ runId, path }: AtpTestArtifactViewProps) {
  const { t } = useI18n();
  const { user, fetchWithAuth } = useAuth();

  const isLib = path.toLowerCase().endsWith(".lib");
  const isLog = /\.(lis|log)$/i.test(path);

  const contentQuery = useQuery({
    queryKey: ["/api/v1/atp/test-runs", runId, "files", "content", path],
    enabled: Boolean(user && runId && path),
    queryFn: async () => {
      const response = await fetchWithAuth(
        `/api/v1/atp/test-runs/${runId}/files/content?path=${encodeURIComponent(path)}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FileContentResponse;
    },
  });

  const libSummary = useMemo(() => {
    const data = contentQuery.data;
    if (!data || data.content_type !== "text") return null;
    const text = data.content || (data.preview_lines || []).join("\n");
    if (!isLib) return null;
    return parseLib(text);
  }, [contentQuery.data, isLib]);

  const logFeatures = useMemo(() => {
    const data = contentQuery.data;
    if (!data || data.content_type !== "text") return [];
    const text = data.content || (data.preview_lines || []).join("\n");
    if (!isLog) return [];
    return findLogFeatures(text.split("\n"));
  }, [contentQuery.data, isLog]);

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
        message={t("读取产物失败")}
        description={contentQuery.error instanceof Error ? contentQuery.error.message : ""}
      />
    );
  }

  const data = contentQuery.data;
  if (!data) return null;
  if (data.content_type === "binary") {
    return <Alert type="warning" showIcon message={t("该产物是二进制格式，无法预览文本内容。")} />;
  }
  if (data.content_type === "not-found") {
    return <Alert type="warning" showIcon message={t("产物文件不存在。")} />;
  }

  const fullText = data.content || (data.preview_lines || []).join("\n");

  return (
    <div>
      <Descriptions
        bordered
        size="small"
        column={3}
        items={[
          { key: "path", label: t("文件"), children: path },
          { key: "size", label: t("大小"), children: `${data.size} B` },
          {
            key: "kind",
            label: t("类型"),
            children: isLib ? "线路模型库(.lib)" : isLog ? "ATP 运行日志" : "文本",
          },
        ]}
      />

      {isLib && libSummary ? (
        <>
          <Typography.Title level={5} style={{ marginTop: 12, fontSize: 14 }}>
            线路模型库摘要(运维可读)
          </Typography.Title>
          <Descriptions
            size="small"
            column={3}
            style={{ marginBottom: 8 }}
            items={[
              { key: "branch", label: t("分支数"), children: String(libSummary.branchCount) },
              { key: "kard", label: "KARD", children: <Typography.Text code style={{ fontSize: 11 }}>{libSummary.kard[0]?.slice(0, 60) || "-"}</Typography.Text> },
              { key: "karg", label: "KARG", children: <Typography.Text code style={{ fontSize: 11 }}>{libSummary.karg[0]?.slice(0, 60) || "-"}</Typography.Text> },
            ]}
          />
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={libSummary.branches}
            columns={[
              { title: t("分支"), dataIndex: "index", width: 70 },
              { title: t("节点(进)"), dataIndex: "nodeIn" },
              { title: t("节点(出)"), dataIndex: "nodeOut" },
              {
                title: t("含义"),
                render: (_v, row: LibBranch) => {
                  const inName = row.nodeIn.replace(/IN___/, "").replace(/OUT__.*/, "");
                  const m = inName.match(/^[A-Za-z0-9_]*?([A-Za-z])$/);
                  const phase = m ? m[1] : "";
                  return phase ? `相线 ${phase}` : "-";
                },
              },
            ]}
          />
        </>
      ) : null}

      {isLog ? (
        <>
          <Typography.Title level={5} style={{ marginTop: 12, fontSize: 14 }}>
            日志特征点({logFeatures.length})
          </Typography.Title>
          {logFeatures.length === 0 ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              未识别到闪络/Halt/KILL/错误/警告特征。
            </Typography.Text>
          ) : (
            <Table
              rowKey="lineNo"
              size="small"
              pagination={{ pageSize: 20, showSizeChanger: false }}
              dataSource={logFeatures}
              columns={[
                { title: t("行号"), dataIndex: "lineNo", width: 70 },
                {
                  title: t("特征"),
                  dataIndex: "label",
                  width: 90,
                  render: (v: string, row: { color: string }) => <Tag color={row.color}>{v}</Tag>,
                },
                { title: t("内容"), dataIndex: "text" },
              ]}
            />
          )}
        </>
      ) : null}

      <details style={{ marginTop: 12 }}>
        <summary style={{ cursor: "pointer", color: "#888", fontSize: 12 }}>{t("查看原始内容")}</summary>
        <pre
          style={{
            marginTop: 8,
            maxHeight: 300,
            overflow: "auto",
            background: "#fafafa",
            padding: 8,
            fontSize: 11,
            lineHeight: 1.5,
            whiteSpace: "pre",
          }}
        >
          {fullText}
        </pre>
      </details>
    </div>
  );
}