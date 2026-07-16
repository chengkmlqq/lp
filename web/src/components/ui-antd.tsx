"use client";

import {
  Children,
  Fragment,
  cloneElement,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type HTMLAttributes,
  type ReactElement,
  type ReactNode,
  type TableHTMLAttributes,
  type TdHTMLAttributes,
  type ThHTMLAttributes,
} from "react";
import {
  Alert,
  App as AntApp,
  Button as AntButton,
  Card as AntCard,
  Checkbox as AntCheckbox,
  ConfigProvider,
  Dropdown as AntDropdown,
  Input,
  Modal as AntModal,
  Select as AntSelect,
  Typography,
  theme as antdTheme,
  type CardProps as AntCardProps,
  type MenuProps,
  type ThemeConfig,
} from "antd";
import zhCN from "antd/locale/zh_CN";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

function cn(...inputs: Array<string | undefined | false | null>) {
  return twMerge(clsx(inputs));
}

function toSpacingValue(value: string | number | undefined): string | undefined {
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

function withSpacingStyle({
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

function mapTextSize(size?: string): number | undefined {
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

function mapHeadingLevel(size?: string, as?: string): 1 | 2 | 3 | 4 | 5 {
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

function mapButtonSize(size?: string): "small" | "middle" | "large" {
  if (size === "1") return "small";
  if (size === "3") return "large";
  return "middle";
}

function mapInputSize(size?: string): "small" | "middle" | "large" {
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
      <ConfigProvider locale={zhCN} theme={themeConfig}>
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
type VisualButtonType = NonNullable<React.ComponentProps<typeof AntButton>["type"]>;

type ButtonProps = Omit<React.ComponentProps<typeof AntButton>, "size" | "color" | "type" | "variant"> & {
  asChild?: boolean;
  color?: "gray" | "indigo" | "red" | string;
  variant?: "solid" | "soft" | "ghost" | string;
  size?: "1" | "2" | "3" | string;
  type?: VisualButtonType | NativeButtonType;
  mt?: string | number;
  mb?: string | number;
};

function isNativeButtonType(value: ButtonProps["type"]): value is NativeButtonType {
  return value === "button" || value === "submit" || value === "reset";
}

function isVisualButtonType(value: ButtonProps["type"]): value is VisualButtonType {
  return value !== undefined && !isNativeButtonType(value);
}

export function Button({
  asChild = false,
  color,
  variant,
  size,
  type: typeProp,
  htmlType,
  className,
  children,
  mt,
  mb,
  style,
  onClick,
  disabled,
  ...rest
}: ButtonProps) {
  const mappedSize = mapButtonSize(size);
  const danger = color === "red";
  const defaultVisualType: VisualButtonType =
    variant === "solid" && color !== "gray" ? "primary" : "default";
  const nativeType = isNativeButtonType(typeProp) ? typeProp : undefined;
  let visualType: VisualButtonType = defaultVisualType;
  if (isVisualButtonType(typeProp)) {
    visualType = typeProp;
  }
  const ghost = variant === "ghost";

  if (asChild && isValidElement(children)) {
    const child = Children.only(children) as ReactElement<{
      className?: string;
      onClick?: (event: unknown) => void;
    }>;
    const childClassName = cn(
      "ant-btn",
      visualType === "primary" ? "ant-btn-primary" : "ant-btn-default",
      mappedSize === "small" ? "ant-btn-sm" : "",
      mappedSize === "large" ? "ant-btn-lg" : "",
      danger ? "ant-btn-dangerous" : "",
      ghost ? "ant-btn-background-ghost" : "",
      disabled ? "ant-btn-disabled" : "",
      className,
      child.props.className,
    );
    return cloneElement(child, {
      className: childClassName,
      onClick: (event: unknown) => {
        child.props.onClick?.(event);
        if (!disabled) {
          (onClick as ((evt: unknown) => void) | undefined)?.(event);
        }
      },
    });
  }

  return (
    <AntButton
      {...rest}
      className={className}
      danger={danger}
      disabled={disabled}
      ghost={ghost}
      onClick={onClick}
      size={mappedSize}
      style={withSpacingStyle({ mt, mb, style })}
      htmlType={nativeType ?? htmlType}
      type={visualType}
    >
      {children}
    </AntButton>
  );
}

type TextProps = {
  children?: ReactNode;
  className?: string;
  color?: "gray" | string;
  size?: "1" | "2" | "3" | "4" | "5" | string;
  weight?: "light" | "regular" | "medium" | "bold" | string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function mapWeight(weight?: string): CSSProperties["fontWeight"] {
  if (!weight) return undefined;
  if (weight === "light") return 300;
  if (weight === "regular") return 400;
  if (weight === "medium") return 500;
  if (weight === "bold") return 700;
  return weight as CSSProperties["fontWeight"];
}

export function Text({
  children,
  className,
  color,
  size,
  weight,
  mt,
  mb,
  style,
}: TextProps) {
  return (
    <Typography.Text
      className={className}
      style={{
        fontSize: mapTextSize(size),
        fontWeight: mapWeight(weight),
        ...withSpacingStyle({ mt, mb, style }),
      }}
      type={color === "gray" ? "secondary" : undefined}
    >
      {children}
    </Typography.Text>
  );
}

type HeadingProps = {
  children?: ReactNode;
  className?: string;
  as?: "h1" | "h2" | "h3" | "h4" | "h5";
  size?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

export function Heading({
  children,
  className,
  as,
  size,
  mt,
  mb,
  style,
}: HeadingProps) {
  return (
    <Typography.Title
      className={className}
      level={mapHeadingLevel(size, as)}
      style={{
        margin: 0,
        ...withSpacingStyle({ mt, mb, style }),
      }}
    >
      {children}
    </Typography.Title>
  );
}

type FlexProps = {
  children?: ReactNode;
  className?: string;
  direction?: "row" | "column";
  gap?: string | number;
  align?: "start" | "center" | "end" | "baseline" | "stretch";
  justify?:
    | "start"
    | "center"
    | "end"
    | "between"
    | "around"
    | "evenly";
  wrap?: "wrap" | "nowrap" | boolean;
  height?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function mapAlign(align?: FlexProps["align"]): CSSProperties["alignItems"] {
  if (align === "start") return "flex-start";
  if (align === "end") return "flex-end";
  return align as CSSProperties["alignItems"];
}

function mapJustify(
  justify?: FlexProps["justify"],
): CSSProperties["justifyContent"] {
  if (justify === "start") return "flex-start";
  if (justify === "end") return "flex-end";
  if (justify === "between") return "space-between";
  if (justify === "around") return "space-around";
  if (justify === "evenly") return "space-evenly";
  return justify as CSSProperties["justifyContent"];
}

export function Flex({
  children,
  className,
  direction = "row",
  gap,
  align,
  justify,
  wrap,
  height,
  mt,
  mb,
  style,
}: FlexProps) {
  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: direction,
        gap: toSpacingValue(gap),
        alignItems: mapAlign(align),
        justifyContent: mapJustify(justify),
        flexWrap: wrap === true ? "wrap" : wrap === false ? undefined : wrap,
        height,
        ...withSpacingStyle({ mt, mb, style }),
      }}
    >
      {children}
    </div>
  );
}

type CardProps = Omit<AntCardProps, "size" | "variant"> & {
  asChild?: boolean;
  size?: "1" | "2" | "3" | string;
  variant?: "surface" | string;
  children?: ReactNode;
};

const AntCardComponent = AntCard as unknown as (props: AntCardProps) => ReactElement;

export function Card({
  asChild = false,
  size,
  variant,
  className,
  children,
  ...rest
}: CardProps) {
  void variant;
  const mappedSize = size === "2" ? "small" : "default";

  if (asChild && isValidElement(children)) {
    const child = Children.only(children) as ReactElement<{
      className?: string;
      children?: ReactNode;
    }>;
    return cloneElement(
      child,
      { className: cn("block", child.props.className) },
      <AntCardComponent {...rest} className={className} size={mappedSize}>
        {child.props.children}
      </AntCardComponent>,
    );
  }

  return (
    <AntCardComponent {...rest} className={className} size={mappedSize}>
      {children}
    </AntCardComponent>
  );
}

type TextFieldRootProps = Omit<React.ComponentProps<typeof Input>, "size"> & {
  size?: "1" | "2" | "3" | string;
  mt?: string | number;
  mb?: string | number;
};

function TextFieldRoot({
  size,
  mt,
  mb,
  style,
  ...rest
}: TextFieldRootProps) {
  return (
    <Input
      {...rest}
      size={mapInputSize(size)}
      style={withSpacingStyle({ mt, mb, style })}
    />
  );
}

export const TextField = {
  Root: TextFieldRoot,
} as const;

type TextAreaProps = Omit<React.ComponentProps<typeof Input.TextArea>, "size"> & {
  size?: "1" | "2" | "3" | string;
  mt?: string | number;
  mb?: string | number;
};

export function TextArea({ size, mt, mb, style, ...rest }: TextAreaProps) {
  return (
    <Input.TextArea
      {...rest}
      size={mapInputSize(size)}
      style={withSpacingStyle({ mt, mb, style })}
    />
  );
}

type SelectOption = {
  value: string;
  label: ReactNode;
  disabled?: boolean;
};

type SelectRootProps = {
  value?: string;
  onValueChange?: (value: string) => void;
  disabled?: boolean;
  children?: ReactNode;
  className?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

type SelectTriggerProps = {
  className?: string;
  placeholder?: string;
  "aria-label"?: string;
};

type SelectContentProps = {
  children?: ReactNode;
};

type SelectItemProps = {
  value: string;
  children?: ReactNode;
  disabled?: boolean;
};

function SelectTrigger(_props: SelectTriggerProps) {
  void _props;
  return null;
}

function SelectContent(_props: SelectContentProps) {
  void _props;
  return null;
}

function SelectItem(_props: SelectItemProps) {
  void _props;
  return null;
}

function collectSelectItems(children: ReactNode, bucket: SelectOption[]) {
  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === SelectItem) {
      const props = node.props as SelectItemProps;
      bucket.push({
        value: props.value,
        label: props.children,
        disabled: props.disabled,
      });
      return;
    }
    if (node.type === Fragment || (node.props as { children?: ReactNode }).children) {
      collectSelectItems((node.props as { children?: ReactNode }).children, bucket);
    }
  });
}

function SelectRoot({
  value,
  onValueChange,
  disabled,
  children,
  className,
  mt,
  mb,
  style,
}: SelectRootProps) {
  let triggerProps: SelectTriggerProps = {};
  const options: SelectOption[] = [];

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === SelectTrigger) {
      triggerProps = node.props as SelectTriggerProps;
      return;
    }
    if (node.type === SelectContent) {
      collectSelectItems((node.props as SelectContentProps).children, options);
      return;
    }
    if (node.type === SelectItem) {
      const props = node.props as SelectItemProps;
      options.push({
        value: props.value,
        label: props.children,
        disabled: props.disabled,
      });
    }
  });

  return (
    <AntSelect
      aria-label={triggerProps["aria-label"]}
      className={cn(triggerProps.className, className)}
      disabled={disabled}
      onChange={(nextValue: unknown) => onValueChange?.(String(nextValue))}
      options={options}
      placeholder={triggerProps.placeholder}
      style={{
        width: "100%",
        ...withSpacingStyle({ mt, mb, style }),
      }}
      value={value}
    />
  );
}

export const Select = {
  Root: SelectRoot,
  Trigger: SelectTrigger,
  Content: SelectContent,
  Item: SelectItem,
} as const;

type DialogContextValue = {
  open: boolean;
  setOpen: (nextOpen: boolean) => void;
};

const DialogContext = createContext<DialogContextValue | null>(null);

type DialogRootProps = {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (nextOpen: boolean) => void;
  children?: ReactNode;
};

function DialogRoot({
  open,
  defaultOpen = false,
  onOpenChange,
  children,
}: DialogRootProps) {
  const [innerOpen, setInnerOpen] = useState(defaultOpen);
  const mergedOpen = open ?? innerOpen;

  const setOpen = (nextOpen: boolean) => {
    if (open === undefined) {
      setInnerOpen(nextOpen);
    }
    onOpenChange?.(nextOpen);
  };

  return (
    <DialogContext.Provider value={{ open: mergedOpen, setOpen }}>
      {children}
    </DialogContext.Provider>
  );
}

type DialogContentProps = {
  children?: ReactNode;
  className?: string;
  maxWidth?: string;
};

function parseDialogWidth(maxWidth?: string): number | undefined {
  if (!maxWidth) {
    return undefined;
  }
  if (/^\d+px$/.test(maxWidth.trim())) {
    return Number(maxWidth.replace("px", ""));
  }
  return undefined;
}

function DialogContent({ children, className, maxWidth }: DialogContentProps) {
  const context = useContext(DialogContext);
  if (!context) {
    return null;
  }

  return (
    <AntModal
      className={className}
      destroyOnClose
      footer={null}
      onCancel={() => context.setOpen(false)}
      open={context.open}
      width={parseDialogWidth(maxWidth)}
    >
      {children}
    </AntModal>
  );
}

type DialogTitleProps = {
  children?: ReactNode;
  className?: string;
};

function DialogTitle({ children, className }: DialogTitleProps) {
  return (
    <Typography.Title className={className} level={4} style={{ marginTop: 0 }}>
      {children}
    </Typography.Title>
  );
}

type DialogDescriptionProps = {
  children?: ReactNode;
  className?: string;
  size?: string;
};

function DialogDescription({
  children,
  className,
  size,
}: DialogDescriptionProps) {
  return (
    <Typography.Paragraph
      className={className}
      style={{ fontSize: mapTextSize(size), marginBottom: 16 }}
      type="secondary"
    >
      {children}
    </Typography.Paragraph>
  );
}

export const Dialog = {
  Root: DialogRoot,
  Content: DialogContent,
  Title: DialogTitle,
  Description: DialogDescription,
} as const;

type DropdownMenuTriggerProps = {
  children?: ReactNode;
};

type DropdownMenuContentProps = {
  children?: ReactNode;
  align?: "start" | "center" | "end";
  size?: string;
  variant?: string;
};

type DropdownMenuItemProps = {
  children?: ReactNode;
  color?: "gray" | "red" | "indigo" | string;
  disabled?: boolean;
  onSelect?: () => void;
  asChild?: boolean;
};

type DropdownMenuLabelProps = {
  children?: ReactNode;
};

function DropdownMenuTrigger(_props: DropdownMenuTriggerProps) {
  void _props;
  return null;
}

function DropdownMenuContent(_props: DropdownMenuContentProps) {
  void _props;
  return null;
}

function DropdownMenuItem(_props: DropdownMenuItemProps) {
  void _props;
  return null;
}

function DropdownMenuLabel(_props: DropdownMenuLabelProps) {
  void _props;
  return null;
}

function DropdownMenuSeparator() {
  return null;
}

type DropdownItems = NonNullable<MenuProps["items"]>;
type DropdownItem = NonNullable<DropdownItems[number]>;

function buildDropdownItems(children: ReactNode, prefix = "item"): DropdownItems {
  const items: DropdownItem[] = [];
  let index = 0;

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }

    if (node.type === DropdownMenuSeparator) {
      items.push({ type: "divider" });
      return;
    }

    if (node.type === DropdownMenuLabel) {
      items.push({
        key: `${prefix}-label-${index++}`,
        disabled: true,
        label: (
          <span className="text-xs text-[var(--gray-11)]">
            {(node.props as DropdownMenuLabelProps).children}
          </span>
        ),
      });
      return;
    }

    if (node.type === DropdownMenuItem) {
      const props = node.props as DropdownMenuItemProps;
      items.push({
        key: `${prefix}-${index++}`,
        disabled: props.disabled,
        danger: props.color === "red",
        label: props.children,
        onClick: () => props.onSelect?.(),
      });
      return;
    }

    const nestedChildren = (node.props as { children?: ReactNode }).children;
    if (node.type === Fragment || nestedChildren) {
      const nestedItems = buildDropdownItems(nestedChildren, `${prefix}-${index++}`)
        .filter((item): item is DropdownItem => item !== null);
      items.push(...nestedItems);
    }
  });

  return items;
}

