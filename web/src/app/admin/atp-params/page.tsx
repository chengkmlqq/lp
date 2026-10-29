"use client";

// ATP 模型计算参数管理页（参数注册表）。
// 定义参数模板使用的那些参数：
//   · line_binding : 从线路导入的杆塔属性绑定（建立 杆塔属性路径 ↔ 参数名 关联）
//   · script       : Python 计算脚本（沙箱求值，纯数学）
//   · constant     : 字面量
// 参数目录（参数模板页 slots_json 的 {"param": code} 形态）消费本页定义；
// 参数 ↔ ATP 模型槽位的关系仍由「参数模板」映射。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Col,
  Drawer,
  Dropdown,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Pagination,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CodeOutlined,
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FunctionOutlined,
  LinkOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";

const { Text } = Typography;

type SourceType = "line_binding" | "script" | "constant";

type DefinitionItem = {
  id: string;
  code: string;
  name: string;
  unit: string | null;
  data_type: string;
  source_type: SourceType;
  binding_json: Record<string, unknown>;
  script_code: string | null;
  deps_json: string[];
  enabled: boolean;
  sort_order: number;
  description: string | null;
  updated_at: string | null;
  updated_by: string | null;
};

type FieldsResponse = {
  fields: {
    value: string;
    label: string;
    source: "base_tower" | "profile" | "options";
    data_type?: string;
    unit?: string | null;
    note?: string | null;
  }[];
  transform_options: string[];
  source_options: { value: string; label: string }[];
  script_functions: string[];
};

// ── 试算（按真实杆塔上下文）相关类型 ──────────────────────────────────────
type LineOption = {
  id: string;
  name: string;
  code?: string | null;
  voltage_kv?: number | null;
  tower_count?: number;
};

type TowerOption = {
  id: string;
  tower_no: string;
  seq_no?: number;
  tower_type?: string | null;
  tower_model?: string | null;
  altitude_m?: number | null;
  ground_resistance_ohm?: number | null;
};

type ResolvedParam = {
  code: string;
  name: string;
  unit?: string | null;
  source_type: string;
  value: unknown;
};

type TowerPreviewResult = {
  tower_id: string;
  tower_no: string | null;
  tower_type: string | null;
  line_name: string | null;
  ok: boolean;
  error: string | null;
  items: ResolvedParam[];
};

const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  line_binding: "线路导入绑定",
  script: "计算脚本",
  constant: "字面量",
};

const DATA_TYPE_LABEL: Record<string, string> = {
  number: "数值",
  string: "字符串",
  bool: "布尔",
};

// 列表视图动态表体高度（严格照搬 power-lines 的常量口径）
const ATP_PARAMS_TABLE_MIN_SCROLL_Y = 180;
const ATP_PARAMS_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const ATP_PARAMS_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const ATP_PARAMS_TABLE_BOTTOM_GAP = 8;

const SOURCE_TYPE_COLOR: Record<SourceType, string> = {
  line_binding: "geekblue",
  script: "purple",
  constant: "orange",
};

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** 绑定 / 脚本摘要（表格列与卡片共用；showIcon=false 时去掉前置图标，卡片用）。 */
function renderSourceSummary(record: DefinitionItem, showIcon = true, t: (s: string) => string = (s) => s) {
  if (record.source_type === "line_binding") {
    const binding = record.binding_json as { source?: string; path?: string };
    const label = `${binding.source ?? ""}.${binding.path ?? ""}`;
    return (
      <Tooltip title={binding.path ?? ""}>
        <Space size={4} style={{ minWidth: 0 }}>
          {showIcon ? <LinkOutlined style={{ color: "#1677ff" }} /> : null}
          <Text style={{ fontSize: 12, maxWidth: 200 }} ellipsis={{ tooltip: label }}>
            {label}
          </Text>
        </Space>
      </Tooltip>
    );
  }
  if (record.source_type === "script") {
    return (
      <Space size={4} style={{ minWidth: 0 }}>
        {showIcon ? <CodeOutlined style={{ color: "#722ed1" }} /> : null}
        <Text
          style={{ fontSize: 12, maxWidth: 200 }}
          ellipsis={{ tooltip: record.script_code ?? "" }}
        >
          {record.script_code ? `${record.script_code.slice(0, 60)}${record.script_code.length > 60 ? "…" : ""}` : t("(空脚本)")}
        </Text>
      </Space>
    );
  }
  const binding = record.binding_json as { value?: unknown };
  return <Text style={{ fontSize: 12 }}>{formatValue(binding.value)}</Text>;
}

interface DefinitionCardProps {
  item: DefinitionItem;
  canManage: boolean;
  onEdit: (item: DefinitionItem) => void;
  onDetail: (item: DefinitionItem) => void;
  onDelete: (item: DefinitionItem) => void;
}

