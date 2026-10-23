"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
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

const PRIMARY_COLOR_MAP: Record<string, string> = {
  indigo: "#4f46e5",
  blue: "#1677ff",
  cyan: "#06b6d4",
  green: "#16a34a",
  red: "#dc2626",
  orange: "#ea580c",
  pink: "#db2777",
  purple: "#7c3aed",
  electric: "#8b5cf6",
};

export const THEME_ACCENT_OPTIONS = [
  { value: "electric", label: "电光紫" },
  { value: "indigo", label: "靛蓝" },
  { value: "blue", label: "蓝色" },
  { value: "cyan", label: "青色" },
  { value: "green", label: "绿色" },
  { value: "orange", label: "橙色" },
  { value: "red", label: "红色" },
  { value: "pink", label: "粉色" },
  { value: "purple", label: "紫色" },
] as const;

export type ThemeAccentColor = keyof typeof PRIMARY_COLOR_MAP;
export type ThemeMode = "light" | "dark" | "compact" | "dark-compact";
export type ThemePrimaryMode = "auto" | "light" | "dark";

const THEME_ACCENT_STORAGE_KEY = "fquiz:theme:accent-color";
const THEME_PRIMARY_MODE_STORAGE_KEY = "fquiz:theme:primary-mode";
const THEME_COMPACT_STORAGE_KEY = "fquiz:theme:compact";
const THEME_HAPPY_WORK_STORAGE_KEY = "fquiz:theme:happy-work";
// Legacy key for backward compatibility with old four-mode switcher.
const THEME_MODE_STORAGE_KEY = "fquiz:theme:mode";

export const THEME_MODE_OPTIONS = [
  { value: "auto", label: "跟随系统" },
  { value: "light", label: "浅色主题" },
  { value: "dark", label: "暗黑主题" },
] as const;

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

function normalizeAccentColor(nextColor: string | undefined | null): ThemeAccentColor {
  if (nextColor && nextColor in PRIMARY_COLOR_MAP) {
    return nextColor as ThemeAccentColor;
  }
  return "electric";
}

function normalizeLegacyThemeMode(nextMode: string | undefined | null): ThemeMode {
  if (nextMode === "dark" || nextMode === "compact" || nextMode === "dark-compact") {
    return nextMode;
  }
  return "light";
}

function normalizeThemePrimaryMode(nextMode: string | undefined | null): ThemePrimaryMode {
  if (nextMode === "light" || nextMode === "dark") {
    return nextMode;
  }
  return "auto";
}

function normalizeBooleanFlag(nextValue: string | undefined | null): boolean | null {
  if (nextValue === "1" || nextValue === "true") {
    return true;
  }
  if (nextValue === "0" || nextValue === "false") {
    return false;
  }
  return null;
}

function toLegacyThemeMode(isDark: boolean, compactMode: boolean): ThemeMode {
  if (compactMode && isDark) {
    return "dark-compact";
  }
  if (compactMode) {
    return "compact";
  }
  return isDark ? "dark" : "light";
}

export function useThemeAppearance(): ThemeAppearanceContextValue {
  const context = useContext(ThemeAppearanceContext);
  if (context) {
    return context;
  }
  return {
    accentColor: "electric",
    setAccentColor: () => {},
    themeMode: "light",
    setThemeMode: () => {},
    themePrimaryMode: "auto",
    setThemePrimaryMode: () => {},
    compactMode: false,
    setCompactMode: () => {},
    happyWorkMode: false,
    setHappyWorkMode: () => {},
    isDark: false,
  };
}

const RADIUS_MAP: Record<string, number> = {
  none: 0,
  small: 4,
  medium: 6,
  large: 8,
  full: 999,
};

function buildThemeVisualTokens(isDark: boolean) {
  return {
    colorBgLayout: isDark ? "#0f1419" : "#f5f5f5",
    shellBg: isDark ? "#111a2c" : "#ffffff",
    tableHeaderBg: isDark ? "#1f1f1f" : "#f0ebff",
  };
}

