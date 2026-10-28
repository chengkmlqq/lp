"use client";

/**
 * ATP 测试集管理（页内动态选项卡）。
 *
 * 测试集 = 一组 ATP 模型的仿真测试用例（普通计算/同跳计算）。页面提供：
 * 列表（新建/编辑/删除/停用）+ 打开详情（用例管理 + 执行 + 历史）。
 * 数据源：GET/POST/PATCH/DELETE /api/v1/atp/test-sets 系列接口。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Popconfirm,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import {
  DeleteOutlined,
  EditOutlined,
  ExperimentOutlined,
  PlusOutlined,
  RedoOutlined,
  SearchOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, readApiError } from "@/lib/api";
import type { AtpTestSetListResponse, AtpTestSetSummary } from "@/types/auth";
import { formatDateTime } from "@/components/atp-models/atp-batch-history-tab";
import { AtpTestSetDetailDrawer } from "@/components/atp-models/atp-test-set-detail-drawer";

const TABLE_MIN_SCROLL_Y = 260;

export function AtpTestSetTab() {
  const { t } = useI18n();
  const { user, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const [keywordDraft, setKeywordDraft] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("atp.manage");
  const canTest = hasPermission("atp.run") || hasPermission("atp.manage");

  // 新建/编辑测试集
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingSet, setEditingSet] = useState<AtpTestSetSummary | null>(null);
  const [setForm] = Form.useForm();

  // 详情抽屉
  const [detailSet, setDetailSet] = useState<AtpTestSetSummary | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const { current: pageCurrent, pageSize: pageSizeValue } = pagination;

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

  const listPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(pageSizeValue));
    params.set("offset", String((pageCurrent - 1) * pageSizeValue));
    if (keyword.trim()) params.set("keyword", keyword.trim());
    return `/api/v1/atp/test-sets?${params.toString()}`;
  }, [keyword, pageCurrent, pageSizeValue]);

  const listQuery = useQuery<AtpTestSetListResponse>({
    queryKey: ["atp-test-sets", listPath],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const response = await fetchWithAuth(listPath);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpTestSetListResponse;
    },
  });

  const handleSearch = useCallback(() => {
    setKeyword(keywordDraft.trim());
    setPagination((previous) => ({ ...previous, current: 1 }));
  }, [keywordDraft]);

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
  }, [queryClient]);

  const openCreate = useCallback(() => {
    setEditingSet(null);
    setForm.setFieldsValue({ name: "", description: "", status: "enabled" });
    setEditModalOpen(true);
  }, [setForm]);

  const openEdit = useCallback((row: AtpTestSetSummary) => {
    setEditingSet(row);
    setForm.setFieldsValue({
      name: row.name,
      description: row.description,
      status: row.status,
    });
    setEditModalOpen(true);
  }, [setForm]);

  const saveSetMutation = useMutation({
    mutationFn: async (values: { name: string; description: string; status: string }) => {
      const body = { name: values.name.trim(), description: values.description.trim(), status: values.status };
      if (editingSet) {
        const response = await fetchWithAuth(`/api/v1/atp/test-sets/${editingSet.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (!response.ok) throw new Error(await readApiError(response));
        return (await response.json()) as AtpTestSetSummary;
      }
      const response = await fetchWithAuth("/api/v1/atp/test-sets", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpTestSetSummary;
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
      message.success(editingSet ? t("测试集已更新") : t("测试集已创建"));
      setEditModalOpen(false);
      setEditingSet(null);
      setForm.resetFields();
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : t("保存测试集失败"));
    },
  });

  const deleteSetMutation = useMutation({
    mutationFn: async (setId: string) => {
      const response = await fetchWithAuth(`/api/v1/atp/test-sets/${setId}`, { method: "DELETE" });
      if (!response.ok) throw new Error(await readApiError(response));
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["atp-test-sets"] });
      message.success(t("测试集已删除"));
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : t("删除测试集失败"));
    },
  });

  const openDetail = useCallback((row: AtpTestSetSummary) => {
    setDetailSet(row);
    setDetailOpen(true);
  }, []);

  const columns = useMemo<ColumnsType<AtpTestSetSummary>>(
    () => [
      {
        title: t("测试集名称"),
        dataIndex: "name",
        width: 200,
        ellipsis: { showTitle: true },
        render: (value: string, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong ellipsis={{ tooltip: value }} style={{ maxWidth: 190 }}>
              {value}
            </Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              更新于 {formatDateTime(row.update_date)}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        width: 90,
        render: (value: string) =>
          value === "disabled" ? <Tag>{t("已停用")}</Tag> : <Tag color="green">{t("启用中")}</Tag>,
      },
      {
        title: t("用例"),
        key: "cases",
        width: 120,
        render: (_, row) => (
          <Space direction="vertical" size={0}>
            <Typography.Text strong>{row.case_count}</Typography.Text>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              启用 {row.enabled_case_count}
            </Typography.Text>
          </Space>
        ),
      },
      {
        title: t("最近执行"),
        key: "last_run",
        width: 180,
        render: (_, row) => {
          const last = row.last_run;
          if (!last) return <Typography.Text type="secondary">-</Typography.Text>;
          return (
            <Space direction="vertical" size={0}>
              <Tag
                color={last.status === "success" ? "green" : last.status === "failed" ? "red" : "processing"}
              >
                {last.status === "success" ? t("全部通过") : last.status === "failed" ? t("有失败") : t("运行中")}
              </Tag>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                {formatDateTime(last.create_date)} · {last.total_cases} 用例
              </Typography.Text>
            </Space>
          );
        },
      },
      {
        title: t("描述"),
        dataIndex: "description",
        ellipsis: { showTitle: true },
        render: (value: string) => value || <Typography.Text type="secondary">-</Typography.Text>,
      },
      {
        title: t("创建人"),
        dataIndex: "create_user",
        width: 100,
        ellipsis: true,
        render: (value: string | null) => value || "-",
      },
      {
        title: t("操作"),
        key: "actions",
        width: 200,
        fixed: "right" as const,
        render: (_, row) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<SettingOutlined />}
              onClick={() => openDetail(row)}
            >
              {t("管理")}
            </Button>
            <Button
              type="link"
              size="small"
              style={{ padding: 0 }}
              icon={<ExperimentOutlined />}
              disabled={!canTest || row.case_count === 0}
              onClick={() => openDetail(row)}
            >
              {t("执行")}
            </Button>
            {canManage ? (
              <>
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  icon={<EditOutlined />}
                  onClick={() => openEdit(row)}
                >
                  编辑
                </Button>
                <Popconfirm
                  title={t("删除测试集？")}
                  description={t("将同时删除其全部用例与执行记录。")}
                  okText={t("删除")}
                  cancelText={t("取消")}
                  okButtonProps={{ danger: true }}
                  onConfirm={() => deleteSetMutation.mutate(row.id)}
                >
                  <Button
                    type="link"
                    size="small"
                    danger
                    style={{ padding: 0 }}
                    icon={<DeleteOutlined />}
                  >
                    删除
                  </Button>
                </Popconfirm>
              </>
            ) : null}
          </Space>
        ),
      },
    ],
    [canManage, canTest, deleteSetMutation, openDetail, openEdit],
  );

  if (!user) {
    return <Empty description={t("请先登录后再访问测试集管理。")} />;
  }
  if (!canRead) {
    return <Empty description={t("暂无权限查看测试集管理。")} />;
  }

  return (
    <div className="admin-atp-batch-history-pane">
      {/* 工具条 */}
      <div className="admin-filter-bar">
        <Form layout="inline" onFinish={handleSearch}>
          <Form.Item label={t("名称/描述")} style={{ marginBottom: 0 }}>
            <Input
              allowClear
              placeholder={t("输入测试集名称/描述")}
              style={{ width: 240 }}
              value={keywordDraft}
              onChange={(event) => setKeywordDraft(event.target.value)}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
              {t("查询")}
            </Button>
          </Form.Item>
          {canManage ? (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                新建测试集
              </Button>
            </Form.Item>
          ) : null}
          <Form.Item style={{ marginBottom: 0 }}>
            <Button icon={<RedoOutlined />} onClick={refresh}>
              刷新
            </Button>
          </Form.Item>
        </Form>
      </div>

      {/* 表格 */}
      <div ref={tableScrollAnchorRef} className="admin-atp-batch-history-table-view flex-1 min-h-0">
        <Table<AtpTestSetSummary>
          rowKey="id"
          size="small"
          loading={listQuery.isFetching}
          dataSource={listQuery.data?.items ?? []}
          columns={columns}
          tableLayout="fixed"
          scroll={{ y: tableScrollY, x: 1100 }}
          pagination={{
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: listQuery.data?.total ?? 0,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (total) => `共 ${total} 条`,
            position: ["bottomRight"],
            onChange: (page, pageSize) => {
              setPagination({ current: page, pageSize });
            },
          }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <Space direction="vertical" size={4}>
                    <span>{t("暂无测试集。")}</span>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      创建测试集后，为其中模型添加「普通计算 / 同跳计算」用例，
                      模型或程序更新时一键批量回归仿真测试。
                    </Typography.Text>
                  </Space>
                }
              />
            ),
          }}
        />
      </div>

      {/* 新建/编辑测试集 */}
      <Modal
        title={editingSet ? t("编辑测试集") : t("新建测试集")}
        open={editModalOpen}
        onCancel={() => {
          setEditModalOpen(false);
          setEditingSet(null);
          setForm.resetFields();
        }}
        onOk={() => void setForm.submit()}
        confirmLoading={saveSetMutation.isPending}
        destroyOnHidden
        okText={saveSetMutation.isPending ? t("提交中...") : editingSet ? t("保存") : t("创建")}
        cancelText={t("取消")}
      >
        <Form form={setForm} layout="vertical" onFinish={(values) => void saveSetMutation.mutateAsync(values)} autoComplete="off">
          <Form.Item
            name="name"
            label={t("名称")}
            rules={[{ required: true, message: t("请输入测试集名称") }]}
          >
            <Input placeholder={t("如：220kV 回归测试集 / 同跳专项验证集")} maxLength={255} />
          </Form.Item>
          <Form.Item name="status" label={t("状态")}>
            <Input.Group compact>
              <Typography.Text type="secondary" style={{ marginRight: 8 }}>
                启用中（停用后仍可查看，不可执行）
              </Typography.Text>
            </Input.Group>
          </Form.Item>
          <Form.Item name="description" label={t("描述")}>
            <Input.TextArea rows={3} placeholder={t("用途说明：如「酒杯塔模型更新后，批量验证普通计算与同跳计算无回归」")} maxLength={8000} />
          </Form.Item>
        </Form>
      </Modal>

      {/* 详情抽屉：用例管理 + 执行 + 历史 */}
      <AtpTestSetDetailDrawer
        setData={detailSet}
        open={detailOpen}
        onClose={() => {
          setDetailOpen(false);
          setDetailSet(null);
        }}
        onChanged={refresh}
      />
    </div>
  );
}