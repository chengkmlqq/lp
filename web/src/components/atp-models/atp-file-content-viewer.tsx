"use client";

// ATP 模型文件通用在线查看：调 /api/v1/atp/assets/{assetId}/files/content 行级懒加载读取。
// 首屏拉前 PAGE_SIZE 行，滚动到底自动续拉下一页并追加，支持查看全文（不截断）。
// 二进制/不存在由后端分类（text / binary / not-found），前端按类型提示。

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Spin, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

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
  offset: number;
  limit: number;
  total_lines: number;
  has_more: boolean;
}

interface AtpFileContentViewerProps {
  assetId: string;
  relativePath: string;
  name: string;
}

const PAGE_SIZE = 500;

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function AtpFileContentViewer({ assetId, relativePath, name }: AtpFileContentViewerProps) {
  const { user, fetchWithAuth } = useAuth();
  const [loadedLines, setLoadedLines] = useState<string[]>([]);
  const [totalLines, setTotalLines] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [offset, setOffset] = useState(0);
  const scrollRef = useRef<HTMLPreElement | null>(null);
  const loadingMoreRef = useRef(false);

  const contentQuery = useQuery({
    queryKey: ["/api/v1/atp/assets", assetId, "files", "content", relativePath],
    enabled: Boolean(user && assetId && relativePath),
    queryFn: async () => {
      // 首屏：拉第一页（含 total_lines/has_more 元信息）
      const params = new URLSearchParams({ path: relativePath, offset: "0", limit: String(PAGE_SIZE) });
      const response = await fetchWithAuth(
        `/api/v1/atp/assets/${assetId}/files/content?${params.toString()}`,
      );
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as AtpFileContentResponse;
    },
  });

  // 首页数据到达后初始化行缓冲
  useEffect(() => {
    const data = contentQuery.data;
    if (!data || contentQuery.isFetching) return;
    const initial = data.content ? data.content.split("\n") : (data.preview_lines ?? []);
    setLoadedLines(initial);
    setTotalLines(data.total_lines || initial.length);
    setHasMore(data.has_more);
    setOffset(data.offset + initial.length);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentQuery.data, contentQuery.isFetching]);

  // 续拉下一页（懒加载）
  const loadMore = useCallback(async () => {
    if (!user || loadingMoreRef.current || !hasMore) return;
    loadingMoreRef.current = true;
    try {
      const params = new URLSearchParams({ path: relativePath, offset: String(offset), limit: String(PAGE_SIZE) });
      const response = await fetchWithAuth(
        `/api/v1/atp/assets/${assetId}/files/content?${params.toString()}`,
      );
      if (!response.ok) return;
      const data = (await response.json()) as AtpFileContentResponse;
      if (data.content) {
        setLoadedLines((prev) => [...prev, ...data.content.split("\n")]);
        setOffset(data.offset + (data.content.split("\n").length));
        setHasMore(data.has_more);
        setTotalLines(data.total_lines || 0);
      }
    } catch {
      // 静默失败：下次滚动会重试
    } finally {
      loadingMoreRef.current = false;
    }
  }, [user, fetchWithAuth, assetId, relativePath, offset, hasMore]);

  // 滚动到底部自动续拉
  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollTop + el.clientHeight >= el.scrollHeight - 40) {
      void loadMore();
    }
  }, [loadMore]);

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

  const showMore = hasMore && !contentQuery.isFetching;

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
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 16,
          marginBottom: 8,
        }}
      >
        <Typography.Title level={5} style={{ fontSize: 14, margin: 0 }}>
          文件内容
        </Typography.Title>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          已加载 {loadedLines.length} / {totalLines > 0 ? totalLines : "?"} 行
          {hasMore ? "（滚动加载更多）" : "（已全部加载）"}
        </Typography.Text>
      </div>
      <pre
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
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
        {loadedLines.length === 0 ? "（空文件）" : loadedLines.join("\n")}
      </pre>
      {showMore && (
        <div style={{ textAlign: "center", marginTop: 8 }}>
          <Button
            type="link"
            size="small"
            onClick={() => void loadMore()}
            loading={loadingMoreRef.current}
          >
            加载更多（已加载 {loadedLines.length} / {totalLines} 行）
          </Button>
        </div>
      )}
    </div>
  );
}