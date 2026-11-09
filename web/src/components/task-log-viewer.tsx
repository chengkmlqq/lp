"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Drawer, Empty, Modal, Spin } from "antd";

import { useAuth } from "@/components/auth-provider";
import { readApiError, API_BASE_URL } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { WsTicketResponse } from "@/types/ws";

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
 *  6. 自动滚动到底部（用户上滚时暂停）
 *  7. 状态仅驱动内部逻辑不展示；任务运行中在日志末尾渲染「三点跳动」加载动效
 *
 * 备注：日志内容底部为深色终端容器，运行中指示器（task-log-streaming-indicator）
 *      样式见 globals.css，仿 AI 聊天工具输出末尾的加载动效。
 *
 * 长行处理：日志行（URL / JSON / 堆栈 / 长路径）常常远超抽屉宽度。早期用
 *      whiteSpace:pre + overflow:auto，超长行会撑出横向滚动条，右侧内容看不到。
 *      现在按容器可用宽度把每条逻辑行预折成若干「显示行」（等宽字体逐列切分），
 *      显示行仍是固定 18px，虚拟滚动的定位精度不受影响；容器 overflow-x:hidden
 *      兜底，任何情况下都不会出现横向滚动条。
 */

const LOG_ROW_HEIGHT = 18;
const LOG_FONT_SIZE = 12;
const LOG_FONT_FAMILY = "ui-monospace, SFMono-Regular, Menlo, monospace";
// 容器左右各 16px padding；clientWidth 已排除纵向滚动条，无需再扣
const LOG_HORIZONTAL_PADDING = 32;
// 首帧 / 非浏览器环境下 ResizeObserver 尚未给出宽度时的兜底可用文本宽度
const LOG_FALLBACK_VIEWPORT_WIDTH = 736;

let cachedLogContext: CanvasRenderingContext2D | null | undefined;
let cachedMonoCharWidth: number | null = null;

/** 复用同一块离屏 canvas，字体与日志容器保持一致。 */
function getLogContext(): CanvasRenderingContext2D | null {
  if (cachedLogContext !== undefined) return cachedLogContext;
  if (typeof document === "undefined") {
    cachedLogContext = null;
    return null;
  }
  const ctx = document.createElement("canvas").getContext("2d");
  if (ctx) ctx.font = `${LOG_FONT_SIZE}px ${LOG_FONT_FAMILY}`;
  cachedLogContext = ctx;
  return ctx;
}

/** 测量等宽字体下单个 ASCII 字符的宽度。 */
function getLogCharWidth(): number {
  if (cachedMonoCharWidth !== null) return cachedMonoCharWidth;
  const ctx = getLogContext();
  if (!ctx) return LOG_FONT_SIZE * 0.6;
  const width = ctx.measureText("0000000000").width / 10;
  cachedMonoCharWidth = width > 0 ? width : LOG_FONT_SIZE * 0.6;
  return cachedMonoCharWidth;
}

const charColumnCache = new Map<string, number>();

/**
 * 字符占的列数：ASCII 恒为 1；其余字符（中文/全角/emoji）用同款字体实测宽度
 * 换算，避免按经验值 2 列低估 emoji 之类的字符，导致行尾被裁。
 */
function logCharColumns(ch: string): number {
  const cached = charColumnCache.get(ch);
  if (cached !== undefined) return cached;
  let cols = 1;
  if ((ch.codePointAt(0) ?? 0) >= 0x80) {
    const ctx = getLogContext();
    // 无 canvas（SSR 首帧）时按 2 列兜底，浏览器端会重新测量
    const width = ctx ? ctx.measureText(ch).width : getLogCharWidth() * 2;
    cols = Math.max(1, Math.ceil(width / getLogCharWidth()));
  }
  charColumnCache.set(ch, cols);
  return cols;
}

/**
 * 把逻辑日志行按可用宽度拆成固定行高的显示行。
 * 无空格长串也在列边界硬折，保证任何日志都不会撑出横向滚动条。
 */
