/**
 * 图标注册表 — 集中管理所有供菜单配置使用的 AntDesign 图标。
 *
 * 按业务场景分类导出，方便维护和扩展。
 * 每个类别至少包含 5-8 个图标，总计 70+ 个图标。
 */
import type { ComponentType } from "react";

// ─── 系统管理（用户、角色、权限、菜单、日志、设置、配置等） ───
import UserOutlined from "@ant-design/icons/UserOutlined";
import TeamOutlined from "@ant-design/icons/TeamOutlined";
import SafetyCertificateOutlined from "@ant-design/icons/SafetyCertificateOutlined";
import MenuOutlined from "@ant-design/icons/MenuOutlined";
import ProfileOutlined from "@ant-design/icons/ProfileOutlined";
import SettingOutlined from "@ant-design/icons/SettingOutlined";
import ControlOutlined from "@ant-design/icons/ControlOutlined";
import KeyOutlined from "@ant-design/icons/KeyOutlined";
import AuditOutlined from "@ant-design/icons/AuditOutlined";
import IdcardOutlined from "@ant-design/icons/IdcardOutlined";

// ─── 业务功能（ATP模型、防雷计算、波形分析、定时任务、报告等） ───
import ThunderboltOutlined from "@ant-design/icons/ThunderboltOutlined";
import ExperimentOutlined from "@ant-design/icons/ExperimentOutlined";
import FunctionOutlined from "@ant-design/icons/FunctionOutlined";
import RadarChartOutlined from "@ant-design/icons/RadarChartOutlined";
import ApartmentOutlined from "@ant-design/icons/ApartmentOutlined";
import DeploymentUnitOutlined from "@ant-design/icons/DeploymentUnitOutlined";
import FundOutlined from "@ant-design/icons/FundOutlined";
import BarChartOutlined from "@ant-design/icons/BarChartOutlined";
import LineChartOutlined from "@ant-design/icons/LineChartOutlined";
import FieldTimeOutlined from "@ant-design/icons/FieldTimeOutlined";
import AlertOutlined from "@ant-design/icons/AlertOutlined";

// ─── 数据/文件（上传、下载、导入、导出、文件、文件夹、表格等） ───
import FileTextOutlined from "@ant-design/icons/FileTextOutlined";
import FolderOpenOutlined from "@ant-design/icons/FolderOpenOutlined";
import DatabaseOutlined from "@ant-design/icons/DatabaseOutlined";
import CloudUploadOutlined from "@ant-design/icons/CloudUploadOutlined";
import CloudDownloadOutlined from "@ant-design/icons/CloudDownloadOutlined";
import ImportOutlined from "@ant-design/icons/ImportOutlined";
import ExportOutlined from "@ant-design/icons/ExportOutlined";
import TableOutlined from "@ant-design/icons/TableOutlined";
import FileAddOutlined from "@ant-design/icons/FileAddOutlined";
import PaperClipOutlined from "@ant-design/icons/PaperClipOutlined";

// ─── 操作（新增、编辑、删除、保存、搜索、刷新、重置等） ───
import PlusOutlined from "@ant-design/icons/PlusOutlined";
import EditOutlined from "@ant-design/icons/EditOutlined";
import DeleteOutlined from "@ant-design/icons/DeleteOutlined";
import SaveOutlined from "@ant-design/icons/SaveOutlined";
import SearchOutlined from "@ant-design/icons/SearchOutlined";
import ReloadOutlined from "@ant-design/icons/ReloadOutlined";
import UndoOutlined from "@ant-design/icons/UndoOutlined";
import CopyOutlined from "@ant-design/icons/CopyOutlined";
import FilterOutlined from "@ant-design/icons/FilterOutlined";
import SortAscendingOutlined from "@ant-design/icons/SortAscendingOutlined";

// ─── 视图/导航（首页、看板、列表、卡片、折叠、展开、返回等） ───
import HomeOutlined from "@ant-design/icons/HomeOutlined";
import DashboardOutlined from "@ant-design/icons/DashboardOutlined";
import AppstoreOutlined from "@ant-design/icons/AppstoreOutlined";
import UnorderedListOutlined from "@ant-design/icons/UnorderedListOutlined";
import AppstoreAddOutlined from "@ant-design/icons/AppstoreAddOutlined";
import UpOutlined from "@ant-design/icons/UpOutlined";
import ExpandOutlined from "@ant-design/icons/ExpandOutlined";
import ArrowLeftOutlined from "@ant-design/icons/ArrowLeftOutlined";
import ArrowRightOutlined from "@ant-design/icons/ArrowRightOutlined";
import MenuFoldOutlined from "@ant-design/icons/MenuFoldOutlined";

