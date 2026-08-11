"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  type MenuProps,
} from "antd";
import { MoreOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useMemo, useState, useEffect, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { LineListResponse, LineSummary } from "@/types/auth";

type LineFormValues = {
  name: string;
  voltage_level: string | null;
};

type DetailTabItem = {
  key: string;
  label: ReactNode;
  closable: boolean;
  children: ReactNode;
};

const LIST_TAB_KEY = "list";

const LINE_VOLTAGE_OPTIONS = [
  { value: "dc_500", label: "直流500kV", voltage_kv: 500 },
  { value: "dc_800", label: "直流800kV", voltage_kv: 800 },
  { value: "dc_1000", label: "直流1000kV", voltage_kv: 1000 },
  { value: "ac_35", label: "交流35kV", voltage_kv: 35 },
  { value: "ac_66", label: "交流66kV", voltage_kv: 66 },
  { value: "ac_110", label: "交流110kV", voltage_kv: 110 },
  { value: "ac_220", label: "交流220kV", voltage_kv: 220 },
  { value: "ac_330", label: "交流330kV", voltage_kv: 330 },
  { value: "ac_500", label: "交流500kV", voltage_kv: 500 },
  { value: "ac_750", label: "交流750kV", voltage_kv: 750 },
  { value: "ac_800", label: "交流800kV", voltage_kv: 800 },
  { value: "ac_1000", label: "交流1000kV", voltage_kv: 1000 },
  { value: "ac_110_x4", label: "交流110kV|交流110kV|交流110kV|交流110kV", voltage_kv: 110 },
  { value: "ac_220_x4", label: "交流220kV|交流220kV|交流220kV|交流220kV", voltage_kv: 220 },
] as const;
const LINE_VOLTAGE_VALUE_TO_KV: Record<(typeof LINE_VOLTAGE_OPTIONS)[number]["value"], number> = {
  dc_500: 500,
  dc_800: 800,
  dc_1000: 1000,
  ac_35: 35,
  ac_66: 66,
  ac_110: 110,
  ac_220: 220,
  ac_330: 330,
  ac_500: 500,
  ac_750: 750,
  ac_800: 800,
  ac_1000: 1000,
  ac_110_x4: 110,
  ac_220_x4: 220,
};
const LINE_VOLTAGE_KV_TO_DEFAULT_OPTION: Partial<Record<number, (typeof LINE_VOLTAGE_OPTIONS)[number]["value"]>> = {
  35: "ac_35",
  66: "ac_66",
  110: "ac_110",
  220: "ac_220",
  330: "ac_330",
  500: "dc_500",
  750: "ac_750",
  800: "dc_800",
  1000: "dc_1000",
};
const EMPTY_LINE_FORM: LineFormValues = {
  name: "",
  voltage_level: null,
};

function resolveVoltageOptionFromKv(voltageKv: number | null): LineFormValues["voltage_level"] {
  if (voltageKv === null) {
    return null;
  }
  return LINE_VOLTAGE_KV_TO_DEFAULT_OPTION[voltageKv] ?? null;
}

export default function AdminPowerLinesPage() {
  const router = useRouter();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const queryClient = useQueryClient();
  const { message: messageApi } = App.useApp();
  const isMobile = useMobileDetection();
  const [lineForm] = Form.useForm<LineFormValues>();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [lineModalOpen, setLineModalOpen] = useState(false);
  const [editingLine, setEditingLine] = useState<LineSummary | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  const canLineManage = hasPermission("line.manage");
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage");
  const canRead = canLineRead || canTowerRead;
  const lineListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(paginationPageSize));
    params.set("offset", String((paginationCurrent - 1) * paginationPageSize));
    if (keyword.trim()) {
      params.set("keyword", keyword.trim());
    }
    const query = params.toString();
    return `/api/v1/lines${query ? `?${query}` : ""}`;
  }, [keyword, paginationCurrent, paginationPageSize]);
  const linesQuery = useQuery({
    queryKey: [lineListPath],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth(lineListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });
  const lineError = linesQuery.error instanceof Error ? linesQuery.error.message : "";
  useToastFeedback({
    errorMessage: error || lineError,
    successMessage: success,
    clearError: () => setError(""),
    clearSuccess: () => setSuccess(""),
  });
  const refreshLines = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lines"),
    });
  }, [queryClient]);
  useTopicSubscription("admin.power-lines", useCallback(() => {
    void refreshLines();
  }, [refreshLines]));
  const lines = useMemo(() => linesQuery.data?.items ?? [], [linesQuery.data?.items]);
  const total = linesQuery.data?.total ?? 0;
  const handleSearch = () => {
    setKeyword(keywordInput);
    setPagination((prev) => ({ ...prev, current: 1 }));
  };
  const saveLineMutation = useMutation({
    mutationFn: async (values: LineFormValues) => {
      if (!canLineManage) {
        throw new Error("缺少 line.manage 权限");
      }
      const payload = {
        name: values.name.trim(),
        voltage_kv: values.voltage_level ? LINE_VOLTAGE_VALUE_TO_KV[values.voltage_level] : null,
      };
      if (editingLine) {
        const response = await fetchWithAuth(`/api/v1/lines/${editingLine.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: payload.name,
            voltage_kv: payload.voltage_kv,
          }),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        return "updated" as const;
      }
      const response = await fetchWithAuth("/api/v1/lines", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return "created" as const;
    },
    onSuccess: async (mode) => {
      setError("");
      messageApi.success(mode === "created" ? "线路已创建" : "线路已更新");
      setLineModalOpen(false);
      setEditingLine(null);
      lineForm.resetFields();
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "保存线路失败");
    },
  });
  const deleteLineMutation = useMutation({
    mutationFn: async (lineId: string) => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}`, { method: "DELETE" });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return lineId;
    },
    onSuccess: async () => {
      setError("");
      messageApi.success("线路已删除");
      await refreshLines();
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除线路失败");
    },
  });

  const openDetail = useCallback((line: LineSummary) => {
    const key = line.id;
    setDetailTabs((previous) => {
      if (previous.some((tab) => tab.key === key)) {
        setActiveTabKey(key);
        return previous;
      }
      return [
        ...previous,
        {
          key,
          label: <span>{line.name}</span>,
          closable: true,
          children: (
            <PowerLineDetailView
              lineId={line.id}
              fetchWithAuth={fetchWithAuth}
              canTowerRead={canTowerRead}
              canLineManage={canLineManage}
              onLineDeleted={async () => {
                setDetailTabs((tabs) => tabs.filter((tab) => tab.key !== key));
                setActiveTabKey(LIST_TAB_KEY);
                await refreshLines();
              }}
            />
          ),
        },
      ];
    });
    setActiveTabKey(key);
  }, [fetchWithAuth, canTowerRead, canLineManage, refreshLines]);

  const handleTabsEdit = useCallback((targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
    if (action !== "remove") {
      return;
    }
    const key = String(targetKey);
    const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
    const next = detailTabs.filter((tab) => tab.key !== key);
    setDetailTabs(next);
    if (activeTabKey === key) {
      const fallback = next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY;
      setActiveTabKey(fallback);
    }
  }, [detailTabs, activeTabKey]);

  const openCreateLineModal = () => {
    setEditingLine(null);
    lineForm.setFieldsValue(EMPTY_LINE_FORM);
    setLineModalOpen(true);
  };
  const openEditLineModal = (line: LineSummary) => {
    setEditingLine(line);
    lineForm.setFieldsValue({
      name: line.name,
      voltage_level: resolveVoltageOptionFromKv(line.voltage_kv),
    });
    setLineModalOpen(true);
  };
  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }
  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再访问线路管理页面。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  if (!canRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `line.read` 或 `tower.read`）。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Tabs
        type="editable-card"
        hideAdd
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        className="admin-power-lines-tabs"
        tabBarExtraContent={
          canLineManage ? (
            <Button type="primary" onClick={openCreateLineModal}>
              新建线路
            </Button>
          ) : null
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-power-lines-tab-title">线路管理</span>,
            closable: false,
            children: (
              <div className="admin-power-lines-list-pane">
                <div className="admin-filter-bar flex justify-between items-center" style={{ marginBottom: 16 }}>
                  <Form layout="inline">
                    <Form.Item label="线路编码/名称" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        value={keywordInput}
                        allowClear
                        onChange={(event) => setKeywordInput(event.target.value)}
                        placeholder="按线路编码/名称筛选"
                        onPressEnter={handleSearch}
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
                    onChange={(value) => setViewMode(value as "card" | "list")}
                    options={[
                      { label: "卡片视图", value: "card" },
                      { label: "列表视图", value: "list" },
                    ]}
                  />
                </div>

                {lines.length === 0 ? (
                  <Empty description="暂无线路数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                ) : viewMode === "card" ? (
                  <div className="admin-power-lines-card-scroll">
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {lines.map((line) => (
                        <PowerLineCard
                          key={line.id}
                          line={line}
                          canLineManage={canLineManage}
                          onEdit={openEditLineModal}
                          onDetail={openDetail}
                          onDelete={() => {
                            Modal.confirm({
                              title: "删除线路",
                              content: `确认删除线路 ${line.name || line.code} 吗？`,
                              okText: "删除",
                              cancelText: "取消",
                              okButtonProps: { danger: true },
                              onOk: async () => {
                                await deleteLineMutation.mutateAsync(line.id);
                              },
                            });
                          }}
                          deleteLoading={deleteLineMutation.isPending}
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="admin-power-lines-table-view">
                    <PowerLineTable
                      lines={lines}
                      canLineManage={canLineManage}
                      onEdit={openEditLineModal}
                      onDetail={openDetail}
                      onDelete={(line) => {
                        Modal.confirm({
                          title: "删除线路",
                          content: `确认删除线路 ${line.name || line.code} 吗？`,
                          okText: "删除",
                          cancelText: "取消",
                          okButtonProps: { danger: true },
                          onOk: async () => {
                            await deleteLineMutation.mutateAsync(line.id);
                          },
                        });
                      }}
                      deleteLoading={deleteLineMutation.isPending}
                    />
                  </div>
                )}

                {total > 0 && (
                  <div className="admin-power-lines-pagination" style={{ marginTop: 16 }}>
                    <Pagination
                      current={pagination.current}
                      pageSize={pagination.pageSize}
                      total={total}
                      showSizeChanger
                      pageSizeOptions={[6, 12, 24, 48]}
                      showTotal={(count) => `共 ${count} 条`}
                      onChange={(page, pageSize) => {
                        setPagination({ current: page, pageSize });
                      }}
                      onShowSizeChange={(page, pageSize) => {
                        setPagination({ current: 1, pageSize });
                      }}
                    />
                  </div>
                )}
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title={editingLine ? "编辑线路" : "新建线路"}
        open={lineModalOpen}
        okText={editingLine ? "保存" : "创建"}
        confirmLoading={saveLineMutation.isPending}
        onCancel={() => {
          if (saveLineMutation.isPending) return;
          setLineModalOpen(false);
        }}
        onOk={async () => {
          const values = await lineForm.validateFields();
          saveLineMutation.mutate(values);
        }}
      >
        <Form<LineFormValues> form={lineForm} layout="vertical" initialValues={EMPTY_LINE_FORM}>
          <Form.Item
            name="name"
            label="线路名称"
            rules={[{ required: true, message: "请输入线路名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="voltage_level"
            label="电压等级"
            rules={[{ required: true, message: "请选择电压等级" }]}
          >
            <Select
              showSearch
              placeholder="请选择电压等级"
              options={[...LINE_VOLTAGE_OPTIONS].map((item) => ({ value: item.value, label: item.label }))}
              filterOption={(input, option) =>
                String(option?.label ?? "").toLowerCase().includes(input.toLowerCase())}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}

interface PowerLineCardProps {
  line: LineSummary;
  canLineManage: boolean;
  onEdit: (line: LineSummary) => void;
  onDetail: (line: LineSummary) => void;
  onDelete: () => void;
  deleteLoading: boolean;
}

function PowerLineCard({ line, canLineManage, onEdit, onDetail, onDelete, deleteLoading }: PowerLineCardProps) {
  const menuItems: MenuProps["items"] = canLineManage
    ? [
        {
          key: "delete",
          label: "删除",
          danger: true,
          onClick: onDelete,
        },
      ]
    : [];

  return (
    <Card
      size="small"
      hoverable
      title={<Typography.Text strong>{line.name}</Typography.Text>}
      extra={
        <Space size={4}>
          <Button
            size="small"
            onClick={(event) => {
              event.stopPropagation();
              onEdit(line);
            }}
          >
            编辑
          </Button>
          <Button
            size="small"
            onClick={(event) => {
              event.stopPropagation();
              onDetail(line);
            }}
          >
            详情
          </Button>
          {canLineManage && menuItems.length > 0 && (
            <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
              <Button
                size="small"
                icon={<MoreOutlined />}
                onClick={(event) => {
                  event.stopPropagation();
                }}
              />
            </Dropdown>
          )}
        </Space>
      }
    >
      <Space direction="vertical" size={4} className="w-full">
        <Typography.Text type="secondary">电压等级：{line.voltage_kv ?? "-"} kV</Typography.Text>
        <Typography.Text type="secondary">杆塔总数：{line.tower_count}</Typography.Text>
        <Typography.Text type="secondary">
          估算长度：{line.estimated_length_km != null && line.estimated_length_km > 0 ? `${line.estimated_length_km.toFixed(2)} km` : "-"}
        </Typography.Text>
        <Typography.Text type="secondary">
          更新时间：{new Date(line.update_date).toLocaleString()}
        </Typography.Text>
      </Space>
    </Card>
  );
}

interface PowerLineTableProps {
  lines: LineSummary[];
  canLineManage: boolean;
  onEdit: (line: LineSummary) => void;
  onDetail: (line: LineSummary) => void;
  onDelete: (line: LineSummary) => void;
  deleteLoading: boolean;
}

function PowerLineTable({ lines, canLineManage, onEdit, onDetail, onDelete, deleteLoading }: PowerLineTableProps) {
  const columns: ColumnsType<LineSummary> = [
    {
      title: "线路编码",
      dataIndex: "code",
      key: "code",
      width: 120,
    },
    {
      title: "线路名称",
      dataIndex: "name",
      key: "name",
      flex: 1,
    },
    {
      title: "电压等级",
      dataIndex: "voltage_kv",
      key: "voltage_kv",
      width: 100,
      render: (value: number | null) => `${value ?? "-"} kV`,
    },
    {
      title: "杆塔总数",
      dataIndex: "tower_count",
      key: "tower_count",
      width: 100,
      align: "right" as const,
    },
    {
      title: "估算长度",
      dataIndex: "estimated_length_km",
      key: "estimated_length_km",
      width: 120,
      render: (value: number | null) =>
        value != null && value > 0 ? `${value.toFixed(2)} km` : "-",
    },
    {
      title: "更新时间",
      dataIndex: "update_date",
      key: "update_date",
      width: 180,
      render: (value: string) => new Date(value).toLocaleString(),
    },
    {
      title: "操作",
      key: "actions",
      width: 160,
      fixed: "right" as const,
      render: (_, line) => {
        const menuItems: MenuProps["items"] = canLineManage
          ? [
              {
                key: "delete",
                label: "删除",
                danger: true,
                onClick: () => onDelete(line),
              },
            ]
          : [];

        return (
          <Space size={4}>
            <Button
              size="small"
              onClick={() => onEdit(line)}
            >
              编辑
            </Button>
            <Button
              size="small"
              onClick={() => onDetail(line)}
            >
              详情
            </Button>
            {canLineManage && menuItems.length > 0 && (
              <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            )}
          </Space>
        );
      },
    },
  ];

  return (
    <Table<LineSummary>
      rowKey="id"
      columns={columns}
      dataSource={lines}
      pagination={false}
      tableLayout="fixed"
    />
  );
}

interface PowerLineDetailViewProps {
  lineId: string;
  fetchWithAuth: (url: string, options?: RequestInit) => Promise<Response>;
  canTowerRead: boolean;
  canLineManage: boolean;
  onLineDeleted: () => Promise<void>;
}

function PowerLineDetailView({ lineId, fetchWithAuth, canTowerRead, canLineManage, onLineDeleted }: PowerLineDetailViewProps) {
  const [lineDetail, setLineDetail] = useState<LineSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    const fetchDetail = async () => {
      try {
        setLoading(true);
        const response = await fetchWithAuth(`/api/v1/lines/${lineId}`);
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const data = (await response.json()) as LineSummary;
        setLineDetail(data);
        setError("");
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载详情失败");
      } finally {
        setLoading(false);
      }
    };
    void fetchDetail();
  }, [lineId, fetchWithAuth]);

  if (loading) {
    return <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[280px]" />;
  }

  if (error || !lineDetail) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="danger">{error || "加载详情失败"}</Typography.Text>
        </Space>
      </Card>
    );
  }

  return (
    <div className="admin-power-lines-detail-view">
      <Card title="线路详情">
        <Space direction="vertical" size={12} className="w-full">
          <Typography.Text>线路编码：{lineDetail.code}</Typography.Text>
          <Typography.Text>线路名称：{lineDetail.name}</Typography.Text>
          <Typography.Text>电压等级：{lineDetail.voltage_kv ?? "-"} kV</Typography.Text>
          <Typography.Text>杆塔总数：{lineDetail.tower_count}</Typography.Text>
          <Typography.Text>
            估算长度：{lineDetail.estimated_length_km != null && lineDetail.estimated_length_km > 0 ? `${lineDetail.estimated_length_km.toFixed(2)} km` : "-"}
          </Typography.Text>
          <Typography.Text>更新时间：{new Date(lineDetail.update_date).toLocaleString()}</Typography.Text>
        </Space>
      </Card>
    </div>
  );
}