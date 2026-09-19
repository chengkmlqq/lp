"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Empty,
  Input,
  InputNumber,
  Radio,
  Space,
  Switch,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { getJson, postJson, readApiError } from "@/lib/api";
import type {
  AtpAssetRunDetail,
  AtpAssetRunListResponse,
  AtpAssetRunSummary,
  AtpAssetSummary,
  AtpAssetTestStage,
  AtpAssetTestStageResult,
} from "@/types/auth";

/**
 * ATP 模型「测试运行」面板。
 *
 * 三段独立判定（可只跑其中一段，依赖会自动补齐）：
 * ① materialize 物化+引擎文件 ② geometry DAT→LIB ③ simulate 单次 ATP。
 * 判据看产物（.lib 是否真重算 / LIS 有无 Halt / 闪络相数），不看退出码
 * —— ATP 退出码不可信。产物 compare.json 与 C# 端同格式，可直接 diff。
 */

const STAGE_OPTIONS: Array<{ value: AtpAssetTestStage; label: string; hint: string }> = [
  {
    value: "materialize",
    label: "① 物化 + 引擎文件",
    hint: "资产文件摊到独立测试目录、$INCLUDE 重写、引擎必需文件（startup/graphics）检查",
  },
  {
    value: "geometry",
    label: "② DAT → LIB（几何/LCC）",
    hint: "按塔改写 .dat 跑 LCC 出 .lib；判据是 .lib 是否真重算（不是拿资产里的旧文件）",
  },
  {
    value: "simulate",
    label: "③ 单次 ATP 仿真",
    hint: "在固定雷电流下跑一次主仿真，取闪络相数（与 C# 同电流才可比）",
  },
];

const ALL_STAGES: AtpAssetTestStage[] = STAGE_OPTIONS.map((item) => item.value);

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
  const raw = (run?.result_summary_json ?? {}) as TestResultSummary;
  return raw;
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

