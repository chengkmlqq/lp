"use client";

// MODO Design System 主题（迁移自 kb_compilation，2026-10-30）。
// 仅保留浅色主题：品牌蓝 #3261CE、12px 基准字号、28px 控件高。
// 历史上的电光紫/暗色/紧凑/快乐工作模式已移除；
// useThemeAppearance 保留为兼容空实现，供旧调用方过渡。

import {
  createContext,
  useContext,
  useMemo,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  App as AntApp,
  Button as AntButton,
  ConfigProvider,
  theme as antdTheme,
  type ThemeConfig,
} from "antd";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { useI18n } from "@/lib/i18n";
import { modoThemeToken } from "@/theme/antd-theme-token";
import { modoAlgorithm } from "@/theme/modo-algorithm";

export function cn(...inputs: Array<string | undefined | false | null>) {
  return twMerge(clsx(inputs));
}

export function toSpacingValue(value: string | number | undefined): string | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (typeof value === "number") {
    return `${value * 4}px`;
  }
  const trimmed = value.trim();
  if (!trimmed) {
    return undefined;
  }
  if (/^\d+(\.\d+)?$/.test(trimmed)) {
    return `${Number(trimmed) * 4}px`;
  }
  return trimmed;
}

export function withSpacingStyle({
  mt,
  mb,
  style,
}: {
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
}): CSSProperties {
  return {
    marginTop: toSpacingValue(mt),
    marginBottom: toSpacingValue(mb),
    ...style,
  };
}

export function mapTextSize(size?: string): number | undefined {
  switch (size) {
    case "1":
      return 12;
    case "2":
      return 14;
    case "3":
      return 16;
    case "4":
      return 18;
    case "5":
      return 20;
    default:
      return undefined;
  }
}

export function mapHeadingLevel(size?: string, as?: string): 1 | 2 | 3 | 4 | 5 {
  if (as) {
    if (as === "h1") return 1;
    if (as === "h2") return 2;
    if (as === "h3") return 3;
    if (as === "h4") return 4;
    return 5;
  }
  if (!size) return 3;
  const numeric = Number(size);
  if (Number.isNaN(numeric)) return 3;
  if (numeric >= 8) return 1;
  if (numeric >= 6) return 2;
  if (numeric >= 5) return 3;
  if (numeric >= 4) return 4;
  return 5;
}

export function mapButtonSize(size?: string): "small" | "middle" | "large" {
  if (size === "1") return "small";
  if (size === "3") return "large";
  return "middle";
}

export function mapInputSize(size?: string): "small" | "middle" | "large" {
  if (size === "1") return "small";
  if (size === "3") return "large";
  return "middle";
}

type ThemeProps = {
  children: ReactNode;
  accentColor?: string;
  grayColor?: string;
  radius?: string;
  scaling?: string;
};

// 兼容保留：历史上多主题色的常量，现固定为 MODO 蓝。
export const THEME_ACCENT_OPTIONS = [{ value: "modo", label: "MODO 蓝" }] as const;
export const THEME_MODE_OPTIONS = [{ value: "light", label: "浅色主题" }] as const;

export type ThemeAccentColor = "modo";
export type ThemeMode = "light";
export type ThemePrimaryMode = "light";

type ThemeAppearanceContextValue = {
  accentColor: ThemeAccentColor;
  setAccentColor: (nextColor: string) => void;
  themeMode: ThemeMode;
  setThemeMode: (nextMode: string) => void;
  themePrimaryMode: ThemePrimaryMode;
  setThemePrimaryMode: (nextMode: string) => void;
  compactMode: boolean;
  setCompactMode: (nextValue: boolean) => void;
  happyWorkMode: boolean;
  setHappyWorkMode: (nextValue: boolean) => void;
  isDark: boolean;
};

const ThemeAppearanceContext = createContext<ThemeAppearanceContextValue | null>(null);

const NOOP_APPEARANCE: ThemeAppearanceContextValue = {
  accentColor: "modo",
  setAccentColor: () => {},
  themeMode: "light",
  setThemeMode: () => {},
  themePrimaryMode: "light",
  setThemePrimaryMode: () => {},
  compactMode: false,
  setCompactMode: () => {},
  happyWorkMode: false,
  setHappyWorkMode: () => {},
  isDark: false,
};

export function useThemeAppearance(): ThemeAppearanceContextValue {
  const context = useContext(ThemeAppearanceContext);
  return context ?? NOOP_APPEARANCE;
}

/** MODO 色板 CSS 变量，供页面样式直接引用（与 kb_compilation 同名同值）。 */
export const MODO_CSS_VARS = {
  "--modo-primary": "#3261CE",
  "--modo-primary-hover": "#517ED8",
  "--modo-primary-active": "#2045AE",
  "--modo-primary-bg": "#E8F3FF",
  "--modo-success": "#55BC8A",
  "--modo-warning": "#F5A623",
  "--modo-error": "#C3342F",
  "--modo-gray-1": "#F9FBFD", // 布局底 / 表头底
  "--modo-gray-2": "#EFF4F9", // 页面灰底 / 输入填充
  "--modo-gray-3": "#E3E9EF", // 边框
  "--modo-gray-4": "#B3C0CC", // 占位 / 禁用
  "--modo-gray-6": "#79879C", // 次要文字
  "--modo-gray-8": "#4D5E7D", // 表单 label
  "--modo-gray-10": "#242E43", // 正文主色
  "--modo-shadow-1": "0 2px 5px 0 rgba(36, 46, 67, 0.1)",
  "--modo-shadow-2": "0 4px 10px 0 rgba(36, 46, 67, 0.1)",
  "--modo-shadow-3": "0 8px 20px 0 rgba(36, 46, 67, 0.1)",
  "--app-header-h": "48px",
} as const;