type DropdownMenuRootProps = {
  children?: ReactNode;
};

function DropdownMenuRoot({ children }: DropdownMenuRootProps) {
  let triggerNode: ReactNode = null;
  let contentProps: DropdownMenuContentProps | null = null;

  Children.forEach(children, (node) => {
    if (!isValidElement(node)) {
      return;
    }
    if (node.type === DropdownMenuTrigger) {
      triggerNode = (node.props as DropdownMenuTriggerProps).children;
      return;
    }
    if (node.type === DropdownMenuContent) {
      contentProps = node.props as DropdownMenuContentProps;
    }
  });

  const contentChildren = (contentProps as DropdownMenuContentProps | null)?.children;
  const contentAlign = (contentProps as DropdownMenuContentProps | null)?.align;
  const items = buildDropdownItems(contentChildren);
  const placement =
    contentAlign === "end"
      ? "bottomRight"
      : contentAlign === "center"
        ? "bottom"
        : "bottomLeft";

  return (
    <AntDropdown
      menu={{ items }}
      placement={placement}
      trigger={["click"]}
    >
      <span className="inline-flex cursor-pointer">{triggerNode}</span>
    </AntDropdown>
  );
}

export const DropdownMenu = {
  Root: DropdownMenuRoot,
  Trigger: DropdownMenuTrigger,
  Content: DropdownMenuContent,
  Item: DropdownMenuItem,
  Label: DropdownMenuLabel,
  Separator: DropdownMenuSeparator,
} as const;

