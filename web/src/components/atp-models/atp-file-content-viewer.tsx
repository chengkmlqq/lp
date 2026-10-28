"use client";

// ATP 模型文件通用在线查看：调 /api/v1/atp/assets/{assetId}/files/content 行级懒加载读取。
// 首屏拉前 PAGE_SIZE 行，滚动到底自动续拉下一页并追加，支持查看全文（不截断）。
// 二进制/不存在由后端分类（text / binary / not-found），前端按类型提示。

import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Spin } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";

import { useI18n } from "@/lib/i18n";
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
  const { t } = useI18n();
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
        message={t("读取文件失败")}
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
        message={t("该文件是二进制格式，无法在线预览文本内容。")}
        description={`${data.name || name}（${formatSize(data.size)}）${data.mime_type ? `，MIME：${data.mime_type}` : ""}。如需查看可下载后使用本地工具打开。`}
      />
    );
  }

  if (data.content_type === "not-found") {
    return <Alert type="warning" showIcon message={t("文件不存在或已被移除。")} />;
  }

  const showMore = hasMore && !contentQuery.isFetching;

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", minHeight: 0 }}>
      <pre
        ref={scrollRef}
        onScroll={handleScroll}
        className="task-log-viewer-scroll"
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          padding: 16,
          backgroundColor: "#0f172a",
          color: "#e2e8f0",
          fontSize: 12,
          lineHeight: "18px",
          whiteSpace: "pre",
          wordBreak: "normal",
          borderRadius: 4,
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
          margin: 0,
        }}
      >
        {loadedLines.length === 0 ? t("（空文件）") : loadedLines.join("\n")}
      </pre>
      {showMore && (
        <div style={{ textAlign: "center", marginTop: 8 }}>
          <Button
            type="link"
            size="small"
            onClick={() => void loadMore()}
            loading={loadingMoreRef.current}
          >
            {t("加载更多（已加载")} {loadedLines.length} / {totalLines} {t("行）")}
          </Button>
        </div>
      )}
    </div>
  );
}