/** 参数定义卡片（严格参照线路管理 <PowerLineCard> 结构）。 */
function DefinitionCard({ item, canManage, onEdit, onDetail, onDelete }: DefinitionCardProps) {
  const { t } = useI18n();
  const sourceColor = SOURCE_TYPE_COLOR[item.source_type];
  const sourceLabel = t(SOURCE_TYPE_LABEL[item.source_type]);
  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-params-card admin-atp-models-card"
      onClick={() => onDetail(item)}
    >
      <div className="admin-atp-params-card-title admin-atp-models-card-title flex items-center gap-2 px-4 py-3">
        {item.source_type === "line_binding" ? (
          <LinkOutlined className="text-base" style={{ color: "#1677ff" }} />
        ) : item.source_type === "script" ? (
          <CodeOutlined className="text-base" style={{ color: "#722ed1" }} />
        ) : (
          <FunctionOutlined className="text-base text-gray-500" />
        )}
        <Typography.Text strong className="truncate flex-1">{item.name}</Typography.Text>
        {item.enabled ? <Tag color="green" style={{ marginInlineEnd: 0 }}>{t("启用")}</Tag> : <Tag style={{ marginInlineEnd: 0 }}>{t("停用")}</Tag>}
      </div>

      <div className="flex flex-col gap-2 px-4 py-3" style={{ minHeight: 120 }}>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("参数编码：")}</Typography.Text>
          <Typography.Text code style={{ fontSize: 12 }}>{item.code}</Typography.Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("参数来源：")}</Typography.Text>
          <Tag color={sourceColor} style={{ marginInlineEnd: 0 }}>{sourceLabel}</Tag>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {t("参数类型")}：{t(DATA_TYPE_LABEL[item.data_type]) ?? item.data_type}
          </Typography.Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          {item.source_type === "line_binding" ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("取数口径：")}</Typography.Text>
          ) : item.source_type === "script" ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("脚本内容：")}</Typography.Text>
          ) : null}
          {renderSourceSummary(item, false, t)}
        </div>
        {item.description ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: item.description }}>
            参数说明：{item.description}
          </Typography.Text>
        ) : null}
      </div>

      <div className="admin-atp-params-card-actions admin-atp-models-card-actions flex items-center justify-end gap-1 px-4 py-2">
        {canManage ? (
          <Space size={4}>
            <Tooltip title={t("详情")}>
              <Button size="small" type="text" icon={<EyeOutlined />} onClick={(event) => { event.stopPropagation(); onDetail(item); }} />
            </Tooltip>
            <Tooltip title={t("编辑")}>
              <Button size="small" type="text" icon={<EditOutlined />} onClick={(event) => { event.stopPropagation(); onEdit(item); }} />
            </Tooltip>
            <Dropdown
              menu={{
                items: [
                  {
                    key: "delete",
                    label: (
                      <Space size={4}>
                        <DeleteOutlined />
                        <span>{t("删除")}</span>
                      </Space>
                    ),
                    danger: true,
                    onClick: (event) => {
                      event.domEvent.stopPropagation();
                      onDelete(item);
                    },
                  },
                ],
              }}
              trigger={["click"]}
            >
              <Tooltip title={t("更多")}>
                <Button
                  type="text"
                  size="small"
                  icon={<MoreOutlined />}
                  onClick={(event) => {
                    event.stopPropagation();
                  }}
                />
              </Tooltip>
            </Dropdown>
          </Space>
        ) : (
          <Button size="small" type="text" icon={<EyeOutlined />} onClick={(event) => { event.stopPropagation(); onDetail(item); }}>
            查看
          </Button>
        )}
      </div>
    </Card>
  );
}

