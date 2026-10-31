"use client";

// 后台外壳 —— 2026-10-30 UI 改造：参照 kb_compilation MODO 设计系统复刻。
// 结构：48px 顶栏（logo + 用户区）+ 双列 rail 侧边导航（80px 一级方块卡 + 160px 子菜单）
// + #EFF4F9 灰底内容区。菜单仍由后端 /api/v1/admin/me/menus 下发。
// 主题切换已移除（仅浅色 MODO 主题）。

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
import { useCallback, useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  BellOutlined,
  CaretDownOutlined,
  LogoutOutlined,
  MenuOutlined,
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
import { withBasePath } from "@/lib/base-path";

const { Header, Content } = AntLayout;
const AntResult = Result as unknown as ComponentType<ResultProps>;
const ADMIN_ME_MENUS_QUERY_KEY = ["/api/v1/admin/me/menus"] as const;

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

const LEGACY_ICON_ALIASES: Record<string, string> = {
  Users: "TeamOutlined",
  ShieldCheck: "SafetyCertificateOutlined",
  MenuSquare: "AppstoreOutlined",
  Settings2: "SettingOutlined",
  Network: "NodeIndexOutlined",
  Zap: "ThunderboltOutlined",
  Map: "GlobalOutlined",
  RadarChart: "RadarChartOutlined",
  CalendarClock: "CalendarOutlined",
  Experiment: "ExperimentOutlined",
  Apartment: "ApartmentOutlined",
  FolderTree: "FolderOpenOutlined",
  Database: "DatabaseOutlined",
  FileText: "FileTextOutlined",
  Terminal: "ConsoleSqlOutlined",
  Bell: "BellOutlined",
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

/** 找到目标菜单所属的一级分组 id（menu.id）。 */
function findTopLevelGroupId(items: MenuTreeItem[], targetId: string): string | null {
  for (const item of items) {
    if (item.id === targetId) {
      return item.id;
    }
    if (item.children.length > 0) {
      const hit = findTopLevelGroupId(item.children, targetId);
      if (hit) {
        return item.id;
      }
    }
  }
  return null;
}

/** 收集一个分组下的叶子菜单（用于二级子菜单列与「跳第一个页面」）。 */
function collectLeafMenus(items: MenuTreeItem[]): MenuTreeItem[] {
  const leaves: MenuTreeItem[] = [];
  for (const item of items) {
    if (item.children.length > 0) {
      leaves.push(...collectLeafMenus(item.children));
    } else if (item.path) {
      leaves.push(item);
    }
  }
  return leaves;
}

/** 二级子菜单的渲染模型：分组标题 + 叶子项。 */
type SubMenuSection = { title: string | null; leaves: MenuTreeItem[] };

function buildSubMenuSections(children: MenuTreeItem[]): SubMenuSection[] {
  const sections: SubMenuSection[] = [];
  for (const child of children) {
    if (child.children.length > 0) {
      sections.push({ title: child.name, leaves: collectLeafMenus(child.children) });
    } else {
      sections.push({ title: null, leaves: [child] });
    }
  }
  return sections.filter((s) => s.leaves.length > 0 || s.title);
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
  const router = useRouter();
  const screens = Grid.useBreakpoint();
  const isDesktop = screens.md === true;
  const queryClient = useQueryClient();
  const { user, initializing, fetchWithAuth, logout } = useAuth();
  const { t, lang, setLang, menuLabel } = useI18n();
  const [subCollapsed, setSubCollapsed] = useState(false);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [unreadMessageCount, setUnreadMessageCount] = useState(0);
  const [groupOverride, setGroupOverride] = useState<string | null>(null);
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
  const firstMenuPath = useMemo(() => findFirstMenuPath(menuTree), [menuTree]);
  const activeMenuState = useMemo(() => findActiveMenuState(menuTree, pathname), [menuTree, pathname]);
  const routeAllowed = useMemo(() => {
    if (pathname === "/admin") {
      return true;
    }
    return activeMenuState.selectedKeys.length > 0;
  }, [activeMenuState.selectedKeys.length, pathname]);

  const activeItemId = activeMenuState.selectedKeys[0] ?? null;
  // 当前路由所属的一级分组（无命中时默认第一组）
  const activeGroupId = useMemo(() => {
    if (activeItemId) {
      const hit = findTopLevelGroupId(menuTree, activeItemId);
      if (hit) return hit;
    }
    return menuTree[0]?.id ?? null;
  }, [menuTree, activeItemId]);

  const groupId = groupOverride ?? activeGroupId;
  const currentGroup = menuTree.find((m) => m.id === groupId) ?? null;
  const hasSub = (currentGroup?.children.length ?? 0) > 0;
  const subSections = useMemo(
    () => (hasSub && currentGroup ? buildSubMenuSections(currentGroup.children) : []),
    [currentGroup, hasSub],
  );

  const handleGroupClick = (item: MenuTreeItem) => {
    setGroupOverride(item.id);
    const leaves = collectLeafMenus(item.children);
    const target = leaves[0]?.path ?? item.path;
    if (target) {
      router.push(target);
    }
    setMobileMenuOpen(false);
  };

  const handleSubClick = (item: MenuTreeItem) => {
    if (item.path) {
      router.push(item.path);
      setMobileMenuOpen(false);
    }
  };

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

  /** 双列 rail 导航（桌面侧栏与移动端 Drawer 共用）。 */
  const renderKbNav = () => (
    <div className="kb-nav">
      {/* 第一列：一级菜单方块卡片 */}
      <div className="kb-nav-rail">
        {menuTree.map((item) => {
          const selected = item.id === groupId;
          return (
            <div
              key={item.id}
              className={`kb-nav-card${selected ? " is-active" : ""}`}
              title={menuLabel(item.code || item.id, item.name)}
              onClick={() => handleGroupClick(item)}
            >
              <span className="kb-nav-card-icon">
                {resolveMenuIcon(item.icon) ?? <UserOutlined />}
              </span>
              <span className="kb-nav-card-label">
                {menuLabel(item.code || item.id, item.name)}
              </span>
            </div>
          );
        })}
      </div>
      {/* 第二列：当前一级分组下的子菜单（无二级菜单时不渲染整列） */}
      {isDesktop && !subCollapsed && hasSub && (
        <div className="kb-nav-sub">
          {subSections.map((section, sectionIdx) => (
            <div key={section.title ?? `section-${sectionIdx}`}>
              {section.title && (
                <div className="kb-nav-sub-title">{section.title}</div>
              )}
              {section.leaves.map((leaf) => {
                const selected = leaf.id === activeItemId;
                return (
                  <div
                    key={leaf.id}
                    className={`kb-nav-sub-item${selected ? " is-active" : ""}`}
                    title={menuLabel(leaf.code || leaf.id, leaf.name)}
                    onClick={() => handleSubClick(leaf)}
                  >
                    {menuLabel(leaf.code || leaf.id, leaf.name)}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
      {!isDesktop && hasSub && (
        <div className="kb-nav-sub">
          {subSections.map((section, sectionIdx) => (
            <div key={section.title ?? `section-${sectionIdx}`}>
              {section.title && <div className="kb-nav-sub-title">{section.title}</div>}
              {section.leaves.map((leaf) => {
                const selected = leaf.id === activeItemId;
                return (
                  <div
                    key={leaf.id}
                    className={`kb-nav-sub-item${selected ? " is-active" : ""}`}
                    onClick={() => handleSubClick(leaf)}
                  >
                    {menuLabel(leaf.code || leaf.id, leaf.name)}
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
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
        <div className="admin-design-header-left">
          {!isDesktop && (
            <Button
              aria-label={t("打开菜单")}
              icon={<MenuOutlined />}
              type="text"
              onClick={() => setMobileMenuOpen(true)}
            />
          )}

          <Link
            href={firstMenuPath ?? "/admin"}
            className="admin-design-header-brand"
          >
            <img
              src={withBasePath("/favicon.ico")}
              alt={t("高压电塔图标")}
              width={24}
              height={24}
              className="h-6 w-6"
            />
            <span className="admin-design-header-title">{t("防雷计算")}</span>
          </Link>
          <div className="admin-design-header-divider" />
        </div>

        <div className="admin-design-header-right">
          <LangSwitcher lang={lang} onChange={setLang} compact />

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
                <Button icon={<BellOutlined />} type="text" />
              </Badge>
            </Popover>
          </Tooltip>

          <Dropdown
            menu={{ items: accountMenuItems, onClick: onAccountMenuClick }}
            arrow={{ pointAtCenter: true }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <div className="admin-design-header-user">
              {user.avatar_url && !avatarError ? (
                <Avatar
                  size={28}
                  src={`${getApiBaseUrl()}${user.avatar_url}?t=${encodeURIComponent(user.updated_at ?? "")}`}
                  style={{ backgroundColor: "var(--ant-color-primary)" }}
                  onError={() => {
                    setAvatarError(true);
                    return false;
                  }}
                />
              ) : (
                <Avatar size={28} style={{ backgroundColor: "var(--ant-color-primary)" }}>
                  {user.username.trim().charAt(0).toUpperCase() || "U"}
                </Avatar>
              )}
              <span className="admin-design-header-username">{user.username}</span>
              <CaretDownOutlined style={{ fontSize: 12, color: "#4D5E7D" }} />
            </div>
          </Dropdown>
        </div>
      </Header>

      <AntLayout hasSider style={{ flex: 1, minHeight: 0 }}>
        {isDesktop && (
          <div
            className="admin-design-sider"
            style={{ width: !subCollapsed && hasSub ? 264 : 104 }}
          >
            {renderKbNav()}
            {hasSub && (
              <div
                className="admin-design-sider-collapse"
                onClick={() => setSubCollapsed((v) => !v)}
                title={subCollapsed ? t("展开子菜单") : t("收起子菜单")}
              >
                <CaretDownOutlined
                  style={{ fontSize: 12, color: "#4D5E7D", transform: "rotate(90deg)" }}
                />
              </div>
            )}
          </div>
        )}

        {!isDesktop && (
          <Drawer
            title={null}
            placement="left"
            open={mobileMenuOpen}
            width={300}
            onClose={() => setMobileMenuOpen(false)}
            styles={{ body: { padding: 0 } }}
          >
            {renderKbNav()}
          </Drawer>
        )}

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
