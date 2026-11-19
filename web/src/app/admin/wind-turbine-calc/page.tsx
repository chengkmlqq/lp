"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Progress,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  DeleteOutlined,
  DownloadOutlined,
  EyeOutlined,
  PlusOutlined,
  ReloadOutlined,
  SearchOutlined,
  StopOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindTurbineCalcCreateResponse,
  WindTurbineCalcEngineInfo,
  WindTurbineCalcJobListResponse,
  WindTurbineCalcJobSummary,
} from "@/types/wind-turbine-calc";
import { DEFAULT_ANGLES, DEFAULT_RADII } from "@/types/wind-turbine-calc";

const { Text, Paragraph } = Typography;
const API_BASE = "/api/v1/wind-turbine-calc";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function parseNumberList(text: string): number[] {
  return text
    .split(/[,，\s]+/)
    .map((v) => v.trim())
    .filter(Boolean)
    .map(Number);
}

export default function WindTurbineCalcListPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_turbine_calc.read") || hasPermission("wind_turbine_calc.manage");
  const canManage = hasPermission("wind_turbine_calc.manage");

  const queryClient = useQueryClient();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [createOpen, setCreateOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm();

  useEffect(() => setPage(1), [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-turbine-calc", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (statusFilter) params.set("status", statusFilter);
      return getJson<WindTurbineCalcJobListResponse>(`${API_BASE}?${params.toString()}`);
    },
    refetchInterval: (queryResult) => {
      const items = queryResult.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing") ? 4000 : false;
    },
  });

  const engineQuery = useQuery({
    queryKey: ["wind-turbine-calc", "engine"],
    enabled: Boolean(user) && canRead,
    queryFn: () => getJson<WindTurbineCalcEngineInfo>(`${API_BASE}/engine`),
  });

  const refreshList = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-turbine-calc"] });
  }, [queryClient]);

  const openCreate = useCallback(() => {
    form.resetFields();
    form.setFieldsValue({
      name: "",
      hub_height: 105.5,
      receptor_radii: DEFAULT_RADII.join(", "),
      blade_length: undefined,
      start_current: 1,
      angle_list: DEFAULT_ANGLES.join(", "),
    });
    setCreateOpen(true);
  }, [form]);

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    const radii = parseNumberList(values.receptor_radii);
    const angles = parseNumberList(values.angle_list);
    if (radii.length === 0) {
      message.error(t("接闪器径向位置不能为空"));
      return;
    }
    if (angles.length === 0 || angles.length > 36) {
      message.error(t("旋转角数量须在 1~36 之间"));
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        name: values.name || "",
        hub_height: Number(values.hub_height),
        receptor_radii: radii,
        blade_length: values.blade_length === undefined || values.blade_length === null ? null : Number(values.blade_length),
        start_current: Number(values.start_current),
        angle_list: angles,
      };
      const response = await fetchWithAuth(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindTurbineCalcCreateResponse;
      message.success(t("已提交单风机计算任务"));
      setCreateOpen(false);
      refreshList();
      router.push(`/admin/wind-turbine-calc/${result.job_id}`);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [fetchWithAuth, form, message, refreshList, router, t]);

  const handleCancel = useCallback(
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("取消该计算任务？"),
        content: t("取消会真正终止 MATLAB Runtime 进程组，已产生的结果不会保留。"),
        okText: t("取消任务"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}/cancel`, { method: "POST" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已发送取消请求"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const handleDelete = useCallback(
    (record: WindTurbineCalcJobSummary) => {
      modal.confirm({
        title: t("删除该计算任务？"),
        content: t("删除后不可恢复。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("返回"),
        onOk: async () => {
          const response = await fetchWithAuth(`${API_BASE}/${record.id}`, { method: "DELETE" });
          if (!response.ok) {
            message.error(await readApiError(response));
            return;
          }
          message.success(t("已删除"));
          refreshList();
        },
      });
    },
    [fetchWithAuth, message, modal, refreshList, t],
  );

  const columns = useMemo<TableColumnsType<WindTurbineCalcJobSummary>>(
    () => [
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        render: (name: string, record) => (
          <Link href={`/admin/wind-turbine-calc/${record.id}`}>{name || record.id.slice(0, 8)}</Link>
        ),
      },
      {
        title: t("参数摘要"),
        key: "params",
        render: (_: unknown, record) => (
          <div style={{ fontSize: 12, lineHeight: 1.5 }}>
            <div>h={record.hub_height} · R={record.blade_length} · Ic={record.start_current}</div>
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              r=[{record.receptor_radii?.join(", ")}]
            </Text>
            <Text type="secondary" ellipsis style={{ maxWidth: 260, display: "block" }}>
              θ=[{record.angle_list?.join(", ")}]
            </Text>
          </div>
        ),
      },
      {
        title: t("引擎版本"),
        key: "engine",
        render: (_: unknown, record) => record.engine_version_tag || record.engine_version_hash?.slice(0, 8) || "-",
      },
      {
        title: t("平均失效率"),
        dataIndex: "mean_failure_rate",
        key: "mean_failure_rate",
        render: (v: number | null) => (v === null ? "-" : v.toExponential(9)),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        render: (status: string, record) => (
          <Space direction="vertical" size={0}>
            <Tag color={STATUS_META[status]?.color ?? "default"}>{STATUS_META[status]?.label ?? status}</Tag>
            {(record.status === "processing" || record.status === "pending") && (
              <Progress percent={record.progress} size="small" style={{ width: 90 }} showInfo={false} />
            )}
          </Space>
        ),
      },
      {
        title: t("耗时"),
        dataIndex: "duration_seconds",
        key: "duration_seconds",
        render: (v: number | null) => formatDuration(v),
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        render: (v: string | null) => formatDateTime(v),
      },
      {
        title: t("操作"),
        key: "actions",
        fixed: "right",
        render: (_: unknown, record) => (
          <Space size={4}>
            <Link href={`/admin/wind-turbine-calc/${record.id}`}>
              <Button type="link" size="small" icon={<EyeOutlined />} />
            </Link>
            <Button
              type="link"
              size="small"
              icon={<DownloadOutlined />}
              title={t("导出 CSV")}
              onClick={() => {
                window.location.href = `${API_BASE}/${record.id}/export?type=csv`;
              }}
            />
            {(record.status === "processing" || record.status === "pending") && canManage && (
              <Button type="link" size="small" danger icon={<StopOutlined />} onClick={() => handleCancel(record)} />
            )}
            {record.status !== "processing" && record.status !== "pending" && canManage && (
              <Button type="link" size="small" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record)} />
            )}
          </Space>
        ),
      },
    ],
    [t, canManage, handleCancel, handleDelete],
  );

  const engine = engineQuery.data;

  return (
    <div style={{ padding: 24 }}>
      <Card
        title={<span style={{ fontSize: 18 }}>{t("单风机计算")}</span>}
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={refreshList}>
              {t("刷新")}
            </Button>
            {canManage && (
              <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
                {t("新建计算")}
              </Button>
            )}
          </Space>
        }
      >
        {engine && (
          <Alert
            type={engine.exe_exists || engine.launch_script_exists ? "success" : "warning"}
            showIcon
            style={{ marginBottom: 16 }}
            message={t("引擎状态")}
            description={
              <div style={{ fontSize: 12 }}>
                <div>
                  {t("模块")}: {engine.module_slug} · {t("队列")}: matlab-wind · {t("目录")}: {engine.configured_dir}
                </div>
                <div>
                  {t("已发布版本")}: {engine.active_version_tag || engine.active_version_hash || "-"} ·{" "}
                  {t("Runtime")}: {engine.runtime_version || "-"}
                </div>
                {engine.message && <div>{engine.message}</div>}
                <Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
                  {t("提示：角度击距公式在 0–90° 拟合，其余姿态为外推。")}
                </Paragraph>
              </div>
            }
          />
        )}

        <Space style={{ marginBottom: 16 }}>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder={t("搜索任务名称 / ID")}
            value={keywordInput}
            onChange={(e) => setKeywordInput(e.target.value)}
            onPressEnter={() => setKeyword(keywordInput.trim())}
            style={{ width: 260 }}
          />
          <Button onClick={() => setKeyword(keywordInput.trim())}>{t("搜索")}</Button>
          <Select
            allowClear
            placeholder={t("状态筛选")}
            value={statusFilter}
            onChange={setStatusFilter}
            style={{ width: 150 }}
            options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.label }))}
          />
        </Space>

        <Table<WindTurbineCalcJobSummary>
          rowKey="id"
          columns={columns}
          dataSource={listQuery.data?.items ?? []}
          loading={listQuery.isLoading}
          pagination={false}
          scroll={{ x: 1180 }}
          locale={{ emptyText: <Empty description={t("暂无任务")} /> }}
        />
        <ModoPagination
          current={page}
          pageSize={pageSize}
          total={listQuery.data?.total ?? 0}
          showSizeChanger
          pageSizeOptions={[10, 20, 50, 100]}
          onChange={(nextPage, nextSize) => {
            setPage(nextPage);
            if (nextSize && nextSize !== pageSize) {
              setPageSize(nextSize);
              setPage(1);
            }
          }}
        />
      </Card>

      <Modal
        open={createOpen}
        title={t("新建单风机计算")}
        onCancel={() => setCreateOpen(false)}
        onOk={handleSubmit}
        confirmLoading={submitting}
        okText={t("提交")}
        cancelText={t("取消")}
        width={640}
        destroyOnClose
      >
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("参数说明")}
          description={t(
            "轮毂高度 h、接闪器径向位置 r_list（严格递增，0<r≤R）、叶片长度 R（默认 max(r_list)）、起始雷电流 Ic、旋转角列表（≤36 个）。",
          )}
        />
        <Form form={form} layout="vertical">
          <Form.Item label={t("任务名称")} name="name">
            <Input placeholder={t("可选")} />
          </Form.Item>
          <Form.Item
            label={t("轮毂高度 h (m)")}
            name="hub_height"
            rules={[{ required: true, message: t("请输入轮毂高度") }, { type: "number", min: 0.0001, message: t("h 必须大于 0") }]}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("接闪器径向位置 r_list (m)")}
            name="receptor_radii"
            rules={[{ required: true, message: t("请输入接闪器径向位置") }]}
            extra={t("逗号分隔，须严格递增")}
          >
            <Input />
          </Form.Item>
          <Form.Item
            label={t("叶片长度 R (m)")}
            name="blade_length"
            extra={t("留空则取 max(r_list)")}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("起始雷电流 Ic (kA)")}
            name="start_current"
            rules={[{ required: true, message: t("请输入起始雷电流") }, { type: "number", min: 0.0001, message: t("Ic 必须大于 0") }]}
          >
            <InputNumber style={{ width: "100%" }} min={0.0001} step={0.1} />
          </Form.Item>
          <Form.Item
            label={t("旋转角列表 (deg)")}
            name="angle_list"
            rules={[{ required: true, message: t("请输入旋转角列表") }]}
            extra={t("逗号分隔，最多 36 个，默认 0–110 步长 10")}
          >
            <Input />
          </Form.Item>
        </Form>

        <Descriptions size="small" column={1} style={{ marginTop: 8 }}>
          <Descriptions.Item label={t("外推提示")}>
            <Text type="secondary">{t("角度击距公式只在 0–90° 拟合，其余姿态按外推处理。")}</Text>
          </Descriptions.Item>
        </Descriptions>
      </Modal>
    </div>
  );
}
