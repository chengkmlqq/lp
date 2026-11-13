"use client";

/**
 * 防雷测试集管理（测试集页「防雷测试」Tab）。
 *
 * 集合按类别（fl_calc 防雷计算 / retrofit 防雷改造）组织用例；本组件提供
 * 集合列表（新建/编辑/删除/停用）与详情抽屉入口（用例管理 + 批量执行 + 历史）。
 * 数据源：GET/POST/PATCH/DELETE /api/v1/fl-test-sets 系列接口。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Radio,
  Segmented,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RedoOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { modoTablePagination } from "@/components/biz/modo-pagination";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type { FlTestSetCategory, FlTestSetListResponse, FlTestSetSummary } from "@/types/fl-test-set";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";
import { FlTestSetDetailDrawer } from "@/components/fl-test-sets/fl-test-set-detail-drawer";

const TABLE_MIN_SCROLL_Y = 300;

export function FlTestSetTab() {
  const { t } = useI18n();
  const { user, hasPermission } = useAuth();
  const { modal: modalApi } = App.useApp();
  const queryClient = useQueryClient();
  const [categoryFilter, setCategoryFilter] = useState<"all" | FlTestSetCategory>("all");
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [editingSet, setEditingSet] = useState<FlTestSetSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [detailSet, setDetailSet] = useState<FlTestSetSummary | null>(null);
  const [form] = Form.useForm();
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const canRead =
    hasPermission("line.read") || hasPermission("line.manage") || hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("fl.create") || hasPermission("line.manage") || hasPermission("atp.manage");
  const canDelete = hasPermission("fl.delete") || hasPermission("line.manage") || hasPermission("atp.manage");

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", "200");
    params.set("offset", "0");
    if (categoryFilter !== "all") params.set("category", categoryFilter);
    if (keyword.trim()) params.set("keyword", keyword.trim());
    return `/api/v1/fl-test-sets?${params.toString()}`;
  }, [categoryFilter, keyword]);

  const setsQuery = useQuery({
    queryKey: [listPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as FlTestSetListResponse;
    },
  });

  const invalidate = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["/api/v1/fl-test-sets"] });
  }, [queryClient]);

  const saveMutation = useMutation({
    mutationFn: async (values: { name: string; category: FlTestSetCategory; description?: string; status?: string }) => {
      const url = editingSet ? `/api/v1/fl-test-sets/${editingSet.id}` : "/api/v1/fl-test-sets";
      const response = await fetchWithAuth(url, {
        method: editingSet ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      setCreateOpen(false);
      setEditingSet(null);
      invalidate();
    },
    onError: (error: Error) => modalApi.error({ title: t("保存测试集失败"), content: error.message }),
  });

  const deleteMutation = useMutation({
    mutationFn: async (setId: string) => {
      const response = await fetchWithAuth(`/api/v1/fl-test-sets/${setId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
      return response.json();
    },
    onSuccess: () => {
      invalidate();
      if (detailSet) setDetailSet(null);
    },
    onError: (error: Error) => modalApi.error({ title: t("删除测试集失败"), content: error.message }),
  });

  const openCreate = () => {
    setEditingSet(null);
    form.setFieldsValue({ name: "", category: categoryFilter === "all" ? "fl_calc" : categoryFilter, description: "", status: "enabled" });
    setCreateOpen(true);
  };

  const openEdit = (row: FlTestSetSummary) => {
    setEditingSet(row);
    form.setFieldsValue({ name: row.name, category: row.category, description: row.description, status: row.status });
    setCreateOpen(true);
  };

  // 表格高度自适应视口（口径与 atp 测试集页 / 线路管理页一致：锚点底边推导）
  useEffect(() => {
    if (typeof window === "undefined") return;
    const measure = () => {
      const anchor = tableScrollAnchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const available = window.innerHeight - rect.top - 190;
      setTableScrollY(Math.max(TABLE_MIN_SCROLL_Y, Math.floor(available)));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const columns = useMemo<ColumnsType<FlTestSetSummary>>(
    () => [
      {
        title: t("名称"),
        dataIndex: "name",
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space size={8}>
            <Typography.Text strong>{value}</Typography.Text>
            {row.status === "disabled" ? <Tag>{t("已停用")}</Tag> : null}
          </Space>
        ),
      },
      {
        title: t("类别"),
        dataIndex: "category",
        width: 110,
        render: (value: FlTestSetCategory) =>
          value === "retrofit" ? <Tag color="teal">{t("防雷改造")}</Tag> : <Tag color="blue">{t("防雷计算")}</Tag>,
      },
      {
        title: t("用例数"),
        width: 110,
        render: (_: unknown, row) => (
          <Typography.Text>
            {row.enabled_case_count}/{row.case_count}
          </Typography.Text>
        ),
      },
      {
        title: t("最近执行"),
        width: 200,
        render: (_: unknown, row) =>
          row.last_run ? (
            <Space size={6}>
              <FlTestRunStatusTag status={row.last_run.status} />
              <Typography.Text type="secondary">{formatDateTime(row.last_run.create_date)}</Typography.Text>
            </Space>
          ) : (
            <Typography.Text type="secondary">-</Typography.Text>
          ),
      },
      {
        title: t("描述"),
        dataIndex: "description",
        ellipsis: { showTitle: true },
        render: (value: string) => (
          <Typography.Text type="secondary">{value || "-"}</Typography.Text>
        ),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 200,
        fixed: "right" as const,
        render: (_: unknown, row) => (
          <ModoActionGroup
            actions={[
              {
                key: "cases",
                label: t("用例与执行"),
                icon: <SettingOutlined />,
                onClick: () => setDetailSet(row),
              },
              {
                key: "edit",
                label: t("编辑"),
                icon: <EditOutlined />,
                visible: canManage,
                onClick: () => openEdit(row),
              },
              {
                key: "delete",
                label: t("删除"),
                icon: <DeleteOutlined />,
                danger: true,
                visible: canDelete,
                onClick: () =>
                  modalApi.confirm({
                    title: t("删除测试集"),
                    content: t("将同时删除其全部用例与执行记录（已创建的计算任务保留）。"),
                    okButtonProps: { danger: true },
                    onOk: () => deleteMutation.mutateAsync(row.id),
                  }),
              },
            ]}
          />
        ),
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [t, canManage, canDelete, openEdit, deleteMutation],
  );

  if (!user || !canRead) {
    return (
      <Empty description={<Typography.Text type="secondary">{t("当前账号无防雷测试权限。")}</Typography.Text>} />
    );
  }

  const items = setsQuery.data?.items ?? [];

  return (
    <div className="admin-fl-test-sets-pane">
      {/* 筛选栏 */}
      <div className="admin-filter-bar">
        <Form layout="inline" onFinish={() => setKeyword(keywordDraft)}>
          <Form.Item style={{ marginBottom: 0 }}>
            <Segmented
              value={categoryFilter}
              onChange={(value) => {
                setCategoryFilter(value as "all" | FlTestSetCategory);
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
              options={[
                { label: t("全部"), value: "all" },
                { label: t("防雷计算"), value: "fl_calc" },
                { label: t("防雷改造"), value: "retrofit" },
              ]}
            />
          </Form.Item>
          <Form.Item label={t("名称/描述")} style={{ marginBottom: 0 }}>
            <Input
              allowClear
              style={{ width: 240 }}
              prefix={<SearchOutlined />}
              placeholder={t("搜索测试集名称/描述")}
              value={keywordDraft}
              onChange={(event) => setKeywordDraft(event.target.value)}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              {t("查询")}
            </Button>
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
            <Button icon={<RedoOutlined />} onClick={() => invalidate()}>
              {t("刷新")}
            </Button>
          </Form.Item>
          {canManage ? (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                {t("新建测试集")}
              </Button>
            </Form.Item>
          ) : null}
        </Form>
      </div>

      {/* 表格 */}
      <div ref={tableScrollAnchorRef} className="admin-fl-test-sets-table-view flex-1 min-h-0">
        <Table<FlTestSetSummary>
          rowKey="id"
          size="small"
          columns={columns}
          dataSource={items}
          loading={setsQuery.isLoading}
          scroll={{ y: tableScrollY, x: 1080 }}
          pagination={modoTablePagination({
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: setsQuery.data?.total ?? 0,
            onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
          })}
          locale={{ emptyText: <Empty description={t("暂无测试集")} /> }}
        />
      </div>
      <Modal
        title={editingSet ? t("编辑测试集") : t("新建测试集")}
        open={createOpen}
        onCancel={() => {
          setCreateOpen(false);
          setEditingSet(null);
        }}
        confirmLoading={saveMutation.isPending}
        onOk={() => form.submit()}
      >
        <Form
          form={form}
          layout="vertical"
          onFinish={(values) => saveMutation.mutate(values)}
        >
          <Form.Item name="category" label={t("类别")} required>
            <Radio.Group disabled={!!editingSet}>
              <Radio.Button value="fl_calc">{t("防雷计算")}</Radio.Button>
              <Radio.Button value="retrofit">{t("防雷改造")}</Radio.Button>
            </Radio.Group>
          </Form.Item>
          <Form.Item
            name="name"
            label={t("名称")}
            rules={[{ required: true, message: t("请输入测试集名称") }]}
          >
            <Input maxLength={255} placeholder={t("例如：115kV 主流程回归")} />
          </Form.Item>
          <Form.Item name="description" label={t("描述")}>
            <Input.TextArea rows={3} maxLength={8000} />
          </Form.Item>
          <Form.Item name="status" label={t("状态")}>
            <Radio.Group>
              <Radio value="enabled">{t("启用中（停用后仍可查看，不可执行）")}</Radio>
              <Radio value="disabled">{t("已停用")}</Radio>
            </Radio.Group>
          </Form.Item>
        </Form>
      </Modal>
      <FlTestSetDetailDrawer
        testSet={detailSet}
        open={!!detailSet}
        onClose={() => setDetailSet(null)}
      />
    </div>
  );
}

