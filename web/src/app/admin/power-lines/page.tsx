"use client";
import Link from "next/link";
import dayjs from "dayjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Descriptions,
  Dropdown,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Radio,
  Segmented,
  Select,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
  Alert,
  type MenuProps,
} from "antd";
import {
  ApartmentOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  DeploymentUnitOutlined,
  EditOutlined,
  EyeOutlined,
  GlobalOutlined,
  MoreOutlined,
  SearchOutlined,
  SwapOutlined,
  TableOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useMemo, useState, useEffect, useRef, type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { PowerLineCesiumMap } from "@/components/power-line-cesium-map";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { useMobileDetection } from "@/hooks/use-mobile-detection";
import { readApiError } from "@/lib/api";
import type { LineListResponse, LineSummary, LineTowerImportResponse, LineTowerListResponse, LineTowerSummary } from "@/types/auth";

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

const TOWER_TYPE_OPTIONS = [
  { value: "", label: "全部塔型" },
  { value: "直线", label: "直线" },
  { value: "耐张", label: "耐张" },
] as const;

const TOWER_TABLE_DEFAULT_PAGE_SIZE = 20;
const TOWER_MAP_QUERY_LIMIT = 500;
const POWER_LINES_PANEL_MIN_HEIGHT = 360;
const POWER_LINES_MAP_MIN_HEIGHT = 240;
const POWER_LINES_TABLE_MIN_SCROLL_Y = 180;
const POWER_LINES_TABLE_ESTIMATED_HEADER_HEIGHT = 56;
const POWER_LINES_TABLE_ESTIMATED_PAGINATION_HEIGHT = 64;
const POWER_LINES_TABLE_BOTTOM_GAP = 8;

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = dayjs(value);
  if (!parsed.isValid()) {
    return "-";
  }
  return parsed.format("YYYY-MM-DD HH:mm:ss");
}

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
  const [tableScrollY, setTableScrollY] = useState(POWER_LINES_TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  const canLineManage = hasPermission("line.manage");
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage");
  const canTowerManage = hasPermission("tower.manage");
  const canRead = canLineRead || canTowerRead;

  const updateTableScrollHeight = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const anchorHeight = anchor.getBoundingClientRect().height;
    const header = anchor.querySelector<HTMLElement>(".ant-table-header");
    const pagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = header?.getBoundingClientRect().height ?? POWER_LINES_TABLE_ESTIMATED_HEADER_HEIGHT;
    const paginationHeight = pagination?.getBoundingClientRect().height ?? POWER_LINES_TABLE_ESTIMATED_PAGINATION_HEIGHT;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - POWER_LINES_TABLE_BOTTOM_GAP);
    const clampedHeight = Math.max(POWER_LINES_TABLE_MIN_SCROLL_Y, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
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

  useEffect(() => {
    const frameId = window.requestAnimationFrame(updateTableScrollHeight);
    return () => {
      window.cancelAnimationFrame(frameId);
    };
  }, [updateTableScrollHeight, viewMode, lines.length]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollHeight);
    });
    resizeObserver.observe(anchor);
    return () => {
      resizeObserver.disconnect();
    };
  }, [updateTableScrollHeight, viewMode, lines.length]);

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
              canTowerManage={canTowerManage}
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
  }, [fetchWithAuth, canTowerRead, canTowerManage, canLineManage, refreshLines]);

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
          <Space>
            {canLineManage && (
              <Button type="primary" onClick={openCreateLineModal}>
                新建线路
              </Button>
            )}
          </Space>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: <span className="admin-power-lines-tab-title">线路管理</span>,
            closable: false,
            children: (
              <div className="admin-power-lines-list-pane">
                <div className="admin-filter-bar">
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
                  <>
                    <div className="admin-power-lines-card-scroll">
                      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
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
                    <div className="admin-power-lines-pagination">
                      <Pagination
                        current={pagination.current}
                        pageSize={pagination.pageSize}
                        total={total}
                        onChange={(page, pageSize) => {
                          setPagination({ current: page, pageSize });
                        }}
                        showSizeChanger
                        showTotal={(total) => `共 ${total} 条`}
                      />
                    </div>
                  </>
                ) : (
                  <div
                    ref={tableScrollAnchorRef}
                    className="admin-power-lines-table-view"
                    style={{ "--admin-power-lines-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
                  >
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
                      scrollY={tableScrollY}
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
  return (
    <Card
      size="small"
      hoverable
      className="admin-power-lines-line-card"
      onClick={() => onDetail(line)}
    >
      <div className="flex flex-col gap-3">
        <div className="flex items-center gap-2 pb-2 border-b border-gray-200">
          <DeploymentUnitOutlined className="text-base text-gray-500" />
          <Typography.Text strong className="truncate">{line.name}</Typography.Text>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            <ThunderboltOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">电压等级：{line.voltage_kv ?? "-"} kV</Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <ApartmentOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">杆塔总数：{line.tower_count}</Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <SwapOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">
              估算长度：{line.estimated_length_km != null && line.estimated_length_km > 0 ? `${line.estimated_length_km.toFixed(2)} km` : "-"}
            </Typography.Text>
          </div>
          <div className="flex items-center gap-2">
            <ClockCircleOutlined className="text-xs text-gray-500" />
            <Typography.Text type="secondary" className="text-xs">
              更新时间：{formatDateTime(line.update_date)}
            </Typography.Text>
          </div>
        </div>

        <div className="flex justify-end pt-2 border-t border-gray-200">
          <Space size="small">
            <Button
              type="text"
              size="small"
              icon={<EyeOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onDetail(line);
              }}
            />
            <Button
              type="text"
              size="small"
              icon={<EditOutlined />}
              onClick={(event) => {
                event.stopPropagation();
                onEdit(line);
              }}
            />
            {canLineManage && (
              <Button
                type="text"
                size="small"
                danger
                icon={<DeleteOutlined />}
                loading={deleteLoading}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete();
                }}
              />
            )}
          </Space>
        </div>
      </div>
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
  scrollY?: number;
}

