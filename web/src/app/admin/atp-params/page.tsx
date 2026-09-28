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
  EyeOutlined,
  FunctionOutlined,
  LinkOutlined,
  MoreOutlined,
  PlusOutlined,
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
function renderSourceSummary(record: DefinitionItem, showIcon = true) {
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
  onEdit: (item: DefinitionItem) => void;
  onDetail: (item: DefinitionItem) => void;
  onDelete: (item: DefinitionItem) => void;
}

/** 参数定义卡片（严格参照线路管理 <PowerLineCard> 结构）。 */
function DefinitionCard({ item, canManage, onEdit, onDetail, onDelete }: DefinitionCardProps) {
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
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>参数编码：</Typography.Text>
          <Typography.Text code style={{ fontSize: 12 }}>{item.code}</Typography.Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>参数来源：</Typography.Text>
          <Tag color={sourceColor} style={{ marginInlineEnd: 0 }}>{sourceLabel}</Tag>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            参数类型：{DATA_TYPE_LABEL[item.data_type] ?? item.data_type}
          </Typography.Text>
        </div>
        <div className="admin-atp-params-card-field admin-atp-models-card-field">
          {item.source_type === "line_binding" ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>取数口径：</Typography.Text>
          ) : item.source_type === "script" ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>脚本内容：</Typography.Text>
          ) : null}
          {renderSourceSummary(item, false)}
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
            <Tooltip title="详情">
              <Button size="small" type="text" icon={<EyeOutlined />} onClick={(event) => { event.stopPropagation(); onDetail(item); }} />
            </Tooltip>
            <Tooltip title="编辑">
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
                        <span>删除</span>
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
              <Tooltip title="更多">
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
          message.warning("线路导入绑定需要选择「来源 + 取数口径」");
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
    } finally {
      setSaving(false);
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
      render: (value: SourceType) => (
        <Tag color={SOURCE_TYPE_COLOR[value]}>{SOURCE_TYPE_LABEL[value]}</Tag>
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
          <Tooltip title="详情">
            <Button size="small" type="text" icon={<EyeOutlined />} onClick={() => openDetail(record)} />
          </Tooltip>
          <Tooltip title="编辑">
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
                      <span>删除</span>
                    </Space>
                  ),
                  danger: true,
                  onClick: () => removeDefinition(record),
                },
              ],
            }}
            trigger={["click"]}
          >
            <Tooltip title="更多">
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
                <FunctionOutlined /> ATP 计算参数管理
              </span>
            ),
            closable: false,
            children: (
              <div className="admin-atp-params-list-pane">
                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label="参数名称" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        placeholder="按 code/名称筛选"
                        onPressEnter={handleSearch}
                      />
                    </Form.Item>
                    <Form.Item label="来源类型" style={{ marginBottom: 0 }}>
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
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Button
                        htmlType="button"
                        icon={<SearchOutlined />}
                        onClick={handleSearch}
                        className="admin-search-btn"
                      >
                        查询
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
                      { label: "卡片视图", value: "card" },
                      { label: "列表视图", value: "list" },
                    ]}
                  />
                </div>
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
                onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
              }}
              scroll={{ x: 900, y: tableScrollY }}
            />
          </div>
        )}
      </Spin>
      </div>
      ),
      },
    ]}>
    </Tabs>

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
                  ? `绑定：${(detail.binding_json as { source?: string }).source}.${(detail.binding_json as { path?: string }).path}`
                  : detail.source_type === "script"
                    ? "计算脚本（沙箱求值，纯数学函数）"
                    : "字面量"
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
                { key: "code", label: "参数 code", value: detail.code },
                { key: "unit", label: "单位", value: detail.unit ?? "-" },
                { key: "data_type", label: "数据类型", value: DATA_TYPE_LABEL[detail.data_type] ?? detail.data_type },
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

      {/* 新建/编辑弹窗（参照防雷计算任务新建：Modal + 表单内按钮） */}
      <Modal
        title={editing ? `编辑参数 ${editing.code}` : "新建参数"}
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
                label="参数 code"
                name="code"
                tooltip="字母/数字/下划线，如 h_u / coupling_k0"
                rules={[{ required: true, pattern: /^[A-Za-z0-9_]+$/, message: "字母/数字/下划线" }]}
              >
                <Input placeholder="请输入参数 code" disabled={!!editing} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="名称" name="name" tooltip="中文名，如 耦合系数 k0" rules={[{ required: true }]}>
                <Input placeholder="请输入中文名称" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="参数来源" name="source_type" rules={[{ required: true }]}>
                <Select
                  options={[
                    { value: "line_binding", label: "线路导入绑定" },
                    { value: "script", label: "计算脚本" },
                    { value: "constant", label: "字面量" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="单位" name="unit" tooltip="结果单位，如 m / kA">
                <Input placeholder="请输入单位" />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="数据类型" name="data_type" tooltip="数值 / 字符串 / 布尔">
                <Select
                  options={[
                    { value: "number", label: "数值" },
                    { value: "string", label: "字符串" },
                    { value: "bool", label: "布尔" },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="排序" name="sort_order" tooltip="数字越小越靠前">
                <InputNumber min={0} style={{ width: "100%" }} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label="启用" name="enabled" valuePropName="checked" tooltip="关闭后模板解析将跳过该参数">
                <Switch />
              </Form.Item>
            </Col>
          </Row>

          {watchSource === "line_binding" ? (
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  label="取数口径"
                  name={["binding_json", "path"]}
                  tooltip="从来源域（杆塔主表 / 塔属性 / 任务执行选项）按点路径（a.b.c）抽取原始字段；按来源域分组展示，选中字段即确定来源"
                >
                  <Select
                    allowClear
                    placeholder="选择杆塔属性字段"
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
                <Form.Item label="单位换算" name={["binding_json", "transform"]} tooltip="取值后应用换算，如 毫米→米（>100 启发式）">
                  <Select
                    allowClear
                    placeholder="无"
                    options={(fieldsMeta?.transform_options ?? []).map((value) => ({ value, label: value === "mm_to_m" ? "毫米→米（>100 启发式）" : value }))}
                  />
                </Form.Item>
              </Col>
            </Row>
          ) : null}

          {watchSource === "script" ? (
            <>
              <Form.Item
                label="依赖参数"
                name="deps_json"
                tooltip="声明脚本依赖的参数（可从注册表选，也可用上下文键名）；依赖会先于脚本求值。未声明依赖时，脚本只能引用输入框外的上下文键（如 shield_h / h_u / voltage），否则保存校验会拦截"
              >
                <Select
                  mode="multiple"
                  allowClear
                  placeholder="选择依赖参数"
                  options={depsOptions}
                />
              </Form.Item>
              <Form.Item
                label="脚本内容"
                name="script_code"
                tooltip="Python 沙箱：只允许纯数学函数（abs/sqrt/hypot/log/pow/exp/sin/cos/tan/clamp/v 等），禁止 import/IO/循环；最后变量 result 作为输出"
                rules={[{ required: true, message: "请输入脚本" }]}
              >
                <Input.TextArea
                  rows={10}
                  placeholder="请输入计算脚本"
                  style={{ fontFamily: "monospace", fontSize: 12 }}
                />
              </Form.Item>
            </>
          ) : null}

          {watchSource === "constant" ? (
            <Form.Item
              label="字面量"
              name={["binding_json", "value"]}
              tooltip="固定常量，如 0.0055"
              rules={[{ required: true, message: "请输入字面量" }]}
            >
              <Input placeholder="请输入字面量" />
            </Form.Item>
          ) : null}

          <Form.Item label="说明" name="description" tooltip="参数用途 / 单位说明 / 来源（可选）">
            <Input.TextArea rows={2} placeholder="请输入说明" />
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
    </div>
  );
}