function ThemeCssVarsScope({ children }: { children: ReactNode }) {
  const { token } = antdTheme.useToken();

  const themeCssVarStyle = useMemo(
    () =>
      ({
        // MODO 色板变量
        ...MODO_CSS_VARS,

        // AntD token aliases used directly in pages
        "--ant-color-primary": token.colorPrimary,
        "--ant-color-text": token.colorText,
        "--ant-color-text-secondary": token.colorTextSecondary,
        "--ant-color-bg-layout": token.colorBgLayout,
        "--ant-color-bg-container": token.colorBgContainer,
        "--ant-color-primary-bg": token.colorPrimaryBg,
        "--ant-color-primary-bg-hover": token.colorPrimaryBgHover,
        "--ant-color-primary-hover": token.colorPrimaryHover,
        "--ant-color-fill-alter": token.colorFillAlter,
        "--ant-color-border": token.colorBorder,
        "--ant-color-border-secondary": token.colorBorderSecondary,
        "--ant-border-radius": `${token.borderRadius}px`,
        "--ant-border-radius-lg": `${token.borderRadiusLG}px`,
        "--ant-padding": `${token.padding}px`,
        "--ant-padding-lg": `${token.paddingLG}px`,
        "--ant-margin-lg": `${token.marginLG}px`,
        "--ant-box-shadow-tertiary": token.boxShadowTertiary,

        // Legacy semantic vars remapped to AntD palette
        "--color-panel-solid": token.colorBgContainer,
        "--border": token.colorBorderSecondary,

        "--gray-1": token.colorBgContainer,
        "--gray-2": token.colorFillAlter,
        "--gray-6": token.colorBorderSecondary,
        "--gray-10": token.colorTextTertiary,
        "--gray-11": token.colorTextSecondary,
        "--gray-12": token.colorText,
        "--gray-a2": token.colorFillQuaternary,
        "--gray-a3": token.colorFillTertiary,

        "--accent-6": token.colorPrimaryBorder,
        "--accent-7": token.colorPrimaryBorderHover,
        "--accent-9": token.colorPrimary,
        "--accent-10": token.colorPrimaryHover,
        "--accent-11": token.colorPrimaryText,
        "--accent-12": token.colorPrimaryTextActive,
        "--accent-a2": token.colorPrimaryBg,
        "--accent-a3": token.colorPrimaryBgHover,
        "--accent-contrast": token.colorTextLightSolid,

        "--indigo-2": token.colorPrimaryBg,
        "--indigo-11": token.colorPrimaryText,
        "--indigo-a2": token.colorPrimaryBg,

        "--green-6": token.colorSuccessBorder,
        "--green-9": token.colorSuccess,
        "--green-11": token.colorSuccessText,
        "--green-a2": token.colorSuccessBg,
        "--green-a3": token.colorSuccessBgHover,

        "--red-2": token.colorErrorBg,
        "--red-6": token.colorErrorBorder,
        "--red-7": token.colorErrorBorderHover,
        "--red-11": token.colorErrorText,
        "--red-a2": token.colorErrorBg,
        "--red-a3": token.colorErrorBgHover,

        "--orange-9": token.colorWarning,
        "--orange-11": token.colorWarningText,
        "--orange-a3": token.colorWarningBgHover,
        "--amber-11": token.colorWarningText,

        // `display: contents` avoids adding extra layout boxes.
        display: "contents",
      }) as CSSProperties,
    [token],
  );

  return <div style={themeCssVarStyle}>{children}</div>;
}

export function Theme({ children }: ThemeProps) {
  const { antdLocale } = useI18n();

  const themeConfig = useMemo<ThemeConfig>(
    () => ({
      ...modoThemeToken,
      algorithm: [modoAlgorithm],
    }),
    [],
  );

  return (
    <ThemeAppearanceContext.Provider value={NOOP_APPEARANCE}>
      <ConfigProvider locale={antdLocale} theme={themeConfig}>
        <AntApp
          message={{
            top: 24,
            duration: 3.5,
          }}
        >
          <ThemeCssVarsScope>{children}</ThemeCssVarsScope>
        </AntApp>
      </ConfigProvider>
    </ThemeAppearanceContext.Provider>
  );
}

type NativeButtonType = "button" | "submit" | "reset";
export type VisualButtonType = NonNullable<React.ComponentProps<typeof AntButton>["type"]>;

export type ButtonProps = Omit<React.ComponentProps<typeof AntButton>, "size" | "color" | "type" | "variant"> & {
  asChild?: boolean;
  color?: "gray" | "indigo" | "red" | string;
  variant?: "solid" | "soft" | "ghost" | string;
  size?: "1" | "2" | "3" | string;
  type?: VisualButtonType | NativeButtonType;
  mt?: string | number;
  mb?: string | number;
};

export function isNativeButtonType(value: ButtonProps["type"]): value is NativeButtonType {
  return value === "button" || value === "submit" || value === "reset";
}

export function isVisualButtonType(value: ButtonProps["type"]): value is VisualButtonType {
  return value !== undefined && !isNativeButtonType(value);
}
