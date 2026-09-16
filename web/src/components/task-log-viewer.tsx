"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Drawer, Empty, Modal, Space, Spin, Tag, Typography } from "antd";

import { useAuth } from "@/components/auth-provider";
import { readApiError, API_BASE_URL } from "@/lib/api";
import type { WsTicketResponse } from "@/types/ws";

const { Text } = Typography;

/**
 * 通用任务日志查看抽屉。
 *
 * 从任务监控页（task-monitor/page.tsx）提炼的 SSE 日志实现：
 *  1. POST /api/v1/ws/ticket 取一次性凭证
 *  2. new EventSource(`${API_BASE_URL}/api/v1/admin/task-logs/${taskId}/sse?ticket=${ticket}`)
 *  3. onmessage: data.lines 全量覆盖 / data.line 增量追加
 *  4. done 事件 → 关闭连接 + 状态「已结束」
 *  5. error 事件：连接错误（如 ticket 过期 401、网络中断）→ 关闭旧连接，
 *     重新签发 ticket 并以 lastEventId 查询参数携带 Last-Event-ID 游标重建连接，
 *     指数退避重试（修复 LP-295：旧 ticket 30s 过期后自动重连持续 401 的循环）
 *  6. 自动滚动到底部（用户上滚时暂停），可复制
 *  7. 状态 Tag：连接中 / 实时接收中 / 重连中 / 已结束 / 无日志 / 连接中断
 */
