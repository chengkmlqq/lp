"use client";

// ATP 模型计算参数管理页（参数注册表）。
// 定义参数模板使用的那些参数：
//   · line_binding : 从线路导入的杆塔属性绑定（建立 杆塔属性路径 ↔ 参数名 关联）
//   · script       : Python 计算脚本（沙箱求值，纯数学）
//   · constant     : 字面量
// 参数目录（参数模板页 slots_json 的 {"param": code} 形态）消费本页定义；
// 参数 ↔ ATP 模型槽位的关系仍由「参数模板」映射。
import { useCallback, useEffect, useRef, useState } from "react";
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
  Pagination,
  Segmented,
  Select,
  Space,
  Spin,
  Switch,
  Table,
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
  ExperimentOutlined,
  EyeOutlined,
  FunctionOutlined,
  LinkOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";

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

type TestScriptResponse = {
  ok: boolean;
  value: unknown;
  errors: string[];
  referenced: string[];
};

type PreviewResponse = {
  items: { code: string; name: string; unit: string | null; source_type: string; value: unknown }[];
};

const SOURCE_TYPE_LABEL: Record<SourceType, string> = {
  line_binding: "线路导入绑定",
  script: "计算脚本",
  constant: "字面量",
};

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

/** 绑定 / 脚本摘要（表格列与卡片共用）。 */
function renderSourceSummary(record: DefinitionItem) {
  if (record.source_type === "line_binding") {
    const binding = record.binding_json as { runtime_key?: string; source?: string; path?: string };
    const label = binding.runtime_key
      ? `现状镜像 ${binding.runtime_key}`
      : `${binding.source ?? ""}.${binding.path ?? ""}`;
    return (
      <Tooltip title={binding.path ?? ""}>
        <Space size={4} style={{ minWidth: 0 }}>
          <LinkOutlined style={{ color: "#1677ff" }} />
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
        <CodeOutlined style={{ color: "#722ed1" }} />
        <Text
          style={{ fontSize: 12, maxWidth: 200 }}
          ellipsis={{ tooltip: record.script_code ?? "" }}
        >
          {record.script_code ? `${record.script_code.slice(0, 60)}${record.script_code.length > 60 ? "…" : ""}` : "(空脚本)"}
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
  onTest: (item: DefinitionItem) => void;
  onDetail: (item: DefinitionItem) => void;
  onDelete: (item: DefinitionItem) => void;
}

/** 参数定义卡片（严格参照线路管理 <PowerLineCard> 结构）。 */
function DefinitionCard({ item, canManage, onTest, onDetail, onDelete }: DefinitionCardProps) {
  const sourceColor = SOURCE_TYPE_COLOR[item.source_type];
  const sourceLabel = SOURCE_TYPE_LABEL[item.source_type];
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
        {item.enabled ? <Tag color="green" style={{ marginInlineEnd: 0 }}>启用</Tag> : <Tag style={{ marginInlineEnd: 0 }}>停用</Tag>}
      </div>

      <div className="flex flex-col gap-2 px-4 py-3" style={{ minHeight: 120 }}>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text code style={{ fontSize: 12 }}>{item.code}</Typography.Text>
          <Tag color={sourceColor} style={{ marginInlineEnd: 0 }}>{sourceLabel}</Tag>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            单位：{item.unit ?? "-"}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            类型：{item.data_type}
          </Typography.Text>
        </div>
        {item.description ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }} ellipsis={{ tooltip: item.description }}>
            说明：{item.description}
          </Typography.Text>
        ) : null}
        <div className="admin-atp-params-card-field admin-atp-models-card-field">{renderSourceSummary(item)}</div>
      </div>

      <div className="admin-atp-params-card-actions admin-atp-models-card-actions flex items-center justify-end gap-1 px-4 py-2">
        {canManage ? (
          <Space size={4}>
            <Tooltip title="试算（脚本）">
              <Button size="small" type="text" icon={<ExperimentOutlined />} onClick={(event) => { event.stopPropagation(); onTest(item); }} />
            </Tooltip>
            <Tooltip title="详情">
              <Button size="small" type="text" icon={<EyeOutlined />} onClick={(event) => { event.stopPropagation(); onDetail(item); }} />
            </Tooltip>
            <Tooltip title="删除">
              <Button size="small" type="text" danger icon={<DeleteOutlined />} onClick={(event) => { event.stopPropagation(); onDelete(item); }} />
            </Tooltip>
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
  const { message, modal } = App.useApp();
  const { fetchWithAuth, hasPermission } = useAuth();
  const canManage = hasPermission("atp.manage");

  const [list, setList] = useState<DefinitionItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [filterSource, setFilterSource] = useState<SourceType | undefined>(undefined);
  const [keyword, setKeyword] = useState("");
  const [fieldsMeta, setFieldsMeta] = useState<FieldsResponse | null>(null);
  // 卡片 / 列表双视图（严格参照线路管理 power-lines 的切换模式；默认卡片视图）
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });

  const [detail, setDetail] = useState<DefinitionItem | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [preview, setPreview] = useState<PreviewResponse | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);

  const [editing, setEditing] = useState<DefinitionItem | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [form] = Form.useForm();
  const [scriptTest, setScriptTest] = useState<TestScriptResponse | null>(null);
  const [scriptTesting, setScriptTesting] = useState(false);

  const isMobile = useMobileDetection();

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
      message.error(error instanceof Error ? error.message : "加载参数列表失败");
    } finally {
      setLoading(false);
    }
  }, [keyword, filterSource, message]);

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
    setScriptTest(null);
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
  const watchScript = Form.useWatch("script_code", form);
  const watchDeps = Form.useWatch("deps_json", form);

  const runScriptTest = async () => {
    const script = String(form.getFieldValue("script_code") ?? "");
    const deps = (form.getFieldValue("deps_json") ?? []) as string[];
    if (!script.trim()) {
      message.warning("请先填写脚本内容");
      return;
    }
    setScriptTesting(true);
    setScriptTest(null);
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-definitions/test-script", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script_code: script,
          deps_json: deps,
          profile: {
            tower_kind: "ganzi",
            shield_wire_height_m: 73.5,
            insulator_length_m: 5945,
            call_height_m: 42.0,
            current_type: 1,
            angle_deg: 10.0,
            geometry_layers_json: {
              I: {
                phase_height_m: { upper: 65.5, middle: 53.0, lower: 42.0 },
                phase_spacing_m: { upper: 12.0, middle: 12.0, lower: 12.0 },
              },
              lightning_wire: { left_mid_distance_m: 12.4, right_mid_distance_m: 12.4, height_m: 73.5 },
            },
          },
          base_tower: {
            tower_type: "ganzi",
            line_voltage_kv: 220.0,
            ground_resistance_ohm: 10.0,
            circuit_geometry_json: {
              tower_height_m: 42.0,
              lightning_wire: { left_mid_distance_m: 12.4, right_mid_distance_m: 12.4, height_m: 73.5 },
            },
          },
          execution_options: { binary_search_current_ka: 146.0, tower_kind: "ganzi" },
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setScriptTest((await response.json()) as TestScriptResponse);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "脚测试算失败");
    } finally {
      setScriptTesting(false);
    }
  };

  const saveDefinition = async () => {
    try {
      const values = await form.validateFields();
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
        if (!binding.runtime_key && (!binding.source || !binding.path)) {
          message.warning("线路导入绑定需要选择「来源 + 字段路径」");
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
      message.success(editing ? "已保存" : "已创建");
      setEditOpen(false);
      await loadList();
    } catch (error) {
      if (error instanceof Error && "errorFields" in error) return; // 表单校验失败由表单提示
      message.error(error instanceof Error ? error.message : "保存失败");
    }
  };

  const removeDefinition = (item: DefinitionItem) => {
    modal.confirm({
      title: `删除参数 ${item.code}？`,
      content: "删除后参数模板若有引用将无法解析（保存时已拦截被引用的删除）。",
      okText: "删除",
      okButtonProps: { danger: true },
      async onOk() {
        try {
          const response = await fetchWithAuth(`/api/v1/atp/param-definitions/${item.id}`, { method: "DELETE" });
          if (!response.ok) throw new Error(await readApiError(response));
          message.success("已删除");
          await loadList();
        } catch (error) {
          message.error(error instanceof Error ? error.message : "删除失败");
        }
      },
    });
  };

  const openPreview = async () => {
    setPreviewOpen(true);
    setPreview(null);
    setPreviewLoading(true);
    try {
      const response = await fetchWithAuth("/api/v1/atp/param-definitions/resolve-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          codes: [],
          profile: {
            tower_kind: "ganzi",
            shield_wire_height_m: 73.5,
            insulator_length_m: 5945,
            call_height_m: 42.0,
            current_type: 1,
            angle_deg: 10.0,
            geometry_layers_json: {
              I: {
                phase_height_m: { upper: 65.5, middle: 53.0, lower: 42.0 },
                phase_spacing_m: { upper: 12.0, middle: 12.0, lower: 12.0 },
              },
              lightning_wire: { left_mid_distance_m: 12.4, right_mid_distance_m: 12.4, height_m: 73.5 },
            },
          },
          base_tower: {
            tower_type: "ganzi",
            line_voltage_kv: 220.0,
            ground_resistance_ohm: 10.0,
            circuit_geometry_json: {
              tower_height_m: 42.0,
              lightning_wire: { left_mid_distance_m: 12.4, right_mid_distance_m: 12.4, height_m: 73.5 },
            },
          },
          execution_options: { binary_search_current_ka: 146.0, tower_kind: "ganzi" },
        }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      setPreview((await response.json()) as PreviewResponse);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "预览解析失败");
    } finally {
      setPreviewLoading(false);
    }
  };

  const depsOptions = (list ?? [])
    .filter((item) => item.enabled)
    .map((item) => ({ value: item.code, label: `${item.code}（${item.name}）` }));

  const bindingSourceOptions = fieldsMeta?.source_options ?? [];
  const bindingFieldOptions = (fieldsMeta?.fields ?? []).map((field) => ({
    value: field.value,
    label: `${field.label}【${field.source}】`,
    source: field.source,
  }));

  const columns: ColumnsType<DefinitionItem> = [
    {
      title: "参数 code",
      dataIndex: "code",
      width: 150,
      fixed: "left",
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    {
      title: "名称",
      dataIndex: "name",
      width: 160,
      render: (value: string, record) => (
        <Space size={4}>
          <Text>{value}</Text>
          {record.unit ? <Text type="secondary" style={{ fontSize: 12 }}>（{record.unit}）</Text> : null}
        </Space>
      ),
    },
    {
      title: "来源类型",
      dataIndex: "source_type",
      width: 130,
      render: (value: SourceType, record) => (
        <Tag color={SOURCE_TYPE_COLOR[value]}>
          {SOURCE_TYPE_LABEL[value]}
          {(record.binding_json as { runtime_baseline?: boolean })?.runtime_baseline ? "（运行期基线）" : ""}
        </Tag>
      ),
    },
    {
      title: "绑定 / 脚本",
      dataIndex: "source_type",
      width: 260,
      render: (_, record) => renderSourceSummary(record),
    },
    {
      title: "状态",
      dataIndex: "enabled",
      width: 80,
      render: (value: boolean) => (value ? <Tag color="green">启用</Tag> : <Tag>停用</Tag>),
    },
  ];

  if (canManage) {
    columns.push({
      title: "操作",
      key: "actions",
      width: 150,
      fixed: "right",
      align: "right",
      render: (_, record) => (
        <Space size={4}>
          <Tooltip title="试算（脚本）">
            <Button size="small" type="text" icon={<ExperimentOutlined />} onClick={() => openEdit(record)} />
          </Tooltip>
          <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => openDetail(record)} />
          <Button size="small" type="text" icon={<DeleteOutlined />} danger onClick={() => removeDefinition(record)} />
        </Space>
      ),
    });
  }

  return (
    <Card
      size="small"
      className="admin-menus-card"
      styles={{ body: { padding: 0 } }}
      title={
        <Space size={8}>
          <FunctionOutlined />
          <Text strong>ATP 计算参数管理（参数注册表）</Text>
        </Space>
      }
      extra={
        <Space size={8}>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索 code/名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onPressEnter={() => void loadList()}
            style={{ width: 200 }}
          />
          <Select
            allowClear
            placeholder="来源类型"
            value={filterSource}
            onChange={(value) => setFilterSource(value as SourceType | undefined)}
            style={{ width: 140 }}
            options={[
              { value: "line_binding", label: "线路导入绑定" },
              { value: "script", label: "计算脚本" },
              { value: "constant", label: "字面量" },
            ]}
          />
          <Button icon={<ReloadOutlined />} onClick={() => void loadList()} />
          <Segmented
            value={viewMode}
            onChange={(value) => {
              setViewMode(value as "card" | "list");
              setPagination((prev) => ({ ...prev, current: 1 }));
            }}
            options={[
              { label: "卡片视图", value: "card" },
              { label: "列表视图", value: "list" },
            ]}
          />
          <Tooltip title="用样例杆塔上下文解析全部参数（与参数模板试算同口径）">
            <Button icon={<ExperimentOutlined />} onClick={() => void openPreview()}>
              试算
            </Button>
          </Tooltip>
          {canManage ? (
            <Button type="primary" icon={<PlusOutlined />} onClick={() => openEdit(null)}>
              新建参数
            </Button>
          ) : null}
        </Space>
      }
    >
      <Spin spinning={loading}>
        {list.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无参数（可先执行「系统种子」或新建）" style={{ padding: 40 }} />
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
                      onTest={openEdit}
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
              onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
            }}
            scroll={{ x: 900, y: "calc(100vh - 260px)" }}
          />
        )}
      </Spin>

      {/* 详情抽屉 */}
      <Drawer title={`参数详情 · ${detail?.code ?? ""}`} open={detailOpen} onClose={() => setDetailOpen(false)} width={520}>
        {detail ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={`${detail.name} ｜ ${SOURCE_TYPE_LABEL[detail.source_type]}`}
              description={
                detail.source_type === "line_binding"
                  ? (detail.binding_json as { source?: string; path?: string; runtime_key?: string }).runtime_key
                    ? `现状镜像：build_context 的 ${(detail.binding_json as { runtime_key?: string }).runtime_key}`
                    : `绑定：${(detail.binding_json as { source?: string }).source}.${(detail.binding_json as { path?: string }).path}`
                  : detail.source_type === "script"
                    ? "计算脚本（沙箱求值，纯数学函数）"
                    : "字面量"
              }
            />
            {(detail.binding_json as { runtime_baseline?: boolean })?.runtime_baseline ? (
              <Alert type="warning" showIcon message="运行期基线脚本" description="执行仍由 atp_work_atp_slots.py 完成（固定列写入）；此处为公式基线，可查看/编辑。" />
            ) : null}
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
                { key: "code", label: "参数 code", value: detail.code },
                { key: "unit", label: "单位", value: detail.unit ?? "-" },
                { key: "data_type", label: "数据类型", value: detail.data_type },
                { key: "deps", label: "依赖参数", value: detail.deps_json.length ? detail.deps_json.join(", ") : "-" },
                { key: "enabled", label: "启用", value: detail.enabled ? "是" : "否" },
                { key: "desc", label: "说明", value: detail.description ?? "-" },
              ]}
              columns={[
                { title: "项", dataIndex: "label", width: 90 },
                { title: "值", dataIndex: "value" },
              ]}
            />
          </Space>
        ) : null}
      </Drawer>

      {/* 试算抽屉：全参数解析预览 */}
      <Drawer title="参数试算（样例杆塔 220kV/ganzi）" open={previewOpen} onClose={() => setPreviewOpen(false)} width={560}>
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            message="样例上下文来自参数模板页同口径：shield_h=73.5 / insul_mm=5945 / h_u=65.5 / lw=12.4 / 220kV / 146kA"
          />
          <Spin spinning={previewLoading}>
            {preview ? (
              <Table
                rowKey="code"
                size="small"
                pagination={{ pageSize: 15, showSizeChanger: false }}
                dataSource={preview.items}
                columns={[
                  { title: "参数", dataIndex: "code", width: 140, render: (v: string) => <Typography.Text code>{v}</Typography.Text> },
                  { title: "名称", dataIndex: "name", width: 130 },
                  { title: "来源", dataIndex: "source_type", width: 110, render: (v: string) => <Tag color={SOURCE_TYPE_COLOR[v as SourceType]}>{(SOURCE_TYPE_LABEL as Record<string, string>)[v] ?? v}</Tag> },
                  { title: "值", dataIndex: "value", render: (v: unknown) => <Typography.Text strong>{formatValue(v)}</Typography.Text> },
                ]}
              />
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="点击上方「试算」执行解析" />
            )}
          </Spin>
        </Space>
      </Drawer>

      {/* 新建/编辑抽屉 */}
      <Drawer
        title={editing ? `编辑参数 ${editing.code}` : "新建参数"}
        open={editOpen}
        onClose={() => setEditOpen(false)}
        width={620}
        extra={
          <Space>
            <Button onClick={() => setEditOpen(false)}>取消</Button>
            <Button type="primary" onClick={() => void saveDefinition()}>
              保存
            </Button>
          </Space>
        }
      >
        <Form form={form} layout="vertical" initialValues={{ data_type: "number", enabled: true, sort_order: 0 }}>
          <Space size={12} style={{ display: "flex" }} wrap>
            <Form.Item label="来源类型" name="source_type" rules={[{ required: true }]} style={{ width: 180 }}>
              <Select
                options={[
                  { value: "line_binding", label: "线路导入绑定" },
                  { value: "script", label: "计算脚本" },
                  { value: "constant", label: "字面量" },
                ]}
              />
            </Form.Item>
            <Form.Item label="参数 code" name="code" rules={[{ required: true, pattern: /^[A-Za-z0-9_]+$/, message: "字母/数字/下划线" }]} style={{ width: 200 }}>
              <Input placeholder="如 h_u / coupling_k0" disabled={!!editing} />
            </Form.Item>
            <Form.Item label="名称" name="name" rules={[{ required: true }]} style={{ width: 220 }}>
              <Input placeholder="中文名（如 耦合系数 k0）" />
            </Form.Item>
          </Space>
          <Space size={12} style={{ display: "flex" }} wrap>
            <Form.Item label="单位" name="unit" style={{ width: 120 }}>
              <Input placeholder="如 m / kA" />
            </Form.Item>
            <Form.Item label="数据类型" name="data_type" style={{ width: 120 }}>
              <Select
                options={[
                  { value: "number", label: "数值" },
                  { value: "string", label: "字符串" },
                  { value: "bool", label: "布尔" },
                ]}
              />
            </Form.Item>
            <Form.Item label="排序" name="sort_order" style={{ width: 100 }}>
              <InputNumber min={0} style={{ width: "100%" }} />
            </Form.Item>
            <Form.Item label="启用" name="enabled" valuePropName="checked" style={{ width: 80 }}>
              <Switch />
            </Form.Item>
          </Space>

          {watchSource === "line_binding" ? (
            <>
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 12 }}
                message="线路导入绑定"
                description="建立「线路中杆塔属性路径 ↔ 参数名」的关联。现状镜像（runtime_key）保持与现有计算链路完全一致；也可选择新字段路径（点路径 a.b.c）。"
              />
              <Space size={12} style={{ display: "flex" }} wrap>
                <Form.Item label="来源域" name={["binding_json", "runtime_key"]} style={{ width: 220 }}>
                  <Select
                    allowClear
                    placeholder="选择现状镜像键（推荐）"
                    showSearch
                    options={depsOptions.map((item) => ({ value: item.value, label: item.label }))}
                  />
                </Form.Item>
                <Form.Item label="自定义绑定来源" name={["binding_json", "source"]} style={{ width: 200 }}>
                  <Select
                    allowClear
                    placeholder="或选来源域"
                    options={bindingSourceOptions}
                  />
                </Form.Item>
                <Form.Item label="字段路径" name={["binding_json", "path"]} style={{ width: 280 }}>
                  <Select
                    allowClear
                    placeholder="选择杆塔属性字段"
                    showSearch
                    options={bindingFieldOptions}
                    onChange={(next) => {
                      const field = (fieldsMeta?.fields ?? []).find((item) => item.value === next);
                      if (field) {
                        // 选字段即确定来源域（避免来源/路径不匹配）
                        form.setFieldValue(["binding_json", "source"], field.source);
                      }
                    }}
                  />
                </Form.Item>
              </Space>
              <Form.Item label="单位换算" name={["binding_json", "transform"]} style={{ width: 200 }}>
                <Select
                  allowClear
                  placeholder="无"
                  options={(fieldsMeta?.transform_options ?? []).map((value) => ({ value, label: value === "mm_to_m" ? "毫米→米（>100 启发式）" : value }))}
                />
              </Form.Item>
            </>
          ) : null}

          {watchSource === "script" ? (
            <>
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 12 }}
                message="Python 计算脚本（沙箱）"
                description="只允许纯数学函数（abs/sqrt/hypot/log/pow/exp/sin/cos/tan/clamp/v 等），禁止 import/IO/循环。最后变量 result 作为输出；依赖参数需在下方显式声明。"
              />
              <Form.Item label="依赖参数" name="deps_json">
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="声明脚本依赖的参数（可从注册表选，也可用上下文键名）"
                  options={depsOptions}
                />
              </Form.Item>
              <Form.Item label="脚本内容" name="script_code" rules={[{ required: true, message: "请输入脚本" }]}>
                <Input.TextArea
                  rows={10}
                  placeholder={
                    "示例：\n# 耦合系数 k0\nrk = 0.0055\ny1 = shield_h - v_arc(voltage) * 2.0 / 3.0\n...\nresult = (z31 + z32) / (z11 + z12)\n\n可用函数见右侧「字段目录」标签的 script_functions。"
                  }
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
              </Form.Item>
              <Space size={8} style={{ marginBottom: 12 }}>
                <Button icon={<ExperimentOutlined />} loading={scriptTesting} onClick={() => void runScriptTest()}>
                  试算
                </Button>
                {scriptTest ? (
                  scriptTest.ok ? (
                    <Alert
                      type="success"
                      showIcon
                      style={{ flex: 1 }}
                      message={`试算结果：${formatValue(scriptTest.value)}`}
                      description={`引用变量：${scriptTest.referenced.length ? scriptTest.referenced.join(", ") : "（无）"}`}
                    />
                  ) : (
                    <Alert
                      type="error"
                      showIcon
                      style={{ flex: 1 }}
                      message="试算失败"
                      description={scriptTest.errors.join("；")}
                    />
                  )
                ) : null}
              </Space>
            </>
          ) : null}

          {watchSource === "constant" ? (
            <Form.Item label="字面量" name={["binding_json", "value"]} rules={[{ required: true, message: "请输入字面量" }]}>
              <Input placeholder="如 0.0055" />
            </Form.Item>
          ) : null}

          <Form.Item label="说明" name="description">
            <Input.TextArea rows={2} placeholder="参数用途 / 单位说明 / 来源（可选）" />
          </Form.Item>

          {watchSource === "script" && (watchDeps ?? []).length === 0 ? (
            <Alert type="warning" showIcon message="尚未声明依赖参数：脚本只能引用输入框外的上下文键（如 shield_h / h_u / voltage），否则保存校验会拦截。" style={{ marginBottom: 12 }} />
          ) : null}
        </Form>
      </Drawer>
    </Card>
  );
}