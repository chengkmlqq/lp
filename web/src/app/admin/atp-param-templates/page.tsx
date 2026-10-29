"use client";

// ATP 参数模板管理页。
// 布局参照「ATP 计算参数管理」页：筛选栏 + 卡片/列表双视图 + 表格操作列。
// 数据源仍为模板树接口（平铺成行），详情/试算/编辑弹窗保留原逻辑。
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  type MenuProps,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  EyeOutlined,
  FunctionOutlined,
  MoreOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

type TreeNodeData = {
  key: string;
  label: string;
  node_type: "global" | "group" | "rule";
  dimension: string | null;
  // 匹配维度摘要（值 null = 通配）；卡片视图展示用
  dimensions?: {
    tower_type?: string | null;
    voltage_level?: string | null;
    circuit_count?: number | null;
    scene_type?: string | null;
    arrester_config?: string | null;
  };
  rule_id: string | null;
  has_template: boolean;
  defined_slots: number;
  effective_slots: number;
  status: "own" | "inherit";
  inherited_from: string | null;
  overridden_by: string[];
  children: TreeNodeData[];
};

type TreeResponse = { total: number; root: TreeNodeData };

type TemplateDetail = {
  id: string;
  name: string;
  marker: string | null;
  tower_type: string | null;
  voltage_level: string | null;
  circuit_count: number | null;
  scene_type: string | null;
  arrester_config: string | null;
  structure_kind: string | null;
  priority: number;
  mode: string;
  enabled: boolean;
  fallback_to: string | null;
  fallback_enabled: boolean;
  specificity: number;
  defined_slots: number;
  defined_defaults?: number;
  slots: Record<string, { expr?: string; value?: string; fmt?: number; enabled?: boolean; when?: string; else?: string; param?: string }>;
  defaults?: Record<string, string | number>;
  updated_at: string | null;
  updated_by: string | null;
};

type ResolvedSlot = { slot: string; value: string; source: string; inherited: boolean };
type PreviewResponse = { chain: string[]; tower_kind: string | null; slots: ResolvedSlot[]; diff: ResolvedSlot[] };

type MetaResponse = {
  tower_types: { value: string; label: string }[];
  voltages: string[];
  scene_types: { value: string; label: string }[];
  arrester_configs: { value: string; label: string }[];
  slot_names: string[];
  variable_names?: string[];
};

type SlotRow = { key: string; slot: string; expr: string; fmt: number; enabled: boolean; value?: string; when?: string; param?: string };
// 槽位引用的注册表参数（详情接口 slot_params 返回）
type SlotParamRef = { code: string; name: string; source_type: string; via: string };
type ParamSourceMap = Record<string, SlotParamRef>;

const { Text, Title } = Typography;

// 右表高度自适应视口（严格照搬 power-lines 口径：可滚动容器 padding-box 底边推导）
const TEMPLATE_TABLE_MIN_SCROLL_Y = 180;
const TEMPLATE_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const TEMPLATE_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const TEMPLATE_TABLE_BOTTOM_GAP = 8;

/** 树节点平铺成「模板行」(含祖先链,用于树点击过滤)。 */
type TemplateRow = {
  key: string;
  node: TreeNodeData;
  ancestors: string[]; // 祖先 key 链(不含自身)
  pathLabel: string; // 祖先名 / 自身名
};

function flattenRules(node: TreeNodeData, ancestors: string[], path: string[]): TemplateRow[] {
  const rows: TemplateRow[] = [];
  const nextPath = [...path, node.label];
  if (node.node_type === "rule" || node.has_template) {
    rows.push({ key: node.key, node, ancestors, pathLabel: nextPath.join(" / ") });
  }
  for (const child of node.children ?? []) {
    rows.push(...flattenRules(child, [...ancestors, node.key], nextPath));
  }
  return rows;
}

interface TemplateCardProps {
  row: TemplateRow;
  canManage: boolean;
  onDetail: () => void;
  onEdit: () => void;
  onPreview: () => void;
  onDerive: () => void;
  onDelete: () => void;
}

const TOWER_TYPE_LABEL: Record<string, string> = {
  ganzi: "干字型",
  guxing: "鼓型",
  jiubei: "酒杯型",
  maotou: "猫头型",
  menxing: "门型",
  shangzi: "上字型",
  sihuita: "四回路型",
};