export function TaskLogViewerDrawer({
  taskId,
  title,
  open,
  onClose,
  variant = "drawer",
}: {
  taskId: string | null;
  title: string;
  open: boolean;
  onClose: () => void;
  variant?: "drawer" | "modal";
}) {
  const { fetchWithAuth } = useAuth();
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState("");
  // 方案A+C（2026-09-16）：日志从「单个大字符串」改为「行数组 + 虚拟滚动窗口」。
  // - lines：全量日志行（复制时用完整内容；渲染只画可视窗口，避免几万行 DOM）
  // - pendingLinesRef + flushTimerRef：SSE 增量先入缓冲，定时批量 flush（追加节流，
  //   避免每行 setState 全量重渲染）
  const [lines, setLines] = useState<string[]>([]);
  const pendingLinesRef = useRef<string[]>([]);
  const flushTimerRef = useRef<number | null>(null);
  // 虚拟滚动窗口（固定行高，日志行不换行 → 精确）
  const [scrollTop, setScrollTop] = useState(0);
  const LOG_ROW_HEIGHT = 18;
  const contentRef = useRef<HTMLDivElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  // 断线补偿游标：记录最近一条 SSE 事件的 id；重连时作为 Last-Event-ID 传给服务端续读
  const lastEventIdRef = useRef("");
  // 重连指数退避（秒）：1 / 2 / 4 / 8 / 16 → 最多 30
  const retryDelayRef = useRef(1);
  // connect / reconnect 相互引用，通过 ref 打破循环（const 后置声明会触发 TDZ）
  const connectRef = useRef<((cancelledRef: { current: boolean }, taskId: string) => Promise<void>) | null>(null);
  const reconnectRef = useRef<((cancelledRef: { current: boolean }, taskId: string) => void) | null>(null);

  const closeEventSource = useCallback(() => {
    const es = eventSourceRef.current;
    if (es) {
      es.close();
      eventSourceRef.current = null;
    }
  }, []);

  /**
   * 断线重连：关闭旧连接（终止 EventSource 自带的"复用旧 URL+旧 ticket"重连），
   * 指数退避后重签发 ticket 并重建连接，恢复日志流（LP-295）。
   */
  const reconnect = useCallback(
    (cancelledRef: { current: boolean }, taskId: string) => {
      if (cancelledRef.current) return;
      closeEventSource();
      setStreaming(false);
      const delay = retryDelayRef.current;
      retryDelayRef.current = Math.min(30, delay * 2);
      setStatus("reconnecting");
      window.setTimeout(() => {
        if (cancelledRef.current) return;
        (async () => {
          try {
            await connectRef.current?.(cancelledRef, taskId);
          } catch (error) {
            if (cancelledRef.current) return;
            const errorMessage = error instanceof Error ? error.message : "获取日志失败";
            setLines([`错误：${errorMessage}`]);
            setLoading(false);
            reconnectRef.current?.(cancelledRef, taskId);
          }
        })();
      }, delay * 1000);
    },
    [closeEventSource],
  );
  // connect / reconnect 相互引用，经 ref 调用；ref 需在渲染后写入（不能渲染期访问）
  useEffect(() => {
    reconnectRef.current = reconnect;
  }, [reconnect]);

  /** 为一个新 ticket 拉起一条 SSE 连接。 */
  const connect = useCallback(
    async (cancelledRef: { current: boolean }, taskId: string) => {
      // 1. 先签发一次性 ticket（复用 /api/v1/ws/ticket）
      const ticketRes = await fetchWithAuth("/api/v1/ws/ticket", { method: "POST" });
      if (!ticketRes.ok) {
        const errorText = await readApiError(ticketRes);
        throw new Error(errorText || "获取日志凭证失败");
      }
      const ticketPayload = (await ticketRes.json()) as WsTicketResponse;
      if (!ticketPayload.ticket) {
        throw new Error("获取日志凭证失败");
      }

      // 2. 建立 SSE 连接（EventSource 无法自定义 Authorization header，走 ticket 查询参数）
      const params = new URLSearchParams({ ticket: ticketPayload.ticket });
      // 断线重连：把 Last-Event-ID 游标作为查询参数带回，服务端据此续读（EventSource
      // 重连会自动带 Last-Event-ID header，但这里重建了连接，必须显式传；后端 sse
      // 端点同时兼容 header 与 lastEventId 查询参数两种来源）
      if (lastEventIdRef.current) {
        params.set("lastEventId", lastEventIdRef.current);
      }
      const es = new EventSource(
        `${API_BASE_URL}/api/v1/admin/task-logs/${encodeURIComponent(taskId)}/sse?${params.toString()}`,
      );
      eventSourceRef.current = es;

      es.onopen = () => {
        if (cancelledRef.current) return;
        retryDelayRef.current = 1;
        setLoading(false);
        setStreaming(true);
        setStatus("");
      };

      es.onmessage = (e) => {
        if (cancelledRef.current) return;
        if (e.lastEventId) {
          lastEventIdRef.current = e.lastEventId;
        }
        try {
          const data = JSON.parse(e.data) as { line?: string; lines?: string };
          const linesText = data.lines;
          const singleLine = data.line;
          if (linesText) {
            // 全量（重连续读/初始）：拆行直接覆盖，清掉挂起的增量缓冲
            pendingLinesRef.current = [];
            if (flushTimerRef.current !== null) {
              window.clearTimeout(flushTimerRef.current);
              flushTimerRef.current = null;
            }
            setLines(linesText.split("\n"));
          } else if (singleLine) {
            // 增量：先入缓冲，定时批量 flush（追加节流，避免每行 setState 全量重渲染）
            pendingLinesRef.current.push(singleLine);
            if (flushTimerRef.current === null) {
              flushTimerRef.current = window.setTimeout(() => {
                flushTimerRef.current = null;
                const batch = pendingLinesRef.current;
                pendingLinesRef.current = [];
                if (batch.length > 0) {
                  setLines((prev) => (prev.length === 0 ? batch : [...prev, ...batch]));
                }
              }, 100);
            }
          }
        } catch {
          // 忽略无法解析的 SSE 数据
        }
      };

      es.addEventListener("done", () => {
        if (cancelledRef.current) return;
        es.close();
        eventSourceRef.current = null;
        setStreaming(false);
        setStatus("done");
      });

      es.addEventListener("error", (e) => {
        if (cancelledRef.current) return;
        // error 事件也可能由 `event: error` 自定义事件触发（服务端推送的明确错误）
        const eventSourceError = e as MessageEvent<string>;
        try {
          const data = JSON.parse(eventSourceError.data ?? "") as { message?: string };
          if (data.message) {
            setLines([data.message]);
            setStreaming(false);
            return;
          }
        } catch {
          // 普通连接错误：关闭旧连接，重新取票并重建连接（ticket 已过期 / 连接中断）
        }
        reconnectRef.current?.(cancelledRef, taskId);
      });
    },
    [fetchWithAuth],
  );
  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!open) {
      return;
    }
    closeEventSource();
    lastEventIdRef.current = "";
    retryDelayRef.current = 1;

    // 从零开始的一次性连接（与 reconnect 复用同一个 connect 实现）。
    // 状态重置放在异步函数内：避免 effect 内同步 setState（lint 规则 + 级联渲染）。
    const cancelledRef: { current: boolean } = { current: false };
    (async () => {
      if (!taskId) {
        setLoading(false);
        setStreaming(false);
        setStatus("no-log");
        setLines([]);
        return;
      }
      setLoading(true);
      setStreaming(false);
      setStatus("");
      setLines([]);
      try {
        await connect(cancelledRef, taskId);
      } catch (error) {
        if (cancelledRef.current) return;
        const errorMessage = error instanceof Error ? error.message : "获取日志失败";
        setLines([`错误：${errorMessage}`]);
        setLoading(false);
      }
    })();

    return () => {
      cancelledRef.current = true;
      closeEventSource();
    };
  }, [open, taskId, fetchWithAuth, connect, closeEventSource]);

  const handleClose = () => {
    closeEventSource();
    setLines([]);
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
  }, [lines, streaming, status]);

  const statusTone = status === "done"
    ? "success"
    : status === "reconnecting"
      ? "warning"
      : streaming
        ? "processing"
        : "default";
  const statusLabel = status === "done"
    ? "已结束"
    : status === "reconnecting"
      ? "重连中"
      : streaming
        ? "实时接收中"
        : status === "no-log"
          ? "无日志"
          : "";

  const contentNode = loading ? (
    <div style={{ textAlign: "center", padding: "40px 0" }}>
      <Spin />
    </div>
  ) : (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
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
        {lines.length > 0 && (
          <Button
            type="link"
            size="small"
            onClick={() => navigator.clipboard?.writeText(lines.join("\n"))}
          >
            复制
          </Button>
        )}
      </Space>
      <div
        ref={contentRef}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        style={{
          flex: 1,
          minHeight: 0,
          overflow: "auto",
          padding: "16px",
          backgroundColor: "#0f172a",
          color: "#e2e8f0",
          borderRadius: "4px",
          fontSize: "12px",
          lineHeight: "18px",
          whiteSpace: "pre",
          wordBreak: "normal",
          fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        }}
      >
        {lines.length === 0 ? (
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description={status === "no-log" ? "暂无日志" : "等待日志..."}
          />
        ) : (
          (() => {
            // 方案A：虚拟滚动——只渲染可视窗口行（固定行高，白屏不换行）
            // 容器高度实时读取（flex 撑开，Drawer/Modal 下不固定），滚动时更新
            const viewportH = contentRef.current?.clientHeight ?? 480;
            const total = lines.length;
            const overscan = 30;
            const start = Math.max(0, Math.floor(scrollTop / LOG_ROW_HEIGHT) - overscan);
            const end = Math.min(
              total,
              Math.ceil((scrollTop + viewportH) / LOG_ROW_HEIGHT) + overscan,
            );
            const visible = lines.slice(start, end);
            return (
              <div style={{ height: total * LOG_ROW_HEIGHT, position: "relative" }}>
                <div
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    right: 0,
                    transform: `translateY(${start * LOG_ROW_HEIGHT}px)`,
                  }}
                >
                  {visible.map((line, i) => (
                    <div
                      key={start + i}
                      style={{ height: LOG_ROW_HEIGHT, lineHeight: `${LOG_ROW_HEIGHT}px`, whiteSpace: "pre" }}
                    >
                      {line || "\u00A0"}
                    </div>
                  ))}
                </div>
              </div>
            );
          })()
        )}
      </div>
    </div>
  );

  if (variant === "modal") {
    return (
      <Modal
        title={title}
        width={800}
        open={open}
        onCancel={handleClose}
        footer={null}
        destroyOnHidden
        styles={{ body: { height: "60vh", overflow: "hidden", display: "flex", flexDirection: "column" } }}
      >
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          {contentNode}
        </div>
      </Modal>
    );
  }

  return (
    <Drawer
      title={title}
      width={800}
      open={open}
      onClose={handleClose}
      destroyOnHidden
    >
      {contentNode}
    </Drawer>
  );
}