// ─── 状态/通知（成功、警告、错误、信息、待办、完成、进度等） ───
import CheckCircleOutlined from "@ant-design/icons/CheckCircleOutlined";
import WarningOutlined from "@ant-design/icons/WarningOutlined";
import CloseCircleOutlined from "@ant-design/icons/CloseCircleOutlined";
import InfoCircleOutlined from "@ant-design/icons/InfoCircleOutlined";
import BellOutlined from "@ant-design/icons/BellOutlined";
import CheckSquareOutlined from "@ant-design/icons/CheckSquareOutlined";
import ClockCircleOutlined from "@ant-design/icons/ClockCircleOutlined";
import ExclamationCircleOutlined from "@ant-design/icons/ExclamationCircleOutlined";
import StopOutlined from "@ant-design/icons/StopOutlined";
import QuestionCircleOutlined from "@ant-design/icons/QuestionCircleOutlined";

// ─── 其他通用（工单、消息、邮件、日历、图表、地图、设置等） ───
import MessageOutlined from "@ant-design/icons/MessageOutlined";
import MailOutlined from "@ant-design/icons/MailOutlined";
import CalendarOutlined from "@ant-design/icons/CalendarOutlined";
import PieChartOutlined from "@ant-design/icons/PieChartOutlined";
import GlobalOutlined from "@ant-design/icons/GlobalOutlined";
import ToolOutlined from "@ant-design/icons/ToolOutlined";
import NodeIndexOutlined from "@ant-design/icons/NodeIndexOutlined";
import ConsoleSqlOutlined from "@ant-design/icons/ConsoleSqlOutlined";
import SyncOutlined from "@ant-design/icons/SyncOutlined";
import StarOutlined from "@ant-design/icons/StarOutlined";
import FlagOutlined from "@ant-design/icons/FlagOutlined";
import EyeOutlined from "@ant-design/icons/EyeOutlined";
import LockOutlined from "@ant-design/icons/LockOutlined";
import LinkOutlined from "@ant-design/icons/LinkOutlined";
import TagOutlined from "@ant-design/icons/TagOutlined";
import PrinterOutlined from "@ant-design/icons/PrinterOutlined";
import ShareAltOutlined from "@ant-design/icons/ShareAltOutlined";
import BranchesOutlined from "@ant-design/icons/BranchesOutlined";
import CodeOutlined from "@ant-design/icons/CodeOutlined";
import CommentOutlined from "@ant-design/icons/CommentOutlined";
import FileExcelOutlined from "@ant-design/icons/FileExcelOutlined";
import AreaChartOutlined from "@ant-design/icons/AreaChartOutlined";
import NumberOutlined from "@ant-design/icons/NumberOutlined";
import DotChartOutlined from "@ant-design/icons/DotChartOutlined";
import FileOutlined from "@ant-design/icons/FileOutlined";
import FolderOutlined from "@ant-design/icons/FolderOutlined";
import FilePdfOutlined from "@ant-design/icons/FilePdfOutlined";
import FileImageOutlined from "@ant-design/icons/FileImageOutlined";
import FileSearchOutlined from "@ant-design/icons/FileSearchOutlined";
import ScissorOutlined from "@ant-design/icons/ScissorOutlined";
import SafetyOutlined from "@ant-design/icons/SafetyOutlined";
import ShopOutlined from "@ant-design/icons/ShopOutlined";
import CrownOutlined from "@ant-design/icons/CrownOutlined";
import ContactsOutlined from "@ant-design/icons/ContactsOutlined";
import BuildOutlined from "@ant-design/icons/BuildOutlined";
import ApiOutlined from "@ant-design/icons/ApiOutlined";
import CloudOutlined from "@ant-design/icons/CloudOutlined";
import ClusterOutlined from "@ant-design/icons/ClusterOutlined";
import NotificationOutlined from "@ant-design/icons/NotificationOutlined";
import SendOutlined from "@ant-design/icons/SendOutlined";
import WechatOutlined from "@ant-design/icons/WechatOutlined";
import CustomerServiceOutlined from "@ant-design/icons/CustomerServiceOutlined";
import DownloadOutlined from "@ant-design/icons/DownloadOutlined";
import UploadOutlined from "@ant-design/icons/UploadOutlined";
import SwapOutlined from "@ant-design/icons/SwapOutlined";
import ShrinkOutlined from "@ant-design/icons/ShrinkOutlined";
import RobotOutlined from "@ant-design/icons/RobotOutlined";
import BulbOutlined from "@ant-design/icons/BulbOutlined";
import FireOutlined from "@ant-design/icons/FireOutlined";