function PowerLineTable({ lines, canLineManage, onEdit, onDetail, onDelete, deleteLoading, scrollY = POWER_LINES_TABLE_MIN_SCROLL_Y }: PowerLineTableProps) {
  const columns: ColumnsType<LineSummary> = [
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
      render: (value: string) => formatDateTime(value),
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
      pagination={{
        hideOnSinglePage: false,
        showSizeChanger: true,
        pageSizeOptions: [6, 12, 24, 48],
        showTotal: (total) => `共 ${total} 条`,
      }}
      scroll={{ x: 1080, y: scrollY }}
      tableLayout="fixed"
    />
  );
}

interface PowerLineDetailViewProps {
  lineId: string;
  fetchWithAuth: (url: string, options?: RequestInit) => Promise<Response>;
  canTowerRead: boolean;
  canTowerManage: boolean;
  canLineManage: boolean;
  onLineDeleted: () => Promise<void>;
}

function PowerLineDetailView({ lineId, fetchWithAuth, canTowerRead, canTowerManage, canLineManage, onLineDeleted }: PowerLineDetailViewProps) {
  const { message: messageApi } = App.useApp();
  const queryClient = useQueryClient();
  const importInputRef = useRef<HTMLInputElement | null>(null);
  const [lineDetail, setLineDetail] = useState<LineSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [towerKeyword, setTowerKeyword] = useState("");
  const [towerTypeFilter, setTowerTypeFilter] = useState("");
  const [towerPagination, setTowerPagination] = useState({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE });
  const [towerViewMode, setTowerViewMode] = useState<"table" | "map">("table");

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

  const towerListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(TOWER_TABLE_DEFAULT_PAGE_SIZE));
    params.set("offset", String((towerPagination.current - 1) * TOWER_TABLE_DEFAULT_PAGE_SIZE));
    if (towerKeyword.trim()) {
      params.set("keyword", towerKeyword.trim());
    }
    if (towerTypeFilter) {
      params.set("tower_type", towerTypeFilter);
    }
    const query = params.toString();
    return `/api/v1/lines/${lineId}/towers${query ? `?${query}` : ""}`;
  }, [lineId, towerKeyword, towerTypeFilter, towerPagination]);

  const towersQuery = useQuery({
    queryKey: [towerListPath],
    enabled: !!canTowerRead && !!lineDetail,
    queryFn: async () => {
      const response = await fetchWithAuth(towerListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const towers = useMemo(() => towersQuery.data?.items ?? [], [towersQuery.data?.items]);

  const refreshLines = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lines"),
    });
  }, [queryClient]);
  const refreshTowers = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].includes("/towers"),
    });
  }, [queryClient]);
  const importMutation = useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerImportResponse;
    },
    onSuccess: async (result) => {
      messageApi.success(
        `导入完成：新增 ${result.imported_count} 条，更新 ${result.updated_count} 条，跳过 ${result.skipped_count} 条`,
      );
      await refreshLines();
      await refreshTowers();
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "导入失败");
    },
  });
  const exportMutation = useMutation({
    mutationFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/export`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const contentDisposition = response.headers.get("Content-Disposition") || "";
      const matched = contentDisposition.match(/filename=\"([^\"]+)\"/i);
      const filename = matched?.[1] ?? "towers_export.csv";
      return { blob, filename };
    },
    onSuccess: ({ blob, filename }) => {
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
      messageApi.success("导出成功");
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "导出失败");
    },
  });

  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: "序号", dataIndex: "seq_no", width: 80 },
    {
      title: "塔号",
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: "模型", dataIndex: "tower_model", width: 180, render: (value: string | null) => value || "-" },
    { title: "塔型", dataIndex: "tower_type", width: 100, render: (value: string | null) => value || "-" },
    {
      title: "坐标",
      key: "geo",
      width: 200,
      render: (_: unknown, row) =>
        row.longitude !== null && row.latitude !== null
          ? `${row.longitude.toFixed(6)}, ${row.latitude.toFixed(6)}`
          : "-",
    },
    { title: "接地电阻", dataIndex: "ground_resistance_ohm", width: 100, render: (value: number | null) => value ?? "-" },
    { title: "地闪密度", dataIndex: "lightning_density", width: 100, render: (value: number | null) => value ?? "-" },
    {
      title: "风险等级",
      dataIndex: "risk_level",
      width: 100,
      render: (value: string | null) => {
        if (!value) return "-";
        const riskLevel = value.trim();
        let color = "default";
        if (riskLevel === "1") {
          color = "green";
        } else if (riskLevel === "2") {
          color = "orange";
        } else if (riskLevel === "3") {
          color = "red";
        }
        return <Tag color={color}>{value}</Tag>;
      },
    },
    {
      title: "更新时间",
      dataIndex: "update_date",
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
  ];

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
      <Card size="small" className="admin-power-line-detail-meta">
        <Descriptions bordered size="small" column={3}>
          <Descriptions.Item label="线路编码">{lineDetail.code || "-"}</Descriptions.Item>
          <Descriptions.Item label="线路名称">{lineDetail.name || "-"}</Descriptions.Item>
          <Descriptions.Item label="电压等级">{lineDetail.voltage_kv ?? "-"} kV</Descriptions.Item>
          <Descriptions.Item label="杆塔总数">{lineDetail.tower_count}</Descriptions.Item>
          <Descriptions.Item label="估算长度">
            {lineDetail.estimated_length_km != null && lineDetail.estimated_length_km > 0 ? `${lineDetail.estimated_length_km.toFixed(2)} km` : "-"}
          </Descriptions.Item>
          <Descriptions.Item label="更新时间">{formatDateTime(lineDetail.update_date)}</Descriptions.Item>
        </Descriptions>
      </Card>
      <div className="mb-3 flex items-center justify-between gap-3">
        <Space size={8} wrap>
          <Space.Compact size="small">
            {canTowerManage && (
              <Button onClick={() => importInputRef.current?.click()} loading={importMutation.isPending}>
                导入 CSV
              </Button>
            )}
            <input
              ref={importInputRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  const maxMB = 50;
                  const allowedExts = ["csv"];
                  const ext = file.name.split(".").pop()?.toLowerCase() || "";
                  if (file.size > maxMB * 1024 * 1024) {
                    messageApi.error(`文件大小超过 ${maxMB}MB 限制，请压缩后重新上传`);
                    event.target.value = "";
                    return;
                  }
                  if (!allowedExts.includes(ext)) {
                    messageApi.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
                    event.target.value = "";
                    return;
                  }
                  importMutation.mutate(file);
                }
                event.target.value = "";
              }}
            />
            {canTowerRead && (
              <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
                导出 CSV
              </Button>
            )}
          </Space.Compact>
        </Space>
        <Radio.Group
          value={towerViewMode}
          onChange={(e) => setTowerViewMode(e.target.value as "table" | "map")}
          optionType="button"
          buttonStyle="solid"
          size="small"
        >
          <Radio.Button value="map" title="地图">
            <GlobalOutlined />
          </Radio.Button>
          <Radio.Button value="table" title="杆塔列表">
            <TableOutlined />
          </Radio.Button>
        </Radio.Group>
      </div>
      <div style={{ display: towerViewMode === "table" ? "block" : "none" }}>
        <Space direction="vertical" size={12} className="w-full">
          <div className="admin-filter-bar">
            <Form layout="inline">
              <Form.Item label="关键词" className="admin-filter-keyword-item">
                <Input value={towerKeyword} allowClear onChange={(event) => setTowerKeyword(event.target.value)} placeholder="按塔号/模型筛选" />
              </Form.Item>
              <Form.Item label="塔型" className="admin-filter-keyword-item">
                <Select value={towerTypeFilter} options={[...TOWER_TYPE_OPTIONS]} onChange={(value) => setTowerTypeFilter(value)} />
              </Form.Item>
              <Form.Item>
                <Button htmlType="button" icon={<SearchOutlined />} onClick={() => setTowerPagination({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE })} className="admin-search-btn">
                  查询
                </Button>
              </Form.Item>
            </Form>
          </div>
          <div className="relative">
            <Table<LineTowerSummary>
              rowKey={(row) => row.id}
              columns={towerColumns}
              dataSource={towers}
              loading={towersQuery.isFetching}
              pagination={{
                current: towerPagination.current,
                pageSize: towerPagination.pageSize,
                total: towersQuery.data?.total ?? 0,
                showSizeChanger: true,
                showTotal: (total) => `共 ${total} 条`,
                hideOnSinglePage: false,
                onChange: (page, pageSize) => {
                  setTowerPagination({ current: page, pageSize });
                },
              }}
              scroll={{ x: 1400 }}
            />
          </div>
        </Space>
      </div>
      <div style={{ display: towerViewMode === "map" ? "block" : "none" }}>
        <div className="flex flex-col gap-3">
          <PowerLineCesiumMap
            lineCode={lineDetail.code}
            lineName={lineDetail.name}
            towers={towers}
            terrainDataset={null}
            accessToken=""
            exaggeration={1}
            loading={towersQuery.isFetching}
            height={500}
          />
        </div>
      </div>
    </div>
  );
}