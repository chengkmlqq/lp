"use client";

import type { ComponentType, ReactNode } from "react";

// ──────────────────────────────────────────────
// 集中式 AntDesign 图标引用文件
// 按业务场景分类，便于菜单配置时引用
// ──────────────────────────────────────────────

// 通用/UI 图标
import {
  AppstoreOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuOutlined,
  MenuUnfoldOutlined,
  MoonOutlined,
  SunOutlined,
  SyncOutlined,
  UserOutlined,
} from "@ant-design/icons";

// 数据与表格
import {
  AuditOutlined,
  BarChartOutlined,
  AreaChartOutlined,
  DatabaseOutlined,
  DotChartOutlined,
  FileExcelOutlined,
  LineChartOutlined,
  NumberOutlined,
  PieChartOutlined,
  TableOutlined,
} from "@ant-design/icons";

// 文件与文档
import {
  CopyOutlined,
  FileAddOutlined,
  FileImageOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FolderOpenOutlined,
  FolderOutlined,
  PaperClipOutlined,
  ScissorOutlined,
} from "@ant-design/icons";

// 用户与权限
import {
  ContactsOutlined,
  CrownOutlined,
  IdcardOutlined,
  KeyOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  SafetyOutlined,
  ShopOutlined,
  TeamOutlined,
} from "@ant-design/icons";

// 系统与设置
import {
  ApiOutlined,
  BuildOutlined,
  CloudOutlined,
  ClusterOutlined,
  ControlOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  SettingOutlined,
  ToolOutlined,
} from "@ant-design/icons";

// 通信与消息
import {
  BellOutlined,
  CommentOutlined,
  CustomerServiceOutlined,
  MailOutlined,
  MessageOutlined,
  NotificationOutlined,
  SendOutlined,
  WechatOutlined,
} from "@ant-design/icons";

// 导航与动作
import {
  DownloadOutlined,
  ExportOutlined,
  ImportOutlined,
  LinkOutlined,
  ReloadOutlined,
  ShrinkOutlined,
  SwapOutlined,
  UploadOutlined,
} from "@ant-design/icons";

// 状态与提示
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  QuestionCircleOutlined,
  StopOutlined,
  WarningOutlined,
} from "@ant-design/icons";

// 杂项工具
import {
  BulbOutlined,
  EyeOutlined,
  FireOutlined,
  RobotOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

// 专业/领域相关
import {
  ApartmentOutlined,
  CalendarOutlined,
  ConsoleSqlOutlined,
  DeploymentUnitOutlined,
  GlobalOutlined,
  NodeIndexOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";

/**
 * 菜单图标映射表
 *
 * 左侧为菜单配置中存储的 icon 名称字符串，
 * 右侧为对应的 AntDesign 图标组件。
 *
 * 支持两种格式：
 * - 友好名称（如 Users、Settings2）── 兼容旧数据
 * - 直接的 Outlined 名称（如 TeamOutlined）── 新配置统一使用
 */
const MENU_ICON_COMPONENTS = {
  // ── 原有友好名称映射（兼容旧数据） ──
  Users: TeamOutlined,
  ShieldCheck: SafetyCertificateOutlined,
  MenuSquare: AppstoreOutlined,
  Settings2: SettingOutlined,
  Network: NodeIndexOutlined,
  Zap: ThunderboltOutlined,
  Map: GlobalOutlined,
  RadarChart: RadarChartOutlined,
  CalendarClock: CalendarOutlined,
  Experiment: ExperimentOutlined,
  Apartment: ApartmentOutlined,
  FolderTree: FolderOpenOutlined,
  Database: DatabaseOutlined,
  FileText: FileTextOutlined,
  Terminal: ConsoleSqlOutlined,
  Bell: BellOutlined,

  // ── 数据与表格 ──
  TableOutlined,
  FileExcelOutlined,
  BarChartOutlined,
  PieChartOutlined,
  LineChartOutlined,
  DotChartOutlined,
  AreaChartOutlined,
  NumberOutlined,
  AuditOutlined,

  // ── 文件与文档 ──
  FileOutlined,
  FolderOutlined,
  FilePdfOutlined,
  FileImageOutlined,
  FileAddOutlined,
  FileSearchOutlined,
  PaperClipOutlined,
  CopyOutlined,
  ScissorOutlined,

  // ── 用户与权限 ──
  SafetyOutlined,
  LockOutlined,
  KeyOutlined,
  ShopOutlined,
  CrownOutlined,
  IdcardOutlined,
  ContactsOutlined,

  // ── 系统与设置 ──
  ToolOutlined,
  BuildOutlined,
  ApiOutlined,
  CloudOutlined,
  ClusterOutlined,
  DashboardOutlined,
  ControlOutlined,

  // ── 通信与消息 ──
  MessageOutlined,
  NotificationOutlined,
  MailOutlined,
  SendOutlined,
  WechatOutlined,
  CustomerServiceOutlined,
  CommentOutlined,

  // ── 导航与动作 ──
  LinkOutlined,
  ExportOutlined,
  ImportOutlined,
  DownloadOutlined,
  UploadOutlined,
  ReloadOutlined,
  SwapOutlined,
  ShrinkOutlined,

  // ── 状态与提示 ──
  CheckCircleOutlined,
  WarningOutlined,
  InfoCircleOutlined,
  CloseCircleOutlined,
  QuestionCircleOutlined,
  StopOutlined,

  // ── 杂项工具 ──
  SearchOutlined,
  EyeOutlined,
  RobotOutlined,
  BulbOutlined,
  FireOutlined,

  // ── 领域相关（已在上面作为友好名称导出，此处保持引用） ──
  DeploymentUnitOutlined,
  RadarChartOutlined,
  CalendarOutlined,
  ExperimentOutlined,
  ApartmentOutlined,
  FolderOpenOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  ConsoleSqlOutlined,
  BellOutlined,
  SettingOutlined,
  NodeIndexOutlined,
  ThunderboltOutlined,
  GlobalOutlined,
  AppstoreOutlined,
  SafetyCertificateOutlined,
  TeamOutlined,
  UserOutlined,
} as const;

type MenuIconKey = keyof typeof MENU_ICON_COMPONENTS;

/**
 * 根据图标名称解析为对应的 React 组件
 */
function resolveMenuIcon(iconName: string | null, fallback?: ReactNode): ReactNode {
  const key = iconName?.trim() as MenuIconKey | undefined;
  if (key && key in MENU_ICON_COMPONENTS) {
    const IconComponent = MENU_ICON_COMPONENTS[key] as ComponentType<Record<string, unknown>>;
    return <IconComponent />;
  }
  return fallback ?? <AppstoreOutlined />;
}

export { MENU_ICON_COMPONENTS, resolveMenuIcon };
export type { MenuIconKey };