type CalloutRootProps = {
  children?: ReactNode;
  color?: "red" | "green" | string;
  className?: string;
  mt?: string | number;
  mb?: string | number;
  style?: CSSProperties;
};

function CalloutRoot({
  children,
  color,
  className,
  mt,
  mb,
  style,
}: CalloutRootProps) {
  const type =
    color === "red" ? "error" : color === "green" ? "success" : "info";

  return (
    <Alert
      className={className}
      description={children}
      message=""
      showIcon
      style={withSpacingStyle({ mt, mb, style })}
      type={type}
    />
  );
}

type CalloutTextProps = {
  children?: ReactNode;
};

function CalloutText({ children }: CalloutTextProps) {
  return <>{children}</>;
}

export const Callout = {
  Root: CalloutRoot,
  Text: CalloutText,
} as const;

type CheckboxProps = Omit<React.ComponentProps<typeof AntCheckbox>, "onChange" | "checked"> & {
  checked?: boolean | "indeterminate";
  onCheckedChange?: (checked: boolean | "indeterminate") => void;
};

export function Checkbox({
  checked,
  onCheckedChange,
  children,
  ...rest
}: CheckboxProps) {
  return (
    <AntCheckbox
      {...rest}
      checked={checked === "indeterminate" ? false : checked}
      indeterminate={checked === "indeterminate"}
      onChange={(event: { target: { checked: boolean } }) =>
        onCheckedChange?.(event.target.checked)}
    >
      {children}
    </AntCheckbox>
  );
}

