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
  Modal,
  Progress,
  Select,
  Space,
  Steps,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "antd";
import {
  ApiOutlined,
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
import { ModoTabs } from "@/components/biz/modo-tabs";
import { downloadFileWithAuth, getJson, readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type {
  WindFarmCalcCreateResponse,
  WindFarmCalcEngineInfo,
  WindFarmCalcJobListResponse,
  WindFarmCalcJobSummary,
  WindFarmCalcPrepBatchOptions,
} from "@/types/wind-farm-calc";
import { RISK_COLORS, RISK_LABELS } from "@/types/wind-farm-calc";

const { Text, Paragraph } = Typography;
const API_BASE = "/api/v1/wind-farm-calc";
const LIST_TAB_KEY = "list";

const STATUS_META: Record<string, { color: string; label: string }> = {
  pending: { color: "default", label: "待处理" },
  processing: { color: "processing", label: "计算中" },
  completed: { color: "success", label: "已完成" },
  failed: { color: "error", label: "失败" },
  cancelled: { color: "warning", label: "已取消" },
};

const RISK_COUNT_KEYS: Record<number, keyof WindFarmCalcJobSummary> = {
  1: "risk_I_count",
  2: "risk_II_count",
  3: "risk_III_count",
  4: "risk_IV_count",
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const pad = (input: number) => String(input).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const total = Math.round(seconds);
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${secs}s`;
  return `${secs}s`;
}

function formatBytes(size: number | null | undefined): string {
  if (!size && size !== 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export default function WindFarmCalcListPage() {
  const { t } = useI18n();
  const router = useRouter();
  const { message, modal } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("wind_farm_calc.read") || hasPermission("wind_farm_calc.manage");
  const canManage = hasPermission("wind_farm_calc.manage");

  const queryClient = useQueryClient();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [createOpen, setCreateOpen] = useState(false);
  const [step, setStep] = useState(0);
  const [form] = Form.useForm<{ prep_batch_id: string; name: string }>();
  const [selectedBatchId, setSelectedBatchId] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => setPage(1), [keyword, statusFilter]);

  const listQuery = useQuery({
    queryKey: ["wind-farm-calc", keyword, statusFilter, page, pageSize],
    enabled: Boolean(user) && canRead,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((page - 1) * pageSize));
      if (keyword.trim()) params.set("keyword", keyword.trim());
      if (statusFilter) params.set("status", statusFilter);
      return getJson<WindFarmCalcJobListResponse>(`${API_BASE}?${params.toString()}`);
    },
    refetchInterval: (queryResult) => {
      const items = queryResult.state.data?.items ?? [];
      return items.some((item) => item.status === "pending" || item.status === "processing") ? 4000 : false;
    },
  });

  const engineQuery = useQuery({
    queryKey: ["wind-farm-calc", "engine"],
    enabled: Boolean(user) && canRead,
    queryFn: () => getJson<WindFarmCalcEngineInfo>(`${API_BASE}/engine`),
  });

  const batchesQuery = useQuery({
    queryKey: ["wind-farm-calc", "prep-batches"],
    enabled: createOpen && Boolean(user) && canRead,
    queryFn: () => getJson<WindFarmCalcPrepBatchOptions>(`${API_BASE}/prep-batches`),
  });

  const refreshList = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["wind-farm-calc"] });
  }, [queryClient]);

  const openCreate = useCallback(() => {
    setStep(0);
    setSelectedBatchId(undefined);
    form.resetFields();
    setCreateOpen(true);
  }, [form]);

  const selectedBatch = useMemo(
    () => batchesQuery.data?.items.find((item) => item.id === selectedBatchId),
    [batchesQuery.data, selectedBatchId],
  );

  const handleSubmit = useCallback(async () => {
    const values = await form.validateFields();
    if (!values.prep_batch_id) {
      message.warning(t("请选择数据准备批次"));
      return;
    }
    setSubmitting(true);
    try {
      const response = await fetchWithAuth(API_BASE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prep_batch_id: values.prep_batch_id, name: values.name || "" }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      const result = (await response.json()) as WindFarmCalcCreateResponse;
      message.success(t("已提交风电场计算任务"));
      setCreateOpen(false);
      refreshList();
      router.push(`/admin/wind-farm-calc/${result.job_id}`);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setSubmitting(false);
    }
  }, [fetchWithAuth, form, message, refreshList, router, t]);

  const handleCancel = useCallback(
    (record: WindFarmCalcJobSummary) => {
      modal.confirm({
        title: t("取消该计算任务？"),
        content: t("取消会终止正在运行的 Wine 进程组，已产生的结果不会保留。"),
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
    (record: WindFarmCalcJobSummary) => {
      modal.confirm({
        title: t("删除该计算任务？"),
        content: t("仅删除任务记录与本地临时工作目录；对象存储中的原始输入输出仍可追溯。"),
        okText: t("删除"),
        okButtonProps: { danger: true },
        cancelText: t("取消"),
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

  const columns = useMemo<TableColumnsType<WindFarmCalcJobSummary>>(
    () => [
      {
        title: t("任务名称"),
        dataIndex: "name",
        key: "name",
        width: 200,
        render: (_value, record) => (
          <Space direction="vertical" size={0}>
            <Link href={`/admin/wind-farm-calc/${record.id}`}>{record.name || record.id}</Link>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("来源批次")}: {record.prep_batch_id.slice(0, 12)}…
            </Text>
          </Space>
        ),
      },
      { title: t("风机数"), dataIndex: "turbine_count", key: "turbine_count", width: 80 },
      {
        title: t("风险分布 I/II/III/IV"),
        key: "risk",
        width: 170,
        render: (_value, record) => (
          <Space size={2}>
            {[1, 2, 3, 4].map((level) => (
              <Tag key={level} color={RISK_COLORS[level]} style={{ marginInlineEnd: 0 }}>
                {RISK_LABELS[level]} {record[RISK_COUNT_KEYS[level]] as number}
              </Tag>
            ))}
          </Space>
        ),
      },
      {
        title: t("状态"),
        dataIndex: "status",
        key: "status",
        width: 170,
        render: (value: string, record) => {
          const meta = STATUS_META[value] ?? STATUS_META.pending;
          return (
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <Tag color={meta.color}>{t(meta.label)}</Tag>
              {value === "processing" || value === "pending" ? (
                <Progress percent={record.progress} size="small" showInfo={false} />
              ) : null}
              {value === "failed" && record.error_message ? (
                <Text type="danger" style={{ fontSize: 12 }} ellipsis={{ tooltip: record.error_message }}>
                  {record.error_message}
                </Text>
              ) : null}
            </Space>
          );
        },
      },
      {
        title: t("耗时"),
        dataIndex: "duration_seconds",
        key: "duration_seconds",
        width: 90,
        render: (value: number | null) => formatDuration(value),
      },
      {
        title: t("创建时间"),
        dataIndex: "create_date",
        key: "create_date",
        width: 150,
        render: (value: string | null) => formatDateTime(value),
      },
      {
        title: t("操作"),
        key: "actions",
        width: 280,
        render: (_value, record) => (
          <Space size={4} wrap>
            <Button size="small" type="link" icon={<EyeOutlined />} onClick={() => router.push(`/admin/wind-farm-calc/${record.id}`)}>
              {t("详情")}
            </Button>
            {record.status === "completed" ? (
              <Button
                size="small"
                type="link"
                icon={<DownloadOutlined />}
                onClick={() => void downloadFileWithAuth(`${API_BASE}/${record.id}/export`, `${record.name || "wind-farm-calc"}-results.xlsx`)}
              >
                {t("导出 Excel")}
              </Button>
            ) : null}
            {(record.status === "processing" || record.status === "pending") && canManage ? (
              <Button size="small" type="link" danger icon={<StopOutlined />} onClick={() => handleCancel(record)}>
                {t("取消")}
              </Button>
            ) : null}
            {canManage ? (
              <Button size="small" type="link" danger icon={<DeleteOutlined />} onClick={() => handleDelete(record)}>
                {t("删除")}
              </Button>
            ) : null}
          </Space>
        ),
      },
    ],
    [canManage, handleCancel, handleDelete, router, t],
  );

  const createContent = (
    <>
      <Steps
        size="small"
        current={step}
        style={{ marginBottom: 20 }}
        items={[{ title: t("选择数据准备批次") }, { title: t("引擎预检") }, { title: t("确认提交") }]}
      />
      <Form<{ prep_batch_id: string; name: string }> form={form} layout="vertical">
        {step === 0 ? (
          <>
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("输入只来自已完成的「风电场数据准备」批次")}
              description={t("不开放直接上传 file_1~4 / P0.abc，以绕开数据校验。")}
            />
            <Form.Item label={t("数据准备批次")} name="prep_batch_id" rules={[{ required: true, message: t("请选择数据准备批次") }]}>
              <Select
                loading={batchesQuery.isLoading}
                placeholder={t("请选择已完成的批次")}
                onChange={(value) => setSelectedBatchId(value)}
                options={(batchesQuery.data?.items ?? []).map((item) => ({
                  value: item.id,
                  label: `${item.name || item.id}（${item.turbine_count} 台 · ${item.grid_nx}×${item.grid_ny}）`,
                }))}
              />
            </Form.Item>
            <Form.Item label={t("任务名称")} name="name">
              <Input maxLength={128} placeholder={t("留空时使用批次名称")} />
            </Form.Item>
          </>
        ) : null}

        {step === 1 ? (
          <>
            {selectedBatch ? (
              <Descriptions column={2} size="small" bordered style={{ marginBottom: 12 }}>
                <Descriptions.Item label={t("风机数")}>{selectedBatch.turbine_count}</Descriptions.Item>
                <Descriptions.Item label={t("网格")}>{selectedBatch.grid_nx} × {selectedBatch.grid_ny}</Descriptions.Item>
                <Descriptions.Item label={t("风险基准 S")}>{selectedBatch.risk_base_s}</Descriptions.Item>
                <Descriptions.Item label={t("五文件齐全度")}>{selectedBatch.files_ready}/5</Descriptions.Item>
              </Descriptions>
            ) : null}
            {engineQuery.data ? (
              <Alert
                type={engineQuery.data.exists && engineQuery.data.wine_available ? "success" : "error"}
                showIcon
                message={engineQuery.data.exists ? t("引擎已就绪") : t("引擎未部署")}
                description={
                  <div>
                    <div>{t("路径")}: {engineQuery.data.resolved || engineQuery.data.configured}</div>
                    <div>{t("大小")}: {formatBytes(engineQuery.data.size)} · MD5: {engineQuery.data.md5 || "-"}</div>
                    <div>
                      Wine: {engineQuery.data.wine_available ? engineQuery.data.wine_version : (engineQuery.data.wine_error || t("不可用"))}
                    </div>
                  </div>
                }
              />
            ) : (
              <Alert type="warning" showIcon message={t("无法获取引擎信息")} />
            )}
          </>
        ) : null}

        {step === 2 ? (
          <Paragraph>
            {t("将使用所选数据准备批次的五文件在 Wine 中调用核心程序，结果逐台落库。任务为小时级长任务，提交后可在详情页查看进度与日志。")}
          </Paragraph>
        ) : null}
      </Form>
    </>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        activeKey={LIST_TAB_KEY}
        className="modo-page-tabs"
        items={[
          {
            key: LIST_TAB_KEY,
            label: <>{t("风电场计算")}</>,
            closable: false,
            children: (
              <div className="modo-page-card">
                <Card size="small" title={<><ApiOutlined /> {t("引擎信息")}</>} style={{ marginBottom: 12 }}>
                  {engineQuery.data ? (
                    <Descriptions column={4} size="small">
                      <Descriptions.Item label={t("引擎路径")}>{engineQuery.data.resolved || engineQuery.data.configured}</Descriptions.Item>
                      <Descriptions.Item label={t("大小")}>{formatBytes(engineQuery.data.size)}</Descriptions.Item>
                      <Descriptions.Item label={t("修改时间")}>{formatDateTime(engineQuery.data.modified_at)}</Descriptions.Item>
                      <Descriptions.Item label="MD5">{engineQuery.data.md5 || "-"}</Descriptions.Item>
                      <Descriptions.Item label="Wine" span={4}>
                        <Tag color={engineQuery.data.wine_available ? "success" : "error"}>
                          {engineQuery.data.wine_available ? (engineQuery.data.wine_version || t("可用")) : t("不可用")}
                        </Tag>
                        {!engineQuery.data.exists ? <Text type="danger">{engineQuery.data.message}</Text> : null}
                      </Descriptions.Item>
                    </Descriptions>
                  ) : (
                    <Text type="secondary">{t("加载中…")}</Text>
                  )}
                </Card>

                <div className="admin-filter-bar">
                  <Form layout="inline">
                    <Form.Item label={t("关键字")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
                      <Input
                        allowClear
                        placeholder={t("任务名称 / ID")}
                        value={keywordInput}
                        onChange={(event) => setKeywordInput(event.target.value)}
                        onPressEnter={() => setKeyword(keywordInput)}
                      />
                    </Form.Item>
                    <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
                      <Select
                        allowClear
                        style={{ width: 140 }}
                        value={statusFilter}
                        onChange={(value) => setStatusFilter(value)}
                        options={(Object.keys(STATUS_META)).map((value) => ({ label: t(STATUS_META[value].label), value }))}
                      />
                    </Form.Item>
                    <Form.Item style={{ marginBottom: 0 }}>
                      <Space>
                        <Button icon={<SearchOutlined />} onClick={() => setKeyword(keywordInput)}>{t("查询")}</Button>
                        <Button icon={<ReloadOutlined />} onClick={refreshList}>{t("刷新")}</Button>
                        {canManage ? (
                          <Button icon={<PlusOutlined />} type="primary" onClick={openCreate}>{t("新建计算")}</Button>
                        ) : null}
                      </Space>
                    </Form.Item>
                  </Form>
                </div>

                <Table<WindFarmCalcJobSummary>
                  rowKey="id"
                  size="middle"
                  loading={listQuery.isLoading}
                  columns={columns}
                  dataSource={listQuery.data?.items ?? []}
                  pagination={false}
                  scroll={{ x: 1300 }}
                  locale={{
                    emptyText: (
                      <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={t("暂无计算任务，点击「新建计算」选择数据准备批次")}
                      />
                    ),
                  }}
                  footer={() => (
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
                      style={{ marginTop: 0 }}
                    />
                  )}
                />
              </div>
            ),
          },
        ]}
      />

      <Modal
        title={t("新建风电场计算")}
        width={640}
        open={createOpen}
        destroyOnHidden
        onCancel={() => setCreateOpen(false)}
        footer={
          <Space>
            <Button disabled={step === 0} onClick={() => setStep(step - 1)}>{t("上一步")}</Button>
            <Button disabled={step === 2} onClick={() => setStep(step + 1)}>{t("下一步")}</Button>
            <Button onClick={() => setCreateOpen(false)}>{t("取消")}</Button>
            <Button type="primary" loading={submitting} onClick={() => void handleSubmit()}>{t("提交计算")}</Button>
          </Space>
        }
      >
        {createContent}
      </Modal>
    </div>
  );
}
