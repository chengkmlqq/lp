"use client";

import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Popconfirm,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import { PlusOutlined, SearchOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

const WIND_MODELS_BASE = "/api/v1/wind-models";

type ModelKind = "turbines" | "blades";
type ModelValueField = "hub_height_m" | "blade_length_m";

/** 后端型号映射记录（字段与迁移 048 一致）。 */
export type WindModelMappingRecord = {
  id: string;
  code: string;
  name: string;
  hub_height_m?: number | null;
  blade_length_m?: number | null;
  description?: string | null;
  is_enabled: boolean;
  sort_order: number;
};

type WindModelListResponse = {
  total?: number;
  items?: WindModelMappingRecord[];
};

type ModelFormValues = {
  code: string;
  name: string;
  value: number | null;
  sort_order: number | null;
};

type ModelSectionConfig = {
  kind: ModelKind;
  valueField: ModelValueField;
  /** 区块标题 / 表格名（机组型号 / 叶片型号） */
  title: string;
  /** 数值列表头，如「轮毂中心高度(m)」 */
  valueColumnTitle: string;
  /** 弹窗数值字段名，如「轮毂中心高度」 */
  valueFormLabel: string;
  createTitle: string;
  editTitle: string;
  emptyText: string;
};

const MODEL_SECTIONS: ModelSectionConfig[] = [
  {
    kind: "turbines",
    valueField: "hub_height_m",
    title: "机组型号",
    valueColumnTitle: "轮毂中心高度(m)",
    valueFormLabel: "轮毂中心高度",
    createTitle: "新增机组型号",
    editTitle: "编辑机组型号",
    emptyText: "暂无机组型号，点击「新增机组型号」添加",
  },
  {
    kind: "blades",
    valueField: "blade_length_m",
    title: "叶片型号",
    valueColumnTitle: "叶片长度(m)",
    valueFormLabel: "叶片长度",
    createTitle: "新增叶片型号",
    editTitle: "编辑叶片型号",
    emptyText: "暂无叶片型号，点击「新增叶片型号」添加",
  },
];

function formatMeters(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "-";
  return `${Number(value).toFixed(2)} m`;
}

type WindModelMappingPanelProps = {
  /** 仅当「型号参数映射」Tab 激活时拉取数据；每次切回该 Tab 时刷新。 */
  active: boolean;
};

/**
 * 风电数据准备页「型号参数映射」Tab：
 * 维护 机组型号 → 轮毂中心高度、叶片型号 → 叶片长度 两组映射。
 * 无 wind_data_prep.manage 权限时表格只读，隐藏新增/编辑/删除/启停入口。
 */
export function WindModelMappingPanel({ active }: WindModelMappingPanelProps) {
  const { hasPermission } = useAuth();
  const canManage = hasPermission("wind_data_prep.manage");
  return (
    <div className="modo-page-card" style={{ gap: 16, overflowY: "auto", paddingTop: 16 }}>
      {MODEL_SECTIONS.map((config) => (
        <WindModelSection key={config.kind} config={config} active={active} canManage={canManage} />
      ))}
    </div>
  );
}

type WindModelSectionProps = {
  config: ModelSectionConfig;
  active: boolean;
  canManage: boolean;
};

function WindModelSection({ config, active, canManage }: WindModelSectionProps) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { fetchWithAuth } = useAuth();
  const queryClient = useQueryClient();

  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<WindModelMappingRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [switchingId, setSwitchingId] = useState<string | null>(null);
  const [form] = Form.useForm<ModelFormValues>();

  const refreshModels = () =>
    queryClient.invalidateQueries({ queryKey: ["wind-models", config.kind] });

  const listQuery = useQuery({
    queryKey: ["wind-models", config.kind, keyword, page, pageSize],
    enabled: active,
    placeholderData: (previousData) => previousData,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      return getJson<WindModelListResponse>(
        `${WIND_MODELS_BASE}/${config.kind}?${params.toString()}`,
      );
    },
  });

  // 切回该 Tab 时刷新（首次挂载由 useQuery 自行拉取，无需重复请求）。
  const wasActiveRef = useRef(false);
  useEffect(() => {
    if (active && wasActiveRef.current) {
      void queryClient.invalidateQueries({ queryKey: ["wind-models", config.kind] });
    }
    wasActiveRef.current = active;
  }, [active, config.kind, queryClient]);

  const items = listQuery.data?.items ?? [];
  const total = listQuery.data?.total ?? items.length;

  const applySearch = () => {
    setPage(1);
    setKeyword(keywordInput.trim());
  };

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ sort_order: 0 });
    setModalOpen(true);
  };

  const openEdit = (record: WindModelMappingRecord) => {
    setEditing(record);
    form.setFieldsValue({
      code: record.code,
      name: record.name,
      value: record[config.valueField] ?? null,
      sort_order: record.sort_order ?? 0,
    });
    setModalOpen(true);
  };

  const handleSave = async () => {
    let values: ModelFormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const payload = {
      code: values.code.trim(),
      name: values.name.trim(),
      [config.valueField]: Number(values.value),
      sort_order: Number(values.sort_order ?? 0),
    };
    setSaving(true);
    try {
      const path = editing
        ? `${WIND_MODELS_BASE}/${config.kind}/${editing.id}`
        : `${WIND_MODELS_BASE}/${config.kind}`;
      const response = await fetchWithAuth(path, {
        method: editing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("型号已保存"));
      setModalOpen(false);
      setEditing(null);
      form.resetFields();
      await refreshModels();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const handleToggle = async (record: WindModelMappingRecord, enabled: boolean) => {
    setSwitchingId(record.id);
    try {
      const response = await fetchWithAuth(`${WIND_MODELS_BASE}/${config.kind}/${record.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_enabled: enabled }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("已更新启用状态"));
      await refreshModels();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSwitchingId(null);
    }
  };

  const handleDelete = async (record: WindModelMappingRecord) => {
    try {
      const response = await fetchWithAuth(`${WIND_MODELS_BASE}/${config.kind}/${record.id}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("型号已删除"));
      // 删除当前页最后一条时回退一页，避免停留在空页
      if (items.length === 1 && page > 1) {
        setPage(page - 1);
      }
      await refreshModels();
    } catch (error) {
      message.error((error as Error).message);
    }
  };

  const columns: TableColumnsType<WindModelMappingRecord> = [
    {
      title: t("编码"),
      dataIndex: "code",
      key: "code",
      width: 180,
      ellipsis: true,
    },
    {
      title: t("名称"),
      dataIndex: "name",
      key: "name",
      width: 220,
      ellipsis: true,
    },
    {
      title: t(config.valueColumnTitle),
      key: "value",
      width: 160,
      render: (_value, record) => formatMeters(record[config.valueField]),
    },
    {
      title: t("启用"),
      dataIndex: "is_enabled",
      key: "is_enabled",
      width: 100,
      render: (value: boolean, record) =>
        canManage ? (
          <Switch
            size="small"
            checked={value}
            loading={switchingId === record.id}
            onChange={(next) => void handleToggle(record, next)}
          />
        ) : (
          <Tag color={value ? "success" : "default"}>{value ? t("启用") : t("停用")}</Tag>
        ),
    },
    {
      title: t("排序"),
      dataIndex: "sort_order",
      key: "sort_order",
      width: 90,
    },
  ];

  if (canManage) {
    columns.push({
      title: t("操作"),
      key: "actions",
      width: 140,
      fixed: "right",
      render: (_value, record) => (
        <Space size={4} style={{ whiteSpace: "nowrap" }}>
          <Button size="small" onClick={() => openEdit(record)}>
            {t("编辑")}
          </Button>
          <Popconfirm
            title={t("删除该型号？")}
            description={t("删除后不可恢复，确认删除？")}
            okText={t("删除")}
            cancelText={t("取消")}
            okButtonProps={{ danger: true }}
            onConfirm={() => handleDelete(record)}
          >
            <Button size="small" danger>
              {t("删除")}
            </Button>
          </Popconfirm>
        </Space>
      ),
    });
  }

  return (
    <section style={{ display: "flex", flexDirection: "column", flexShrink: 0 }}>
      <div className="admin-filter-bar" style={{ marginBottom: 0 }}>
        <Typography.Text strong style={{ whiteSpace: "nowrap" }}>
          {t(config.title)}
        </Typography.Text>
        <Form
          layout="inline"
          onSubmitCapture={(event) => {
            event.preventDefault();
            applySearch();
          }}
        >
          <Form.Item style={{ marginBottom: 0 }}>
            <Input
              allowClear
              prefix={<SearchOutlined />}
              placeholder={t("搜索编码 / 名称")}
              style={{ width: 240 }}
              value={keywordInput}
              onChange={(event) => {
                const next = event.target.value;
                setKeywordInput(next);
                if (!next) {
                  setPage(1);
                  setKeyword("");
                }
              }}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button htmlType="submit">{t("查询")}</Button>
          </Form.Item>
        </Form>
        {canManage ? (
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            {t(config.createTitle)}
          </Button>
        ) : null}
      </div>

      {listQuery.isError ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 8 }}
          message={t("型号数据加载失败")}
          description={(listQuery.error as Error)?.message}
        />
      ) : null}

      <Table<WindModelMappingRecord>
        rowKey="id"
        size="small"
        loading={listQuery.isLoading || listQuery.isFetching}
        columns={columns}
        dataSource={items}
        pagination={false}
        scroll={{ x: 900 }}
        locale={{
          emptyText: (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t(config.emptyText)} />
          ),
        }}
      />

      <ModoPagination
        current={page}
        pageSize={pageSize}
        total={total}
        showSizeChanger={false}
        showQuickJumper={false}
        onChange={(nextPage, nextSize) => {
          setPage(nextPage);
          if (nextSize && nextSize !== pageSize) {
            setPageSize(nextSize);
            setPage(1);
          }
        }}
      />

      <Modal
        title={editing ? t(config.editTitle) : t(config.createTitle)}
        open={modalOpen}
        forceRender
        okText={t("保存")}
        cancelText={t("取消")}
        confirmLoading={saving}
        onCancel={() => {
          if (saving) return;
          setModalOpen(false);
        }}
        onOk={() => void handleSave()}
      >
        <Form<ModelFormValues> form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="code"
            label={t("编码")}
            rules={[
              { required: true, message: t("请输入编码") },
              { max: 128, message: t("编码不能超过 128 个字符") },
            ]}
          >
            <Input maxLength={128} placeholder="WT-5.0MW" />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("名称")}
            rules={[
              { required: true, message: t("请输入名称") },
              { max: 255, message: t("名称不能超过 255 个字符") },
            ]}
          >
            <Input maxLength={255} />
          </Form.Item>
          <Form.Item
            name="value"
            label={t(config.valueFormLabel)}
            rules={[
              { required: true, message: t("请填写数值") },
              {
                validator: (_rule, value) =>
                  Number.isFinite(Number(value)) && Number(value) > 0
                    ? Promise.resolve()
                    : Promise.reject(new Error(t("数值必须大于 0"))),
              },
            ]}
          >
            <InputNumber style={{ width: "100%" }} min={0} step={0.1} precision={2} addonAfter="m" />
          </Form.Item>
          <Form.Item name="sort_order" label={t("排序")} tooltip={t("数字越小越靠前")}>
            <InputNumber style={{ width: "100%" }} min={0} max={1000000} precision={0} />
          </Form.Item>
        </Form>
      </Modal>
    </section>
  );
}

export default WindModelMappingPanel;