function wrapLogLines(lines: string[], availableWidth: number): string[] {
  // 留 1 列余量，吸收字体度量/字体回退的误差，避免行尾字符被容器裁掉
  const columns = Math.max(8, Math.floor(availableWidth / getLogCharWidth()) - 1);
  const rows: string[] = [];
  for (const raw of lines) {
    // 快速路径：纯 ASCII 短行无需逐字符计算（绝大多数日志行走这里，
    // 使 SSE 每批增量后整体重算折行也只耗时几毫秒）
    if (
      raw.length <= columns &&
      !/[\u0080-\uffff]/u.test(raw) &&
      !raw.includes("\t") &&
      !raw.includes("\r")
    ) {
      rows.push(raw);
      continue;
    }
    // tab 展开成空格：CSS pre 下 tab 的实际占位与逐字符度量不一致
    const line = raw.replace(/\t/g, "    ").replace(/\r/g, "");
    if (!line) {
      rows.push("");
      continue;
    }
    let segment = "";
    let used = 0;
    for (const ch of line) {
      const cols = logCharColumns(ch);
      if (used + cols > columns) {
        rows.push(segment);
        segment = "";
        used = 0;
      }
      segment += ch;
      used += cols;
    }
    rows.push(segment);
  }
  return rows;
}

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
  const { t } = useI18n();
  const [loading, setLoading] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [status, setStatus] = useState("");
  // 方案A+C（2026-09-16）：日志从「单个大字符串」改为「行数组 + 虚拟滚动窗口」。
  // - lines：全量日志行（渲染只画可视窗口，避免几万行 DOM）
  // - pendingLinesRef + flushTimerRef：SSE 增量先入缓冲，定时批量 flush（追加节流，
  //   避免每行 setState 全量重渲染）
  const [lines, setLines] = useState<string[]>([]);
  const pendingLinesRef = useRef<string[]>([]);
  const flushTimerRef = useRef<number | null>(null);
  // 虚拟滚动窗口（显示行仍是固定行高，长行已按宽度预折 → 定位保持精确）
  const [scrollTop, setScrollTop] = useState(0);
  // 日志容器尺寸由 ResizeObserver 统一维护：width 用于折行、height 用于虚拟窗口；
  // 渲染期只读 state，不再读 ref.current（React Compiler 的 refs 规则要求）
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 });
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

  /** 抽屉尺寸变化时重新测量：长行折行列数与虚拟窗口高度一起刷新。 */
  useEffect(() => {
    if (!open || loading) return;
    const el = contentRef.current;
    if (!el) return;
    const measure = () => {
      const width = Math.max(0, el.clientWidth - LOG_HORIZONTAL_PADDING);
      const height = el.clientHeight;
      setViewportSize((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    };
    if (typeof ResizeObserver === "undefined") {
      // 无 ResizeObserver 时异步兜底测量（避免在 effect 内同步 setState）
      const frameId = window.requestAnimationFrame(measure);
      return () => window.cancelAnimationFrame(frameId);
    }
    // observe 后浏览器会立即回调一次，无需在 effect 内同步 setState
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [open, loading]);

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
            const errorMessage = error instanceof Error ? error.message : t("获取日志失败");
            setLines([`${t("错误")}：${errorMessage}`]);
            setLoading(false);
            reconnectRef.current?.(cancelledRef, taskId);
          }
        })();
      }, delay * 1000);
    },
    [closeEventSource, t],
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
        throw new Error(errorText || t("获取日志凭证失败"));
      }
      const ticketPayload = (await ticketRes.json()) as WsTicketResponse;
      if (!ticketPayload.ticket) {
        throw new Error(t("获取日志凭证失败"));
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
    [fetchWithAuth, t],
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
        const errorMessage = error instanceof Error ? error.message : t("获取日志失败");
        setLines([`${t("错误")}：${errorMessage}`]);
        setLoading(false);
      }
    })();

    return () => {
      cancelledRef.current = true;
      closeEventSource();
    };
  }, [open, taskId, fetchWithAuth, connect, closeEventSource, t]);

  const handleClose = () => {
    closeEventSource();
    setLines([]);
    setStatus("");
    setStreaming(false);
    onClose();
  };

  /** 逻辑行 → 显示行；短 ASCII 行走快速路径，全量重算也只是几毫秒。 */
  const displayRows = useMemo(
    () => wrapLogLines(lines, viewportSize.width > 0 ? viewportSize.width : LOG_FALLBACK_VIEWPORT_WIDTH),
    [lines, viewportSize.width],
  );

  // 日志追加时自动滚底（仅流式且未结束场景）
  useEffect(() => {
    if (!streaming || status) {
      return;
    }
    const el = contentRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [displayRows, streaming, status]);

  // 方案A：虚拟滚动——只渲染可视窗口的「显示行」（每行固定 18px，长行已按
  // 容器宽度预折，因此定位精确且不会横向溢出）；尺寸取自 ResizeObserver 的 state
  const viewportH = viewportSize.height || 480;
  const total = displayRows.length;
  const overscan = 30;
  const start = Math.max(0, Math.floor(scrollTop / LOG_ROW_HEIGHT) - overscan);
  const end = Math.min(total, Math.ceil((scrollTop + viewportH) / LOG_ROW_HEIGHT) + overscan);
  const visible = displayRows.slice(start, end);

  const contentNode = loading ? (
    <div style={{ textAlign: "center", padding: "40px 0" }}>
      <Spin />
    </div>
  ) : (
    <div style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div
        ref={contentRef}
        onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
        className="task-log-viewer-scroll"
        style={{
          flex: 1,
          minHeight: 0,
          // 长行已在 wrapLogLines 里按宽度折成多行，横向永不滚动（只保留纵向）
          overflowX: "hidden",
          overflowY: "auto",
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
            description={status === "no-log" ? t("暂无日志") : t("等待日志...")}
          />
        ) : (
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
                  style={{
                    height: LOG_ROW_HEIGHT,
                    lineHeight: `${LOG_ROW_HEIGHT}px`,
                    whiteSpace: "pre",
                    // 兜底：字体度量偏差时裁掉行尾多余像素，绝不让单行撑高/撑宽
                    overflow: "hidden",
                    maxWidth: "100%",
                  }}
                >
                  {line || "\u00A0"}
                </div>
              ))}
            </div>
          </div>
        )}
        {streaming && !status && (
          <div className="task-log-streaming-indicator" role="status" aria-label={t("任务运行中")}>
            <span className="task-log-dot" />
            <span className="task-log-dot" />
            <span className="task-log-dot" />
            {t("任务运行中")}
          </div>
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