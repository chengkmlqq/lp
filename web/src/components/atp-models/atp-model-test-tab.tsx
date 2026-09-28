"use client";

// ATP 模型「测试记录」页内 Tab（参照地闪密度回填列表）。
//   · 顶部工具条：模型信息 + 「测试」按钮 → AtpTestRunModal 弹窗填参数（三来源）
//   · 记录表格：状态带进度条回显（跑批时轮询），操作列「测试详情」→ 抽屉
//   · 详情抽屉：复用各产物子组件（AtpTestArtifactView / AtpParamTraceDrawer / WaveformChart）
import { useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  App,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Input,
  Modal,
  Progress,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CopyOutlined,
  DownloadOutlined,
  ExperimentOutlined,
  EyeOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { getJson, readApiError } from "@/lib/api";
import type {
  AtpAssetRunDetail,
  AtpAssetRunListResponse,
  AtpAssetRunSummary,
  AtpAssetSummary,
  AtpAssetTestStage,
  AtpAssetTestStageResult,
} from "@/types/auth";
import { AtpTestArtifactView } from "./atp-test-artifact-view";
import { AtpParamTraceDrawer } from "./atp-param-trace-drawer";
import { WaveformChart, type WaveformData } from "./atp-waveform-chart";
import { AtpTestRunModal } from "./atp-test-run-modal";

const STAGE_ORDER: AtpAssetTestStage[] = ["materialize", "geometry", "simulate"];

const STAGE_LABEL: Record<AtpAssetTestStage, string> = {
  materialize: "① 物化",
  geometry: "② 几何",
  simulate: "③ 单次ATP",
};

type TestResultSummary = {
  dry_run?: boolean;
  requested_stages?: string[];
  failed_stage?: string | null;
  stages?: Record<string, AtpAssetTestStageResult>;
  compare?: {
    params_source?: string;
    params_diagnostics?: {
      chain?: string[];
    };
  };
};

function readSummary(run: AtpAssetRunDetail | undefined): TestResultSummary {
  return (run?.result_summary_json ?? {}) as TestResultSummary;
}

function statusTag(status: string | null | undefined) {
  if (status === "success") return <Tag color="green">成功</Tag>;
  if (status === "failed") return <Tag color="red">失败</Tag>;
  if (status === "running") return <Tag color="blue">运行中</Tag>;
  if (status === "pending") return <Tag>排队中</Tag>;
  return <Tag>{status || "-"}</Tag>;
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

/** 运行进度：requested_stages 中已完成（ok/failed）段占比；排队中 0。 */
function runProgress(run: AtpAssetRunSummary | AtpAssetRunDetail): number {
  if (run.status === "pending") return 0;
  if (run.status === "success") return 100;
  if (run.status === "failed") return 100;
  const summary = readSummary(run as AtpAssetRunDetail);
  const requested = summary.requested_stages ?? STAGE_ORDER;
  const done = requested.filter((stage) => {
    const result = summary.stages?.[stage];
    return result && result.status !== "skipped";
  }).length;
  if (requested.length === 0) return 0;
  return Math.min(99, Math.round((done / requested.length) * 100));
}

type AtpModelTestTabProps = {
  assetId: string;
};

export function AtpModelTestTab({ assetId }: AtpModelTestTabProps) {
  const { message } = App.useApp();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRun = hasPermission("atp.run") || hasPermission("atp.manage");

  const [testModalOpen, setTestModalOpen] = useState(false);
  const [detailRunId, setDetailRunId] = useState<string | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);

  const assetQuery = useQuery({
    queryKey: ["atp-models-asset-detail", assetId],
    enabled: Boolean(user && assetId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/assets/${assetId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpAssetSummary;
    },
  });

  const runsQuery = useQuery({
    queryKey: ["atp-test-runs-tab", assetId],
    enabled: Boolean(user && assetId),
    refetchInterval: (query) => {
      const data = query.state.data as AtpAssetRunListResponse | undefined;
      const live = (data?.items ?? []).some(
        (item) => item.status === "pending" || item.status === "running"
      );
      return live ? 3000 : false;
    },
    queryFn: async () =>
      getJson<AtpAssetRunListResponse>(`/api/v1/atp/assets/${assetId}/test-runs?limit=100`),
  });

  const detailQuery = useQuery({
    queryKey: ["atp-test-run-detail", detailRunId],
    enabled: Boolean(user && detailRunId),
    refetchInterval: (query) => {
      const data = query.state.data as AtpAssetRunDetail | undefined;
      if (!data) return false;
      return data.status === "pending" || data.status === "running" ? 3000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/runs/${detailRunId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpAssetRunDetail;
    },
  });

  const asset = assetQuery.data;
  const runs = runsQuery.data?.items ?? [];
  const detail = detailQuery.data;
  const detailSummary = readSummary(detail);
  const detailRunning =
    detail?.status === "pending" || detail?.status === "running";

  const handleCreated = useCallback(() => {
    void runsQuery.refetch();
  }, [runsQuery]);

  const handleDownload = async () => {
    if (!detailRunId) return;
    try {
      const response = await fetchWithAuth(`/api/v1/atp/test-runs/${detailRunId}/artifacts`);
      if (!response.ok) {
        message.error(await readApiError(response));
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `atp-test-${detailRunId}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "下载失败");
    }
  };

  const handleCopyCompare = async () => {
    if (!detailRunId) return;
    try {
      const compare = await getJson<Record<string, unknown>>(
        `/api/v1/atp/test-runs/${detailRunId}/compare`
      );
      await navigator.clipboard.writeText(JSON.stringify(compare, null, 2));
      message.success("已复制 compare.json（可直接与 C# 侧产物 diff）");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "获取 compare.json 失败");
    }
  };

  const columns = useMemo<ColumnsType<AtpAssetRunSummary>>(
    () => [
      {
        title: "发起时间",
        dataIndex: "create_date",
        width: 170,
        render: (value: string) => formatDateTime(value),
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 150,
        render: (value: string, record) =>
          record.status === "pending" || record.status === "running" ? (
            <Space direction="vertical" size={2} style={{ width: "100%" }}>
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                {statusTag(value)}
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {runProgress(record)}%
                </Typography.Text>
              </div>
              <Progress
                percent={runProgress(record)}
                size="small"
                strokeColor="var(--accent-9)"
                trailColor="var(--ant-color-border-secondary)"
                style={{ width: 120 }}
              />
            </Space>
          ) : (
            statusTag(value)
          ),
      },
      {
        title: "测试段",
        key: "stages",
        width: 150,
        render: (_: unknown, record) => {
          const summary = record.result_summary_json as TestResultSummary | undefined;
          const requested = summary?.requested_stages;
          return (requested ?? STAGE_ORDER).map((stage) => STAGE_LABEL[stage]).join(" / ");
        },
      },
      {
        title: "参数来源",
        key: "params_source",
        width: 140,
        render: (_: unknown, record) => {
          const summary = record.result_summary_json as TestResultSummary | undefined;
          const source = summary?.compare?.params_source;
          return source === "template" ? (
            <Tag>模板默认值</Tag>
          ) : source === "tower" ? (
            <Tag color="purple">手工杆塔</Tag>
          ) : source === "line-tower" ? (
            <Tag color="geekblue">线路杆塔</Tag>
          ) : (
            "-"
          );
        },
      },
      {
        title: "耗时",
        dataIndex: "duration_ms",
        width: 90,
        render: (value: number | null) => (value != null ? `${(value / 1000).toFixed(1)}s` : "-"),
      },
      {
        title: "操作人",
        dataIndex: "create_user",
        width: 110,
        render: (value: string | null) => value || "-",
      },
      {
        title: "操作",
        key: "actions",
        width: 100,
        fixed: "right",
        render: (_: unknown, record) => (
          <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailRunId(record.id)}>
            测试详情
          </Button>
        ),
      },
    ],
    []
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col p-4">
      {/* 工具条：模型信息 + 测试按钮 */}
      <div className="mb-4 flex items-center gap-3">
        <Card size="small" style={{ flex: 1 }}>
          <Space size={16} wrap>
            <Typography.Text strong>
              {asset?.name || asset?.code || assetId}
            </Typography.Text>
            {asset?.voltage_level ? (
              <Tag>{asset.voltage_level}kV</Tag>
            ) : null}
            {asset?.tower_type ? <Tag color="blue">{asset.tower_type}</Tag> : null}
            {asset?.scene_type ? <Tag color="purple">{asset.scene_type}</Tag> : null}
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              共 {runs.length} 条测试记录
            </Typography.Text>
          </Space>
        </Card>
        {canRun ? (
          <Button
            type="primary"
            icon={<ExperimentOutlined />}
            onClick={() => setTestModalOpen(true)}
          >
            测试
          </Button>
        ) : null}
      </div>

      <div className="admin-power-lines-list-pane" style={{ padding: 0 }}>
        <Spin spinning={runsQuery.isFetching}>
          <Table<AtpAssetRunSummary>
            rowKey="id"
            size="small"
            dataSource={runs}
            loading={runsQuery.isLoading}
            columns={columns}
            pagination={{ pageSize: 10, showSizeChanger: true, showTotal: (total) => `共 ${total} 条` }}
            locale={{ emptyText: "暂无测试记录，点击右上角「测试」发起" }}
            scroll={{ x: 900 }}
          />
        </Spin>
      </div>

      {/* 测试参数弹窗 */}
      {asset ? (
        <AtpTestRunModal
          asset={asset}
          open={testModalOpen}
          onClose={() => setTestModalOpen(false)}
          onCreated={handleCreated}
        />
      ) : null}

      {/* 测试详情抽屉 */}
      <Drawer
        title={`测试详情 · ${detail?.asset_name ?? detailRunId ?? ""}`}
        open={Boolean(detailRunId)}
        onClose={() => setDetailRunId(null)}
        width={760}
      >
        {detail ? (
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            <Space size={8} wrap>
              {statusTag(detail.status)}
              {detailSummary.dry_run ? <Tag color="orange">试跑</Tag> : null}
              <Typography.Text type="secondary">
                用时{" "}
                {detail.duration_ms != null ? `${(detail.duration_ms / 1000).toFixed(1)}s` : "-"}
              </Typography.Text>
              <Typography.Text type="secondary">run {detail.id.slice(0, 8)}</Typography.Text>
              <Typography.Text type="secondary">
                发起于 {formatDateTime(detail.create_date)}
              </Typography.Text>
            </Space>

            {detailSummary.compare?.params_source ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                参数来源：
                {detailSummary.compare.params_source === "template"
                  ? `模板默认值（链：${(detailSummary.compare.params_diagnostics?.chain ?? []).join(" → ") || "-"}）`
                  : detailSummary.compare.params_source === "line-tower"
                    ? "线路杆塔（按塔组装）"
                    : "手工杆塔数据"}
              </Typography.Text>
            ) : null}

            {detail.error_message ? (
              <Alert type="error" showIcon message="测试失败" description={detail.error_message} />
            ) : null}
            {detailRunning ? (
              <Alert type="info" showIcon message="正在执行，结果会自动刷新…" />
            ) : null}

            <Space>
              <Button size="small" icon={<DownloadOutlined />} disabled={detailRunning} onClick={() => void handleDownload()}>
                下载产物包
              </Button>
              <Button size="small" icon={<CopyOutlined />} disabled={detailRunning} onClick={() => void handleCopyCompare()}>
                复制对比 JSON
              </Button>
              <Button size="small" icon={<ExperimentOutlined />} disabled={detailRunning} onClick={() => setTraceOpen(true)}>
                参数溯源
              </Button>
            </Space>

            <Descriptions
              size="small"
              bordered
              column={2}
              items={(detailSummary.requested_stages ?? STAGE_ORDER).map((stage) => {
                const result = detailSummary.stages?.[stage];
                return {
                  key: stage,
                  label: STAGE_LABEL[stage] ?? stage,
                  children: !result ? (
                    <Typography.Text type="secondary">未执行</Typography.Text>
                  ) : result.status === "ok" ? (
                    <Tag color="green">通过</Tag>
                  ) : result.status === "failed" ? (
                    <Tag color="red">未通过</Tag>
                  ) : (
                    <Tag>跳过</Tag>
                  ),
                };
              })}
            />

            {STAGE_ORDER.map((stage) => {
              const result = detailSummary.stages?.[stage];
              if (!result) return null;
              return (
                <Card
                  key={stage}
                  size="small"
                  title={
                    <Space size={8}>
                      <Typography.Text strong>{STAGE_LABEL[stage]}</Typography.Text>
                      {result.status === "ok" ? (
                        <Tag color="green">通过</Tag>
                      ) : result.status === "failed" ? (
                        <Tag color="red">未通过</Tag>
                      ) : (
                        <Tag>跳过</Tag>
                      )}
                    </Space>
                  }
                >
                  <StageDetailBody result={result} runId={detail.id} />
                </Card>
              );
            })}
          </Space>
        ) : detailQuery.isLoading ? (
          <div style={{ textAlign: "center", padding: "40px 0" }}>
            <Spin />
          </div>
        ) : (
          <Empty description="暂无详情" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        )}
      </Drawer>

      {detailRunId ? (
        <AtpParamTraceDrawer runId={detailRunId} open={traceOpen} onClose={() => setTraceOpen(false)} />
      ) : null}
    </div>
  );
}

/** 单段产物/判据/日志展示（复用原测试抽屉 StageDetail 的展示能力）。 */
function StageDetailBody({ result, runId }: { result: AtpAssetTestStageResult; runId: string | null }) {
  const [viewPath, setViewPath] = useState<string | null>(null);
  const [viewWave, setViewWave] = useState(false);
  const artifactRows = Object.values(result.artifacts ?? {}).map((item) => ({
    key: item.path,
    path: item.path,
    bytes: item.bytes,
    sha256: item.sha256,
  }));
  const flashoverRows = useMemo(() => {
    const m = result.metrics ?? {};
    const flashoverCount = m.flashover_count;
    if (flashoverCount === undefined) return null;
    return [
      { key: "flashover_count", label: "闪络相数", value: String(flashoverCount) },
      {
        key: "flashover_phases",
        label: "闪络相位",
        value: Array.isArray(m.flashover_phases) ? m.flashover_phases.join(", ") : String(m.flashover_phases ?? "-"),
      },
    ];
  }, [result.metrics]);

  return (
    <Space direction="vertical" size={8} style={{ width: "100%" }}>
      <Table
        rowKey="name"
        size="small"
        pagination={false}
        dataSource={result.verdicts ?? []}
        columns={[
          { title: "判据", dataIndex: "name", width: 260, render: (value: string) => <Typography.Text code>{value}</Typography.Text> },
          {
            title: "",
            dataIndex: "ok",
            width: 70,
            render: (value: boolean) => (value ? <Tag color="green">通过</Tag> : <Tag color="red">未通过</Tag>),
          },
          { title: "说明", dataIndex: "detail", render: (value: string) => value || "-" },
        ]}
      />
      {flashoverRows ? (
        <Table
          rowKey="key"
          size="small"
          pagination={false}
          dataSource={flashoverRows}
          columns={[
            { title: "指标", dataIndex: "label", width: 140 },
            { title: "值", dataIndex: "value", render: (value: string) => <Typography.Text strong>{value}</Typography.Text> },
          ]}
        />
      ) : null}
      {artifactRows.length > 0 ? (
        <>
          <Typography.Text strong style={{ fontSize: 12 }}>
            计算产物
          </Typography.Text>
          <Table
            rowKey="key"
            size="small"
            pagination={false}
            dataSource={artifactRows}
            columns={[
              { title: "产物", dataIndex: "path" },
              { title: "大小", dataIndex: "bytes", width: 100, render: (value: number) => `${value}B` },
              {
                title: "查看",
                key: "view",
                width: 90,
                render: (_value, row: { path: string }) => {
                  const lower = row.path.toLowerCase();
                  if (lower.endsWith(".pl4") || lower.endsWith(".plt")) {
                    return (
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        icon={<EyeOutlined />}
                        disabled={!runId}
                        onClick={() => {
                          setViewWave(true);
                          setViewPath(row.path);
                        }}
                      >
                        波形
                      </Button>
                    );
                  }
                  if (
                    lower.endsWith(".lib") ||
                    lower.endsWith(".dat") ||
                    lower.endsWith(".lis") ||
                    lower.endsWith(".log") ||
                    lower.endsWith(".pch")
                  ) {
                    return (
                      <Button
                        type="link"
                        size="small"
                        style={{ padding: 0 }}
                        icon={<EyeOutlined />}
                        disabled={!runId}
                        onClick={() => {
                          setViewWave(false);
                          setViewPath(row.path);
                        }}
                      >
                        查看
                      </Button>
                    );
                  }
                  return <span style={{ color: "#bbb", fontSize: 12 }}>-</span>;
                },
              },
            ]}
          />
        </>
      ) : null}
      {result.log ? (
        <Input.TextArea value={result.log} readOnly autoSize={{ minRows: 2, maxRows: 6 }} />
      ) : null}
      {runId && viewPath ? (
        <Modal
          open
          title={viewWave ? `波形：${viewPath}` : `产物：${viewPath}`}
          width={viewWave ? 920 : 860}
          footer={null}
          onCancel={() => {
            setViewPath(null);
            setViewWave(false);
          }}
        >
          {viewWave ? (
            <WaveformModalContentInner runId={runId} />
          ) : (
            <AtpTestArtifactView runId={runId} path={viewPath} />
          )}
        </Modal>
      ) : null}
    </Space>
  );
}

function WaveformModalContentInner({ runId }: { runId: string }) {
  const { user, fetchWithAuth } = useAuth();
  const waveformQuery = useQuery({
    queryKey: ["/api/v1/atp/test-runs", runId, "waveform-tab"],
    enabled: Boolean(user && runId),
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/test-runs/${runId}/waveform`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as WaveformData;
    },
  });
  if (waveformQuery.isLoading) {
    return (
      <div style={{ textAlign: "center", padding: "40px 0" }}>
        <Spin />
      </div>
    );
  }
  if (waveformQuery.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message="波形解析失败"
        description={waveformQuery.error instanceof Error ? waveformQuery.error.message : ""}
      />
    );
  }
  if (!waveformQuery.data) return null;
  return <WaveformChart data={waveformQuery.data} />;
}