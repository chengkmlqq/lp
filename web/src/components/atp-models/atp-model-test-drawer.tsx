"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Drawer,
  Empty,
  Input,
  InputNumber,
  Modal,
  Radio,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import {
  CopyOutlined,
  DownloadOutlined,
  ExperimentOutlined,
  EyeOutlined,
  RocketOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { getJson, postJson, readApiError } from "@/lib/api";
import type {
  AtpAssetRunDetail,
  AtpAssetRunListResponse,
  AtpAssetRunStatus,
  AtpAssetRunSummary,
  AtpAssetSummary,
  AtpAssetTestStage,
  AtpAssetTestStageResult,
} from "@/types/auth";
import { AtpTestArtifactView } from "./atp-test-artifact-view";
import { AtpParamTraceDrawer } from "./atp-param-trace-drawer";
import { WaveformChart, type WaveformData } from "./atp-waveform-chart";

/**
 * ATP 模型「模型测试」抽屉。
 *
 * 三类测试独立呈现（可单独发起某一段，也可「全部执行」依次跑完）：
 * ① materialize 物化+引擎文件 ② geometry DAT→LIB（LCC） ③ simulate 单次 ATP 仿真。
 * 判据看产物（.lib 是否真重算 / LIS 有无 Halt / 闪络相数），不看退出码；
 * 每段结果均展示其判据、产物清单（path/bytes/sha256）与日志。
 */

const STAGE_META: Array<{
  stage: AtpAssetTestStage;
  label: string;
  hint: string;
  tagColor: string;
}> = [
  {
    stage: "materialize",
    label: "① 物化 + 引擎文件",
    hint: "资产文件摊到独立测试目录、$INCLUDE 重写、引擎必需文件（startup/graphics）检查",
    tagColor: "geekblue",
  },
  {
    stage: "geometry",
    label: "② LCC（DAT → LIB）",
    hint: "按塔改写 .dat 跑 LCC 出 .lib；判据是 .lib 是否真重算（不是拿资产里的旧文件）",
    tagColor: "purple",
  },
  {
    stage: "simulate",
    label: "③ ATP 计算（单次仿真）",
    hint: "在固定雷电流下跑一次主仿真，取闪络相数（与 C# 同电流才可比）",
    tagColor: "gold",
  },
];

const ALL_STAGES: AtpAssetTestStage[] = STAGE_META.map((item) => item.stage);

type TestResultSummary = {
  schema?: string;
  dry_run?: boolean;
  requested_stages?: string[];
  failed_stage?: string | null;
  stages?: Record<string, AtpAssetTestStageResult>;
  compare?: {
    params_source?: string;
    params_diagnostics?: {
      chain?: string[];
      tower_kind?: string;
      defaults_applied?: string[];
      defaults_used?: Record<string, string>;
      unresolved?: Record<string, string[]>;
    };
  };
};

function readTestSummary(run: AtpAssetRunDetail | undefined): TestResultSummary {
  return (run?.result_summary_json ?? {}) as TestResultSummary;
}

function readStageResult(
  run: AtpAssetRunDetail | undefined,
  stage: AtpAssetTestStage,
): AtpAssetTestStageResult | undefined {
  return readTestSummary(run).stages?.[stage];
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

function parseJsonObject(text: string, fieldLabel: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      message.error(`${fieldLabel} 需要是一个 JSON 对象`);
      return null;
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    message.error(
      `${fieldLabel} JSON 解析失败：${error instanceof Error ? error.message : String(error)}`,
    );
    return null;
  }
}

interface AtpModelTestDrawerProps {
  asset: AtpAssetSummary | null;
  open: boolean;
  onClose: () => void;
}

export function AtpModelTestDrawer({ asset, open, onClose }: AtpModelTestDrawerProps) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRun = hasPermission("atp.run") || hasPermission("atp.manage");

  const [currentKa, setCurrentKa] = useState<number>(31);
  const [dryRun, setDryRun] = useState(false);
  // 参数来源：template = 无杆塔（资产维度 + 参数模板默认值，默认）；tower = 手工给杆塔数据
  const [paramsSource, setParamsSource] = useState<"template" | "tower">("template");
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [towerKind, setTowerKind] = useState("");
  const [scene, setScene] = useState("");
  const [baseTowerText, setBaseTowerText] = useState("{}");
  const [profileText, setProfileText] = useState("{}");
  const [paramsRaw, setParamsRaw] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  // 当前正在提交的段：null=无；"all"=全部执行；否则为单段
  const [submittingStage, setSubmittingStage] = useState<AtpAssetTestStage | "all" | null>(null);
  const [paramsDrawerOpen, setParamsDrawerOpen] = useState(false);

  // 抽屉每次重新打开时清空当前运行态，避免残留上一次的结果
  useEffect(() => {
    if (!open) {
      setActiveRunId(null);
      setSubmittingStage(null);
      return;
    }
    setTowerKind(asset?.tower_type ?? "");
    setScene(asset?.scene_type ?? "");
  }, [open, asset]);

  const activeRunQuery = useQuery({
    queryKey: ["atp-test-run", activeRunId],
    enabled: Boolean(user && open && activeRunId),
    refetchInterval: (query) => {
      const data = query.state.data as AtpAssetRunDetail | undefined;
      if (!data) return 2000;
      return data.status === "pending" || data.status === "running" ? 3000 : false;
    },
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/atp/runs/${activeRunId}`);
      if (!response.ok) throw new Error(await readApiError(response));
      return (await response.json()) as AtpAssetRunDetail;
    },
  });

  const historyQuery = useQuery({
    queryKey: ["atp-test-runs", asset?.id],
    enabled: Boolean(user && open && asset),
    queryFn: async () =>
      getJson<AtpAssetRunListResponse>(`/api/v1/atp/assets/${asset!.id}/test-runs?limit=20`),
  });

  const activeRun = activeRunQuery.data;
  const summary = readTestSummary(activeRun);
  const running = activeRun?.status === "pending" || activeRun?.status === "running";

  const handleSubmit = async (stages: AtpAssetTestStage[], marker: AtpAssetTestStage | "all") => {
    if (!asset) return;
    let baseTower: Record<string, unknown> = {};
    let profile: Record<string, unknown> = {};
    if (paramsSource === "tower") {
      const parsedBase = parseJsonObject(baseTowerText, "base_tower");
      if (parsedBase === null) return;
      const parsedProfile = parseJsonObject(profileText, "profile");
      if (parsedProfile === null) return;
      baseTower = parsedBase;
      profile = parsedProfile;
    }

    setSubmittingStage(marker);
    try {
      const run = await postJson<AtpAssetRunDetail>(
        `/api/v1/atp/assets/${asset.id}/test-runs`,
        {
          stages,
          tower_kind: towerKind.trim() || null,
          voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
          scene: scene.trim() || null,
          base_tower: baseTower,
          profile,
          params_source: paramsSource,
          allow_incomplete_defaults: allowIncomplete,
          params_raw: paramsRaw.trim() || null,
          current_ka: currentKa,
          dry_run: dryRun,
        },
      );
      setActiveRunId(run.id);
      message.success(dryRun ? "已发起试跑（只列命令，不执行）" : "测试已发起，结果自动刷新");
      void historyQuery.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "发起测试失败");
    } finally {
      setSubmittingStage(null);
    }
  };

  const handleDownload = async () => {
    if (!activeRunId) return;
    try {
      const response = await fetchWithAuth(`/api/v1/atp/test-runs/${activeRunId}/artifacts`);
      if (!response.ok) {
        message.error(await readApiError(response));
        return;
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `atp-test-${activeRunId}.zip`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      message.error(error instanceof Error ? error.message : "下载失败");
    }
  };

  const handleCopyCompare = async () => {
    if (!activeRunId) return;
    try {
      const compare = await getJson<Record<string, unknown>>(
        `/api/v1/atp/test-runs/${activeRunId}/compare`,
      );
      await navigator.clipboard.writeText(JSON.stringify(compare, null, 2));
      message.success("已复制 compare.json（可直接与 C# 侧产物 diff）");
    } catch (error) {
      message.error(error instanceof Error ? error.message : "获取 compare.json 失败");
    }
  };

  const stageResults = summary.stages ?? {};
  const failedCountByStage = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const result of Object.values(stageResults)) {
      counts[result.stage] = result.verdicts.filter((item) => !item.ok).length;
    }
    return counts;
  }, [stageResults]);

  const compareParamsSource = summary.compare?.params_source;
  const compareDiagnostics = summary.compare?.params_diagnostics;
  const defaultsApplied = compareDiagnostics?.defaults_applied ?? [];
  const unresolvedKeys = Object.keys(compareDiagnostics?.unresolved ?? {});

  return (
    <Drawer
      title={
        asset
          ? `模型测试 - ${asset.name || asset.code || asset.id}`
          : "模型测试"
      }
      open={open}
      onClose={onClose}
      width={1000}
      destroyOnHidden
    >
      {asset && canRun ? (
        <Space direction="vertical" size={16} style={{ width: "100%" }}>
          {/* 公共参数工具栏 */}
          <Card size="small">
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Space wrap size={16}>
                <Space size={8}>
                  <Typography.Text>固定雷电流</Typography.Text>
                  <InputNumber
                    min={0.1}
                    step={1}
                    value={currentKa}
                    onChange={(value) => setCurrentKa(typeof value === "number" ? value : 31)}
                    addonAfter="kA"
                    style={{ width: 140 }}
                  />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    与 C# 侧必须同值
                  </Typography.Text>
                </Space>
                <Space size={8}>
                  <Typography.Text>试跑</Typography.Text>
                  <Switch checked={dryRun} onChange={setDryRun} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    只列命令不执行
                  </Typography.Text>
                </Space>
              </Space>

              <Space size={16} wrap>
                <Space size={8}>
                  <Typography.Text>参数来源</Typography.Text>
                  <Radio.Group
                    value={paramsSource}
                    onChange={(event) => setParamsSource(event.target.value as "template" | "tower")}
                    options={[
                      { value: "template", label: "参数模板默认值（无需杆塔）" },
                      { value: "tower", label: "手工杆塔数据" },
                    ]}
                    optionType="button"
                  />
                </Space>
              </Space>

              <Collapse
                size="small"
                items={[
                  {
                    key: "params",
                    label:
                      paramsSource === "template"
                        ? "高级：塔型/场景、C# 参数串、默认值不完整时放行"
                        : "高级：杆塔数据（base_tower / profile）",
                    children: (
                      <Space direction="vertical" size={8} style={{ width: "100%" }}>
                        <Space wrap size={8}>
                          <Input
                            addonBefore="塔型"
                            value={towerKind}
                            placeholder="如 d220maotou"
                            onChange={(event) => setTowerKind(event.target.value)}
                            style={{ width: 260 }}
                          />
                          <Input
                            addonBefore="场景"
                            value={scene}
                            placeholder="如 fanji"
                            onChange={(event) => setScene(event.target.value)}
                            style={{ width: 220 }}
                          />
                        </Space>
                        {paramsSource === "tower" ? (
                          <>
                            <Input.TextArea
                              rows={4}
                              value={baseTowerText}
                              onChange={(event) => setBaseTowerText(event.target.value)}
                              placeholder='base_tower（JSON 对象），如 {"line_voltage_kv":220,"ground_resistance":7}'
                            />
                            <Input.TextArea
                              rows={3}
                              value={profileText}
                              onChange={(event) => setProfileText(event.target.value)}
                              placeholder='profile（JSON 对象），如 {"insulator_length_mm":2491.5}'
                            />
                          </>
                        ) : (
                          <Space size={8}>
                            <Typography.Text>模板默认值不完整时仍继续</Typography.Text>
                            <Switch checked={allowIncomplete} onChange={setAllowIncomplete} />
                            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                              默认关闭：缺默认值会直接报错并列出缺哪些变量（避免算出无意义结果）
                            </Typography.Text>
                          </Space>
                        )}
                        <Input
                          value={paramsRaw}
                          onChange={(event) => setParamsRaw(event.target.value)}
                          placeholder="C# javaParams 原始串（原样进 compare.json，供对拍）"
                        />
                      </Space>
                    ),
                  },
                ]}
              />

              <Space>
                <Button
                  type="primary"
                  icon={<RocketOutlined />}
                  loading={submittingStage === "all"}
                  disabled={running}
                  onClick={() => void handleSubmit(ALL_STAGES, "all")}
                >
                  全部执行
                </Button>
                <Tooltip title="从头按 ①→②→③ 依次跑完整测试；依赖段会自动补齐">
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    仅跑某一段时，前置段会自动补跑（产物必须先存在）。
                  </Typography.Text>
                </Tooltip>
              </Space>
            </Space>
          </Card>

          {/* 当前运行概览 */}
          {activeRun ? (
            <Card size="small">
              <Space size={8} wrap>
                <Typography.Text strong>当前测试</Typography.Text>
                {statusTag(activeRun.status)}
                <Typography.Text type="secondary">
                  用时{" "}
                  {activeRun.duration_ms != null
                    ? `${(activeRun.duration_ms / 1000).toFixed(1)}s`
                    : "-"}
                </Typography.Text>
                <Typography.Text type="secondary">run {activeRun.id.slice(0, 8)}</Typography.Text>
                {summary.dry_run ? <Tag color="orange">试跑</Tag> : null}
              </Space>
              {compareParamsSource ? (
                <div style={{ marginTop: 6 }}>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    参数来源：
                    {compareParamsSource === "template"
                      ? `参数模板默认值（链：${(compareDiagnostics?.chain ?? []).join(" → ") || "-"}）`
                      : "手工杆塔数据"}
                    {defaultsApplied.length > 0
                      ? `；用默认值的变量 ${defaultsApplied.length} 个：${defaultsApplied.slice(0, 8).join(", ")}`
                      : ""}
                    {unresolvedKeys.length > 0
                      ? `；⚠️ 未解析槽位 ${unresolvedKeys.length} 个`
                      : ""}
                  </Typography.Text>
                </div>
              ) : null}
              {activeRun.error_message ? (
                <Alert
                  style={{ marginTop: 8 }}
                  type="error"
                  showIcon
                  message="测试未通过"
                  description={activeRun.error_message}
                />
              ) : null}
              {running ? (
                <Alert style={{ marginTop: 8 }} type="info" showIcon message="正在执行，结果会自动刷新…" />
              ) : null}
              {activeRun ? (
                <Space style={{ marginTop: 10 }}>
                  <Button
                    size="small"
                    icon={<DownloadOutlined />}
                    disabled={running}
                    onClick={handleDownload}
                  >
                    下载产物包
                  </Button>
                  <Button
                    size="small"
                    icon={<CopyOutlined />}
                    disabled={running}
                    onClick={handleCopyCompare}
                  >
                    复制对比 JSON
                  </Button>
                  <Button
                    size="small"
                    icon={<ExperimentOutlined />}
                    disabled={running}
                    onClick={() => setParamsDrawerOpen(true)}
                  >
                    参数溯源
                  </Button>
                </Space>
              ) : null}
            </Card>
          ) : null}

          {/* 三类测试卡片 */}
          <Space direction="vertical" size={12} style={{ width: "100%" }}>
            {STAGE_META.map((meta) => (
              <StageCard
                key={meta.stage}
                meta={meta}
                result={readStageResult(activeRun, meta.stage)}
                runStatus={activeRun?.status ?? null}
                running={running}
                submitting={submittingStage === meta.stage}
                failedCount={failedCountByStage[meta.stage] ?? 0}
                runId={activeRun?.id ?? null}
                onRun={() => void handleSubmit([meta.stage], meta.stage)}
              />
            ))}
          </Space>

          {/* 历史记录 */}
          <Card size="small" title="历史记录">
            <Table<AtpAssetRunSummary>
              rowKey="id"
              size="small"
              loading={historyQuery.isLoading}
              dataSource={historyQuery.data?.items ?? []}
              pagination={false}
              locale={{ emptyText: "暂无测试记录" }}
              onRow={(record) => ({
                onClick: () => setActiveRunId(record.id),
                style: { cursor: "pointer" },
              })}
              columns={[
                { title: "时间", dataIndex: "create_date", width: 180, render: (value: string) => formatDateTime(value) },
                { title: "状态", dataIndex: "status", width: 100, render: (value: string) => statusTag(value) },
                {
                  title: "结果",
                  key: "result",
                  render: (_: unknown, record: AtpAssetRunSummary) =>
                    record.error_message ? (
                      <Typography.Text type="danger" ellipsis={{ tooltip: record.error_message }}>
                        {record.error_message}
                      </Typography.Text>
                    ) : (
                      <Typography.Text type="secondary">-</Typography.Text>
                    ),
                },
                {
                  title: "耗时",
                  dataIndex: "duration_ms",
                  width: 100,
                  render: (value: number | null) => (value != null ? `${(value / 1000).toFixed(1)}s` : "-"),
                },
                { title: "操作人", dataIndex: "create_user", width: 120, render: (value: string | null) => value || "-" },
              ]}
            />
          </Card>
        </Space>
      ) : asset ? (
        <Alert
          type="info"
          showIcon
          message="当前账号缺少测试权限（需要 atp.run 或 atp.manage），无法发起测试。"
        />
      ) : null}
      {activeRunId ? (
        <AtpParamTraceDrawer
          runId={activeRunId}
          open={paramsDrawerOpen}
          onClose={() => setParamsDrawerOpen(false)}
        />
      ) : null}
    </Drawer>
  );
}

function StageCard({
  meta,
  result,
  runStatus,
  running,
  submitting,
  failedCount,
  runId,
  onRun,
}: {
  meta: (typeof STAGE_META)[number];
  result: AtpAssetTestStageResult | undefined;
  runStatus: AtpAssetRunStatus | null;
  running: boolean;
  submitting: boolean;
  failedCount: number;
  runId: string | null;
  onRun: () => void;
}) {
  return (
    <Card
      size="small"
      title={
        <Space size={8}>
          <ExperimentOutlined style={{ color: meta.tagColor === "gold" ? "var(--orange-9)" : undefined }} />
          <Typography.Text strong>{meta.label}</Typography.Text>
          {result ? (
            result.status === "ok" ? (
              <Tag color="green">通过</Tag>
            ) : result.status === "failed" ? (
              <Tag color="red">未通过</Tag>
            ) : (
              <Tag>跳过</Tag>
            )
          ) : null}
        </Space>
      }
      extra={
        <Button
          size="small"
          type="primary"
          ghost
          loading={submitting}
          disabled={running}
          onClick={onRun}
        >
          测试该段
        </Button>
      }
    >
      <Space direction="vertical" size={8} style={{ width: "100%" }}>
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {meta.hint}
        </Typography.Text>
        {runStatus && result ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            {failedCount > 0
              ? `${failedCount} 条判据未通过`
              : `${result.verdicts.length} 条判据`}
          </Typography.Text>
        ) : null}
        {!result && !running && runStatus ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            该段在本次运行中未执行（未勾选且非依赖段）。
          </Typography.Text>
        ) : null}
        {result ? <StageDetail result={result} runId={runId} /> : null}
        {!result && !running ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该段尚未运行，点击「测试该段」发起" />
        ) : null}
      </Space>
    </Card>
  );
}

function StageDetail({ result, runId }: { result: AtpAssetTestStageResult; runId: string | null }) {
  const [viewPath, setViewPath] = useState<string | null>(null);
  const [viewWave, setViewWave] = useState(false);
  const artifactRows = Object.values(result.artifacts ?? {}).map((item) => ({
    key: item.path,
    path: item.path,
    bytes: item.bytes,
    sha256: item.sha256,
  }));
  const metricRows = Object.entries(result.metrics ?? {})
    .filter(([, value]) => value === null || typeof value !== "object")
    .map(([key, value]) => ({ key, value: String(value) }));

  const flashoverRows = useMemo(() => {
    const m = result.metrics ?? {};
    const flashoverCount = m.flashover_count;
    const flashoverPhases = m.flashover_phases;
    if (flashoverCount === undefined) return null;
    return [
      { key: "flashover_count", label: "闪络相数", value: String(flashoverCount) },
      { key: "flashover_phases", label: "闪络相位", value: Array.isArray(flashoverPhases) ? flashoverPhases.join(", ") : String(flashoverPhases ?? "-") },
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
          {
            title: "判据",
            dataIndex: "name",
            width: 260,
            render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
          },
          {
            title: "",
            dataIndex: "ok",
            width: 70,
            render: (value: boolean) =>
              value ? <Tag color="green">通过</Tag> : <Tag color="red">未通过</Tag>,
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
            {
              title: "值",
              dataIndex: "value",
              render: (value: string) => <Typography.Text strong>{value}</Typography.Text>,
            },
          ]}
        />
      ) : null}
      {metricRows.length > 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {metricRows.map((item) => `${item.key}=${item.value}`).join("  ·  ")}
        </Typography.Text>
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
              { title: "大小", dataIndex: "bytes", width: 100 },
              {
                title: "sha256",
                dataIndex: "sha256",
                render: (value: string | null) => (
                  <Typography.Text copyable={{ text: value ?? "" }} style={{ fontSize: 12 }}>
                    {(value ?? "").slice(0, 16) || "-"}
                  </Typography.Text>
                ),
              },
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
                          setViewPath(row.path);
                          setViewWave(false);
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
            <WaveformModalContent runId={runId} path={viewPath} />
          ) : (
            <AtpTestArtifactView runId={runId} path={viewPath} />
          )}
        </Modal>
      ) : null}
    </Space>
  );
}

function WaveformModalContent({ runId, path }: { runId: string; path: string }) {
  const { user, fetchWithAuth } = useAuth();
  const waveformQuery = useQuery({
    queryKey: ["/api/v1/atp/test-runs", runId, "waveform"],
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

export default AtpModelTestDrawer;