type TableRootProps = TableHTMLAttributes<HTMLTableElement>;
type TableSectionProps = HTMLAttributes<HTMLTableSectionElement>;
type TableRowProps = HTMLAttributes<HTMLTableRowElement>;
type TableHeaderCellProps = ThHTMLAttributes<HTMLTableCellElement>;
type TableCellProps = TdHTMLAttributes<HTMLTableCellElement>;

function TableRoot({ children, className, ...rest }: TableRootProps) {
  return (
    <table {...rest} className={cn("w-full border-collapse", className)}>
      {children}
    </table>
  );
}

function TableHeader({ children, className, ...rest }: TableSectionProps) {
  return (
    <thead {...rest} className={className}>
      {children}
    </thead>
  );
}

function TableBody({ children, className, ...rest }: TableSectionProps) {
  return (
    <tbody {...rest} className={className}>
      {children}
    </tbody>
  );
}

function TableRow({ children, className, ...rest }: TableRowProps) {
  return (
    <tr {...rest} className={className}>
      {children}
    </tr>
  );
}

function TableColumnHeaderCell({
  children,
  className,
  scope = "col",
  ...rest
}: TableHeaderCellProps) {
  return (
    <th {...rest} className={className} scope={scope}>
      {children}
    </th>
  );
}

function TableCell({ children, className, ...rest }: TableCellProps) {
  return (
    <td {...rest} className={className}>
      {children}
    </td>
  );
}

export const Table = {
  Root: TableRoot,
  Header: TableHeader,
  Body: TableBody,
  Row: TableRow,
  ColumnHeaderCell: TableColumnHeaderCell,
  Cell: TableCell,
} as const;
