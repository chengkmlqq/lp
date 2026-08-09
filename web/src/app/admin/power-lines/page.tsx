"use client";
import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Typography,
} from "antd";
import { SearchOutlined } from "@ant-design/icons";
import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { readApiError } from "@/lib/api";
import type { LineListResponse, LineSummary } from "@/types/auth";

type LineFormValues = {
  name: string;
  voltage_level: string | null;
};

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
  const [lineForm] = Form.useForm<LineFormValues>();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [pagination, setPagination] = useState({ current: 1, pageSize: 12 });
  const { current: paginationCurrent, pageSize: paginationPageSize } = pagination;
  const [lineModalOpen, setLineModalOpen] = useState(false);
  const [editingLine, setEditingLine] = useState<LineSummary | null>(null);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
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
      router.push("/admin/power-lines");
    },
    onError: (candidate) => {
      setError(candidate instanceof Error ? candidate.message : "删除线路失败");
    },
  });
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
      <Card
        className="admin-power-lines-card"
        title="线路管理"
        extra={canLineManage ? (
          <Button type="primary" onClick={openCreateLineModal}>
            新建线路
          </Button>
        ) : null}
      >
        <div className="admin-power-lines-card-body">
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
            </div>
            {lines.length === 0 ? (
              <Empty description="暂无线路数据" image={Empty.PRESENTED_IMAGE_SIMPLE} />
            ) : (
              <div className="admin-power-lines-card-scroll">
                <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {lines.map((line) => (
                    <Card
                      key={line.id}
                      size="small"
                      hoverable
                      onClick={() => router.push(`/admin/power-lines/${line.id}`)}
                      title={<Typography.Text strong>{line.name}</Typography.Text>}
                      extra={canLineManage ? (
                        <Space size={4}>
                          <Button
                            size="small"
                            onClick={(event) => {
                              event.stopPropagation();
                              openEditLineModal(line);
                            }}
                          >
                            编辑
                          </Button>
                          <Button
                            size="small"
                            onClick={() => router.push(`/admin/power-lines/${line.id}`)}
                          >
                            详情
                          </Button>
                          <Button
                            size="small"
                            danger
                            loading={deleteLineMutation.isPending}
                            onClick={(event) => {
                              event.stopPropagation();
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
                          >
                            删除
                          </Button>
                        </Space>
                      ) : (
                        <Button
                          size="small"
                          onClick={(event) => {
                            event.stopPropagation();
                            router.push(`/admin/power-lines/${line.id}`);
                          }}
                        >
                          详情
                        </Button>
                      )}
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
                  ))}
                </div>
              </div>
            )}
            {total > 0 && (
              <div className="admin-power-lines-pagination">
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
      </Card>
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