/** 参数模板卡片（参照 ATP 计算参数管理页 DefinitionCard 结构）。 */
function TemplateCard({ row, canManage, onDetail, onEdit, onPreview, onDerive, onDelete }: TemplateCardProps) {
  const { t } = useI18n();
  const hasRule = Boolean(row.node.rule_id);
  const dims = row.node.dimensions;
  const towerText = dims?.tower_type
    ? (TOWER_TYPE_LABEL[dims.tower_type] ? t(TOWER_TYPE_LABEL[dims.tower_type]) : dims.tower_type)
    : t("全部");
  const moreItems: MenuProps["items"] = [
    { key: "preview", label: t("试算"), icon: <ExperimentOutlined />, disabled: !hasRule, onClick: onPreview },
    ...(canManage
      ? [
          { key: "derive", label: t("细分"), icon: <PlusOutlined />, disabled: !hasRule, onClick: onDerive },
          { key: "delete", label: t("删除"), icon: <DeleteOutlined />, danger: true, disabled: !hasRule, onClick: onDelete },
        ]
      : []),
  ];
  return (
    <Card
      size="small"
      hoverable
      className="admin-atp-params-card admin-atp-models-card"
      onClick={() => void onDetail()}
    >
      <div className="admin-atp-params-card-title admin-atp-models-card-title flex items-center gap-2 px-4 py-3">
        <FunctionOutlined className="text-base text-gray-500" />
        <Typography.Text strong className="truncate flex-1">{row.node.label}</Typography.Text>
        {row.node.status === "inherit" ? (
          <Tag style={{ marginInlineEnd: 0 }}>{t("继承")}</Tag>
        ) : (
          <Tag color="blue" style={{ marginInlineEnd: 0 }}>{t("本级")}</Tag>
        )}
      </div>

      <div className="flex flex-col gap-2 px-4 py-3" style={{ minHeight: 120 }}>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("杆塔类型：")}</Typography.Text>
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: towerText }}>
            {towerText}
          </Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("电压等级：")}</Typography.Text>
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: dims?.voltage_level ?? t("全部") }}>
            {dims?.voltage_level ? `${dims.voltage_level}kV` : t("全部")}
          </Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("回路数量：")}</Typography.Text>
          <Text style={{ fontSize: 12 }}>{dims?.circuit_count != null ? `${dims.circuit_count} ${t("回")}` : t("全部")}</Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("场景：")}</Typography.Text>
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: dims?.scene_type ?? t("全部") }}>
            {dims?.scene_type ?? t("全部")}
          </Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("避雷器组合：")}</Typography.Text>
          <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: dims?.arrester_config ?? t("全部") }}>
            {dims?.arrester_config ?? t("全部")}
          </Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("槽位数量：")}</Typography.Text>
          {row.node.has_template ? (
            <Typography.Text style={{ fontSize: 12 }}>
              {row.node.defined_slots}/{row.node.effective_slots}
            </Typography.Text>
          ) : (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>{t("继承")}</Typography.Text>
          )}
        </div>
      </div>

      <div className="admin-atp-params-card-actions admin-atp-models-card-actions flex items-center justify-end gap-1 px-4 py-2">
        <Space size={4}>
          <Tooltip title={t("详情")}>
            <Button size="small" type="text" icon={<EyeOutlined />} disabled={!hasRule} onClick={(event) => { event.stopPropagation(); onDetail(); }} />
          </Tooltip>
          {canManage ? (
            <Tooltip title={t("编辑")}>
              <Button size="small" type="text" icon={<EditOutlined />} disabled={!hasRule} onClick={(event) => { event.stopPropagation(); onEdit(); }} />
            </Tooltip>
          ) : null}
          <Dropdown menu={{ items: moreItems }} trigger={["click"]}>
            <Tooltip title={t("更多")}>
              <Button size="small" type="text" icon={<MoreOutlined />} onClick={(event) => { event.stopPropagation(); }} />
            </Tooltip>
          </Dropdown>
        </Space>
      </div>
    </Card>
  );
}