// ─── 导出类型 ───

export type IconEntry = {
  name: string;
  label: string;
  component: ComponentType<{ className?: string; style?: React.CSSProperties }>;
};

export type IconCategory = {
  key: string;
  label: string;
  icons: IconEntry[];
};

/** 图标名称 → 组件映射（扁平化，供 resolveIcon 使用） */
export const ICON_MAP: Record<string, ComponentType<{ className?: string; style?: React.CSSProperties }>> = {
  // 系统管理
  UserOutlined,
  TeamOutlined,
  SafetyCertificateOutlined,
  MenuOutlined,
  ProfileOutlined,
  SettingOutlined,
  ControlOutlined,
  KeyOutlined,
  AuditOutlined,
  IdcardOutlined,
  // 业务功能
  ThunderboltOutlined,
  ExperimentOutlined,
  FunctionOutlined,
  RadarChartOutlined,
  ApartmentOutlined,
  DeploymentUnitOutlined,
  FundOutlined,
  BarChartOutlined,
  LineChartOutlined,
  FieldTimeOutlined,
  AlertOutlined,
  // 数据/文件
  FileTextOutlined,
  FolderOpenOutlined,
  DatabaseOutlined,
  CloudUploadOutlined,
  CloudDownloadOutlined,
  ImportOutlined,
  ExportOutlined,
  TableOutlined,
  FileAddOutlined,
  PaperClipOutlined,
  // 操作
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  SaveOutlined,
  SearchOutlined,
  ReloadOutlined,
  UndoOutlined,
  CopyOutlined,
  FilterOutlined,
  SortAscendingOutlined,
  // 视图/导航
  HomeOutlined,
  DashboardOutlined,
  AppstoreOutlined,
  UnorderedListOutlined,
  AppstoreAddOutlined,
  UpOutlined,
  ExpandOutlined,
  ArrowLeftOutlined,
  ArrowRightOutlined,
  MenuFoldOutlined,
  // 状态/通知
  CheckCircleOutlined,
  WarningOutlined,
  CloseCircleOutlined,
  InfoCircleOutlined,
  BellOutlined,
  CheckSquareOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  StopOutlined,
  QuestionCircleOutlined,
  // 其他通用
  MessageOutlined,
  MailOutlined,
  CalendarOutlined,
  PieChartOutlined,
  GlobalOutlined,
  ToolOutlined,
  NodeIndexOutlined,
  ConsoleSqlOutlined,
  SyncOutlined,
  StarOutlined,
  FlagOutlined,
  EyeOutlined,
  LockOutlined,
  LinkOutlined,
  TagOutlined,
  PrinterOutlined,
  ShareAltOutlined,
  BranchesOutlined,
  CodeOutlined,
  CommentOutlined,
  // 补充图标
  FileExcelOutlined,
  AreaChartOutlined,
  NumberOutlined,
  DotChartOutlined,
  FileOutlined,
  FolderOutlined,
  FilePdfOutlined,
  FileImageOutlined,
  FileSearchOutlined,
  ScissorOutlined,
  SafetyOutlined,
  ShopOutlined,
  CrownOutlined,
  ContactsOutlined,
  BuildOutlined,
  ApiOutlined,
  CloudOutlined,
  ClusterOutlined,
  NotificationOutlined,
  SendOutlined,
  WechatOutlined,
  CustomerServiceOutlined,
  DownloadOutlined,
  UploadOutlined,
  SwapOutlined,
  ShrinkOutlined,
  RobotOutlined,
  BulbOutlined,
  FireOutlined,
};

