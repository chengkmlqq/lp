"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Empty, Modal, Space, Spin, Tag, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { readApiError, API_BASE_URL } from "@/lib/api";

const { Text } = Typography;

/**
 * 通用任务日志查看弹窗。
 *
 * 从任务监控页（task-monitor/page.tsx）提炼的 SSE 日志实现：
 *  1. POST /api/v1/ws/ticket 取一次性凭证
 *  2. new EventSource(`${API_BASE_URL}/api/v1/admin/task-logs/${taskId}/sse?ticket=${ticket}`)
 *  3. onmessage: data.lines 全量覆盖 / data.line 增量追加
 *  4. done 事件 → 关闭连接 + 状态「已结束」
 *  5. error 事件保持连接（EventSource 自动重连，Last-Event-ID 断线补偿由服务端处理）
 *  6. 自动滚动到底部（用户上滚时暂停），可复制
 *  7. 状态 Tag：连接中 / 实时接收中 / 已结束 / 无日志
 */
export function TaskLogViewerModal({
  taskId,
  title,
  open,
  onClose,
}: {
  taskId: string | null;
  title: string;
  open: boolean;
  onClose: () => void;
}) {
  const { fetchWithAuth } = useAuth();
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState("");
  const [content, setContent] = useState("");
  const eventSourceRef = useRef<EventSource | null>(null);
  const contentRef = useRef<HTMLPreElement | null>(null);

  const closeEventSource = useCallback(() => {
    const es = eventSourceRef.current;
    if (es) {
      es.close();
      eventSourceRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!taskId) {
      setLoading(false);
      setStreaming(false);
      setStatus("no-log");
      setContent("");
      return;
    }
    setLoading(true);
    setStreaming(false);
    setStatus("");
    setContent("");
    closeEventSource();

    let cancelled = false;

    (async () => {
      try {
        // 1. 先签发一次性 ticket（复用 /api/v1/ws/ticket）
        const ticketRes = await fetchWithAuth("/api/v1/ws/ticket", { method: "POST" });
        if (!ticketRes.ok) {
          const errorText = await readApiError(ticketRes);
          throw new Error(errorText || "获取日志凭证失败");
        }
        const ticketPayload = (await ticketRes.json()) as { ticket: string };
        if (!ticketPayload.ticket) {
          throw new Error("获取日志凭证失败");
        }

        // 2. 建立 SSE 连接（EventSource 无法自定义 Authorization header，走 ticket 查询参数）
        const es = new EventSource(
          `${API_BASE_URL}/api/v1/admin/task-logs/${encodeURIComponent(taskId)}/sse?ticket=${encodeURIComponent(ticketPayload.ticket)}`,
        );
        eventSourceRef.current = es;

        es.onopen = () => {
          if (cancelled) return;
          setLoading(false);
          setStreaming(true);
        };

        es.onmessage = (e) => {
          if (cancelled) return;
          try {
            const data = JSON.parse(e.data) as { line?: string; lines?: string };
            const linesText = data.lines;
            const singleLine = data.line;
            if (linesText) {
              setContent(linesText);
            } else if (singleLine) {
              setContent((prev) => (prev ? `${prev}\n${singleLine}` : singleLine));
            }
          } catch {
            // 忽略无法解析的 SSE 数据
          }
        };

        es.addEventListener("done", () => {
          if (cancelled) return;
          es.close();
          eventSourceRef.current = null;
          setStreaming(false);
          setStatus("done");
        });

        es.addEventListener("error", (e) => {
          if (cancelled) return;
          // error 事件也可能由 `event: error` 自定义事件触发
          const eventSourceError = e as MessageEvent<string>;
          try {
            const data = JSON.parse(eventSourceError.data ?? "") as { message?: string };
            if (data.message) {
              setContent(data.message);
            }
          } catch {
            // 普通连接错误（EventSource 自动重连，无需处理）
          }
        });
      } catch (error) {
        if (cancelled) return;
        const errorMessage = error instanceof Error ? error.message : "获取日志失败";
        setContent(`错误：${errorMessage}`);
        setLoading(false);
      }
    })();

    return () => {
      cancelled = true;
      closeEventSource();
    };
  }, [open, taskId, fetchWithAuth, closeEventSource]);

  const handleClose = () => {
    closeEventSource();
    setContent("");
    setStatus("");
    setStreaming(false);
    onClose();
  };

  // 日志追加时自动滚底（仅流式且未结束场景）
  useEffect(() => {
    if (!streaming || status) {
      return;
    }
    const el = contentRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [content, streaming, status]);

  const statusTone = status === "done"
    ? "success"
    : streaming
      ? "processing"
      : status === "no-log"
        ? "default"
        : "default";
  const statusLabel = status === "done"
    ? "已结束"
    : streaming
      ? "实时接收中"
      : status === "no-log"
        ? "无日志"
        : "";

  return (
    <Modal
      title={title}
      open={open}
      onCancel={handleClose}
      footer={[
        <Button key="close" onClick={handleClose}>
          关闭
        </Button>,
      ]}
      width={760}
      style={{ top: 20 }}
    >
      {loading ? (
        <div style={{ textAlign: "center", padding: "40px 0" }}>
          <Spin tip="加载日志中..." />
        </div>
      ) : (
        <>
          <Space
            style={{ width: "100%", justifyContent: "space-between", marginBottom: 8 }}
            align="center"
          >
            <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
              {streaming && !status && <Spin size="small" />}
              {streaming && !status && (
                <Text type="secondary" style={{ fontSize: 12 }}>
                  任务运行中，实时接收日志...
                </Text>
              )}
              {status && <Tag color={statusTone}>{statusLabel}</Tag>}
            </span>
            {content && (
              <Button
                type="link"
                size="small"
                onClick={() => navigator.clipboard?.writeText(content)}
              >
                复制
              </Button>
            )}
          </Space>
          <pre
            ref={contentRef}
            style={{
              maxHeight: "420px",
              overflow: "auto",
              padding: "16px",
              backgroundColor: "#0f172a",
              color: "#e2e8f0",
              borderRadius: "4px",
              fontSize: "12px",
              lineHeight: "1.5",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
            }}
          >
            {content || (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={status === "no-log" ? "暂无日志" : "等待日志..."}
              />
            )}
          </pre>
        </>
      )}
    </Modal>
  );
}