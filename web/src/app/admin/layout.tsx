"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";

// 2026-10-02：消息触发时间格式统一 YYYY-MM-DD HH:mm:ss（横杠分隔，不用斜杠）
function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode, type SVGProps } from "react";
import { usePathname } from "next/navigation";
import Icon, {
  BellOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SunOutlined,
  SyncOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { resolveIcon } from "@/lib/icon-registry";
import {
  Avatar,
  Badge,
  Button,
  Drawer,
  Dropdown,
  Empty,
  Grid,
  Layout as AntLayout,
  List,
  Menu as AntMenu,
  Popover,
  Result,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  type MenuProps,
  type ResultProps,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { LangSwitcher } from "@/components/lang-switcher";
import { useI18n } from "@/lib/i18n";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError, getApiBaseUrl } from "@/lib/api";
import { normalizeAppRoutePath } from "@/lib/app-route-path";
import { findFirstMenuPath } from "@/lib/menu-tree-path";
import type { MenuTreeItem, SystemMessageListResponse, SystemMessageSummary } from "@/types/auth";
import { useThemeAppearance } from "@/components/ui-theme";
import { withBasePath } from "@/lib/base-path";

const { Header, Sider, Content } = AntLayout;
const AntResult = Result as unknown as ComponentType<ResultProps>;
const ADMIN_ME_MENUS_QUERY_KEY = ["/api/v1/admin/me/menus"] as const;

const ThemeSvgIcon = (props: SVGProps<SVGSVGElement>) => (
  <svg width={20} height={20} viewBox="0 0 24 24" fill="currentColor" {...props}>
    <title>Theme icon</title>
    <g fillRule="evenodd">
      <g fillRule="nonzero">
        <path d="M7.02 3.635l12.518 12.518a1.863 1.863 0 010 2.635l-1.317 1.318a1.863 1.863 0 01-2.635 0L3.068 7.588A2.795 2.795 0 117.02 3.635zm2.09 14.428a.932.932 0 110 1.864.932.932 0 010-1.864zm-.043-9.747L7.75 9.635l9.154 9.153 1.318-1.317-9.154-9.155zM3.52 12.473c.514 0 .931.417.931.931v.932h.932a.932.932 0 110 1.864h-.932v.931a.932.932 0 01-1.863 0l-.001-.931h-.93a.932.932 0 010-1.864h.93v-.932c0-.514.418-.931.933-.931zm15.374-3.727a1.398 1.398 0 110 2.795 1.398 1.398 0 010-2.795zM4.385 4.953a.932.932 0 000 1.317l2.046 2.047L7.75 7 5.703 4.953a.932.932 0 00-1.318 0zM14.701.36a.932.932 0 01.931.932v.931h.932a.932.932 0 010 1.864h-.933l.001.932a.932.932 0 11-1.863 0l-.001-.932h-.93a.932.932 0 110-1.864h.93v-.931a.932.932 0 01.933-.932z" />
      </g>
    </g>
  </svg>
);

function ThemeIcon() {
  return <Icon component={ThemeSvgIcon} />;
}

function normalizeAdminPath(path: string | null): string | null {
  return normalizeAppRoutePath(path);
}

function normalizeMenuTreePaths(items: MenuTreeItem[]): MenuTreeItem[] {
  return items.map((item) => ({
    ...item,
    path: normalizeAdminPath(item.path),
    children: normalizeMenuTreePaths(item.children),
  }));
}

function isActivePath(pathname: string, menuPath: string | null): boolean {
  if (!menuPath) {
    return false;
  }
  return pathname === menuPath || pathname.startsWith(`${menuPath}/`);
}

type AntdMenuItems = NonNullable<MenuProps["items"]>;

const LEGACY_ICON_ALIASES: Record<string, string> = {
  Users: 'TeamOutlined',
  ShieldCheck: 'SafetyCertificateOutlined',
  MenuSquare: 'AppstoreOutlined',
  Settings2: 'SettingOutlined',
  Network: 'NodeIndexOutlined',
  Zap: 'ThunderboltOutlined',
  Map: 'GlobalOutlined',
  RadarChart: 'RadarChartOutlined',
  CalendarClock: 'CalendarOutlined',
  Experiment: 'ExperimentOutlined',
  Apartment: 'ApartmentOutlined',
  FolderTree: 'FolderOpenOutlined',
  Database: 'DatabaseOutlined',
  FileText: 'FileTextOutlined',
  Terminal: 'ConsoleSqlOutlined',
  Bell: 'BellOutlined',
};

function resolveMenuIcon(icon: string | null): ReactNode {
  if (!icon) return null;
  const name = icon.trim();
  const canonicalName = LEGACY_ICON_ALIASES[name] ?? name;
  const IconComponent = resolveIcon(canonicalName);
  if (IconComponent) {
    return <IconComponent />;
  }
  return null;
}

function buildMenuItems(
  items: MenuTreeItem[],
  menuLabel: (code: string | null | undefined, zhName: string) => string,
): AntdMenuItems {
  return items.map((item) => {
    const children = buildMenuItems(item.children, menuLabel);
    const displayName = menuLabel(item.code || item.id, item.name);
    const label = item.path ? (
      <Link href={item.path} prefetch={false}>
        {displayName}
      </Link>
    ) : (
      displayName
    );
    const icon = resolveMenuIcon(item.icon);

    if (children.length > 0) {
      return {
        key: item.id,
        label,
        icon,
        children,
      };
    }

    return {
      key: item.id,
      label,
      icon,
      disabled: !item.path,
    };
  });
}

type ActiveMenuState = {
  selectedKeys: string[];
  openKeys: string[];
};

function findActiveMenuState(
  items: MenuTreeItem[],
  pathname: string,
  parentKeys: string[] = [],
): ActiveMenuState {
  for (const item of items) {
    const nextParents = [...parentKeys, item.id];
    if (isActivePath(pathname, item.path)) {
      return {
        selectedKeys: [item.id],
        openKeys: parentKeys,
      };
    }

    if (item.children.length > 0) {
      const childMatch = findActiveMenuState(item.children, pathname, nextParents);
      if (childMatch.selectedKeys.length > 0) {
        return childMatch;
      }
    }
  }

  return {
    selectedKeys: [],
    openKeys: [],
  };
}

function AdminCenteredState({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--ant-color-bg-layout)] px-6 py-20">
      {children}
    </main>
  );
}

