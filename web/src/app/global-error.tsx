"use client";

import { useEffect } from "react";

import { useI18n } from "@/lib/i18n";
import { isChunkLoadError, reloadOnceOnChunkError } from "@/lib/chunk-error";

type GlobalErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function GlobalError({ error, reset }: GlobalErrorProps) {
  const { t } = useI18n();
  useEffect(() => {
    reloadOnceOnChunkError(error);
  }, [error]);

  const chunkError = isChunkLoadError(error);

  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          padding: 24,
          background: "var(--fquiz-theme-bg-layout, var(--ant-color-bg-layout))",
          color: "var(--fquiz-theme-text-primary, var(--ant-color-text))",
          fontFamily:
            "Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif",
        }}
      >
        <section
          style={{
            width: "100%",
            maxWidth: 560,
            borderRadius: 14,
            background: "var(--fquiz-theme-bg-container, var(--ant-color-bg-container))",
            border: "1px solid var(--fquiz-theme-border, var(--ant-color-border-secondary))",
            boxShadow: "var(--fquiz-theme-shadow-card, var(--ant-box-shadow-tertiary))",
            padding: 24,
          }}
        >
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{t("应用暂时不可用")}</h1>
          <p style={{ margin: "12px 0 0", lineHeight: 1.6, color: "var(--fquiz-theme-text-secondary, var(--ant-color-text-secondary))" }}>
            {chunkError
              ? t("检测到静态资源版本不一致，正在尝试自动刷新页面。")
              : t("应用遇到未处理错误，请重试或刷新后再试。")}
          </p>
          <div style={{ marginTop: 18, display: "flex", gap: 10, flexWrap: "wrap" }}>
            <button
              type="button"
              onClick={reset}
              style={{
                border: "1px solid var(--fquiz-theme-border, var(--ant-color-border-secondary))",
                background: "var(--fquiz-theme-bg-container, var(--ant-color-bg-container))",
                color: "var(--fquiz-theme-text-primary, var(--ant-color-text))",
                borderRadius: 8,
                padding: "8px 14px",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              重试
            </button>
            <button
              type="button"
              onClick={() => window.location.reload()}
              style={{
                border: "1px solid var(--fquiz-theme-primary, var(--ant-color-primary))",
                background: "var(--fquiz-theme-primary, var(--ant-color-primary))",
                color: "var(--fquiz-theme-text-on-primary, var(--accent-contrast))",
                borderRadius: 8,
                padding: "8px 14px",
                cursor: "pointer",
                fontWeight: 600,
              }}
            >
              {t("刷新页面")}
            </button>
          </div>
        </section>
      </body>
    </html>
  );
}
