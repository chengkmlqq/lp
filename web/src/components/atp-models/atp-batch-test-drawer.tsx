"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Checkbox, Drawer, Form, Input, InputNumber, Progress, Select, Space, Spin, Statistic, Table, Tag, Typography, message } from "antd";
import { DownloadOutlined, ExperimentOutlined, RocketOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { fetchWithAuth, getJson, postJson, readApiError } from "@/lib/api";
import type { AtpAssetListResponse, AtpAssetRunStatus, AtpAssetSummary, AtpBatchTestRunItem, AtpBatchTestRunSummary } from "@/types/auth";

const STAGES = [
  { value: "materialize", label: "① 物化 + 引擎文件" },
  { value: "geometry", label: "② LCC（DAT → LIB）" },
  { value: "simulate", label: "③ ATP 计算（单次仿真）" },
];

const STATUS_TAG: Record<string, { color: string; text: string }> = {
  pending: { color: "default", text: "排队中" },
  running: { color: "processing", text: "运行中" },
  success: { color: "green", text: "成功" },
  failed: { color: "red", text: "失败" },
};

interface AtpBatchTestDrawerProps {
  open: boolean;
  /** 非空:直接进入该批次的进度/报告视图(从历史记录「查看」进入) */
  initialBatchId?: string | null;
  onClose: () => void;
}

/** 批量测试抽屉:勾选资产 → 公共参数 → 下发 → 进度看板 + 总体报告 */
export function AtpBatchTestDrawer({ open, initialBatchId = null, onClose }: AtpBatchTestDrawerProps) {
  const { t } = useI18n();
  const { user } = useAuth();
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [volFilter, setVolFilter] = useState<string>("");
  const [twFilter, setTwFilter] = useState<string>("");
  const [stageList, setStageList] = useState<string[]>(["materialize", "geometry", "simulate"]);
  const [currentKa, setCurrentKa] = useState<number>(31.0);
  const [paramsSource, setParamsSource] = useState<string>("template");
  const [submitting, setSubmitting] = useState(false);
  const [batch, setBatch] = useState<AtpBatchTestRunSummary | null>(null);
  const [polling, setPolling] = useState(false);
  const [submitError, setSubmitError] = useState("");

  // 资产全量(勾选用)：仅在抽屉打开且非「历史查看」时按需并行拉取，避免页面首屏全量加载
  const assetsQuery = useQuery({
    queryKey: ["atp-assets-all-lazy"],
    enabled: open && !initialBatchId,
    queryFn: async () => {
      const PAGE = 200;
      const first = await fetchWithAuth(`/api/v1/atp/assets?limit=${PAGE}&offset=0`);
      if (!first.ok) {
        throw new Error(await readApiError(first));
      }
      const firstPayload = (await first.json()) as AtpAssetListResponse;
      const items = [...firstPayload.items];
      const pages = Math.ceil(firstPayload.total / PAGE);
      if (pages > 1) {
        const rest = await Promise.all(
          Array.from({ length: pages - 1 }, (_, i) =>
            fetchWithAuth(`/api/v1/atp/assets?limit=${PAGE}&offset=${(i + 1) * PAGE}`).then(async (response) => {
              if (!response.ok) {
                throw new Error(await readApiError(response));
              }
              return ((await response.json()) as AtpAssetListResponse).items;
            }),
          ),
        );
        items.push(...rest.flat());
      }
      return items;
    },
  });
  const assets = useMemo(() => assetsQuery.data ?? [], [assetsQuery.data]);

  // 维度过滤
  const volOptions = useMemo(
    () => [...new Set(assets.map((a) => a.voltage_level).filter(Boolean))].sort() as string[],
    [assets],
  );
  const twOptions = useMemo(
    () => [...new Set(assets.map((a) => a.tower_type).filter(Boolean))].sort() as string[],
    [assets],
  );
  const filtered = useMemo(() => assets.filter(
    (a) => (!volFilter || a.voltage_level === volFilter) && (!twFilter || a.tower_type === twFilter),
  ), [assets, volFilter, twFilter]);

  const selectedAssets = useMemo(
    () => assets.filter((a) => selectedKeys.has(a.id)),
    [assets, selectedKeys],
  );

  // 全选当前筛选结果
  const toggleSelectAll = (checked: boolean) => {
    const next = new Set(selectedKeys);
    filtered.forEach((a) => (checked ? next.add(a.id) : next.delete(a.id)));
    setSelectedKeys(next);
  };

  // 重置(打开时)
  useEffect(() => {
    if (open) {
      if (initialBatchId) {
        // 历史记录「查看」:直接加载该批次进度/报告
        setBatch({ batch_id: initialBatchId, total: 0, pending: 0, running: 0, success: 0, failed: 0, report: { groups: [], overall_pass_rate: 0, flashover_count_distribution: {}, failure_reasons_top: [] }, items: [] });
        setPolling(true);
        return;
      }
      setSelectedKeys(new Set());
      setVolFilter("");
      setTwFilter("");
      setStageList(["materialize", "geometry", "simulate"]);
      setCurrentKa(31.0);
      setParamsSource("template");
      setBatch(null);
      setSubmitError("");
      setPolling(false);
    }
  }, [open, initialBatchId]);

  // 批量轮询
  useEffect(() => {
    if (!polling || !batch?.batch_id || !user) return;
    const timer = window.setInterval(async () => {
      try {
        const data = await getJson<AtpBatchTestRunSummary>(
          `/api/v1/atp/batch-test-runs/${batch.batch_id}`,
        );
        setBatch(data);
        const done = data.success + data.failed;
        if (done >= data.total || (data.running === 0 && data.pending === 0 && done > 0)) {
          setPolling(false);
        }
      } catch {
        // 暂时失败继续轮询
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [polling, batch?.batch_id, user]);

  const submit = async () => {
    if (selectedKeys.size === 0) {
      setSubmitError(t("请至少勾选一个模型"));
      return;
    }
    setSubmitting(true);
    setSubmitError("");
    try {
      const data = await postJson<AtpBatchTestRunSummary>("/api/v1/atp/batch-test-runs", {
        asset_ids: [...selectedKeys],
        stages: stageList,
        current_ka: currentKa,
        params_source: paramsSource,
      });
      setBatch(data);
      setPolling(true);
    } catch (error) {
      setSubmitError(error instanceof Error ? error.message : "批量测试发起失败");
    } finally {
      setSubmitting(false);
    }
  };

  /** 下载批量测试报告包(report.xlsx + detail.csv + report.json zip) */
  const downloadReport = async (batchId: string) => {
    try {
      const response = await fetchWithAuth(`/api/v1/atp/batch-test-runs/${batchId}/report`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `atp-batch-report-${batchId.replace(/[/\\]/g, "_")}.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "报告下载失败");
    }
  };


  const done = batch ? batch.success + batch.failed : 0;
  const progress = batch ? (batch.total > 0 ? Math.round((done / batch.total) * 100) : 0) : 0;
  const finished = batch ? done >= batch.total : false;

  const columns: ColumnsType<AtpBatchTestRunItem> = [
    {
      title: t("资产"),
      dataIndex: "asset_name",
      width: 220,
      render: (v, row) => (
        <Space direction="vertical" size={0}>
          <Typography.Text ellipsis={{ tooltip: v }} style={{ maxWidth: 200 }}>
            {v}
          </Typography.Text>
          <Typography.Text type="secondary" style={{ fontSize: 12 }} code>
            {row.asset_code}
          </Typography.Text>
        </Space>
      ),
    },
    { title: t("电压"), dataIndex: "voltage_level", width: 60, render: (v) => v ? `${v}kV` : "-" },
    { title: t("塔型"), dataIndex: "tower_type", width: 110 },
    { title: t("场景"), dataIndex: "scene_type", width: 80 },
    { title: t("配置"), dataIndex: "arrester_config", width: 100 },
    {
      title: t("状态"),
      dataIndex: "status",
      width: 90,
      render: (v: AtpAssetRunStatus) => {
        const meta = STATUS_TAG[v] ?? { color: "default", text: v };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: t("耗时"),
      dataIndex: "duration_ms",
      width: 80,
      render: (v: number | null) => (v != null ? `${(v / 1000).toFixed(1)}s` : "-"),
    },
    { title: t("错误"), dataIndex: "error_message", render: (v: string | null) => v ? <Typography.Text type="danger" ellipsis style={{ maxWidth: 200 }}>{v}</Typography.Text> : "-" },
  ];

  const groupColumns: ColumnsType<{ group: string; total: number; success: number; failed: number; pass_rate: number; flashover_count_distribution: Record<string, number> }> = [
    { title: t("分组(电压/塔型/场景/配置)"), dataIndex: "group" },
    { title: t("总数"), dataIndex: "total", width: 70 },
    { title: t("成功"), dataIndex: "success", width: 70 },
    { title: t("失败"), dataIndex: "failed", width: 70 },
    {
      title: t("通过率"),
      dataIndex: "pass_rate",
      width: 100,
      render: (v: number) => <Typography.Text strong>{v}%</Typography.Text>,
    },
    {
      title: t("闪络相数分布"),
      dataIndex: "flashover_count_distribution",
      render: (v: Record<string, number>) => {
        const entries = Object.entries(v ?? {});
        return entries.length === 0 ? "-" : entries.map(([k, n]) => <Tag key={k}>{k}相×{n}</Tag>);
      },
    },
  ];

  return (
    <Drawer
      title={t("ATP 模型批量测试")}
      open={open}
      onClose={onClose}
      width={1000}
      destroyOnHidden
      extra={
        batch && !finished ? (
          <Typography.Text type="secondary">{t("轮询中…")}</Typography.Text>
        ) : batch ? (
          <Button size="small" icon={<DownloadOutlined />} onClick={() => void downloadReport(batch.batch_id)}>
            {t("下载报告")}
          </Button>
        ) : null
      }
    >
      {!batch ? (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          <Card size="small" title={t("① 选择模型")}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <Select
                  allowClear
                  placeholder={t("按电压过滤")}
                  style={{ width: 140 }}
                  value={volFilter || undefined}
                  onChange={(v) => setVolFilter(v ?? "")}
                  options={volOptions.map((v) => ({ value: v, label: `${v}kV` }))}
                />
                <Select
                  allowClear
                  placeholder={t("按塔型过滤")}
                  style={{ width: 180 }}
                  value={twFilter || undefined}
                  onChange={(v) => setTwFilter(v ?? "")}
                  options={twOptions.map((v) => ({ value: v, label: v }))}
                />
                <Checkbox
                  indeterminate={selectedKeys.size > 0 && selectedKeys.size < filtered.length}
                  checked={filtered.length > 0 && selectedKeys.size >= filtered.length}
                  onChange={(e) => toggleSelectAll(e.target.checked)}
                >
                  全选当前筛选({filtered.length})
                </Checkbox>
                <Typography.Text type="secondary">已选 {selectedKeys.size} 个</Typography.Text>
              </Space>
              <Table
                size="small"
                rowKey="id"
                pagination={{ pageSize: 10, showSizeChanger: false }}
                dataSource={filtered}
                scroll={{ y: 360 }}
                rowSelection={{
                  selectedRowKeys: [...selectedKeys],
                  onChange: (keys) => setSelectedKeys(new Set(keys as string[])),
                  preserveSelectedRowKeys: true,
                }}
                columns={[
                  { title: t("资产"), dataIndex: "name", ellipsis: true },
                  { title: t("电压"), dataIndex: "voltage_level", width: 80, render: (v) => (v ? `${v}kV` : "-") },
                  { title: t("塔型"), dataIndex: "tower_type", width: 110 },
                  { title: t("场景"), dataIndex: "scene_type", width: 80 },
                  { title: t("配置"), dataIndex: "arrester_config", width: 100 },
                ]}
              />
            </Space>
          </Card>

          <Card size="small" title={t("② 测试参数(公共)")}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Space wrap>
                <Form.Item label={t("测试阶段")} style={{ marginBottom: 0 }}>
                  <Select
                    mode="multiple"
                    style={{ minWidth: 420 }}
                    value={stageList}
                    onChange={setStageList}
                    options={STAGES}
                  />
                </Form.Item>
                <Form.Item label={t("固定雷电流(kA)")} style={{ marginBottom: 0 }}>
                  <InputNumber min={0.1} value={currentKa} onChange={(v) => setCurrentKa(Number(v ?? 31))} />
                </Form.Item>
                <Form.Item label={t("参数来源")} style={{ marginBottom: 0 }}>
                  <Select
                    style={{ width: 150 }}
                    value={paramsSource}
                    onChange={setParamsSource}
                    options={[
                      { value: "template", label: t("无杆塔(模板链)") },
                      { value: "tower", label: t("杆塔数据") },
                    ]}
                  />
                </Form.Item>
              </Space>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                对拍口径:雷电流幅值全部用同一值;依赖段(simulate→LCC→物化)自动补齐;判据看产物不看退出码。
              </Typography.Text>
            </Space>
          </Card>

          {submitError ? <Alert type="error" showIcon message={submitError} /> : null}

          <Button
            type="primary"
            icon={<RocketOutlined />}
            loading={submitting}
            disabled={selectedKeys.size === 0}
            onClick={() => void submit()}
          >
            {t("发起批量测试(")}{selectedKeys.size} {t("个模型)")}
          </Button>
        </Space>
      ) : (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <Card size="small" title={`批量测试进度 · ${batch.batch_id}`}>
            <Space direction="vertical" size={8} style={{ width: "100%" }}>
              <Progress percent={progress} status={finished ? "success" : "active"} />
              <Space size={24}>
                <Statistic title={t("总数")} value={batch.total} />
                <Statistic title={t("排队")} value={batch.pending} valueStyle={{ fontSize: 18 }} />
                <Statistic title={t("运行中")} value={batch.running} valueStyle={{ color: "#1677ff", fontSize: 18 }} />
                <Statistic title={t("成功")} value={batch.success} valueStyle={{ color: "#3f8600", fontSize: 18 }} />
                <Statistic title={t("失败")} value={batch.failed} valueStyle={{ color: "#cf1322", fontSize: 18 }} />
                <Statistic title={t("总体通过率")} value={`${batch.report.overall_pass_rate ?? 0}%`} valueStyle={{ fontSize: 18 }} />
              </Space>
              {(batch.errors ?? []).length > 0 ? (
                <Alert
                  type="warning"
                  showIcon
                  message={`${batch.errors!.length} 个资产发起失败(未生成 run)`}
                  description={batch.errors!.slice(0, 5).map((e) => `${e.code}: ${e.error}`).join("；")}
                />
              ) : null}
            </Space>
          </Card>

          {finished ? (
            <>
              <Card size="small" title={t("总体测试报告")}>
                <Space direction="vertical" size={12} style={{ width: "100%" }}>
                  <Space size={24}>
                    <Statistic title={t("总模型数")} value={batch.total} />
                    <Statistic title={t("成功")} value={batch.success} valueStyle={{ color: "#3f8600" }} />
                    <Statistic title={t("失败")} value={batch.failed} valueStyle={{ color: "#cf1322" }} />
                    <Statistic title={t("通过率")} value={`${batch.report.overall_pass_rate ?? 0}%`} />
                  </Space>
                  {batch.report.flashover_count_distribution &&
                  Object.keys(batch.report.flashover_count_distribution).length > 0 ? (
                    <div>
                      <Typography.Text strong>{t("闪络相数分布:")}</Typography.Text>
                      {Object.entries(batch.report.flashover_count_distribution).map(([k, v]) => (
                        <Tag key={k} color="purple">{k}相 × {v}</Tag>
                      ))}
                    </div>
                  ) : null}
                  {batch.report.failure_reasons_top?.length > 0 ? (
                    <div>
                      <Typography.Text strong>{t("失败原因 TOP:")}</Typography.Text>
                      {batch.report.failure_reasons_top.map((r) => (
                        <Tag key={r.reason} color="red">{r.reason}({r.count})</Tag>
                      ))}
                    </div>
                  ) : null}
                </Space>
              </Card>

              <Card size="small" title={t("分组成绩")}>
                <Table
                  size="small"
                  rowKey="group"
                  pagination={false}
                  dataSource={batch.report.groups ?? []}
                  columns={groupColumns}
                />
              </Card>

              <Card size="small" title={t("明细")}>
                <Table
                  size="small"
                  rowKey="run_id"
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  dataSource={batch.items}
                  columns={columns}
                />
              </Card>
            </>
          ) : (
            <Card size="small" title={t("运行明细(实时)")}>
              {batch.items.length === 0 ? (
                <EmptyState />
              ) : (
                <Table
                  size="small"
                  rowKey="run_id"
                  pagination={{ pageSize: 20, showSizeChanger: false }}
                  dataSource={batch.items}
                  loading={polling}
                  columns={columns}
                />
              )}
            </Card>
          )}
        </Space>
      )}
    </Drawer>
  );
}

function EmptyState() {
  return (
    <div style={{ textAlign: "center", padding: "24px 0" }}>
      <Spin />
    </div>
  );
}