"use client";

import { DeleteOutlined, EditOutlined, PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableColumnsType,
} from "antd";
import { useCallback, useMemo, useState } from "react";

import { fetchWithAuth, readApiError } from "@/lib/api";

type Priority = "高" | "中" | "低";
type Status = "待处理" | "进行中" | "已完成" | "已关闭";

type Requirement = {
  id: string;
  title: string;
  module: string | null;
  priority: Priority;
  status: Status;
  description: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type RequirementList = { items: Requirement[]; total: number };
type RequirementMeta = { modules: string[]; priorities: Priority[]; statuses: Status[] };

type FormValues = {
  title: string;
  module?: string;
  priority: Priority;
  status: Status;
  description?: string;
};

const PRIORITY_COLOR: Record<string, string> = { 高: "red", 中: "orange", 低: "default" };
const STATUS_COLOR: Record<string, string> = { 待处理: "default", 进行中: "processing", 已完成: "success", 已关闭: "warning" };

async function fetchList(params: URLSearchParams): Promise<RequirementList> {
  const res = await fetchWithAuth(`/api/v1/feature-requirements?${params.toString()}`);
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as RequirementList;
}

async function fetchMeta(): Promise<RequirementMeta> {
  const res = await fetchWithAuth("/api/v1/feature-requirements/meta");
  if (!res.ok) {
    throw new Error(await readApiError(res));
  }
  return (await res.json()) as RequirementMeta;
}

function formatTime(value: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export default function FeatureRequirementsPage() {
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [form] = Form.useForm<FormValues>();

  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [moduleFilter, setModuleFilter] = useState<string | undefined>();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [priorityFilter, setPriorityFilter] = useState<string | undefined>();
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Requirement | null>(null);

  const metaQuery = useQuery({ queryKey: ["feature-requirement-meta"], queryFn: fetchMeta, staleTime: 5 * 60 * 1000 });

  const queryParams = useMemo(() => {
    const params = new URLSearchParams();
    if (keyword.trim()) params.set("keyword", keyword.trim());
    if (moduleFilter) params.set("module", moduleFilter);
    if (statusFilter) params.set("status", statusFilter);
    if (priorityFilter) params.set("priority", priorityFilter);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return params;
  }, [keyword, moduleFilter, statusFilter, priorityFilter, page, pageSize]);

  const listQuery = useQuery({
    queryKey: ["feature-requirements", queryParams.toString()],
    queryFn: () => fetchList(queryParams),
  });

  const invalidate = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: ["feature-requirements"] });
  }, [queryClient]);

  const createMutation = useMutation({
    mutationFn: async (values: FormValues) => {
      const res = await fetchWithAuth("/api/v1/feature-requirements", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: async () => {
      message.success("需求单已创建");
      setModalOpen(false);
      await invalidate();
    },
    onError: (error: Error) => message.error(error.message || "创建失败"),
  });

  const updateMutation = useMutation({
    mutationFn: async ({ id, values }: { id: string; values: FormValues }) => {
      const res = await fetchWithAuth(`/api/v1/feature-requirements/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: async () => {
      message.success("需求单已更新");
      setModalOpen(false);
      await invalidate();
    },
    onError: (error: Error) => message.error(error.message || "更新失败"),
  });

  const statusMutation = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: string }) => {
      const res = await fetchWithAuth(`/api/v1/feature-requirements/${id}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status }),
      });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: async () => {
      message.success("状态已更新");
      await invalidate();
    },
    onError: (error: Error) => message.error(error.message || "状态更新失败"),
  });

  const deleteMutation = useMutation({
    mutationFn: async (id: string) => {
      const res = await fetchWithAuth(`/api/v1/feature-requirements/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await readApiError(res));
      return res.json();
    },
    onSuccess: async () => {
      message.success("需求单已删除");
      await invalidate();
    },
    onError: (error: Error) => message.error(error.message || "删除失败"),
  });

  const openCreate = () => {
    setEditing(null);
    form.resetFields();
    form.setFieldsValue({ priority: "中", status: "待处理" });
    setModalOpen(true);
  };

  const openEdit = (row: Requirement) => {
    setEditing(row);
    form.setFieldsValue({
      title: row.title,
      module: row.module ?? undefined,
      priority: row.priority,
      status: row.status,
      description: row.description ?? undefined,
    });
    setModalOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    if (editing) {
      await updateMutation.mutateAsync({ id: editing.id, values });
    } else {
      await createMutation.mutateAsync(values);
    }
  };

  const columns: TableColumnsType<Requirement> = [
    {
      title: "需求名称",
      dataIndex: "title",
      key: "title",
      width: 260,
      render: (value: string, row) => (
        <div className="flex flex-col gap-1">
          <span className="font-medium">{value}</span>
          {row.description ? (
            <Tooltip title={<pre className="whitespace-pre-wrap m-0">{row.description}</pre>}>
              <span className="text-xs text-gray-500 line-clamp-2">{row.description.split("\n")[0]}</span>
            </Tooltip>
          ) : null}
        </div>
      ),
    },
    { title: "模块", dataIndex: "module", key: "module", width: 120, render: (v: string | null) => v || "-" },
    {
      title: "优先级",
      dataIndex: "priority",
      key: "priority",
      width: 90,
      render: (value: string) => <Tag color={PRIORITY_COLOR[value] ?? "default"}>{value}</Tag>,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      width: 140,
      render: (value: string, row) => (
        <Select
          size="small"
          value={value}
          className="w-28"
          options={(metaQuery.data?.statuses ?? ["待处理", "进行中", "已完成", "已关闭"]).map((s) => ({ value: s, label: s }))}
          onChange={(next) => statusMutation.mutate({ id: row.id, status: next })}
        />
      ),
    },
    { title: "创建人", dataIndex: "created_by", key: "created_by", width: 100, render: (v: string | null) => v || "-" },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 150,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: "更新时间",
      dataIndex: "updated_at",
      key: "updated_at",
      width: 150,
      render: (v: string | null) => formatTime(v),
    },
    {
      title: "操作",
      key: "action",
      width: 140,
      fixed: "right",
      render: (_, row) => (
        <Space size={4}>
          <Button type="link" size="small" icon={<EditOutlined />} onClick={() => openEdit(row)}>
            编辑
          </Button>
          <Popconfirm title="确认删除该需求单？" okText="删除" cancelText="取消" onConfirm={() => deleteMutation.mutate(row.id)}>
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div className="admin-feature-requirements-page">
      <div className="admin-feature-requirements-header">
        <div>
          <Typography.Title level={5} style={{ margin: 0 }}>
            功能需求单
          </Typography.Title>
          <Typography.Text type="secondary">记录并跟踪功能需求（模块 / 优先级 / 状态 / 需求描述）</Typography.Text>
        </div>
        <Space wrap>
          <Input
            allowClear
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onPressEnter={() => {
              setKeyword(keywordInput);
              setPage(1);
            }}
            placeholder="搜索需求名称/描述"
            prefix={<SearchOutlined />}
            style={{ width: 220 }}
          />
          <Select
            allowClear
            placeholder="模块"
            style={{ width: 130 }}
            value={moduleFilter}
            onChange={(value) => {
              setModuleFilter(value);
              setPage(1);
            }}
            options={(metaQuery.data?.modules ?? []).map((m) => ({ value: m, label: m }))}
          />
          <Select
            allowClear
            placeholder="状态"
            style={{ width: 120 }}
            value={statusFilter}
            onChange={(value) => {
              setStatusFilter(value);
              setPage(1);
            }}
            options={(metaQuery.data?.statuses ?? []).map((s) => ({ value: s, label: s }))}
          />
          <Select
            allowClear
            placeholder="优先级"
            style={{ width: 110 }}
            value={priorityFilter}
            onChange={(value) => {
              setPriorityFilter(value);
              setPage(1);
            }}
            options={(metaQuery.data?.priorities ?? []).map((p) => ({ value: p, label: p }))}
          />
          <Button
            icon={<SearchOutlined />}
            onClick={() => {
              setKeyword(keywordInput);
              setPage(1);
            }}
          >
            查询
          </Button>
          <Button icon={<ReloadOutlined />} onClick={() => listQuery.refetch()}>
            刷新
          </Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
            新建需求单
          </Button>
        </Space>
      </div>

      <Table<Requirement>
        rowKey="id"
        size="small"
        loading={listQuery.isLoading}
        dataSource={listQuery.data?.items ?? []}
        columns={columns}
        scroll={{ x: 1180 }}
        pagination={{
          current: page,
          pageSize,
          total: listQuery.data?.total ?? 0,
          showSizeChanger: true,
          showTotal: (total) => `共 ${total} 条`,
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            setPageSize(nextSize);
          },
        }}
        locale={{ emptyText: listQuery.isError ? `加载失败：${(listQuery.error as Error).message}` : "暂无需求单" }}
      />

      <Modal
        title={editing ? "编辑需求单" : "新建需求单"}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={submit}
        confirmLoading={createMutation.isPending || updateMutation.isPending}
        okText="保存"
        cancelText="取消"
        width={640}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" initialValues={{ priority: "中", status: "待处理" }}>
          <Form.Item name="title" label="需求名称" rules={[{ required: true, message: "请输入需求名称" }]}>
            <Input placeholder="如：新建防雷计算页面布局调整" maxLength={200} />
          </Form.Item>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <Form.Item name="module" label="模块">
              <Input placeholder="如：防雷计算" maxLength={64} />
            </Form.Item>
            <Form.Item name="priority" label="优先级">
              <Select options={(metaQuery.data?.priorities ?? ["高", "中", "低"]).map((p) => ({ value: p, label: p }))} />
            </Form.Item>
            <Form.Item name="status" label="状态">
              <Select
                options={(metaQuery.data?.statuses ?? ["待处理", "进行中", "已完成", "已关闭"]).map((s) => ({ value: s, label: s }))}
              />
            </Form.Item>
          </div>
          <Form.Item name="description" label="需求描述">
            <Input.TextArea rows={6} placeholder={"1. ……\n2. ……"} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