export default function AtpParamsPage() {
  const { t } = useI18n();
  const { message, modal } = App.useApp();
  const { fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("atp.manage");

  const [list, setList] = useState<DefinitionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterSource, setFilterSource] = useState<SourceType | undefined>(undefined);
  // 搜索：输入框值（keywordInput）与生效值（keyword）分离，点「查询」/回车才生效（参照线路管理）
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [fieldsMeta, setFieldsMeta] = useState<FieldsResponse | null>(null);
  // 卡片 / 列表双视图（严格参照线路管理 power-lines 的切换模式；默认卡片视图）
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  // 查询强制重拉：每次点「查询」自增 searchNonce（参照线路管理），
  // 即使关键词/筛选未变化也必然触发一次 loadList。
  const [searchNonce, setSearchNonce] = useState(0);
  const handleSearch = useCallback(() => {
    setKeyword(keywordInput.trim());
    setPagination((prev) => ({ ...prev, current: 1 }));
    setSearchNonce((n) => n + 1);
  }, [keywordInput]);
  // 列表视图动态表体高度（参照 power-lines：按列表面板 padding-box 底边推导，自适应窗口）
  const [tableScrollY, setTableScrollY] = useState(ATP_PARAMS_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return ATP_PARAMS_TABLE_MIN_SCROLL_Y;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return ATP_PARAMS_TABLE_MIN_SCROLL_Y;
    }
    // 口径与 power-lines 一致：不用 anchor 自身高度反推（会被 min-height 撑大 → 正反馈），
    // 不用 window.innerHeight（漏底部 padding → 多余纵向滚动条）。
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".admin-atp-params-list-pane");
    const container = pane ?? document.documentElement;
    const containerRect = container.getBoundingClientRect();
    const containerPadBottom = Number.parseFloat(getComputedStyle(container).paddingBottom) || 0;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const paginationEl = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? ATP_PARAMS_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight =
      paginationEl?.getBoundingClientRect().height ?? ATP_PARAMS_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available =
      containerRect.bottom - containerPadBottom - anchorTop - ATP_PARAMS_TABLE_BOTTOM_GAP;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
    return Math.max(ATP_PARAMS_TABLE_MIN_SCROLL_Y, nextHeight);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollHeight);
    };
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollHeight]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      setTableScrollY(updateTableScrollHeight());
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
  }, [updateTableScrollHeight, viewMode, list.length, loading, pagination.current, pagination.pageSize]);

  const [detail, setDetail] = useState<DefinitionItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [editing, setEditing] = useState<DefinitionItem | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form] = Form.useForm();
  const isMobile = useMobileDetection();

  // ── 试算（按真实杆塔上下文）：选线路 → 勾选杆塔 → 批量解析参数 ──────────
  const [trialOpen, setTrialOpen] = useState(false);
  const [trialLines, setTrialLines] = useState<LineOption[]>([]);
  const [trialLineId, setTrialLineId] = useState<string | undefined>(undefined);
  const [trialTowers, setTrialTowers] = useState<TowerOption[]>([]);
  const [trialTowersLoading, setTrialTowersLoading] = useState(false);
  const [trialSelected, setTrialSelected] = useState<string[]>([]);
  const [trialRunning, setTrialRunning] = useState(false);
  const [trialResults, setTrialResults] = useState<TowerPreviewResult[]>([]);
  const [trialResultOpen, setTrialResultOpen] = useState(false);
  // 结果抽屉：关键字过滤（按参数 code / 名称 / 值，跨塔共享）+ 当前塔 + 每塔分页状态
  const [trialResultKeyword, setTrialResultKeyword] = useState("");
  const [trialResultActiveTab, setTrialResultActiveTab] = useState<string | undefined>(undefined);
  const [trialResultPages, setTrialResultPages] = useState<Record<string, { current: number; pageSize: number }>>({});

  /** 关键字过滤：按 code / 名称 / 试算值匹配。 */
  const filterTrialItems = (items: ResolvedParam[], keyword: string): ResolvedParam[] => {
    const kw = keyword.trim().toLowerCase();
    if (!kw) return items;
    return items.filter(
      (item) =>
        item.code.toLowerCase().includes(kw) ||
        (item.name ?? "").toLowerCase().includes(kw) ||
        formatValue(item.value).toLowerCase().includes(kw),
    );
  };

  /** 打开试算弹窗：加载线路列表（缓存复用）。 */
  const openTrial = useCallback(async () => {
    setTrialOpen(true);
    try {
      if (trialLines.length === 0) {
        const response = await fetchWithAuth("/api/v1/lines?limit=1000");
        if (response.ok) {
          const data: { items: LineOption[] } = await response.json();
          setTrialLines(data.items ?? []);
        }
      }
    } catch {
      // 线路列表加载失败不阻塞弹窗（可手动重选）
    }
  }, [fetchWithAuth, trialLines.length]);

  /** 切换线路：加载该线路杆塔并重置勾选。 */
  const handleTrialLineChange = useCallback(
    async (lineId: string) => {
      setTrialLineId(lineId);
      setTrialSelected([]);
      setTrialTowers([]);
      if (!lineId) return;
      setTrialTowersLoading(true);
      try {
        const response = await fetchWithAuth(
          `/api/v1/lines/${lineId}/towers?limit=1000`
        );
        if (!response.ok) throw new Error(await readApiError(response));
        const data: { items: TowerOption[] } = await response.json();
        setTrialTowers(data.items ?? []);
      } catch (error) {
        message.error(error instanceof Error ? error.message : t("加载杆塔失败"));
      } finally {
        setTrialTowersLoading(false);
      }
    },
    [fetchWithAuth, message]
  );

  /** 确认试算：批量按真实杆塔上下文解析参数，结果用抽屉展示。 */
  const runTrial = useCallback(async () => {
    if (!trialSelected.length) {
      message.warning(t("请先勾选至少一根杆塔"));
      return;
    }
    setTrialRunning(true);
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-definitions/resolve-preview-by-towers", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tower_ids: trialSelected }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const data: { results: TowerPreviewResult[] } = await response.json();
      setTrialResults(data.results ?? []);
      setTrialResultKeyword("");
      setTrialResultPages({});
      setTrialResultActiveTab(data.results?.[0]?.tower_id);
      setTrialOpen(false);
      setTrialResultOpen(true);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("试算失败"));
    } finally {
      setTrialRunning(false);
    }
  }, [fetchWithAuth, message, trialSelected]);

  const loadList = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (filterSource) params.set("source_type", filterSource);
      const response = await fetchWithAuth(`/api/v1/atp/param-definitions?${params.toString()}`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data: { items: DefinitionItem[] } = await response.json();
      setList(data.items ?? []);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("加载参数列表失败"));
    } finally {
      setLoading(false);
    }
  }, [keyword, filterSource, searchNonce, message]);

  const loadFieldsMeta = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-definitions/fields");
      if (!response.ok) return;
      setFieldsMeta((await response.json()) as FieldsResponse);
    } catch {
      // 字段目录加载失败不阻塞页面
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    void loadFieldsMeta();
  }, [loadFieldsMeta]);

  const openDetail = (item: DefinitionItem) => {
    setDetail(item);
    setDetailOpen(true);
  };

  const openEdit = (item: DefinitionItem | null) => {
    setEditing(item);
    if (item) {
      form.setFieldsValue({
        code: item.code,
        name: item.name,
        unit: item.unit ?? "",
        data_type: item.data_type,
        source_type: item.source_type,
        binding_json: item.binding_json,
        script_code: item.script_code ?? "",
        deps_json: item.deps_json,
        enabled: item.enabled,
        sort_order: item.sort_order,
        description: item.description ?? "",
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        source_type: "line_binding",
        data_type: "number",
        enabled: true,
        sort_order: 0,
        deps_json: [],
        binding_json: {},
      });
    }
    setEditOpen(true);
  };

  const watchSource = Form.useWatch("source_type", form);

  const saveDefinition = async () => {
    setSaving(true);
    try {
      await form.validateFields();
      // ⚠️ 不用 validateFields() 的返回值：它只含「有 Form.Item 绑定」的字段，
      // 而 binding_json.source 由取数口径 onChange 写入 store、无对应 Form.Item，会被漏掉。
      // 这里校验后从完整 store 取值（true = 含未注册字段）。
      const values = form.getFieldsValue(true);
      const payload = {
        code: String(values.code ?? "").trim(),
        name: String(values.name ?? "").trim(),
        unit: values.unit ? String(values.unit).trim() : null,
        data_type: values.data_type ?? "number",
        source_type: values.source_type,
        binding_json: values.binding_json ?? {},
        script_code: values.source_type === "script" ? String(values.script_code ?? "") : null,
        deps_json: values.source_type === "script" ? (values.deps_json ?? []) : [],
        enabled: Boolean(values.enabled),
        sort_order: Number(values.sort_order ?? 0),
        description: values.description ? String(values.description).trim() : null,
      };
      if (values.source_type === "line_binding") {
        const binding = payload.binding_json || {};
        if (!binding.source || !binding.path) {
          message.warning(t("线路导入绑定需要选择「来源 + 取数口径」"));
          return;
        }
      }
      const url = editing
        ? `/api/v1/atp/param-definitions/${editing.id}`
        : "/api/v1/atp/param-definitions";
      const response = await fetchWithAuth(url, {
        method: editing ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(editing ? t("已保存") : t("已创建"));
      setEditOpen(false);
      await loadList();
    } catch (error) {
      if (error instanceof Error && "errorFields" in error) return; // 表单校验失败由表单提示
      message.error(error instanceof Error ? error.message : t("保存失败"));
    } finally {
      setSaving(false);
    }
  };

  const removeDefinition = (item: DefinitionItem) => {
    modal.confirm({
      title: `删除参数 ${item.code}？`,
      content: t("删除后参数模板若有引用将无法解析（保存时已拦截被引用的删除）。"),
      okText: t("删除"),
      okButtonProps: { danger: true },
      async onOk() {
        try {
          const response = await fetchWithAuth(`/api/v1/atp/param-definitions/${item.id}`, { method: "DELETE" });
          if (!response.ok) throw new Error(await readApiError(response));
          message.success(t("已删除"));
          await loadList();
        } catch (error) {
          message.error(error instanceof Error ? error.message : t("删除失败"));
        }
      },
    });
  };

  const depsOptions = (list ?? [])
    .filter((item) => item.enabled)
    .map((item) => ({ value: item.code, label: `${item.code}（${item.name}）` }));

  const bindingSourceOptions = fieldsMeta?.source_options ?? [];
  // 取数口径按来源域分组（OptGroup）：选中字段即确定来源域，无需单独选择来源
  const bindingFieldOptions = useMemo(() => {
    const groups = new Map<string, { label: string; options: { value: string; label: string; source: string }[] }>();
    for (const field of fieldsMeta?.fields ?? []) {
      const groupLabel = bindingSourceOptions.find((s) => s.value === field.source)?.label ?? field.source;
      if (!groups.has(field.source)) {
        groups.set(field.source, { label: groupLabel, options: [] });
      }
      groups.get(field.source)!.options.push({ value: field.value, label: field.label, source: field.source });
    }
    return Array.from(groups.values());
  }, [fieldsMeta, bindingSourceOptions]);

  const columns: ColumnsType<DefinitionItem> = [
    {
      title: t("参数 code"),
      dataIndex: "code",
      width: 221,
      fixed: "left",
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: t("名称"),
      dataIndex: "name",
      width: 235,
      render: (value: string, record) => (
        <Space size={4}>
          <Text>{value}</Text>
          {record.unit ? <Text type="secondary" style={{ fontSize: 12 }}>（{record.unit}）</Text> : null}
        </Space>
      ),
    },
    {
      title: t("来源类型"),
      dataIndex: "source_type",
      width: 191,
      render: (value: SourceType) => (
        <Tag color={SOURCE_TYPE_COLOR[value]}>{t(SOURCE_TYPE_LABEL[value])}</Tag>
      ),
    },
    {
      title: t("绑定 / 脚本"),
      dataIndex: "source_type",
      width: 383,
      render: (_, record) => renderSourceSummary(record, true, t),
    },
    {
      title: t("状态"),
      dataIndex: "enabled",
      width: 118,
      render: (value: boolean) => (value ? <Tag color="green">{t("启用")}</Tag> : <Tag>{t("停用")}</Tag>),
    },
  ];

  if (canManage) {
    columns.push({
      title: t("操作"),
      key: "actions",
      width: 150,
      fixed: "right",
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title={t("详情")}>
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => openDetail(record)} />
          </Tooltip>
          <Tooltip title={t("编辑")}>
            <Button size="small" type="text" icon={<EditOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Dropdown
            menu={{
              items: [
                {
                  key: "delete",
                  label: (
                    <Space size={4}>
                      <DeleteOutlined />
                      <span>{t("删除")}</span>
                    </Space>
                  ),
                  danger: true,
                  onClick: () => removeDefinition(record),
                },
              ],
            }}
            trigger={["click"]}
          >
            <Tooltip title={t("更多")}>
              <Button type="text" size="small" icon={<MoreOutlined />} />
            </Tooltip>
          </Dropdown>
        </Space>
      ),
    });
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey="list"
        className="admin-atp-params-tabs"
        tabBarExtraContent={
          <Space size={8}>
            <Button icon={<ExperimentOutlined />} onClick={() => void openTrial()}>
              试算
            </Button>
            {canManage ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>
                新建参数
              </Button>
            ) : null}
          </Space>
        }
        items={[
          {
            key: "list",
            label: (
              <span className="admin-atp-params-tab-title">
                ATP 计算参数管理
              </span>
            ),
            closable: false,
            children: (
              <div className="admin-atp-params-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("参数名称")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        placeholder={t("按 code/名称筛选")}
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item label={t("来源类型")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        placeholder={t("来源类型")}
                        value={filterSource}
                        onChange={(value) => setFilterSource(value as SourceType | undefined)}
                        style={{ width: 140 }}
                        options={[
                          { value: "line_binding", label: t("线路导入绑定") },
                          { value: "script", label: t("计算脚本") },
                          { value: "constant", label: t("字面量") },
                        ]}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={handleSearch}
                         loading={loading}className="admin-search-btn"
                      >
                        {t("查询")}
                      </Button>
                    </Form.Item>
                  </Form>
                  <Segmented
                    value={viewMode}
                    onChange={(value) => {
                      setViewMode(value as "card" | "list");
                      setPagination((prev) => ({ ...prev, current: 1 }));
                    }}
                    options={[
                      { label: t("卡片视图"), value: "card" },
                      { label: t("列表视图"), value: "list" },
                    ]}
                  />
                </div>
                <Spin spinning={loading}>
        {list.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无参数（可先执行「系统种子」或新建）")} style={{ padding: 40 }} />
        ) : viewMode === "card" ? (
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div className="admin-atp-params-card-scroll">
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                {list
                  .slice((pagination.current - 1) * pagination.pageSize, pagination.current * pagination.pageSize)
                  .map((item) => (
                    <DefinitionCard
                      key={item.id}
                      item={item}
                      canManage={canManage}
                      onEdit={openEdit}
                      onDetail={openDetail}
                      onDelete={removeDefinition}
                    />
                  ))}
              </div>
            </div>
            {loading ? (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-[color-mix(in_srgb,var(--ant-color-bg-layout)_60%,transparent)]">
                <Spin />
              </div>
            ) : null}
            <div className="admin-atp-params-pagination">
              <Pagination
                current={pagination.current}
                pageSize={pagination.pageSize}
                total={list.length}
                onChange={(page, pageSize) => setPagination({ current: page, pageSize })}
                showSizeChanger
                showTotal={(total) => `共 ${total} 条`}
              />
            </div>
          </div>
        ) : (
          <div
            ref={tableScrollAnchorRef}
            className="admin-atp-params-table-view"
            style={{ "--admin-atp-params-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
          >
            <Table
              rowKey="id"
              size="small"
              columns={columns}
              dataSource={list}
              pagination={{
                current: pagination.current,
                pageSize: pagination.pageSize,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 条`,
                // 与卡片视图独立分页组件尺寸一致（不随 Table size=small 缩到 24px）
                size: "default",
                onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
              }}
              scroll={{ x: 780, y: tableScrollY }}
            />
          </div>
        )}
      </Spin>
      </div>
      ),
      },
    ]}>
    </Tabs>

      {/* 详情弹窗（统一弹窗展示，与新建/编辑一致） */}
      <Modal
        title={`${t("参数详情")} · ${detail?.code ?? ""}`}
        open={detailOpen}
        onCancel={() => setDetailOpen(false)}
        width={520}
        footer={<Button onClick={() => setDetailOpen(false)}>{t("关闭")}</Button>}
      >
        {detail ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={`${detail.name} ｜ ${t(SOURCE_TYPE_LABEL[detail.source_type])}`}
              description={
                detail.source_type === "line_binding"
                  ? `${t("绑定")}：${(detail.binding_json as { source?: string }).source}.${(detail.binding_json as { path?: string }).path}`
                  : detail.source_type === "script"
                    ? t("计算脚本（沙箱求值，纯数学函数）")
                    : t("字面量")
              }
            />
            {detail.source_type === "script" && detail.script_code ? (
              <pre
                style={{
                  background: "#f5f5f5",
                  padding: 12,
                  borderRadius: 8,
                  fontSize: 12,
                  maxHeight: 300,
                  overflow: "auto",
                  whiteSpace: "pre-wrap",
                }}
              >
                {detail.script_code}
              </pre>
            ) : null}
            <Table
              rowKey="key"
              size="small"
              pagination={false}
              dataSource={[
                { key: "code", label: t("参数 code"), value: detail.code },
                { key: "unit", label: t("单位"), value: detail.unit ?? "-" },
                { key: "data_type", label: t("数据类型"), value: t(DATA_TYPE_LABEL[detail.data_type]) ?? detail.data_type },
                { key: "deps", label: t("依赖参数"), value: detail.deps_json.length ? detail.deps_json.join(", ") : "-" },
                { key: "enabled", label: t("启用"), value: detail.enabled ? "是" : "否" },
                { key: "desc", label: t("说明"), value: detail.description ?? "-" },
              ]}
              columns={[
                { title: t("项"), dataIndex: "label", width: 90 },
                { title: t("值"), dataIndex: "value" },
              ]}
            />
          </Space>
        ) : null}
      </Modal>

      {/* 新建/编辑弹窗（参照防雷计算任务新建：Modal + 表单内按钮） */}
      <Modal
        title={editing ? `${t("编辑参数")} ${editing.code}` : t("新建参数")}
        open={editOpen}
        width={880}
        footer={null}
        onCancel={() => {
          if (saving) return;
          setEditOpen(false);
        }}
        destroyOnHidden={false}
      >
        <Form form={form} layout="vertical" initialValues={{ data_type: "number", enabled: true, sort_order: 0 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                label={t("参数 code")}
                name="code"
                tooltip={t("字母/数字/下划线，如 h_u / coupling_k0")}
                rules={[{ required: true, pattern: /^[A-Za-z0-9_]+$/, message: t("字母/数字/下划线") }]}
              >
                <Input placeholder={t("请输入参数 code")} disabled={!!editing} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("名称")} name="name" tooltip={t("中文名，如 耦合系数 k0")} rules={[{ required: true }]}>
                <Input placeholder={t("请输入中文名称")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("参数来源")} name="source_type" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: "line_binding", label: t("线路导入绑定") },
                    { value: "script", label: t("计算脚本") },
                    { value: "constant", label: t("字面量") },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("单位")} name="unit" tooltip={t("结果单位，如 m / kA")}>
                <Input placeholder={t("请输入单位")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("数据类型")} name="data_type" tooltip={t("数值 / 字符串 / 布尔")}>
                <Select
                  options={[
                    { value: "number", label: t("数值") },
                    { value: "string", label: t("字符串") },
                    { value: "bool", label: t("布尔") },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("排序")} name="sort_order" tooltip={t("数字越小越靠前")}>
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t("启用")} name="enabled" valuePropName="checked" tooltip={t("关闭后模板解析将跳过该参数")}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          {watchSource === "line_binding" ? (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  label={t("取数口径")}
                  name={["binding_json", "path"]}
                  tooltip={t("从来源域（杆塔主表 / 塔属性 / 任务执行选项）按点路径（a.b.c）抽取原始字段；按来源域分组展示，选中字段即确定来源")}
                >
                  <Select
                    allowClear
                    placeholder={t("选择杆塔属性字段")}
                    showSearch
                    options={bindingFieldOptions}
                    onChange={(next) => {
                      const field = (fieldsMeta?.fields ?? []).find((item) => item.value === next);
                      if (field) {
                        // 选字段即确定来源域（避免来源/路径不匹配）。
                        // ⚠️ 不用 form.setFieldValue：它内部 setFields 每次传新的 errors 字面量，
                        // 触发 rc-util isEqual 把「errors/warnings 共享的 EMPTY_ERRORS 引用」误判为
                        // 循环引用（控制台 Warning: There may be circular references）。
                        // setFieldsValue 走 external 分支不传 errors/warnings，深合并只改 source。
                        form.setFieldsValue({ binding_json: { source: field.source } });
                      }
                    }}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label={t("单位换算")} name={["binding_json", "transform"]} tooltip={t("取值后应用换算，如 毫米→米（>100 启发式）")}>
                  <Select
                    allowClear
                    placeholder={t("无")}
                    options={(fieldsMeta?.transform_options ?? []).map((value) => ({ value, label: value === "mm_to_m" ? t("毫米→米（>100 启发式）") : value }))}
                  />
                </Form.Item>
              </Col>
            </Row>
          ) : null}

          {watchSource === "script" ? (
            <>
              <Form.Item
                label={t("依赖参数")}
                name="deps_json"
                tooltip={t("声明脚本依赖的参数（可从注册表选，也可用上下文键名）；依赖会先于脚本求值。未声明依赖时，脚本只能引用输入框外的上下文键（如 shield_h / h_u / voltage），否则保存校验会拦截")}
              >
                <Select
                  mode="multiple"
                  allowClear
                  placeholder={t("选择依赖参数")}
                  options={depsOptions}
                />
              </Form.Item>
              <Form.Item
                label={t("脚本内容")}
                name="script_code"
                tooltip={t("Python 沙箱：只允许纯数学函数（abs/sqrt/hypot/log/pow/exp/sin/cos/tan/clamp/v 等），禁止 import/IO/循环；最后变量 result 作为输出")}
                rules={[{ required: true, message: t("请输入脚本") }]}
              >
                <Input.TextArea
                  rows={10}
                  placeholder={t("请输入计算脚本")}
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
              </Form.Item>
            </>
          ) : null}

          {watchSource === "constant" ? (
            <Form.Item
              label={t("字面量")}
              name={["binding_json", "value"]}
              tooltip={t("固定常量，如 0.0055")}
              rules={[{ required: true, message: t("请输入字面量") }]}
            >
              <Input placeholder={t("请输入字面量")} />
            </Form.Item>
          ) : null}

          <Form.Item label={t("说明")} name="description" tooltip={t("参数用途 / 单位说明 / 来源（可选）")}>
            <Input.TextArea rows={2} placeholder={t("请输入说明")} />
          </Form.Item>

          <Space style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
            <Button disabled={saving} onClick={() => setEditOpen(false)}>
              取消
            </Button>
            <Button type="primary" loading={saving} onClick={() => void saveDefinition()}>
              保存
            </Button>
          </Space>
        </Form>
      </Modal>

      {/* 试算弹窗：选线路 → 勾选杆塔 → 确认后按真实杆塔上下文解析参数 */}
      <Modal
        title={t("参数试算（按真实杆塔上下文）")}
        open={trialOpen}
        onCancel={() => setTrialOpen(false)}
        width={720}
        footer={
          <Space style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
            <Button disabled={trialRunning} onClick={() => setTrialOpen(false)}>
              取消
            </Button>
            <Button
              type="primary"
              loading={trialRunning}
              disabled={trialSelected.length === 0}
              onClick={() => void runTrial()}
            >
              {t("确认试算（已选")} {trialSelected.length} {t("座）")}
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Form layout="vertical">
            <Form.Item label={t("线路")} style={{ marginBottom: 8 }}>
              <Select
                showSearch
                placeholder={t("选择线路")}
                value={trialLineId}
                loading={trialTowersLoading}
                onChange={(value) => void handleTrialLineChange(String(value))}
                optionFilterProp="label"
                options={trialLines.map((line) => ({
                  value: line.id,
                  label: `${line.name}${line.voltage_kv ? `（${line.voltage_kv}kV）` : ""}`,
                }))}
              />
            </Form.Item>
          </Form>
          <Spin spinning={trialTowersLoading}>
            <Table
              rowKey="id"
              size="small"
              dataSource={trialTowers}
              pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `${t("共 ")}${total}${t(" 座杆塔")}`, size: "default" }}
              locale={{ emptyText: trialLineId ? t("该线路暂无杆塔") : t("请先选择线路") }}
              rowSelection={{
                selectedRowKeys: trialSelected,
                onChange: (keys) => setTrialSelected(keys.map(String)),
              }}
              columns={[
                { title: t("塔号"), dataIndex: "tower_no", width: 100 },
                { title: t("塔型"), dataIndex: "tower_type", width: 110, render: (value: string | null) => value || "-" },
                { title: t("杆塔模型"), dataIndex: "tower_model", render: (value: string | null) => value || "-" },
                {
                  title: t("海拔(m)"),
                  dataIndex: "altitude_m",
                  width: 90,
                  render: (value: number | null) => (value == null ? "-" : String(value)),
                },
                {
                  title: t("接地电阻(Ω)"),
                  dataIndex: "ground_resistance_ohm",
                  width: 110,
                  render: (value: number | null) => (value == null ? "-" : String(value)),
                },
              ]}
            />
          </Spin>
        </Space>
      </Modal>

      {/* 试算结果抽屉：按塔分组展示参数解析值（过滤条固定顶部、表格区滚动、分页固定右下角） */}
      <Drawer
        title={`${t("参数试算结果")}（${trialResults.length} ${t("座杆塔")}）`}
        open={trialResultOpen}
        onClose={() => setTrialResultOpen(false)}
        width={720}
        styles={{ body: { display: "flex", flexDirection: "column", paddingBottom: 0, overflow: "hidden" } }}
      >
        {trialResults.length === 0 ? (
          <Empty description={t("暂无试算结果")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <>
            {/* 顶部固定：关键字过滤表单 */}
            <div style={{ flex: "none", paddingBottom: 12 }}>
              <Input
                allowClear
                prefix={<SearchOutlined />}
                placeholder={t("按参数 code / 名称 / 值过滤")}
                value={trialResultKeyword}
                onChange={(event) => {
                  setTrialResultKeyword(event.target.value);
                  setTrialResultPages({}); // 关键字变化回到第 1 页
                }}
                style={{ width: 300 }}
              />
            </div>

            {/* 中间滚动区：塔 tabs + 当前塔参数表（分页在底部，表格不内部分页） */}
            <div style={{ flex: 1, minHeight: 0, overflowY: "auto", paddingRight: 4 }}>
              <Tabs
                type="card"
                size="small"
                activeKey={trialResultActiveTab}
                onChange={(key) => setTrialResultActiveTab(key)}
                items={trialResults.map((result) => ({
                  key: result.tower_id,
                  label: `${result.tower_no ?? t("未知塔号")}${result.tower_type ? `（${result.tower_type}）` : ""}`,
                  children: result.ok ? (
                    <Table
                      rowKey="code"
                      size="small"
                      dataSource={filterTrialItems(result.items ?? [], trialResultKeyword)}
                      pagination={false}
                      columns={[
                        {
                          title: t("参数 code"),
                          dataIndex: "code",
                          width: 150,
                          render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
                        },
                        { title: t("名称"), dataIndex: "name", width: 160 },
                        {
                          title: t("来源"),
                          dataIndex: "source_type",
                          width: 120,
                          render: (value: string) => (
                            <Tag color={SOURCE_TYPE_COLOR[value as SourceType] ?? "default"}>
                              {t(SOURCE_TYPE_LABEL[value as SourceType]) ?? value}
                            </Tag>
                          ),
                        },
                        {
                          title: t("试算值"),
                          dataIndex: "value",
                          render: (value: unknown) => <Typography.Text strong>{formatValue(value)}</Typography.Text>,
                        },
                        {
                          title: t("单位"),
                          dataIndex: "unit",
                          width: 80,
                          render: (value: string | null) => value || "-",
                        },
                      ]}
                    />
                  ) : (
                    <Alert
                      type="error"
                      showIcon
                      message={`${t("试算失败")}：${result.error ?? t("未知错误")}`}
                      description={t("该杆塔缺少必要的台账/profile 数据（如未导入塔属性），请先补齐后再试算。")}
                    />
                  ),
                }))}
              />
            </div>

            {/* 底部固定：分页右下角（作用于当前激活塔，过滤后总数） */}
            {(() => {
              const active = trialResults.find((r) => r.tower_id === trialResultActiveTab);
              if (!active) return null;
              const total = active.ok ? filterTrialItems(active.items ?? [], trialResultKeyword).length : 0;
              const page = trialResultPages[active.tower_id] ?? { current: 1, pageSize: 20 };
              return (
                <div
                  style={{
                    flex: "none",
                    display: "flex",
                    justifyContent: "flex-end",
                    alignItems: "center",
                    padding: "10px 0 12px",
                  }}
                >
                  <Pagination
                    size="small"
                    current={page.current}
                    pageSize={page.pageSize}
                    total={total}
                    showSizeChanger
                    showTotal={(t) => `共 ${t} 个参数`}
                    onChange={(current, pageSize) =>
                      setTrialResultPages((prev) => ({ ...prev, [active.tower_id]: { current, pageSize } }))
                    }
                  />
                </div>
              );
            })()}
          </>
        )}
      </Drawer>
    </div>
  );
}
