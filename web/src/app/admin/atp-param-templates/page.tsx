"use client";

// ATP 参数模板管理页。
// 布局严格参照「菜单管理」页:左侧模板树(可搜索/可拖拽调宽) + 右侧模板节点表格;
// 原「选中节点详情 + 试算预览」改为表格操作列的「详情 / 试算」按钮,点击用抽屉打开。
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Drawer,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Tree,
  Typography,
} from "antd";
import type { DataNode } from "antd/es/tree";
import type { ColumnsType } from "antd/es/table";
import {
  DeleteOutlined,
  ExperimentOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

type TreeNodeData = {
  key: string;
  label: string;
  node_type: "global" | "group" | "rule";
  dimension: string | null;
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
  slots: Record<string, { expr?: string; value?: string; fmt?: number; enabled?: boolean; when?: string; else?: string }>;
  defaults?: Record<string, string | number>;
  updated_at: string | null;
  updated_by: string | null;
};

type DefaultRow = { key: string; name: string; value: string };
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

type SlotRow = { key: string; slot: string; expr: string; fmt: number; enabled: boolean; value?: string; when?: string };

const { Text, Title } = Typography;

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

export default function AtpParamTemplatesPage() {
  const { message } = App.useApp();
  const { fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("atp.manage");
  const [keyword, setKeyword] = useState("");
  const [tree, setTree] = useState<TreeResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [meta, setMeta] = useState<MetaResponse | null>(null);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewCtx, setPreviewCtx] = useState<{ tower_type?: string; voltage_level?: string; circuit_count?: number; scene_type?: string; arrester_config?: string }>({});
  const [editing, setEditing] = useState(false);
  const [editingForChild, setEditingForChild] = useState(false);
  const [slotRows, setSlotRows] = useState<SlotRow[]>([]);
  const [defaultRows, setDefaultRows] = useState<DefaultRow[]>([]);
  const [form] = Form.useForm();

  // 抽屉状态
  const [detailOpen, setDetailOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  // 左侧树宽度(参照菜单页:可拖拽调宽)
  const [leftPanelWidth, setLeftPanelWidth] = useState(300);
  const containerRef = useRef<HTMLDivElement>(null);
  const isResizing = useRef(false);

  const loadTree = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/param-templates/tree${keyword ? `?keyword=${encodeURIComponent(keyword)}` : ""}`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data: TreeResponse = await response.json();
      setTree(data);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "加载模板树失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, message]);

  const loadMeta = useCallback(async () => {
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-templates/meta");
      if (!response.ok) return;
      setMeta((await response.json()) as MetaResponse);
    } catch {
      // meta 加载失败不阻塞页面
    }
  }, []);

  useEffect(() => {
    void loadTree();
    void loadMeta();
  }, [loadTree, loadMeta]);

  const nodeMap = useMemo(() => {
    const map = new Map<string, TreeNodeData>();
    const walk = (node: TreeNodeData) => {
      map.set(node.key, node);
      node.children?.forEach(walk);
    };
    if (tree?.root) walk(tree.root);
    return map;
  }, [tree]);

  const selectedNode = nodeMap.get(selectedKey) ?? null;

  const loadDetail = useCallback(
    async (ruleId: string) => {
      try {
        const response = await fetchWithAuth(`/api/v1/atp/param-templates/${ruleId}`);
        if (!response.ok) throw new Error(await readApiError(response));
        setDetail((await response.json()) as TemplateDetail);
      } catch (error) {
        message.error(error instanceof Error ? error.message : "加载模板失败");
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
      message.error(error instanceof Error ? error.message : "试算失败");
    }
  }, [previewCtx, detail?.id, message]);

  const onSelect = (keys: React.Key[]) => {
    const key = String(keys[0] ?? "");
    setSelectedKey(key);
    const node = nodeMap.get(key);
    if (node?.rule_id) {
      void loadDetail(node.rule_id);
    } else {
      setDetail(null);
      setPreview(null);
    }
  };

  // 打开详情抽屉:先加载模板数据再开
  const openDetailDrawer = async (row: TemplateRow) => {
    if (!row.node.rule_id) {
      message.info(row.node.has_template ? "该节点是继承节点,没有独立模板" : "该层为分组节点");
      return;
    }
    setSelectedKey(row.key);
    await loadDetail(row.node.rule_id);
    setDetailOpen(true);
  };

  // 打开试算抽屉:沿用当前选中模板上下文
  const openPreviewDrawer = async (row: TemplateRow) => {
    if (!row.node.rule_id) {
      message.info("该节点没有独立模板,请选择一个有模板的节点试算");
      return;
    }
    setSelectedKey(row.key);
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
      message.success(detail.enabled ? "已停用" : "已启用");
      await loadTree();
      if (detail.id) void loadDetail(detail.id);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "操作失败");
    }
  };

  const removeTemplate = async () => {
    if (!detail) return;
    Modal.confirm({
      title: `确认删除模板「${detail.name}」？`,
      content: "删除后该节点将回退到上层继承,不可恢复。",
      okText: "删除",
      okButtonProps: { danger: true },
      cancelText: "取消",
      onOk: async () => {
        try {
          const response = await fetchWithAuth(`/api/v1/atp/param-templates/${detail.id}`, { method: "DELETE" });
          if (!response.ok) throw new Error(await readApiError(response));
          message.success("已删除");
          setDetail(null);
          setDetailOpen(false);
          setPreview(null);
          await loadTree();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除失败");
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
      message.error(error instanceof Error ? error.message : "派生失败");
    }
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
        })),
      );
      setDefaultRows(
        Object.entries(detail.defaults ?? {}).map(([name, value]) => ({
          key: name,
          name,
          value: String(value),
        })),
      );
    }
    if (inherited) {
      form.setFieldsValue({ fallback_enabled: true, priority: 100 });
    }
    setEditing(true);
  };

  const saveEditor = async () => {
    try {
      const values = await form.validateFields();
      const slots: Record<string, unknown> = {};
      slotRows.forEach((row) => {
        if (!row.slot) return;
        const spec: Record<string, unknown> = { fmt: row.fmt, enabled: row.enabled };
        if (row.value) spec.value = row.value;
        else spec.expr = row.expr;
        if (row.when) spec.when = row.when;
        slots[row.slot] = spec;
      });
      const defaults: Record<string, number | string> = {};
      defaultRows.forEach((row) => {
        const name = row.name.trim();
        const raw = row.value.trim();
        if (!name || !raw) return;
        const numeric = Number(raw);
        defaults[name] = Number.isFinite(numeric) && /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(raw) ? numeric : raw;
      });
      const payload = { ...values, slots, defaults };
      const url = detail && !editingForChild ? `/api/v1/atp/param-templates/${detail.id}` : "/api/v1/atp/param-templates";
      const method = detail && !editingForChild ? "PUT" : "POST";
      const response = await fetchWithAuth(url, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success("已保存（保存即生效）");
      setEditing(false);
      setEditingForChild(false);
      await loadTree();
      const saved: TemplateDetail = await response.json();
      if (saved?.id) void loadDetail(saved.id);
    } catch (error) {
      if (error instanceof Error && error.message) message.error(error.message);
    }
  };

  const treeData = useMemo(() => {
    const convert = (node: TreeNodeData): DataNode => {
      const badge =
        node.node_type === "global" ? null : node.has_template ? (
          <Tag color="blue" style={{ marginInlineStart: 6 }}>
            {node.defined_slots}/{node.effective_slots}
          </Tag>
        ) : (
          <Tag style={{ marginInlineStart: 6 }}>继承</Tag>
        );
      const dot = node.node_type === "rule" && node.has_template ? "●" : node.node_type === "group" && node.children.length ? "" : "○";
      return {
        key: node.key,
        title: (
          <span>
            <span style={{ opacity: node.has_template || node.node_type === "global" ? 1 : 0.55, marginInlineEnd: 4 }}>{dot}</span>
            {node.label}
            {badge}
          </span>
        ),
        children: node.children.map(convert),
      };
    };
    return tree ? [convert(tree.root)] : [];
  }, [tree]);

  // 表格数据:树节点平铺(rule/has_template 节点)
  const templateRows = useMemo(() => (tree?.root ? flattenRules(tree.root, [], []) : []), [tree]);
  const filteredRows = useMemo(() => {
    if (!selectedKey) return templateRows;
    // 树点击:只显示选中节点及其子节点的模板
    return templateRows.filter((row) => row.ancestors.includes(selectedKey) || row.key === selectedKey);
  }, [templateRows, selectedKey]);

  const slotColumns: ColumnsType<SlotRow> = [
    { title: "槽位", dataIndex: "slot", width: 130, render: (v) => <Text code>{v}</Text> },
    { title: "表达式 / 值", dataIndex: "expr", render: (v, row) => (row.value ? <Text type="secondary">字面量 {row.value}</Text> : <Text>{v}</Text>) },
    { title: "格式", dataIndex: "fmt", width: 70, render: (v) => `${v} 位` },
    { title: "启用", dataIndex: "enabled", width: 70, render: (v) => (v ? <Tag color="green">启用</Tag> : <Tag>关闭</Tag>) },
    {
      title: "",
      width: 60,
      render: (_, row) => (
        <Button type="link" danger size="small" onClick={() => setSlotRows((rows) => rows.filter((item) => item.key !== row.key))}>
          删除
        </Button>
      ),
    },
  ];

  const previewColumns: ColumnsType<ResolvedSlot> = [
    { title: "槽位", dataIndex: "slot", width: 130, render: (v) => <Text code>{v}</Text> },
    { title: "值", dataIndex: "value", width: 110 },
    {
      title: "来源",
      dataIndex: "source",
      render: (v, row) => (row.inherited ? <Tag color="orange">继承 · {v}</Tag> : <Tag color="blue">本级 · {v}</Tag>),
    },
    {
      title: "",
      width: 70,
      render: (_, row) => (preview?.diff.some((item) => item.slot === row.slot) ? <Tag color="red">差异</Tag> : null),
    },
  ];

  const tableColumns: ColumnsType<TemplateRow> = [
    {
      title: "模板名称",
      dataIndex: ["node", "label"],
      render: (_v, row) => (
        <Space size={6}>
          <span>{row.node.label}</span>
          {row.node.status === "inherit" ? <Tag>继承</Tag> : <Tag color="blue">本级</Tag>}
        </Space>
      ),
    },
    {
      title: "覆盖路径",
      dataIndex: "pathLabel",
      width: 260,
      render: (v: string) => <Text type="secondary" style={{ fontSize: 12 }}>{v}</Text>,
    },
    {
      title: "槽位",
      key: "slots",
      width: 100,
      render: (_v, row) =>
        row.node.has_template ? (
          <span>
            {row.node.defined_slots}/{row.node.effective_slots}
          </span>
        ) : (
          <Text type="secondary">继承</Text>
        ),
    },
    {
      title: "状态",
      key: "status",
      width: 100,
      render: (_v, row) => {
        if (!row.node.has_template) return <Tag>继承</Tag>;
        // 模板启用状态以 detail 为准;表格里统一显示「本级/继承」+ 槽位
        return row.node.status === "own" ? <Tag color="blue">本级</Tag> : <Tag color="orange">继承</Tag>;
      },
    },
    {
      title: "操作",
      key: "actions",
      fixed: "right",
      width: 240,
      render: (_v, row) => (
        <Space wrap size={4}>
          <Button size="small" icon={<EyeOutlined />} disabled={!row.node.rule_id} onClick={() => void openDetailDrawer(row)}>
            详情
          </Button>
          <Button size="small" icon={<ExperimentOutlined />} disabled={!row.node.rule_id} onClick={() => void openPreviewDrawer(row)}>
            试算
          </Button>
          {canManage ? (
            <>
              <Button
                size="small"
                disabled={!row.node.rule_id}
                onClick={() => {
                  setSelectedKey(row.key);
                  if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => openEditor());
                }}
              >
                编辑
              </Button>
              {row.node.rule_id ? (
                <Button
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => {
                    setSelectedKey(row.key);
                    const ruleId = row.node.rule_id;
                    if (ruleId) void loadDetail(ruleId).then(() => void deriveChild());
                  }}
                >
                  细分
                </Button>
              ) : null}
              <Button
                size="small"
                danger
                disabled={!row.node.rule_id}
                onClick={() => {
                  setSelectedKey(row.key);
                  if (row.node.rule_id) void loadDetail(row.node.rule_id).then(() => void removeTemplate());
                }}
              >
                删除
              </Button>
            </>
          ) : null}
        </Space>
      ),
    },
  ];

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isResizing.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!isResizing.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      setLeftPanelWidth(Math.max(180, Math.min(600, e.clientX - rect.left)));
    };
    const handleMouseUp = () => {
      if (isResizing.current) {
        isResizing.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  return (
    <div className="admin_menus_list_pane">
      <div ref={containerRef} className="admin-menus-page-body">
        {/* 左侧:模板树(参照菜单管理页) */}
        <div style={{ width: leftPanelWidth, minWidth: 180, maxWidth: 600, flexShrink: 0, display: "flex" }}>
          <Card
            className="admin-menus-tree-card"
            style={{ height: "100%", width: "100%", display: "flex", flexDirection: "column" }}
            styles={{ body: { flex: 1, padding: 0 } }}
          >
            <div className="admin-menus-sider-search">
              <Input
                className="admin-menus-search-input"
                placeholder="搜索模板..."
                prefix={<SearchOutlined />}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                onPressEnter={() => void loadTree()}
                allowClear
              />
            </div>
            <div className="admin-menus-sider-menu">
              <Spin spinning={loading}>
                {treeData.length ? (
                  <Tree
                    showLine
                    defaultExpandAll
                    selectedKeys={selectedKey ? [selectedKey] : []}
                    onSelect={onSelect}
                    treeData={treeData}
                  />
                ) : (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无参数模板" />
                )}
              </Spin>
            </div>
          </Card>
        </div>
        <div className="admin-menus-resize-handle" onMouseDown={handleResizeStart}>
          <div className="admin-menus-resize-handle-line" />
        </div>

        {/* 右侧:模板节点表格 */}
        <div className="admin-menus-main">
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item style={{ marginBottom: 0 }}>
                <Button icon={<ReloadOutlined />} onClick={() => void loadTree()}>
                  刷新
                </Button>
              </Form.Item>
              {selectedKey ? (
                <Form.Item style={{ marginBottom: 0 }}>
                  <Button onClick={() => setSelectedKey("")}>清除筛选</Button>
                </Form.Item>
              ) : null}
              <Form.Item style={{ marginBottom: 0 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  共 {filteredRows.length} 个模板节点{selectedKey ? `(筛选自 ${templateRows.length})` : ""}
                </Text>
              </Form.Item>
            </Form>
          </div>
          <div
            className="admin-menus-table-anchor"
            style={{ "--admin-menus-table-body-min-height": "320px" } as React.CSSProperties}
          >
            <Table<TemplateRow>
              rowKey="key"
              size="small"
              dataSource={filteredRows}
              loading={loading}
              columns={tableColumns}
              tableLayout="fixed"
              scroll={{ x: 900 }}
              pagination={{
                pageSize: 20,
                showSizeChanger: true,
                pageSizeOptions: [10, 20, 50, 100],
                showTotal: () => `共 ${filteredRows.length} 条`,
                hideOnSinglePage: false,
                style: { marginBottom: 0 },
              }}
              locale={{
                emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到符合筛选条件的模板节点。" />,
              }}
            />
          </div>
        </div>
      </div>

      {/* ── 详情抽屉 ── */}
      <Drawer
        open={detailOpen}
        title={detail ? `模板详情：${detail.name}` : "模板详情"}
        width={680}
        onClose={() => setDetailOpen(false)}
        destroyOnClose
        extra={
          detail && canManage ? (
            <Space>
              <Button icon={<PlusOutlined />} onClick={() => { setEditingForChild(true); void deriveChild(); }}>
                新建细分
              </Button>
              <Button onClick={() => void disableTemplate()}>{detail.enabled ? "停用" : "启用"}</Button>
              <Button danger icon={<DeleteOutlined />} onClick={() => void removeTemplate()}>
                删除
              </Button>
            </Space>
          ) : null
        }
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
              message={`${detail.name}${detail.enabled ? "" : "（已停用）"} · 特异性 ${detail.specificity} · 优先级 ${detail.priority} · ${
                detail.mode === "replace" ? "整块替换" : "逐槽位合并"
              }${detail.fallback_to ? ` · wine 回退 → ${detail.fallback_to}` : ""}`}
            />
            <Card size="small" title={`槽位定义（${detail.defined_slots} 个）`}>
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
                }))}
              />
              <Text type="secondary" style={{ display: "block", marginTop: 8 }}>
                {detail.defined_defaults ?? 0} 个测试默认值；更新于 {detail.updated_at ? new Date(detail.updated_at).toLocaleString() : "-"}
                {detail.updated_by ? ` · ${detail.updated_by}` : ""}
              </Text>
            </Card>
            {detail.defaults && Object.keys(detail.defaults).length > 0 ? (
              <Card size="small" title="测试默认值">
                <Table
                  size="small"
                  rowKey="name"
                  pagination={false}
                  dataSource={Object.entries(detail.defaults).map(([name, value]) => ({ key: name, name, value: String(value) }))}
                  columns={[
                    { title: "变量名", dataIndex: "name", width: 200 },
                    { title: "默认值", dataIndex: "value" },
                  ]}
                />
              </Card>
            ) : null}
          </Space>
        )}
      </Drawer>

      {/* ── 试算抽屉 ── */}
      <Drawer
        open={previewOpen}
        title={detail ? `试算预览：${detail.name}` : "试算预览"}
        width={720}
        onClose={() => setPreviewOpen(false)}
        destroyOnClose
        extra={
          <Button type="primary" ghost onClick={() => void runPreview()}>
            试算
          </Button>
        }
      >
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Space wrap>
            <Select
              style={{ width: 190 }}
              placeholder="杆塔类型"
              allowClear
              value={previewCtx.tower_type}
              options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, tower_type: value }))}
            />
            <Select
              style={{ width: 130 }}
              placeholder="电压等级"
              allowClear
              value={previewCtx.voltage_level}
              options={(meta?.voltages ?? []).map((item) => ({ value: item, label: `${item}kV` }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, voltage_level: value }))}
            />
            <Select
              style={{ width: 130 }}
              placeholder="回路数量"
              allowClear
              value={previewCtx.circuit_count}
              options={[1, 2, 4].map((item) => ({ value: item, label: `${item} 回` }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, circuit_count: value }))}
            />
            <Select
              style={{ width: 150 }}
              placeholder="场景"
              allowClear
              value={previewCtx.scene_type}
              options={(meta?.scene_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, scene_type: value }))}
            />
            <Select
              style={{ width: 170 }}
              placeholder="避雷器组合"
              allowClear
              value={previewCtx.arrester_config}
              options={(meta?.arrester_configs ?? []).map((item) => ({ value: item.value, label: item.label }))}
              onChange={(value) => setPreviewCtx((ctx) => ({ ...ctx, arrester_config: value }))}
            />
          </Space>
          {preview ? (
            <>
              <div>
                <Text type="secondary">命中链（粗 → 细）：</Text>{" "}
                {preview.chain.map((item, index) => (
                  <Tag key={item} color={index === preview.chain.length - 1 ? "blue" : "default"}>
                    {item}
                  </Tag>
                ))}
                {preview.diff.length ? <Tag color="red">本层定义/覆盖 {preview.diff.length} 个槽位</Tag> : null}
              </div>
              <Table size="small" rowKey="slot" pagination={false} scroll={{ y: 300 }} columns={previewColumns} dataSource={preview.slots} />
            </>
          ) : (
            <Text type="secondary">选择上下文后点击「试算」，会显示命中链、每个槽位的最终值与来源、以及被本层覆盖的槽位。</Text>
          )}
        </Space>
      </Drawer>

      {/* ── 编辑 / 新建细分弹窗(保留原逻辑) ── */}
      <Modal
        open={editing}
        title={editingForChild || !detail ? "新建细分模板" : `编辑：${detail.name}`}
        width={880}
        onCancel={() => setEditing(false)}
        onOk={() => void saveEditor()}
        okText="保存并生效"
      >
        <Form form={form} layout="vertical">
          <Space wrap>
            <Form.Item name="name" label="名称" rules={[{ required: true }]} style={{ minWidth: 260 }}>
              <Input placeholder="如：猫头型 · 220kV" />
            </Form.Item>
            <Form.Item name="tower_type" label="杆塔类型">
              <Select
                style={{ width: 190 }}
                allowClear
                options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              />
            </Form.Item>
            <Form.Item name="voltage_level" label="电压等级">
              <Select style={{ width: 130 }} allowClear options={(meta?.voltages ?? []).map((item) => ({ value: item, label: `${item}kV` }))} />
            </Form.Item>
            <Form.Item name="circuit_count" label="回路数量">
              <Select style={{ width: 120 }} allowClear options={[1, 2, 4].map((item) => ({ value: item, label: `${item} 回` }))} />
            </Form.Item>
            <Form.Item name="scene_type" label="场景">
              <Select style={{ width: 140 }} allowClear options={(meta?.scene_types ?? []).map((item) => ({ value: item.value, label: item.label }))} />
            </Form.Item>
            <Form.Item name="arrester_config" label="避雷器组合">
              <Select
                style={{ width: 170 }}
                allowClear
                options={(meta?.arrester_configs ?? []).map((item) => ({ value: item.value, label: item.label }))}
              />
            </Form.Item>
            <Form.Item name="priority" label="优先级" initialValue={100}>
              <InputNumber style={{ width: 100 }} min={0} max={9999} />
            </Form.Item>
            <Form.Item name="mode" label="合并方式" initialValue="merge">
              <Select
                style={{ width: 140 }}
                options={[
                  { value: "merge", label: "逐槽位合并" },
                  { value: "replace", label: "整块替换" },
                ]}
              />
            </Form.Item>
            <Form.Item name="fallback_to" label="wine 回退到">
              <Select
                style={{ width: 160 }}
                allowClear
                options={(meta?.tower_types ?? []).map((item) => ({ value: item.value, label: item.label }))}
              />
            </Form.Item>
            <Form.Item name="fallback_enabled" label="启用回退" valuePropName="checked" initialValue={true}>
              <Switch />
            </Form.Item>
          </Space>
        </Form>

        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 10 }}
          message="只填写需要覆盖的槽位；未填写的槽位自动继承上层。表达式可用变量与函数见下方示例。"
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              变量：ground_r / insul_m / shield_h / tower_h / lw_l / lw_r / h_u / h_m / h_l / sp_u / sp_m / sp_l / voltage / current_ka / head_ms / tail_ms / wave_type
              ；四回路：c1_u…c4_l、c1_sp_u…c4_sp_l
              <br />
              函数：abs(x) / sqrt(x) / min / max / round(x,n) / clamp(x,lo) / v(35,66,110,220,330,500,750,1000)
            </Text>
          }
        />

        <Table
          size="small"
          rowKey="key"
          pagination={false}
          dataSource={slotRows}
          columns={[
            {
              title: "槽位",
              dataIndex: "slot",
              width: 130,
              render: (value: string, row: SlotRow) => (
                <Select
                  showSearch
                  style={{ width: 120 }}
                  value={value || undefined}
                  options={(meta?.slot_names ?? []).map((item) => ({ value: item, label: item }))}
                  onChange={(next) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, slot: next, key: next } : item)))}
                />
              ),
            },
            {
              title: "表达式（或字面量）",
              dataIndex: "expr",
              render: (value: string, row: SlotRow) => (
                <Input
                  value={value}
                  placeholder="如：abs(h_u - insul_m - v(10/3,1.5,10/3,14/3,14/3,8,14/3,0))"
                  onChange={(event) => setSlotRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, expr: event.target.value } : item)))}
                />
              ),
            },
            {
              title: "格式",
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
              title: "启用",
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
                添加槽位
              </Button>
              <Tooltip title="保存时后端会做表达式语法与变量校验">
                <Text type="secondary">仅需填写与上层不同的槽位</Text>
              </Tooltip>
            </Space>
          )}
        />

        <Alert
          type="info"
          showIcon
          style={{ margin: "14px 0 10px" }}
          message="测试默认参数集（无杆塔测试用）"
          description={
            <Text type="secondary" style={{ fontSize: 12 }}>
              这些是「上下文变量」的默认值：ATP 模型测试时可以不给杆塔数据，直接用它们算出全套 $PARAMETER 参数（对齐 C# —— 引擎只吃一串参数，不需要杆塔）。
              <br />
              只补上下文里没有的值（有真实杆塔数据时以真实值优先）；未提供默认值的变量会让对应槽位报「未解析」，测试会拒绝执行，而不是静默算成 1. 这种无物理意义的占位值。
            </Text>
          }
        />
        <Table
          size="small"
          rowKey="key"
          pagination={false}
          dataSource={defaultRows}
          columns={[
            {
              title: "变量名",
              dataIndex: "name",
              width: 190,
              render: (value: string, row: DefaultRow) => (
                <Select
                  showSearch
                  style={{ width: 180 }}
                  value={value || undefined}
                  placeholder="如 h_u / shield_h"
                  options={(meta?.variable_names ?? []).map((item) => ({ value: item, label: item }))}
                  onChange={(next) => setDefaultRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, name: next, key: next } : item)))}
                  dropdownRender={(menu) => (
                    <>
                      {menu}
                      <Input
                        size="small"
                        style={{ marginTop: 6 }}
                        placeholder="不在列表里？直接输入变量名"
                        onPressEnter={(event) => {
                          const typed = (event.target as HTMLInputElement).value.trim();
                          if (!typed) return;
                          setDefaultRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, name: typed, key: typed } : item)));
                        }}
                      />
                    </>
                  )}
                />
              ),
            },
            {
              title: "默认值",
              dataIndex: "value",
              render: (value: string, row: DefaultRow) => (
                <Input
                  value={value}
                  placeholder="如 65.5"
                  onChange={(event) => setDefaultRows((rows) => rows.map((item) => (item.key === row.key ? { ...item, value: event.target.value } : item)))}
                />
              ),
            },
            {
              title: "",
              width: 60,
              render: (_: unknown, row: DefaultRow) => (
                <Button type="link" danger size="small" onClick={() => setDefaultRows((rows) => rows.filter((item) => item.key !== row.key))}>
                  删除
                </Button>
              ),
            },
          ]}
          footer={() => (
            <Button
              size="small"
              icon={<PlusOutlined />}
              onClick={() => setDefaultRows((rows) => [...rows, { key: `new-${rows.length}-${Date.now()}`, name: "", value: "" }])}
            >
              添加默认值
            </Button>
          )}
        />
      </Modal>
    </div>
  );
}