function ThemeCssVarsScope({ children }: { children: ReactNode }) {
  const { token } = antdTheme.useToken();

  const themeCssVarStyle = useMemo(
    () =>
      ({
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

export function Theme({
  children,
  accentColor = "blue",
  radius = "medium",
}: ThemeProps) {
  const [resolvedAccentColor, setResolvedAccentColor] = useState<ThemeAccentColor>(() =>
    normalizeAccentColor(accentColor),
  );
  const [themePrimaryMode, setThemePrimaryModeState] = useState<ThemePrimaryMode>("auto");
  const [compactMode, setCompactModeState] = useState(false);
  const [happyWorkMode, setHappyWorkModeState] = useState(false);
  const [systemPrefersDark, setSystemPrefersDark] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    let active = true;
    queueMicrotask(() => {
      if (!active) {
        return;
      }
      const storedAccentColor = window.localStorage.getItem(THEME_ACCENT_STORAGE_KEY);
      if (storedAccentColor) {
        setResolvedAccentColor(normalizeAccentColor(storedAccentColor));
        return;
      }
      setResolvedAccentColor(normalizeAccentColor(accentColor));
    });
    return () => {
      active = false;
    };
  }, [accentColor]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    let active = true;
    queueMicrotask(() => {
      if (!active) {
        return;
      }
      const storedPrimaryMode = window.localStorage.getItem(THEME_PRIMARY_MODE_STORAGE_KEY);
      const storedCompactMode = normalizeBooleanFlag(window.localStorage.getItem(THEME_COMPACT_STORAGE_KEY));
      const storedHappyWorkMode = normalizeBooleanFlag(
        window.localStorage.getItem(THEME_HAPPY_WORK_STORAGE_KEY),
      );
      const legacyThemeMode = normalizeLegacyThemeMode(
        window.localStorage.getItem(THEME_MODE_STORAGE_KEY),
      );

      if (storedPrimaryMode) {
        setThemePrimaryModeState(normalizeThemePrimaryMode(storedPrimaryMode));
      } else {
        setThemePrimaryModeState(
          legacyThemeMode === "dark" || legacyThemeMode === "dark-compact" ? "dark" : "light",
        );
      }

      if (storedCompactMode !== null) {
        setCompactModeState(storedCompactMode);
      } else {
        setCompactModeState(legacyThemeMode === "compact" || legacyThemeMode === "dark-compact");
      }

      if (storedHappyWorkMode !== null) {
        setHappyWorkModeState(storedHappyWorkMode);
      }
    });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = (matches: boolean) => {
      setSystemPrefersDark(matches);
    };

    update(media.matches);

    if (typeof media.addEventListener === "function") {
      const listener = (event: MediaQueryListEvent) => update(event.matches);
      media.addEventListener("change", listener);
      return () => media.removeEventListener("change", listener);
    }

    const legacyListener = (event: MediaQueryListEvent) => update(event.matches);
    media.addListener(legacyListener);
    return () => media.removeListener(legacyListener);
  }, []);

  const setAccentColor = useCallback((nextColor: string) => {
    const normalizedColor = normalizeAccentColor(nextColor);
    setResolvedAccentColor(normalizedColor);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_ACCENT_STORAGE_KEY, normalizedColor);
    }
  }, []);

  const setThemePrimaryMode = useCallback((nextMode: string) => {
    const normalizedMode = normalizeThemePrimaryMode(nextMode);
    setThemePrimaryModeState(normalizedMode);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_PRIMARY_MODE_STORAGE_KEY, normalizedMode);
    }
  }, []);

  const setCompactMode = useCallback((nextValue: boolean) => {
    setCompactModeState(nextValue);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_COMPACT_STORAGE_KEY, nextValue ? "1" : "0");
    }
  }, []);

  const setHappyWorkMode = useCallback((nextValue: boolean) => {
    setHappyWorkModeState(nextValue);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(THEME_HAPPY_WORK_STORAGE_KEY, nextValue ? "1" : "0");
    }
  }, []);

  const isDark = themePrimaryMode === "auto" ? systemPrefersDark : themePrimaryMode === "dark";
  const visualTokens = useMemo(() => buildThemeVisualTokens(isDark), [isDark]);

  const themeMode = useMemo<ThemeMode>(() => toLegacyThemeMode(isDark, compactMode), [compactMode, isDark]);

  const setThemeMode = useCallback(
    (nextMode: string) => {
      const normalizedMode = normalizeLegacyThemeMode(nextMode);
      const nextDark = normalizedMode === "dark" || normalizedMode === "dark-compact";
      const nextCompact = normalizedMode === "compact" || normalizedMode === "dark-compact";
      setThemePrimaryMode(nextDark ? "dark" : "light");
      setCompactMode(nextCompact);
    },
    [setCompactMode, setThemePrimaryMode],
  );

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.localStorage.setItem(THEME_MODE_STORAGE_KEY, themeMode);
  }, [themeMode]);

  const themeAlgorithm = useMemo(() => {
    const algorithms = [isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm];
    if (compactMode) {
      algorithms.push(antdTheme.compactAlgorithm);
    }
    return algorithms.length === 1 ? algorithms[0] : algorithms;
  }, [compactMode, isDark]);

  useEffect(() => {
    if (typeof document === "undefined") {
      return;
    }
    document.documentElement.classList.toggle("fquiz-happy-work", happyWorkMode);
    document.documentElement.dataset.fquizTheme = isDark ? "dark" : "light";
    return () => {
      document.documentElement.classList.remove("fquiz-happy-work");
      delete document.documentElement.dataset.fquizTheme;
    };
  }, [happyWorkMode, isDark]);

  const { antdLocale } = useI18n();
  const themeConfig = useMemo<ThemeConfig>(
    () => ({
      algorithm: themeAlgorithm,
      token: {
        colorPrimary: PRIMARY_COLOR_MAP[resolvedAccentColor] ?? PRIMARY_COLOR_MAP.blue,
        borderRadius: RADIUS_MAP[radius] ?? RADIUS_MAP.medium,
        fontFamily:
          "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Noto Sans', sans-serif",
        colorBgLayout: visualTokens.colorBgLayout,
      },
      components: {
        Layout: {
          headerBg: visualTokens.shellBg,
          siderBg: visualTokens.shellBg,
          bodyBg: visualTokens.colorBgLayout,
          headerHeight: 64,
          headerPadding: "0 24px",
        },
        Card: {
          borderRadiusLG: RADIUS_MAP.large,
        },
        Menu: {
          itemBorderRadius: RADIUS_MAP.medium,
          subMenuItemBorderRadius: RADIUS_MAP.medium,
        },
        Table: {
          headerBg: visualTokens.tableHeaderBg,
        },
        Message: {
          contentBg: visualTokens.shellBg,
          contentPadding: "14px 18px",
        },
      },
    }),
    [radius, resolvedAccentColor, themeAlgorithm, visualTokens],
  );

  return (
    <ThemeAppearanceContext.Provider
      value={{
        accentColor: resolvedAccentColor,
        setAccentColor,
        themeMode,
        setThemeMode,
        themePrimaryMode,
        setThemePrimaryMode,
        compactMode,
        setCompactMode,
        happyWorkMode,
        setHappyWorkMode,
        isDark,
      }}
    >
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
