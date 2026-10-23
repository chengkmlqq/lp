"use client";

/**
 * 轻量 i18n 层（中 / 英）。
 *
 * 设计：以「中文原文」为 key 的翻译表 —— 现有页面文案全部硬编码中文，
 * 改造时只需把文案包一层 t("原文")，英文词典里加一条映射；查不到映射的
 * 原文在英文环境下原样回落（保持中文），保证增量接入时界面不出现空洞。
 *
 * - 语言存 localStorage（键 lp.lang），默认跟随浏览器语言（zh 开头→中文）。
 * - 菜单名来自后端 DB（中文 name）：前端按菜单 code 查 MENU_LABELS_EN，
 *   查不到再按中文 name 查翻译表，最后回落原 name。
 * - antd ConfigProvider 的 locale（zhCN/enUS）由 useI18n 提供，随语言切换。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Locale } from "antd/es/locale";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";

export type AppLang = "zh" | "en";

const LANG_STORAGE_KEY = "lp.lang";

// ─────────────────────────── 翻译表 ───────────────────────────

/** 中文原文 → 英文。英文环境查不到时回落中文原文。 */
export const EN_DICT: Record<string, string> = {
  // ── 登录 / 注册 ──
  防雷计算: "Lightning Protection",
  "用户 ID": "User ID",
  密码: "Password",
  记住密码: "Remember me",
  登录: "Sign in",
  正在初始化会话: "Initializing session",
  正在跳转到控制台: "Redirecting to console",
  未知错误: "Unknown error",
  高压电塔图标: "Tower icon",
  用户注册: "Register",
  邮箱: "Email",
  "用户名（3-64 个字符）": "Username (3-64 chars)",
  "密码（至少 8 个字符）": "Password (min 8 chars)",
  确认密码: "Confirm password",
  注册: "Register",
  立即登录: "Sign in now",
  "已有账号？": "Already have an account?",
  两次输入的密码不一致: "Passwords do not match",
  "密码长度至少为 8 个字符": "Password must be at least 8 characters",
  返回登录: "Back to sign in",
  请先登录后再访问: "Please sign in first",
  暂无权限: "No permission",

  // ── 布局 / 通用 ──
  退出登录: "Sign out",
  跟随系统: "Follow system",
  浅色主题: "Light theme",
  暗黑主题: "Dark theme",
  主题: "Theme",
  用户菜单: "User menu",
  角色: "Role",
  通知: "Notifications",
  任务完成: "Task done",
  错误: "Error",
  警告: "Warning",
  成功: "Success",
  信息: "Info",
  新建: "New",
  新增: "Add",
  编辑: "Edit",
  删除: "Delete",
  保存: "Save",
  取消: "Cancel",
  确定: "OK",
  查询: "Search",
  刷新: "Refresh",
  查看: "View",
  详情: "Details",
  测试: "Test",
  下载: "Download",
  返回: "Back",
  确认: "Confirm",
  提交: "Submit",
  全部: "All",
  启用中: "Enabled",
  已停用: "Disabled",
  启用: "Enable",
  停用: "Disable",
  名称: "Name",
  描述: "Description",
  状态: "Status",
  更新时间: "Updated",
  创建时间: "Created",
  创建人: "Creator",
  操作: "Actions",
  共: "Total",
  条: "items",
  暂无数据: "No data",
  加载中: "Loading…",
  请先登录: "Please sign in first",
  无权限: "No permission",
};

/** 后端菜单 code → 英文名（32 个菜单）。 */
export const MENU_LABELS_EN: Record<string, string> = {
  "admin.overview": "Overview",
  "admin.ai_chat": "AI Chat",
  "admin.power_lines": "Power Lines",
  "admin.fault_analysis": "Fault Analysis",
  "admin.fault_recurrence": "Fault Recurrence",
  "admin.fl_analysis": "Lightning Analysis",
  "admin.lightning_currents": "Lightning Currents",
  "admin.lightning_distribution": "Lightning Distribution",
  "admin.lightning_retrofit": "Lightning Retrofit",
  "admin.docs_view": "Docs",
  "admin.basic_data": "Master Data",
  "admin.tower_models": "Tower Models",
  "admin.atp_models": "ATP Models",
  "admin.atp_test_sets": "Test Sets",
  "admin.atp_param_templates": "Param Templates",
  "admin.atp_params": "ATP Params",
  "admin.elevation": "Elevation Data",
  "admin.system_monitor": "System Monitor",
  "admin.task_monitor": "Task Monitor",
  "admin.workers": "Workers",
  "admin.syslog": "System Logs",
  "admin.system": "System",
  "admin.users": "Users",
  "admin.roles": "Roles",
  "admin.menus": "Menus",
  "admin.system_params": "System Params",
  "admin.system_message": "System Messages",
  "admin.documents": "Documents",
  "admin.dimensions": "Dimensions",
  "admin.scheduled_tasks": "Scheduled Tasks",
  "admin.debug": "Debug",
  "admin.files": "Files",
  "admin.matlab_engine": "MATLAB Engine",
};

// ─────────────────────────── Context ───────────────────────────

type I18nContextValue = {
  lang: AppLang;
  setLang: (next: AppLang) => void;
  /** 中文原文 → 当前语言文案；英文查不到映射时回落中文原文。 */
  t: (zhText: string) => string;
  /** 菜单显示名：按 code → 中文名 → 回落。 */
  menuLabel: (code: string | null | undefined, zhName: string) => string;
  /** antd Locale（随语言切换）。 */
  antdLocale: Locale;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function detectBrowserLang(): AppLang {
  if (typeof window === "undefined") {
    return "zh";
  }
  const stored = window.localStorage.getItem(LANG_STORAGE_KEY);
  if (stored === "zh" || stored === "en") {
    return stored;
  }
  return (navigator.language || "").toLowerCase().startsWith("zh") ? "zh" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<AppLang>("zh");

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    let active = true;
    queueMicrotask(() => {
      if (active) {
        setLangState(detectBrowserLang());
      }
    });
    return () => {
      active = false;
    };
  }, []);

  const setLang = useCallback((next: AppLang) => {
    setLangState(next);
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LANG_STORAGE_KEY, next);
    }
  }, []);

  const t = useCallback(
    (zhText: string) => {
      if (lang === "zh" || !zhText) {
        return zhText;
      }
      return EN_DICT[zhText] ?? zhText;
    },
    [lang],
  );

  const menuLabel = useCallback(
    (code: string | null | undefined, zhName: string) => {
      if (lang === "zh") {
        return zhName;
      }
      if (code && MENU_LABELS_EN[code]) {
        return MENU_LABELS_EN[code];
      }
      return EN_DICT[zhName] ?? zhName;
    },
    [lang],
  );

  const antdLocale = useMemo<Locale>(
    () => (lang === "en" ? enUS : zhCN),
    [lang],
  );

  const value = useMemo<I18nContextValue>(
    () => ({ lang, setLang, t, menuLabel, antdLocale }),
    [lang, setLang, t, menuLabel, antdLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (context) {
    return context;
  }
  // 组件树外兜底：直接渲染中文，避免抛错中断页面
  return {
    lang: "zh",
    setLang: () => {},
    t: (zhText: string) => zhText,
    menuLabel: (_code, zhName) => zhName,
    antdLocale: { locale: "zh-cn" } as unknown as Locale,
  };
}