export function AtpModelTestPanel({ asset }: { asset: AtpAssetSummary }) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRun = hasPermission("atp.run") || hasPermission("atp.manage");

  const [stages, setStages] = useState<AtpAssetTestStage[]>(ALL_STAGES);
  const [currentKa, setCurrentKa] = useState<number>(31);
  const [dryRun, setDryRun] = useState(false);
  // 参数来源：template = 无杆塔（资产维度 + 参数模板默认值，默认）；tower = 手工给杆塔数据
  const [paramsSource, setParamsSource] = useState<"template" | "tower">("template");
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [towerKind, setTowerKind] = useState(asset.tower_type ?? "");
  const [scene, setScene] = useState(asset.scene_type ?? "");
  const [baseTowerText, setBaseTowerText] = useState("{}");
  const [profileText, setProfileText] = useState("{}");
  const [paramsRaw, setParamsRaw] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const activeRunQuery = useQuery({
    queryKey: ["atp-test-run", activeRunId],
    enabled: Boolean(user && activeRunId),
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
    queryKey: ["atp-test-runs", asset.id],
    enabled: Boolean(user),
    queryFn: async () =>
      getJson<AtpAssetRunListResponse>(`/api/v1/atp/assets/${asset.id}/test-runs?limit=20`),
  });

  const activeRun = activeRunQuery.data;
  const summary = readTestSummary(activeRun);
  const stageResults = summary.stages ?? {};
  const running = activeRun?.status === "pending" || activeRun?.status === "running";

  const stageItems = useMemo(
    () =>
      Object.values(stageResults).map((result) => ({
        key: result.stage,
        label: (
          <Space size={8}>
            <Typography.Text strong>{stageLabel(result.stage)}</Typography.Text>
            {result.status === "ok" ? (
              <Tag color="green">通过</Tag>
            ) : result.status === "failed" ? (
              <Tag color="red">未通过</Tag>
            ) : (
              <Tag>跳过</Tag>
            )}
            <Typography.Text type="secondary">
              {result.verdicts.filter((item) => !item.ok).length > 0
                ? `${result.verdicts.filter((item) => !item.ok).length} 条判据未通过`
                : `${result.verdicts.length} 条判据`}
            </Typography.Text>
          </Space>
        ),
        children: <StageDetail result={result} />,
      })),
    [stageResults],
  );

  const handleSubmit = async () => {
    if (stages.length === 0) {
      message.warning("请至少选择一段");
      return;
    }
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

    setSubmitting(true);
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
      message.success(dryRun ? "已发起试跑（只列命令，不执行）" : "测试已发起");
      void historyQuery.refetch();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "发起测试失败");
    } finally {
      setSubmitting(false);
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

  return (
    <Card
      size="small"
      title="测试运行"
      extra={
        <Tooltip title="测试在独立目录执行（不污染生产目录），并强制重算几何">
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            分段执行 · 判据看产物
          </Typography.Text>
        </Tooltip>
      }
    >
      {!canRun ? (
        <Alert
          type="info"
          showIcon
          message="当前账号缺少测试权限（需要 atp.run 或 atp.manage），可查看历史记录。"
        />
      ) : (
        <Space direction="vertical" size={12} style={{ width: "100%" }}>
          <div>
            <Typography.Text strong>测试段</Typography.Text>
            <div style={{ marginTop: 4 }}>
              <Checkbox.Group
                value={stages}
                onChange={(values) => setStages(values as AtpAssetTestStage[])}
                options={STAGE_OPTIONS.map((item) => ({ value: item.value, label: item.label }))}
              />
            </div>
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              只勾「③ 单次 ATP」时，①② 会作为前置自动补跑（产物必须先存在）。
            </Typography.Text>
          </div>

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
            {paramsSource === "template" ? (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                按资产自带的塔型/电压匹配参数模板，用模板默认值算参数（对齐 C#：引擎只吃一串参数）
              </Typography.Text>
            ) : (
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                用下面手工填的杆塔几何/参数（与生产同源）
              </Typography.Text>
            )}
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
            <Button type="primary" loading={submitting} onClick={handleSubmit}>
              开始测试
            </Button>
            {activeRunId ? (
              <>
                <Button onClick={handleDownload} disabled={running}>
                  下载产物包
                </Button>
                <Button onClick={handleCopyCompare} disabled={running}>
                  复制对比 JSON
                </Button>
              </>
            ) : null}
          </Space>
        </Space>
      )}

      {activeRun ? (
        <div style={{ marginTop: 16 }}>
          <Space size={8} wrap>
            <Typography.Text strong>当前测试</Typography.Text>
            {statusTag(activeRun.status)}
            <Typography.Text type="secondary">
              用时 {activeRun.duration_ms != null ? `${(activeRun.duration_ms / 1000).toFixed(1)}s` : "-"}
            </Typography.Text>
            <Typography.Text type="secondary">run {activeRun.id.slice(0, 8)}</Typography.Text>
            {summary.dry_run ? <Tag color="orange">试跑</Tag> : null}
          </Space>
          {summary.compare?.params_source ? (
            <div style={{ marginTop: 6 }}>
              <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                参数来源：
                {summary.compare.params_source === "template"
                  ? `参数模板默认值（链：${(summary.compare.params_diagnostics?.chain ?? []).join(" → ") || "-"}）`
                  : "手工杆塔数据"}
                {(summary.compare.params_diagnostics?.defaults_applied ?? []).length > 0
                  ? `；用默认值的变量 ${(summary.compare.params_diagnostics?.defaults_applied ?? []).length} 个：${(summary.compare.params_diagnostics?.defaults_applied ?? []).slice(0, 8).join(", ")}`
                  : ""}
                {Object.keys(summary.compare.params_diagnostics?.unresolved ?? {}).length > 0
                  ? `；⚠️ 未解析槽位 ${Object.keys(summary.compare.params_diagnostics?.unresolved ?? {}).length} 个`
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
          <div style={{ marginTop: 12 }}>
            {stageItems.length === 0 ? (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无分段结果" />
            ) : (
              <Collapse size="small" items={stageItems} defaultActiveKey={Object.keys(stageResults)} />
            )}
          </div>
        </div>
      ) : null}

      <div style={{ marginTop: 16 }}>
        <Typography.Text strong>历史记录</Typography.Text>
        <Table<AtpAssetRunSummary>
          rowKey="id"
          size="small"
          style={{ marginTop: 8 }}
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
      </div>
    </Card>
  );
}

function stageLabel(stage: string): string {
  return STAGE_OPTIONS.find((item) => item.value === stage)?.label ?? stage;
}

function StageDetail({ result }: { result: AtpAssetTestStageResult }) {
  const artifactRows = Object.values(result.artifacts ?? {}).map((item) => ({
    key: item.path,
    path: item.path,
    bytes: item.bytes,
    sha256: item.sha256,
  }));
  const metricRows = Object.entries(result.metrics ?? {})
    .filter(([, value]) => value === null || typeof value !== "object")
    .map(([key, value]) => ({ key, value: String(value) }));

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
      {metricRows.length > 0 ? (
        <Typography.Text type="secondary" style={{ fontSize: 12 }}>
          {metricRows.map((item) => `${item.key}=${item.value}`).join("  ·  ")}
        </Typography.Text>
      ) : null}
      {artifactRows.length > 0 ? (
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
          ]}
        />
      ) : null}
      {result.log ? (
        <Input.TextArea value={result.log} readOnly autoSize={{ minRows: 2, maxRows: 6 }} />
      ) : null}
    </Space>
  );
}

export default AtpModelTestPanel;