export function FlTestRunStatusTag({ status }: { status: string | null | undefined }) {
  const { t } = useI18n();
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: "default", label: t("待执行") },
    running: { color: "processing", label: t("执行中") },
    success: { color: "success", label: t("全部通过") },
    partial: { color: "warning", label: t("部分通过") },
    failed: { color: "error", label: t("失败") },
    cancelled: { color: "default", label: t("已取消") },
  };
  const item = map[status ?? ""] ?? { color: "default", label: status ?? "-" };
  return <Tag color={item.color}>{item.label}</Tag>;
}

export function FlTestVerdictTag({ verdict }: { verdict: string | null | undefined }) {
  const { t } = useI18n();
  const map: Record<string, { color: string; label: string }> = {
    auto_pass: { color: "success", label: t("自动通过") },
    auto_fail: { color: "error", label: t("自动不通过") },
    pending_manual: { color: "warning", label: t("待人工判定") },
    manual_pass: { color: "success", label: t("人工通过") },
    manual_fail: { color: "error", label: t("人工不通过") },
  };
  const item = map[verdict ?? ""] ?? { color: "default", label: verdict ?? "-" };
  return <Tag color={item.color}>{item.label}</Tag>;
}

export function FlTestJobStatusTag({ status }: { status: string | null | undefined }) {
  const { t } = useI18n();
  const map: Record<string, { color: string; label: string }> = {
    pending: { color: "default", label: t("排队中") },
    queued: { color: "processing", label: t("已入队") },
    running: { color: "processing", label: t("计算中") },
    blocked: { color: "warning", label: t("阻塞") },
    success: { color: "success", label: t("成功") },
    failed: { color: "error", label: t("失败") },
    cancelled: { color: "default", label: t("已取消") },
  };
  const item = map[status ?? ""] ?? { color: "default", label: status ?? "-" };
  return <Tag color={item.color}>{item.label}</Tag>;
}