export default function AdminLayout({ children }: { children: ReactNode }) {
  const rawPathname = usePathname();
  const pathname = normalizeAppRoutePath(rawPathname) ?? rawPathname;
  const screens = Grid.useBreakpoint();
  const isDesktop = screens.md === true;
  const queryClient = useQueryClient();
  const { user, initializing, fetchWithAuth, logout } = useAuth();
  const { t, lang, setLang, menuLabel } = useI18n();
  const {
    themePrimaryMode,
    setThemePrimaryMode,
  } = useThemeAppearance();
  const [menuOpenKeys, setMenuOpenKeys] = useState<string[]>([]);
  const [siderCollapsed, setSiderCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [unreadMessageCount, setUnreadMessageCount] = useState(0);
  const emptyMenuTree = useMemo<MenuTreeItem[]>(() => [], []);
  const menusQueryKey = useMemo(
    () => [...ADMIN_ME_MENUS_QUERY_KEY, user?.id ?? "anonymous"] as const,
    [user?.id],
  );

  const loadMenus = useCallback(async () => {
    const response = await fetchWithAuth("/api/v1/admin/me/menus");
    if (!response.ok) {
      throw new Error(await readApiError(response));
    }

    const payload = (await response.json()) as MenuTreeItem[];
    return normalizeMenuTreePaths(payload);
  }, [fetchWithAuth]);

  const menusQuery = useQuery({
    queryKey: menusQueryKey,
    queryFn: loadMenus,
    enabled: !!user,
  });

  useTopicSubscription("admin.menus", useCallback(() => {
    if (user) {
      void queryClient.invalidateQueries({ queryKey: ADMIN_ME_MENUS_QUERY_KEY });
    }
  }, [queryClient, user]));

  useTopicSubscription("auth", useCallback(() => {
    if (user) {
      void queryClient.invalidateQueries({ queryKey: ADMIN_ME_MENUS_QUERY_KEY });
    }
  }, [queryClient, user]));

  const menuTree = menusQuery.data ?? emptyMenuTree;
  const menuItems = useMemo(() => buildMenuItems(menuTree, menuLabel), [menuTree, menuLabel]);
  const firstMenuPath = useMemo(() => findFirstMenuPath(menuTree), [menuTree]);
  const activeMenuState = useMemo(() => findActiveMenuState(menuTree, pathname), [menuTree, pathname]);
  const routeAllowed = useMemo(() => {
    if (pathname === "/admin") {
      return true;
    }
    return activeMenuState.selectedKeys.length > 0;
  }, [activeMenuState.selectedKeys.length, pathname]);

  useEffect(() => {
    queueMicrotask(() => {
      setMenuOpenKeys(activeMenuState.openKeys);
    });
  }, [activeMenuState.openKeys]);

  const themeBadge = useMemo(
    () => <Badge color="var(--fquiz-theme-primary, var(--ant-color-primary))" style={{ marginTop: -1 }} />,
    [],
  );
  const themeMenuItems = useMemo<NonNullable<MenuProps["items"]>>(
    () => [
      {
        key: "auto",
        icon: <SyncOutlined />,
        label: t("跟随系统"),
        extra: themePrimaryMode === "auto" ? themeBadge : null,
      },
      {
        key: "light",
        icon: <SunOutlined />,
        label: t("浅色主题"),
        extra: themePrimaryMode === "light" ? themeBadge : null,
      },
      {
        key: "dark",
        icon: <MoonOutlined />,
        label: t("暗黑主题"),
        extra: themePrimaryMode === "dark" ? themeBadge : null,
      },
    ],
    [t, themeBadge, themePrimaryMode],
  );

  const accountMenuItems = useMemo<NonNullable<MenuProps["items"]>>(
    () => [
      {
        key: "account",
        icon: <UserOutlined />,
        disabled: true,
        label: (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{user?.username}</Typography.Text>
            <Typography.Text type="secondary">
              {t("角色")}: {user?.role_codes.join(", ") || "-"}
            </Typography.Text>
          </Space>
        ),
      },
      { type: "divider" },
      {
        key: "logout",
        danger: true,
        icon: <LogoutOutlined />,
        label: t("退出登录"),
      },
    ],
    [t, user?.role_codes, user?.username],
  );

  const onThemeMenuClick = useCallback(
    ({ key }: Parameters<NonNullable<MenuProps["onClick"]>>[0]) => {
      if (key === "auto" || key === "light" || key === "dark") {
        setThemePrimaryMode(key);
        return;
      }
    },
    [setThemePrimaryMode],
  );

  const onAccountMenuClick = useCallback(
    ({ key }: Parameters<NonNullable<MenuProps["onClick"]>>[0]) => {
      if (key === "logout") {
        void logout();
      }
    },
    [logout],
  );

  const [messagePopoverOpen, setMessagePopoverOpen] = useState(false);
  const [messages, setMessages] = useState<SystemMessageSummary[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [avatarError, setAvatarError] = useState(false);

  const loadMessages = useCallback(async () => {
    setLoadingMessages(true);
    try {
      const response = await fetchWithAuth("/api/v1/system-messages/me?limit=50");
      if (!response.ok) {
        return;
      }
      const data = (await response.json()) as SystemMessageListResponse;
      // 2026-10-02：已读消息从铃铛列表移除（管理页 /admin/system-messages 保留全部历史）
      setMessages((data.items || []).filter((item) => !item.is_read));
      setUnreadMessageCount(data.unread_count || 0);
    } catch (error) {
      console.error("Failed to load messages:", error);
    } finally {
      setLoadingMessages(false);
    }
  }, [fetchWithAuth]);

  const loadUnreadCount = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/system-messages/me/unread-count");
      if (!response.ok) {
        return;
      }
      const data = (await response.json()) as { unread_count: number };
      setUnreadMessageCount(data.unread_count || 0);
    } catch (error) {
      console.error("Failed to load unread count:", error);
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    if (user) {
      void loadUnreadCount();
    }
  }, [loadUnreadCount, user]);

  // 2026-09-30：任务完成通知（WS 实时推送）——收到新消息立即刷新铃铛角标与列表
  useTopicSubscription("user.messages", useCallback(() => {
    if (user) {
      void loadUnreadCount();
      void loadMessages();
    }
  }, [user, loadUnreadCount, loadMessages]));

  // Reset avatar error state when user changes
  useEffect(() => {
    setAvatarError(false);
  }, [user?.avatar_url]);

  const markAsRead = useCallback(async (messageIds: string[]) => {
    try {
      const response = await fetchWithAuth("/api/v1/system-messages/me/mark-read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_ids: messageIds }),
      });
      if (response.ok) {
        await loadMessages();
      }
    } catch (error) {
      console.error("Failed to mark messages as read:", error);
    }
  }, [fetchWithAuth, loadMessages]);

  const navigationMenu = (
    <AntMenu
      mode="inline"
      items={menuItems}
      openKeys={siderCollapsed && isDesktop ? [] : menuOpenKeys}
      selectedKeys={activeMenuState.selectedKeys}
      style={{ borderInlineEnd: "none", background: "transparent" }}
      onClick={() => setMobileMenuOpen(false)}
      onOpenChange={(keys: string[]) => setMenuOpenKeys(keys)}
    />
  );

  if (initializing || (user && menusQuery.isLoading)) {
    return (
      <AdminCenteredState>
        <Space align="center" direction="vertical" size={12}>
          <Spin size="large" />
          <Typography.Text type="secondary">{t("正在加载后台工作台...")}</Typography.Text>
        </Space>
      </AdminCenteredState>
    );
  }

  if (!user) {
    return (
      <AdminCenteredState>
        <AntResult
          status="403"
          title={t("请先登录")}
          subTitle={t("登录后才能访问后台工作台。")}
          extra={(
            <Button type="primary">
              <Link href="/login">{t("前往登录")}</Link>
            </Button>
          )}
        />
      </AdminCenteredState>
    );
  }

  if (menusQuery.isError || !routeAllowed) {
    const subTitle = menusQuery.isError
      ? menusQuery.error instanceof Error
        ? menusQuery.error.message
        : t("菜单加载失败，请检查网络连接或后端服务。")
      : t("该菜单已禁用或你没有访问该菜单的权限。");

    return (
      <AdminCenteredState>
        <AntResult
          status="403"
          title={t("无法访问")}
          subTitle={subTitle}
          extra={(
            <Button type="primary">
              <Link href="/admin">{t("返回后台首页")}</Link>
            </Button>
          )}
        />
      </AdminCenteredState>
    );
  }

  return (
    <AntLayout className="admin-design-shell">
      <Header className="admin-design-header">
        {!isDesktop && (
          <Button
            aria-label={t("打开菜单")}
            icon={<MenuOutlined />}
            type="text"
            onClick={() => setMobileMenuOpen(true)}
          />
        )}

        <Link
          href={firstMenuPath ?? "/dashboard"}
          className="ml-2 flex items-center gap-2 text-inherit no-underline md:ml-0"
        >
          <img
            src={withBasePath("/favicon.ico")}
            alt={t("高压电塔图标")}
            width={22}
            height={22}
            className="h-[22px] w-[22px]"
          />
          <Typography.Text strong style={{ marginBottom: 0 }}>
            {t("防雷计算")}
          </Typography.Text>
        </Link>

        <Space style={{ marginLeft: "auto" }}>
          <LangSwitcher lang={lang} onChange={setLang} compact />

          <Dropdown
            menu={{ items: themeMenuItems, onClick: onThemeMenuClick }}
            arrow={{ pointAtCenter: true }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <Tooltip title={t("主题")}>
              <Button icon={<ThemeIcon />} type="text" />
            </Tooltip>
          </Dropdown>

          <Tooltip title={t("系统消息")}>
            <Popover
              title={t("系统消息")}
              trigger="click"
              open={messagePopoverOpen}
              onOpenChange={(open) => {
                setMessagePopoverOpen(open);
                if (open) {
                  void loadMessages();
                }
              }}
              content={
                <div style={{ width: 360, maxHeight: 480, overflowY: "auto" }}>
                  {loadingMessages ? (
                    <div style={{ textAlign: "center", padding: "40px 0" }}>
                      <Spin />
                    </div>
                  ) : messages.length === 0 ? (
                    <Empty description={t("暂无消息")} />
                  ) : (
                    <List<SystemMessageSummary>
                      dataSource={messages}
                      renderItem={(item) => (
                        <List.Item
                          key={item.id}
                          style={{
                            backgroundColor: "var(--ant-color-bg-container-active)",
                            cursor: item.link_url ? "pointer" : "default",
                          }}
                          actions={[
                            <Button
                              key="mark-read"
                              type="link"
                              size="small"
                              onClick={() => markAsRead([item.id])}
                            >
                              标记已读
                            </Button>,
                          ]}
                          onClick={() => {
                            if (item.link_url) {
                              markAsRead([item.id]);
                              window.location.href = item.link_url;
                            }
                          }}
                        >
                          <List.Item.Meta
                            title={
                              <Space>
                                <span>{item.title}</span>
                                <Tag color={
                                  item.message_type === "error" ? "red" :
                                  item.message_type === "warning" ? "orange" :
                                  item.message_type === "success" ? "green" :
                                  item.message_type === "task_done" ? "purple" : "blue"
                                }>
                                  {{
                                    task_done: t("任务完成"),
                                    error: t("错误"),
                                    warning: t("警告"),
                                    success: t("成功"),
                                    info: t("信息"),
                                  }[item.message_type] ?? item.message_type}
                                </Tag>
                              </Space>
                            }
                            description={
                              <Space direction="vertical" size={4} style={{ width: "100%" }}>
                                <Typography.Text>{item.content}</Typography.Text>
                                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                                  {formatMessageTime(item.created_at)}
                                </Typography.Text>
                              </Space>
                            }
                          />
                        </List.Item>
                      )}
                    />
                  )}
                </div>
              }
              placement="bottomRight"
            >
              <Badge count={unreadMessageCount} size="small">
                <Button
                  icon={<BellOutlined />}
                  type="text"
                />
              </Badge>
            </Popover>
          </Tooltip>

          <Dropdown
            menu={{ items: accountMenuItems, onClick: onAccountMenuClick }}
            arrow={{ pointAtCenter: true }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <Button aria-label={t("用户菜单")} type="text">
              {user.avatar_url && !avatarError ? (
                <Avatar
                  size="small"
                  src={`${getApiBaseUrl()}${user.avatar_url}?t=${encodeURIComponent(user.updated_at ?? "")}`}
                  style={{ backgroundColor: "var(--ant-color-primary)" }}
                  onError={() => {
                    setAvatarError(true);
                    return false;
                  }}
                />
              ) : (
                <Avatar size="small" style={{ backgroundColor: "var(--ant-color-primary)" }}>
                  {user.username.trim().charAt(0).toUpperCase() || "U"}
                </Avatar>
              )}
            </Button>
          </Dropdown>
        </Space>
      </Header>

      <AntLayout>
        {isDesktop && (
          <Sider
            className="admin-design-sider"
            collapsed={siderCollapsed}
            collapsedWidth={72}
            theme="light"
            trigger={null}
            width={256}
          >
            <div className="admin-design-sider-inner">
              <div className="admin-design-sider-menu">
                {navigationMenu}
              </div>
              <div className="admin-design-sider-footer">
                <Button
                  aria-label={siderCollapsed ? t("展开菜单") : t("收起菜单")}
                  icon={siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
                  type="text"
                  onClick={() => setSiderCollapsed((previous) => !previous)}
                />
              </div>
            </div>
          </Sider>
        )}

        <Drawer
          title={null}
          placement="left"
          open={!isDesktop && mobileMenuOpen}
          width={288}
          onClose={() => setMobileMenuOpen(false)}
        >
          {navigationMenu}
        </Drawer>

        <AntLayout className="admin-design-main">
          <Content className="admin-design-content">
            <div className="admin-design-page-body">
              {children}
            </div>
          </Content>
        </AntLayout>
      </AntLayout>
    </AntLayout>
  );
}