export default function AtpParamTemplatesPage() {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("atp.manage");
  const [tree, setTree] = useState<TreeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewCtx, setPreviewCtx] = useState<{ tower_type?: string; voltage_level?: string; circuit_count?: number; scene_type?: string; arrester_config?: string }>({});
  const [editing, setEditing] = useState(false);
  const [editingForChild, setEditingForChild] = useState(false);
  const [slotRows, setSlotRows] = useState<SlotRow[]>([]);
  const [form] = Form.useForm();
  const [slotOptions, setSlotOptions] = useState<string[]>([]);
  const [slotOptionsLoading, setSlotOptionsLoading] = useState(false);

  // 维度联动槽位并集：编辑态下按当前表单维度拉 /assets/slot-options
  const refreshSlotOptions = useCallback(async () => {
    const vals = form.getFieldsValue(["tower_type", "voltage_level", "scene_type", "arrester_config"]);
    const params = new URLSearchParams();
    if (vals.tower_type) params.set("tower_type", vals.tower_type);
    if (vals.voltage_level) params.set("voltage_level", String(vals.voltage_level));
    if (vals.scene_type) params.set("scene_type", vals.scene_type);
    if (vals.arrester_config) params.set("arrester_config", vals.arrester_config);
    setSlotOptionsLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/assets/slot-options?${params.toString()}`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data = (await response.json()) as { slot_names: string[] };
      setSlotOptions(data.slot_names ?? []);
    } catch {
      setSlotOptions([]);
    } finally {
      setSlotOptionsLoading(false);
    }
  }, [fetchWithAuth, form]);
  // 参数注册表 code（槽位「参数引用」模式用）
  const [paramCodes, setParamCodes] = useState<string[]>([]);
  // 槽位引用参数解析（详情接口返回）: {槽位名: [参数...]}
  const [slotParams, setSlotParams] = useState<Record<string, SlotParamRef[]>>({});
  const [paramSources, setParamSources] = useState<ParamSourceMap>({});

  // 弹窗状态
  const [detailOpen, setDetailOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  // 视图模式：卡片 / 列表（参照 ATP 计算参数管理页）
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  // 表体高度随视口自适应
  const [tableScrollY, setTableScrollY] = useState(TEMPLATE_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  // 本地筛选（关键词 + 层级 + 查询）
  const [tableKeywordInput, setTableKeywordInput] = useState("");
  const [tableKeyword, setTableKeyword] = useState("");
  const [levelFilter, setLevelFilter] = useState<"own" | "inherit" | undefined>(undefined);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const loadTree = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-templates/tree");
      if (!response.ok) throw new Error(await readApiError(response));
      const data: TreeResponse = await response.json();
      setTree(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("加载模板树失败"));
    } finally {
      setLoading(false);
    }
  }, [message]);

  const loadMeta = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-templates/meta");
      if (!response.ok) return;
      setMeta((await response.json()) as MetaResponse);
    } catch {
      // meta 加载失败不阻塞页面
    }
  }, []);

  const loadParamCodes = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-definitions");
      if (!response.ok) return;
      const data: { items?: { code: string; enabled: boolean }[] } = await response.json();
      setParamCodes((data.items ?? []).filter((item) => item.enabled).map((item) => item.code));
    } catch {
      // 注册表加载失败不阻塞页面
    }
  }, []);

  useEffect(() => {
    void loadTree();
    void loadMeta();
    void loadParamCodes();
  }, [loadTree, loadMeta, loadParamCodes]);

  const nodeMap = useMemo(() => {
    const map = new Map<string, TreeNodeData>();
    const walk = (node: TreeNodeData) => {
      map.set(node.key, node);
      node.children?.forEach(walk);
    };
    if (tree?.root) walk(tree.root);
    return map;
  }, [tree]);

  const loadDetail = useCallback(
    async (ruleId: string) => {
      try {
        const response = await fetchWithAuth(`/api/v1/atp/param-templates/${ruleId}`);
        if (!response.ok) throw new Error(await readApiError(response));
        const data = (await response.json()) as TemplateDetail & {
          slot_params?: Record<string, SlotParamRef[]>;
          param_sources?: ParamSourceMap;
        };
        setDetail(data);
        setSlotParams(data.slot_params ?? {});
        setParamSources(data.param_sources ?? {});
      } catch (error) {
        message.error(error instanceof Error ? error.message : t("加载模板失败"));
      }
    },
    [message],
  );

  const runPreview = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-templates/resolve-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...previewCtx, rule_id: detail?.id }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setPreview((await response.json()) as PreviewResponse);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("试算失败"));
    }
  }, [previewCtx, detail?.id, message]);

  // 右表「查询」:提交关键词(本地过滤);每次点击都强制触发一次接口请求
  const handleTableSearch = () => {
    setTableKeyword(tableKeywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
    void loadTree();
  };

  // 清除筛选:清掉关键词与层级过滤
  const clearFilters = () => {
    setTableKeywordInput("");
    setTableKeyword("");
    setLevelFilter(undefined);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };

  // 打开详情弹窗:先加载模板数据再开
  const openDetailDrawer = async (row: TemplateRow) => {
    if (!row.node.rule_id) {
      message.info(row.node.has_template ? t("该节点是继承节点,没有独立模板") : t("该层为分组节点"));
      return;
    }
    await loadDetail(row.node.rule_id);
    setDetailOpen(true);
  };

  // 打开试算抽屉:沿用当前选中模板上下文
  const openPreviewDrawer = async (row: TemplateRow) => {
    if (!row.node.rule_id) {
      message.info(t("该节点没有独立模板,请选择一个有模板的节点试算"));
      return;
    }
    await loadDetail(row.node.rule_id);
    setPreview(null);
    setPreviewOpen(true);
  };

  const disableTemplate = async () => {
    if (!detail) return;
    try {
      const response = await fetchWithAuth(`/api/v1/atp/param-templates/${detail.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...detail, enabled: !detail.enabled }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(detail.enabled ? t("已停用") : t("已启用"));
      await loadTree();
      if (detail.id) void loadDetail(detail.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("操作失败"));
    }
  };

  const removeTemplate = async () => {
    if (!detail) return;
    Modal.confirm({
      title: `${t("确认删除模板")}「${detail.name}」${t("？")}`,
      content: t("删除后该节点将回退到上层继承,不可恢复。"),
      okText: t("删除"),
      okButtonProps: { danger: true },
      cancelText: t("取消"),
      onOk: async () => {
        try {
          const response = await fetchWithAuth(`/api/v1/atp/param-templates/${detail.id}`, { method: "DELETE" });
          if (!response.ok) throw new Error(await readApiError(response));
          message.success(t("已删除"));
          setDetail(null);
          setDetailOpen(false);
          setPreview(null);
          await loadTree();
        } catch (error) {
          message.error(error instanceof Error ? error.message : t("删除失败"));
        }
      },
    });
  };

  const deriveChild = async () => {
    if (!detail) return;
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-templates/derive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parent_id: detail.id }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const derived = await response.json();
      form.setFieldsValue({
        name: derived.suggested_name,
        tower_type: derived.dimensions.tower_type ?? detail.tower_type,
        voltage_level: derived.dimensions.voltage_level ?? undefined,
        priority: 100,
        mode: "merge",
        fallback_to: undefined,
      });
      setSlotRows([]);
      openEditor(derived.inherited_slots);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("派生失败"));
    }
  };

  // 新建顶层模板（不带父级细分）
  const openCreate = () => {
    setDetail(null);
    setEditingForChild(false);
    form.resetFields();
    form.setFieldsValue({ priority: 100, mode: "merge", fallback_enabled: true });
    setSlotRows([]);
    setEditing(true);
    void refreshSlotOptions();
  };

  const openEditor = (inherited?: Record<string, string>) => {
    if (detail && !inherited) {
      form.setFieldsValue({
        name: detail.name,
        tower_type: detail.tower_type,
        voltage_level: detail.voltage_level,
        circuit_count: detail.circuit_count,
        scene_type: detail.scene_type,
        arrester_config: detail.arrester_config,
        priority: detail.priority,
        mode: detail.mode,
        fallback_to: detail.fallback_to,
        fallback_enabled: detail.fallback_enabled,
      });
      setSlotRows(
        Object.entries(detail.slots ?? {}).map(([slot, spec]) => ({
          key: slot,
          slot,
          expr: spec.expr ?? spec.value ?? "",
          fmt: spec.fmt ?? 2,
          enabled: spec.enabled !== false,
          value: spec.value ?? "",
          when: spec.when ?? "",
          param: spec.param ?? undefined,
        })),
      );
    }
    if (inherited) {
      form.setFieldsValue({ fallback_enabled: true, priority: 100 });
    }
    setEditing(true);
    void refreshSlotOptions();
  };

  const saveEditor = async () => {
    try {
      const values = await form.validateFields();
      const slots: Record<string, unknown> = {};
      slotRows.forEach((row) => {
        if (!row.slot) return;
        const spec: Record<string, unknown> = { fmt: row.fmt, enabled: row.enabled };
        if (row.param) spec.param = row.param;
        else if (row.value) spec.value = row.value;
        else spec.expr = row.expr;
        if (row.when) spec.when = row.when;
        slots[row.slot] = spec;
      });
      // 「测试默认参数集」UI 已下线：不再提交 defaults 键 ——
      // 后端 update_template 是 `if "defaults" in payload` 才写入，故历史
      // defaults_json 原样保留，「无杆塔测试」路径仍可读取既有默认值。
      const payload = { ...values, slots };
      const url = detail && !editingForChild ? `/api/v1/atp/param-templates/${detail.id}` : "/api/v1/atp/param-templates";
      const method = detail && !editingForChild ? "PUT" : "POST";
      const response = await fetchWithAuth(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("已保存（保存即生效）"));
      setEditing(false);
      setEditingForChild(false);
      await loadTree();
      const saved: TemplateDetail = await response.json();
      if (saved?.id) void loadDetail(saved.id);
    } catch (error) {
      if (error instanceof Error && error.message) message.error(error.message);
    }
  };

  // 表格数据:树节点平铺(rule/has_template 节点)
  const templateRows = useMemo(() => (tree?.root ? flattenRules(tree.root, [], []) : []), [tree]);
  const hasTableFilter = Boolean(tableKeyword.trim() || levelFilter);
  const filteredRows = useMemo(() => {
    let rows = templateRows;
    const kw = tableKeyword.trim().toLowerCase();
    if (kw) {
      rows = rows.filter(
        (row) => row.node.label.toLowerCase().includes(kw) || row.pathLabel.toLowerCase().includes(kw),
      );
    }
    if (levelFilter) {
      rows = rows.filter((row) => row.node.status === levelFilter);
    }
    return rows;
  }, [templateRows, tableKeyword, levelFilter]);

  const slotColumns: ColumnsType<SlotRow> = [
    { title: t("槽位"), dataIndex: "slot", width: 250, render: (v) => <Text code>{v}</Text> },
    {
      title: t("表达式 / 值 / 参数"),
      dataIndex: "expr",
      render: (v, row) =>
        row.param ? (
          <Space size={4}>
            <Tag color="purple">{t("参数")}</Tag>
            <Text code>{row.param}</Text>
          </Space>
        ) : row.value ? (
          <Text type="secondary">{t("字面量")} {row.value}</Text>
        ) : (
          <Text>{v}</Text>
        ),
    },
    {
      title: t("映射参数"),
      key: "ref_params",
      width: 190,
      render: (_, row) => {
        const refs = slotParams[row.slot] ?? [];
        if (refs.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
        return (
          <Space size={4} wrap>
            {refs.map((ref) => (
              <Tooltip
                key={ref.code}
                title={
                  ref.source_type === "line_binding"
                    ? `${t("线路导入绑定")}：${ref.via}`
                    : ref.source_type === "script"
                      ? `${ref.name}（${t("脚本计算")}）`
                      : t("字面量")
                }
              >
                <Tag color={ref.source_type === "line_binding" ? "geekblue" : "purple"} style={{ marginInlineEnd: 0 }}>
                  {ref.code}
                </Tag>
              </Tooltip>
            ))}
          </Space>
        );
      },
    },
    {
      title: t("参数来源"),
      key: "param_source",
      width: 240,
      render: (_, row) => {
        const refs = slotParams[row.slot] ?? [];
        if (refs.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
        return (
          <Space direction="vertical" size={2} style={{ width: "100%" }}>
            {refs.map((ref) => (
              <Tooltip key={ref.code} title={ref.via}>
                <Text style={{ fontSize: 12 }} ellipsis={{ tooltip: ref.via }}>
                  <Text code style={{ fontSize: 12 }}>{ref.code}</Text>{" "}
                  {ref.source_type === "line_binding" ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>{ref.via}</Text>
                  ) : (
                    <Text type="secondary" style={{ fontSize: 12 }}>{t("脚本计算")}</Text>
                  )}
                </Text>
              </Tooltip>
            ))}
          </Space>
        );
      },
    },
    { title: t("格式"), dataIndex: "fmt", width: 70, render: (v) => `${v} ${t("位")}` },
    { title: t("启用"), dataIndex: "enabled", width: 70, render: (v) => (v ? <Tag color="green">{t("启用")}</Tag> : <Tag>{t("关闭")}</Tag>) },
    {
      title: "",
      width: 60,
      render: (_, row) => (
        <Button type="link" danger size="small" onClick={() => setSlotRows((rows) => rows.filter((item) => item.key !== row.key))}>
          {t("删除")}
        </Button>
      ),
    },
  ];

  const previewColumns: ColumnsType<ResolvedSlot> = [
    { title: t("槽位"), dataIndex: "slot", width: 130, render: (v) => <Text code>{v}</Text> },
    { title: t("值"), dataIndex: "value", width: 110 },
    {
      title: t("来源"),
      dataIndex: "source",
      render: (v, row) => (row.inherited ? <Tag color="orange">{t("继承")} · {v}</Tag> : <Tag color="blue">{t("本级")} · {v}</Tag>),
    },
    {
      title: "",
      width: 70,
      render: (_, row) => (preview?.diff.some((item) => item.slot === row.slot) ? <Tag color="red">{t("差异")}</Tag> : null),
    },
  ];

  const tableColumns: ColumnsType<TemplateRow> = [
    {
      title: t("模板名称"),
      dataIndex: ["node", "label"],
      render: (_v, row) => (
        <Space size={6}>
          <span>{row.node.label}</span>
          {row.node.status === "inherit" ? <Tag>{t("继承")}</Tag> : <Tag color="blue">{t("本级")}</Tag>}
        </Space>
      ),
    },
    {
      title: t("覆盖路径"),
      dataIndex: "pathLabel",
      width: 649,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: t("槽位"),
      key: "slots",
      width: 100,
      render: (_v, row) =>
        row.node.has_template ? (
          <span>
            {row.node.defined_slots}/{row.node.effective_slots}
          </span>
        ) : (
          <Text type="secondary">{t("继承")}</Text>
        ),
    },
    {
      title: t("状态"),
      key: "status",
      width: 250,
      render: (_v, row) => {
        if (!row.node.has_template) return <Tag>{t("继承")}</Tag>;
        // 模板启用状态以 detail 为准;表格里统一显示「本级/继承」+ 槽位
        return row.node.status === "own" ? <Tag color="blue">{t("本级")}</Tag> : <Tag color="orange">{t("继承")}</Tag>;
      },
    },
    {
      title: t("操作"),
      key: "actions",
      fixed: "right",
      width: 150,
      render: (_v, row) => {
        const hasRule = Boolean(row.node.rule_id);
        const editTemplate = () => {
          if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => openEditor());
        };
        const deleteTemplate = () => {
          if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => void removeTemplate());
        };
        const deriveTemplate = () => {
          const ruleId = row.node.rule_id;
          if (ruleId) void loadDetail(ruleId).then(() => void deriveChild());
        };

        const moreMenuItems: MenuProps["items"] = [
          {
            key: "preview",
            label: t("试算"),
            icon: <ExperimentOutlined />,
            disabled: !hasRule,
            onClick: () => void openPreviewDrawer(row),
          },
          ...(canManage
            ? [
                {
                  key: "derive",
                  label: t("细分"),
                  icon: <PlusOutlined />,
                  disabled: !hasRule,
                  onClick: () => void deriveTemplate(),
                },
                {
                  key: "delete",
                  label: t("删除"),
                  icon: <DeleteOutlined />,
                  danger: true,
                  disabled: !hasRule,
                  onClick: () => void deleteTemplate(),
                },
              ]
            : []),
        ];

        if (!canManage) {
          return (
            <Space wrap size={4}>
              <Button size="small" disabled={!hasRule} onClick={() => void openDetailDrawer(row)}>
                {t("详情")}
              </Button>
              <Button size="small" disabled={!hasRule} onClick={() => void openPreviewDrawer(row)}>
                {t("试算")}
              </Button>
            </Space>
          );
        }

        return (
          <Space wrap size={4}>
            <Button size="small" disabled={!hasRule} onClick={() => void openDetailDrawer(row)}>
              {t("详情")}
            </Button>
            <Button size="small" disabled={!hasRule} onClick={() => void editTemplate()}>
              {t("编辑")}
            </Button>
            <Dropdown menu={{ items: moreMenuItems }} trigger={["click"]}>
              <Button size="small" icon={<MoreOutlined />} aria-label={t("更多操作")} />
            </Dropdown>
          </Space>
        );
      },
    },
  ];

  // 列表视图动态表体高度（严格照搬 power-lines 口径：按列表面板 padding-box 底边推导，自适应窗口）
  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return TEMPLATE_TABLE_MIN_SCROLL_Y;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return TEMPLATE_TABLE_MIN_SCROLL_Y;
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
    const headerHeight = header?.getBoundingClientRect().height ?? TEMPLATE_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight =
      paginationEl?.getBoundingClientRect().height ?? TEMPLATE_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const available = containerRect.bottom - containerPadBottom - anchorTop - TEMPLATE_TABLE_BOTTOM_GAP;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16 - 4);
    return Math.max(TEMPLATE_TABLE_MIN_SCROLL_Y, nextHeight);
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(() => {
        setTableScrollY(updateTableScrollY());
      });
    };
    window.addEventListener("resize", onViewportChange);
    return () => {
      window.removeEventListener("resize", onViewportChange);
    };
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const frame = window.requestAnimationFrame(() => {
      setTableScrollY(updateTableScrollY());
    });
    return () => {
      window.cancelAnimationFrame(frame);
    };
    // 列表视图挂载（viewMode 切换）与数据/分页变化时重算
  }, [updateTableScrollY, viewMode, filteredRows.length, loading, pagination.current, pagination.pageSize]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        defaultActiveKey="list"
        className="admin-atp-params-tabs"
        tabBarExtraContent={
          canManage ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openCreate()}>
              {t("新建模板")}
            </Button>
          ) : null
        }
        items={[
          {
            key: "list",
            label: (
              <span className="admin-atp-params-tab-title">
                <FunctionOutlined /> {t("参数模板管理")}
              </span>
            ),
            closable: false,
            children: (
              <div className="admin-atp-params-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        value={tableKeywordInput}
                        onChange={(event) => setTableKeywordInput(event.currentTarget.value)}
                        placeholder={t("按模板名称/覆盖路径搜索")}
                        onPressEnter={() => handleTableSearch()}
                      />
                    </Form.Item>

                    <Form.Item label={t("层级")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Select<"own" | "inherit">
                        value={levelFilter}
                        allowClear
                        placeholder={t("全部")}
                        onChange={(value) => {
                          setLevelFilter(value);
                          setPagination((prev) => ({ ...prev, current: 1 }));
                        }}
                        options={[
                          { value: "own", label: t("本级模板") },
                          { value: "inherit", label: t("继承节点") },
                        ]}
                      />
                    </Form.Item>

                    <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                      <Button htmlType="button" icon={<SearchOutlined />} onClick={() => handleTableSearch()}  loading={loading}className="admin-search-btn">
                        {t("查询")}
                      </Button>
                    </Form.Item>

                    {hasTableFilter ? (
                      <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
                        <Button htmlType="button" onClick={() => clearFilters()}>
                          {t("清除筛选")}
                        </Button>
                      </Form.Item>
                    ) : null}

                    <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
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
                    </Form.Item>
                  </Form>
                </div>

                {filteredRows.length === 0 && !loading ? (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("未找到符合筛选条件的模板节点。")} style={{ padding: 40 }} />
                ) : viewMode === "card" ? (
                  <div className="relative flex min-h-0 flex-1 flex-col">
                    <div className="admin-atp-params-card-scroll">
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                        {filteredRows
                          .slice((pagination.current - 1) * pagination.pageSize, pagination.current * pagination.pageSize)
                          .map((row) => (
                            <TemplateCard
                              key={row.key}
                              row={row}
                              canManage={canManage}
                              onDetail={() => void openDetailDrawer(row)}
                              onEdit={() => {
                                if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => openEditor());
                              }}
                              onPreview={() => void openPreviewDrawer(row)}
                              onDerive={() => {
                                const ruleId = row.node.rule_id;
                                if (ruleId) void loadDetail(ruleId).then(() => void deriveChild());
                              }}
                              onDelete={() => {
                                if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => void removeTemplate());
                              }}
                            />
                          ))}
                      </div>
                    </div>
                    {loading ? (
                      <div className="absolute inset-0 z-10 flex items-center justify-center bg-[color-mix(in_srgb,var(--ant-color-bg-layout)_60%,transparent)]">
                        <Spin />
                      </div>
                    ) : null}
                    {filteredRows.length > 0 ? (
                      <div className="admin-power-lines-pagination">
                        <Pagination
                          current={pagination.current}
                          pageSize={pagination.pageSize}
                          total={filteredRows.length}
                          onChange={(page, pageSize) => setPagination({ current: page, pageSize })}
                          showSizeChanger
                          showTotal={(total) => `${t("共")} ${total} ${t("条")}`}
                        />
                      </div>
                    ) : null}
                  </div>
                ) : (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-atp-models-table-view"
                    style={{ "--admin-atp-models-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
                    <Table<TemplateRow>
                      rowKey="key"
                      size="small"
                      dataSource={filteredRows}
                      loading={loading}
                      columns={tableColumns}
                      tableLayout="fixed"
                      scroll={{ x: 900, y: tableScrollY }}
                      pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total: Math.max(filteredRows.length, 1),
                        hideOnSinglePage: false,
                        showSizeChanger: true,
                        pageSizeOptions: [10, 20, 50, 100],
                        showTotal: () => `${t("共")} ${filteredRows.length} ${t("条")}`,
                        // 与卡片视图独立分页组件尺寸一致（default=32px，不随 Table size=small 缩到 24px）
                        size: "default",
                        onChange: (page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        },
                      }}
                      locale={{
                        emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("未找到符合筛选条件的模板节点。")} />,
                      }}
                    />
                  </div>
                )}
              </div>
            ),
          },
        ]}
      />

      {/* ── 详情弹窗（原抽屉） ── */}
      <Modal
        open={detailOpen}
        title={detail ? `${t("模板详情")}：${detail.name}` : t("模板详情")}
        width={720}
        footer={
          detail && canManage ? (
            <Space>
              <Button icon={<PlusOutlined />} onClick={() => { setEditingForChild(true); void deriveChild(); }}>
                {t("新建细分")}
              </Button>
              <Button onClick={() => void disableTemplate()}>{detail.enabled ? t("停用") : t("启用")}</Button>
              <Button danger icon={<DeleteOutlined />} onClick={() => void removeTemplate()}>
                {t("删除")}
              </Button>
            </Space>
          ) : null
        }
        onCancel={() => setDetailOpen(false)}
        destroyOnHidden
      >
        {!detail ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin />
          </div>
        ) : (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={`${detail.name}${detail.enabled ? "" : t("（已停用）")} · ${t("特异性")} ${detail.specificity} · ${t("优先级")} ${detail.priority} · ${
                detail.mode === "replace" ? t("整块替换") : t("逐槽位合并")
              }${detail.fallback_to ? ` · ${t("wine 回退")} → ${detail.fallback_to}` : ""}`}
            />
            <Card size="small" title={`${t("槽位定义")}（${detail.defined_slots} ${t("个")}）`}>
              <Table
                size="small"
                rowKey="slot"
                pagination={false}
                scroll={{ y: 300 }}
                columns={slotColumns}
                dataSource={Object.entries(detail.slots ?? {}).map(([slot, spec]) => ({
                  key: slot,
                  slot,
                  expr: spec.expr ?? "",
                  fmt: spec.fmt ?? 2,
                  enabled: spec.enabled !== false,
                  value: spec.value ?? undefined,
                  when: spec.when ?? undefined,
                  param: spec.param ?? undefined,
                }))}
              />
              <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                {t("更新于")} {detail.updated_at ? new Date(detail.updated_at).toLocaleString() : "-"}
                {detail.updated_by ? ` · ${detail.updated_by}` : ""}
              </Text>
            </Card>
          </Space>
        )}
      </Modal>

      {/* ── 试算抽屉 ── */}
      <Drawer
        open={previewOpen}
        title={detail ? `${t("试算预览")}：${detail.name}` : t("试算预览")}
        width={720}
        onClose={() => setPreviewOpen(false)}
        destroyOnClose
        extra={
          <Button type="primary" ghost onClick={() => void runPreview()}>
            {t("试算")}
          </Button>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Select
              style={{ width: 190 }}
              placeholder={t("杆塔类型")}
              allowClear
              value={previewCtx.tower_type}
              options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, tower_type: value }))}
            />
            <Select
              style={{ width: 130 }}
              placeholder={t("电压等级")}
              allowClear
              value={previewCtx.voltage_level}
              options={(meta?.voltages ?? []).map((item) => ({ value: item, label: `${item}kV` }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, voltage_level: value }))}
            />
            <Select
              style={{ width: 130 }}
              placeholder={t("回路数量")}
              allowClear
              value={previewCtx.circuit_count}
              options={[1, 2, 4].map((item) => ({ value: item, label: `${item} ${t("回")}` }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, circuit_count: value }))}
            />
            <Select
              style={{ width: 150 }}
              placeholder={t("场景")}
              allowClear
              value={previewCtx.scene_type}
              options={(meta?.scene_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, scene_type: value }))}
            />
            <Select
              style={{ width: 170 }}
              placeholder={t("避雷器组合")}
              allowClear
              value={previewCtx.arrester_config}
              options={(meta?.arrester_configs ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, arrester_config: value }))}
            />
          </Space>
          {preview ? (
            <>
              <div>
                <Text type="secondary">{t("命中链（粗 → 细）：")}</Text>{" "}
                {preview.chain.map((item, index) => (
                  <Tag key={item} color={index === preview.chain.length - 1 ? "blue" : "default"}>
                    {item}
                  </Tag>
                ))}
                {preview.diff.length ? <Tag color="red">{t("本层定义/覆盖")} {preview.diff.length} {t("个槽位")}</Tag> : null}
              </div>
              <Table size="small" rowKey="slot" pagination={false} scroll={{ y: 300 }} columns={previewColumns} dataSource={preview.slots} />
            </>
          ) : (
            <Text type="secondary">{t("选择上下文后点击「试算」，会显示命中链、每个槽位的最终值与来源、以及被本层覆盖的槽位。")}</Text>
          )}
        </Space>
      </Drawer>

      {/* ── 编辑 / 新建 / 新建细分弹窗 ── */}
      <Modal
        open={editing}
        title={editingForChild ? t("新建细分模板") : detail ? `${t("编辑")}：${detail.name}` : t("新建模板")}
        width={880}
        onCancel={() => setEditing(false)}
        onOk={() => void saveEditor()}
        okText={t("保存并生效")}
      >
        <Form form={form} layout="vertical">
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="name" label={t("名称")} rules={[{ required: true }]} tooltip={t("模板名称，如：猫头型 · 220kV")}>
                <Input placeholder={t("如：猫头型 · 220kV")} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tower_type" label={t("杆塔类型")} tooltip={t("匹配条件；留空 = 通配所有塔型")}>
                <Select
                  allowClear
                  placeholder={t("选择杆塔类型")}
                  options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
                  onChange={() => void refreshSlotOptions()}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="voltage_level" label={t("电压等级")} tooltip={t("匹配条件；留空 = 通配所有电压等级")}>
                <Select allowClear placeholder={t("选择电压等级")} options={(meta?.voltages ?? []).map((item) => ({ value: item, label: `${item}kV` }))} onChange={() => void refreshSlotOptions()} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="circuit_count" label={t("回路数量")} tooltip={t("匹配条件；留空 = 通配")}>
                <Select allowClear placeholder={t("选择回路数量")} options={[1, 2, 4].map((item) => ({ value: item, label: `${item} ${t("回")}` }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="scene_type" label={t("场景")} tooltip={t("匹配条件；留空 = 通配")}>
                <Select allowClear placeholder={t("选择场景")} options={(meta?.scene_types ?? []).map((item) => ({ value: item.value, label: item.label }))} onChange={() => void refreshSlotOptions()} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="arrester_config" label={t("避雷器组合")} tooltip={t("匹配条件；留空 = 通配")}>
                <Select allowClear placeholder={t("选择避雷器组合")} options={(meta?.arrester_configs ?? []).map((item) => ({ value: item.value, label: item.label }))} onChange={() => void refreshSlotOptions()} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="priority" label={t("优先级")} initialValue={100} tooltip={t("数字越小越优先；条件越细的模板优先级更高，此值用于同级兜底排序")} rules={[{ type: "number", min: 0, max: 10000, message: t("优先级须在 0~10000 之间") }]}>
                <InputNumber style={{ width: "100%" }} min={0} max={9999} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="mode" label={t("合并方式")} initialValue="merge" tooltip={t("逐槽位合并：只覆盖填了的槽位，未填继承上层；整块替换：整套槽位用自己的")}>
                <Select
                  options={[
                    { value: "merge", label: t("逐槽位合并") },
                    { value: "replace", label: t("整块替换") },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="fallback_to" label={t("wine 回退到")} tooltip={t("槽位公式算不出来时回退到哪个塔型的模板继续算；留空 = 不回退")}>
                <Select allowClear placeholder={t("选择回退塔型")} options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="fallback_enabled" label={t("启用回退")} valuePropName="checked" initialValue={true} tooltip={t("回退行为的总开关")}>
                <Switch />
              </Form.Item>
            </Col>
          </Row>
        </Form>

        <Table
          size="small"
          rowKey="key"
          pagination={false}
          dataSource={slotRows}
          columns={[
            {
              title: t("槽位"),
              dataIndex: "slot",
              width: 130,
              render: (value: string, row: SlotRow) => (
                <Select
                  showSearch
                  style={{ width: 120 }}
                  loading={slotOptionsLoading}
                  value={value || undefined}
                  options={(slotOptions.length > 0 ? slotOptions : meta?.slot_names ?? []).map((item) => ({ value: item, label: item }))}
                  onChange={(next) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, slot: next, key: next } : item)))}
                />
              ),
            },
            {
              title: t("参数引用（可选）"),
              dataIndex: "param",
              width: 180,
              render: (value: string | undefined, row: SlotRow) => (
                <Select
                  showSearch
                  allowClear
                  style={{ width: 160 }}
                  value={value || undefined}
                  placeholder={t("选注册表参数（ATP计算参数管理）")}
                  options={paramCodes.map((item) => ({ value: item, label: item }))}
                  onChange={(next) =>
                    setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, param: next, expr: next ? "" : item.expr, value: next ? "" : item.value } : item)))
                  }
                />
              ),
            },
            {
              title: t("表达式（或字面量）"),
              dataIndex: "expr",
              render: (value: string, row: SlotRow) => (
                <Input
                  value={value}
                  disabled={!!row.param}
                  placeholder={row.param ? t("已选参数引用") : t("如：abs(h_u - insul_m - v(10/3,1.5,10/3,14/3,14/3,8,14/3,0))")}
                  onChange={(event) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, expr: event.target.value } : item)))}
                />
              ),
            },
            {
              title: t("引用参数"),
              key: "edit_ref_params",
              width: 190,
              render: (_, row: SlotRow) => {
                // 从表达式（或已选参数引用）里按词边界匹配注册表参数 code
                const source = row.param || row.expr || "";
                if (!source) return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
                const refs = Object.values(paramSources).filter((ref) => {
                  if (!ref.code) return false;
                  const re = new RegExp(`\\b${ref.code}\\b`);
                  return re.test(source);
                });
                if (refs.length === 0) return <Text type="secondary" style={{ fontSize: 12 }}>—</Text>;
                return (
                  <Space size={4} wrap>
                    {refs.map((ref) => (
                      <Tooltip
                        key={ref.code}
                        title={
                          ref.source_type === "line_binding"
                            ? `${t("线路导入绑定")}：${ref.via}`
                            : ref.source_type === "script"
                              ? `${ref.name}（${t("脚本计算")}：${ref.via}）`
                              : `${t("字面量")}：${ref.via}`
                        }
                      >
                        <Tag color={ref.source_type === "line_binding" ? "geekblue" : "purple"} style={{ marginInlineEnd: 0 }}>
                          {ref.code}
                        </Tag>
                      </Tooltip>
                    ))}
                  </Space>
                );
              },
            },
            {
              title: t("格式"),
              dataIndex: "fmt",
              width: 90,
              render: (value: number, row: SlotRow) => (
                <InputNumber
                  min={0}
                  max={10}
                  value={value}
                  onChange={(next) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, fmt: Number(next ?? 2) } : item)))}
                />
              ),
            },
            {
              title: t("启用"),
              dataIndex: "enabled",
              width: 70,
              render: (value: boolean, row: SlotRow) => (
                <Switch
                  checked={value}
                  onChange={(next) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, enabled: next } : item)))}
                />
              ),
            },
          ]}
          footer={() => (
            <Space>
              <Button
                size="small"
                icon={<PlusOutlined />}
                onClick={() =>
                  setSlotRows((rows) => [...rows, { key: `new-${rows.length}-${Date.now()}`, slot: "", expr: "", fmt: 2, enabled: true }])
                }
              >
                {t("添加槽位")}
              </Button>
              <Tooltip title={t("保存时后端会做表达式语法与变量校验")}>
                <Text type="secondary">{t("仅需填写与上层不同的槽位")}</Text>
              </Tooltip>
            </Space>
          )}
        />

      </Modal>
    </div>
  );
}