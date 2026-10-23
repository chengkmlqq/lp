"use client";

import { useEffect } from "react";

import { useI18n } from "@/lib/i18n";
import { isChunkLoadError, reloadOnceOnChunkError } from "@/lib/chunk-error";

type AppErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppError({ error, reset }: AppErrorProps) {
  const { t } = useI18n();
  useEffect(() => {
    reloadOnceOnChunkError(error);
  }, [error]);

  const chunkError = isChunkLoadError(error);

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
        background: "var(--fquiz-theme-bg-layout, var(--ant-color-bg-layout))",
        color: "var(--fquiz-theme-text-primary, var(--ant-color-text))",
      }}
    >
      <section
        style={{
          width: "100%",
          maxWidth: 520,
          borderRadius: 14,
          background: "var(--fquiz-theme-bg-container, var(--ant-color-bg-container))",
          border: "1px solid var(--fquiz-theme-border, var(--ant-color-border-secondary))",
          boxShadow: "var(--fquiz-theme-shadow-card, var(--ant-box-shadow-tertiary))",
          padding: 24,
        }}
      >
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 700 }}>{t("页面加载失败")}</h1>
        <p style={{ margin: "12px 0 0", lineHeight: 1.6, color: "var(--fquiz-theme-text-secondary, var(--ant-color-text-secondary))" }}>
          {chunkError
            ? "检测到前端静态资源已更新，页面将尝试自动刷新恢复。"
            : "页面发生运行时错误，请重试或手动刷新。"}
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
            刷新页面
          </button>
        </div>
      </section>
    </main>
  );
}
