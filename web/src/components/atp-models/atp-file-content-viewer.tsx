"use client";

// ATP 模型文件通用在线查看：调 /api/v1/atp/assets/{assetId}/files/content 读取文本内容，
// 以等宽原文展示。二进制/超限文件由后端分类（text / binary / not-found），前端按类型提示。

import { useQuery } from "@tanstack/react-query";
import { Alert, Descriptions, Spin, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

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

interface AtpFileContentViewerProps {
  assetId: string;
  relativePath: string;
  name: string;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function AtpFileContentViewer({ assetId, relativePath, name }: AtpFileContentViewerProps) {
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
        message="读取文件失败"
        description={contentQuery.error instanceof Error ? contentQuery.error.message : ""}
      />
    );
  }

  const data = contentQuery.data;
  if (!data) return null;

  if (data.content_type === "binary") {
    return (
      <Alert
        type="warning"
        showIcon
        message="该文件是二进制格式，无法在线预览文本内容。"
        description={`${data.name || name}（${formatSize(data.size)}）${data.mime_type ? `，MIME：${data.mime_type}` : ""}。如需查看可下载后使用本地工具打开。`}
      />
    );
  }

  if (data.content_type === "not-found") {
    return <Alert type="warning" showIcon message="文件不存在或已被移除。" />;
  }

  const displayText = data.content || (data.preview_lines || []).join("\n");

  return (
    <div>
      <Descriptions
        bordered
        size="small"
        column={3}
        items={[
          { key: "name", label: "文件名", children: data.name || name || "-" },
          { key: "size", label: "文件大小", children: formatSize(data.size) },
          { key: "mime", label: "MIME", children: data.mime_type || "-" },
        ]}
      />
      <Typography.Title level={5} style={{ marginTop: 16, fontSize: 14 }}>
        文件内容
      </Typography.Title>
      {!displayText ? (
        <Alert type="info" showIcon message="文件较大，仅展示前 300 行预览。" />
      ) : null}
      <pre
        style={{
          marginTop: 8,
          maxHeight: 480,
          overflow: "auto",
          background: "#fafafa",
          padding: 12,
          fontSize: 12,
          lineHeight: 1.5,
          whiteSpace: "pre",
          wordBreak: "normal",
          border: "1px solid #f0f0f0",
          borderRadius: 4,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {displayText || "（空文件）"}
      </pre>
    </div>
  );
}