/** 分类图标列表 — 供图标选择器 UI 使用 */
export const ICON_CATEGORIES: IconCategory[] = [
  {
    key: "system",
    label: "系统管理",
    icons: [
      { name: "UserOutlined", label: "用户", component: UserOutlined },
      { name: "TeamOutlined", label: "团队/角色", component: TeamOutlined },
      { name: "SafetyCertificateOutlined", label: "权限/安全", component: SafetyCertificateOutlined },
      { name: "MenuOutlined", label: "菜单", component: MenuOutlined },
      { name: "ProfileOutlined", label: "日志/档案", component: ProfileOutlined },
      { name: "SettingOutlined", label: "设置", component: SettingOutlined },
      { name: "ControlOutlined", label: "控制", component: ControlOutlined },
      { name: "KeyOutlined", label: "密钥", component: KeyOutlined },
      { name: "AuditOutlined", label: "审计", component: AuditOutlined },
      { name: "IdcardOutlined", label: "身份", component: IdcardOutlined },
      { name: "SafetyOutlined", label: "安全", component: SafetyOutlined },
      { name: "ShopOutlined", label: "租户/组织", component: ShopOutlined },
      { name: "CrownOutlined", label: "管理/特权", component: CrownOutlined },
      { name: "ContactsOutlined", label: "通讯录", component: ContactsOutlined },
    ],
  },
  {
    key: "business",
    label: "业务功能",
    icons: [
      { name: "ThunderboltOutlined", label: "雷电/防雷", component: ThunderboltOutlined },
      { name: "ExperimentOutlined", label: "实验/ATP", component: ExperimentOutlined },
      { name: "FunctionOutlined", label: "函数/参数", component: FunctionOutlined },
      { name: "RadarChartOutlined", label: "雷达/分析", component: RadarChartOutlined },
      { name: "ApartmentOutlined", label: "架构/模型", component: ApartmentOutlined },
      { name: "DeploymentUnitOutlined", label: "部署单元", component: DeploymentUnitOutlined },
      { name: "FundOutlined", label: "资金/统计", component: FundOutlined },
      { name: "BarChartOutlined", label: "柱状图", component: BarChartOutlined },
      { name: "LineChartOutlined", label: "折线图", component: LineChartOutlined },
      { name: "FieldTimeOutlined", label: "定时任务", component: FieldTimeOutlined },
      { name: "AlertOutlined", label: "告警", component: AlertOutlined },
      { name: "AreaChartOutlined", label: "面积图", component: AreaChartOutlined },
      { name: "NumberOutlined", label: "数值统计", component: NumberOutlined },
      { name: "DotChartOutlined", label: "散点图", component: DotChartOutlined },
    ],
  },
  {
    key: "data",
    label: "数据/文件",
    icons: [
      { name: "FileTextOutlined", label: "文档", component: FileTextOutlined },
      { name: "FolderOpenOutlined", label: "文件夹", component: FolderOpenOutlined },
      { name: "DatabaseOutlined", label: "数据库", component: DatabaseOutlined },
      { name: "CloudUploadOutlined", label: "上传", component: CloudUploadOutlined },
      { name: "CloudDownloadOutlined", label: "下载", component: CloudDownloadOutlined },
      { name: "ImportOutlined", label: "导入", component: ImportOutlined },
      { name: "ExportOutlined", label: "导出", component: ExportOutlined },
      { name: "TableOutlined", label: "表格", component: TableOutlined },
      { name: "FileAddOutlined", label: "新建文件", component: FileAddOutlined },
      { name: "PaperClipOutlined", label: "附件", component: PaperClipOutlined },
      { name: "FileExcelOutlined", label: "Excel表格", component: FileExcelOutlined },
      { name: "FileOutlined", label: "通用文件", component: FileOutlined },
      { name: "FolderOutlined", label: "文件夹", component: FolderOutlined },
      { name: "FilePdfOutlined", label: "PDF文档", component: FilePdfOutlined },
      { name: "FileImageOutlined", label: "图片", component: FileImageOutlined },
      { name: "FileSearchOutlined", label: "文件搜索", component: FileSearchOutlined },
      { name: "ScissorOutlined", label: "剪切", component: ScissorOutlined },
    ],
  },
  {
    key: "action",
    label: "操作",
    icons: [
      { name: "PlusOutlined", label: "新增", component: PlusOutlined },
      { name: "EditOutlined", label: "编辑", component: EditOutlined },
      { name: "DeleteOutlined", label: "删除", component: DeleteOutlined },
      { name: "SaveOutlined", label: "保存", component: SaveOutlined },
      { name: "SearchOutlined", label: "搜索", component: SearchOutlined },
      { name: "ReloadOutlined", label: "刷新", component: ReloadOutlined },
      { name: "UndoOutlined", label: "重置", component: UndoOutlined },
      { name: "CopyOutlined", label: "复制", component: CopyOutlined },
      { name: "FilterOutlined", label: "筛选", component: FilterOutlined },
      { name: "SortAscendingOutlined", label: "排序", component: SortAscendingOutlined },
    ],
  },
  {
    key: "nav",
    label: "视图/导航",
    icons: [
      { name: "HomeOutlined", label: "首页", component: HomeOutlined },
      { name: "DashboardOutlined", label: "看板", component: DashboardOutlined },
      { name: "AppstoreOutlined", label: "应用/菜单", component: AppstoreOutlined },
      { name: "UnorderedListOutlined", label: "列表", component: UnorderedListOutlined },
      { name: "AppstoreAddOutlined", label: "新增应用", component: AppstoreAddOutlined },
      { name: "UpOutlined", label: "向上/收起", component: UpOutlined },
      { name: "ExpandOutlined", label: "展开", component: ExpandOutlined },
      { name: "ArrowLeftOutlined", label: "返回", component: ArrowLeftOutlined },
      { name: "ArrowRightOutlined", label: "前进", component: ArrowRightOutlined },
      { name: "MenuFoldOutlined", label: "菜单折叠", component: MenuFoldOutlined },
    ],
  },
  {
    key: "status",
    label: "状态/通知",
    icons: [
      { name: "CheckCircleOutlined", label: "成功", component: CheckCircleOutlined },
      { name: "WarningOutlined", label: "警告", component: WarningOutlined },
      { name: "CloseCircleOutlined", label: "错误", component: CloseCircleOutlined },
      { name: "InfoCircleOutlined", label: "信息", component: InfoCircleOutlined },
      { name: "BellOutlined", label: "通知/待办", component: BellOutlined },
      { name: "CheckSquareOutlined", label: "完成", component: CheckSquareOutlined },
      { name: "ClockCircleOutlined", label: "时钟/待办", component: ClockCircleOutlined },
      { name: "ExclamationCircleOutlined", label: "感叹/注意", component: ExclamationCircleOutlined },
      { name: "StopOutlined", label: "停止/禁止", component: StopOutlined },
      { name: "QuestionCircleOutlined", label: "帮助/疑问", component: QuestionCircleOutlined },
    ],
  },
  {
    key: "general",
    label: "其他通用",
    icons: [
      { name: "MessageOutlined", label: "消息", component: MessageOutlined },
      { name: "MailOutlined", label: "邮件", component: MailOutlined },
      { name: "CalendarOutlined", label: "日历", component: CalendarOutlined },
      { name: "PieChartOutlined", label: "饼图/图表", component: PieChartOutlined },
      { name: "GlobalOutlined", label: "地图/全局", component: GlobalOutlined },
      { name: "ToolOutlined", label: "工具", component: ToolOutlined },
      { name: "NodeIndexOutlined", label: "节点索引", component: NodeIndexOutlined },
      { name: "ConsoleSqlOutlined", label: "SQL控制台", component: ConsoleSqlOutlined },
      { name: "SyncOutlined", label: "同步", component: SyncOutlined },
      { name: "StarOutlined", label: "星标/收藏", component: StarOutlined },
      { name: "FlagOutlined", label: "标记", component: FlagOutlined },
      { name: "EyeOutlined", label: "查看/预览", component: EyeOutlined },
      { name: "LockOutlined", label: "锁定/安全", component: LockOutlined },
      { name: "LinkOutlined", label: "链接", component: LinkOutlined },
      { name: "TagOutlined", label: "标签", component: TagOutlined },
      { name: "PrinterOutlined", label: "打印", component: PrinterOutlined },
      { name: "ShareAltOutlined", label: "分享", component: ShareAltOutlined },
      { name: "BranchesOutlined", label: "分支/流程", component: BranchesOutlined },
      { name: "CodeOutlined", label: "代码", component: CodeOutlined },
      { name: "CommentOutlined", label: "评论/备注", component: CommentOutlined },
      { name: "BuildOutlined", label: "构建/部署", component: BuildOutlined },
      { name: "ApiOutlined", label: "API接口", component: ApiOutlined },
      { name: "CloudOutlined", label: "云服务", component: CloudOutlined },
      { name: "ClusterOutlined", label: "集群", component: ClusterOutlined },
      { name: "NotificationOutlined", label: "通知推送", component: NotificationOutlined },
      { name: "SendOutlined", label: "发送", component: SendOutlined },
      { name: "WechatOutlined", label: "微信", component: WechatOutlined },
      { name: "CustomerServiceOutlined", label: "客服", component: CustomerServiceOutlined },
      { name: "DownloadOutlined", label: "下载", component: DownloadOutlined },
      { name: "UploadOutlined", label: "上传", component: UploadOutlined },
      { name: "SwapOutlined", label: "交换/切换", component: SwapOutlined },
      { name: "ShrinkOutlined", label: "收缩", component: ShrinkOutlined },
      { name: "RobotOutlined", label: "机器人/AI", component: RobotOutlined },
      { name: "BulbOutlined", label: "灵感/提示", component: BulbOutlined },
      { name: "FireOutlined", label: "热门/紧急", component: FireOutlined },
    ],
  },
];

/** 根据图标名称获取图标组件 */
export function resolveIcon(iconName: string | null): ComponentType<{ className?: string; style?: React.CSSProperties }> | null {
  if (!iconName) return null;
  return ICON_MAP[iconName] ?? null;
}