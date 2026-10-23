"use client";

/**
 * 语言切换器：中文 / English 双按钮（Segmented 风格），
 * 登录页（compact 小尺寸）与 admin 布局 header 复用。
 */
import { Button, Space, Tooltip } from "antd";
import { GlobalOutlined } from "@ant-design/icons";
import type { AppLang } from "@/lib/i18n";

export function LangSwitcher({
  lang,
  onChange,
  compact = false,
}: {
  lang: AppLang;
  onChange: (next: AppLang) => void;
  compact?: boolean;
}) {
  return (
    <Tooltip title={lang === "zh" ? "切换语言 / Switch language" : "切换语言 / Switch language"}>
      <Space size={2}>
        {compact ? <GlobalOutlined style={{ color: "var(--ant-color-text-secondary)" }} /> : null}
        <Button
          type={lang === "zh" ? "primary" : "text"}
          size="small"
          style={{ fontSize: 12, paddingInline: compact ? 8 : 12 }}
          onClick={() => onChange("zh")}
        >
          中
        </Button>
        <Button
          type={lang === "en" ? "primary" : "text"}
          size="small"
          style={{ fontSize: 12, paddingInline: compact ? 8 : 12 }}
          onClick={() => onChange("en")}
        >
          EN
        </Button>
      </Space>
    </Tooltip>
  );
}
