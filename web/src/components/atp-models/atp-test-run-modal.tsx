"use client";

// ATP 模型「测试参数」弹窗。
// 参数来源四种（默认走测试线路）：
//   · test-line  —— 单塔基准测试线路（同一条线路 = 逐字节相同输入，可回归对比）
//   · template   —— 参数模板默认值（无需杆塔）
//   · tower      —— 手工杆塔数据（base_tower / profile JSON）
//   · line-tower —— 从线路杆塔选择（后端按塔组装上下文，与「参数试算」同口径）
// 确认后触发测试任务（POST /atp/assets/{id}/test-runs）。
import { useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Checkbox,
  Col,

  Form,
  Input,
  InputNumber,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Switch,
  Table,
  Tag,
  Typography,
} from "antd";
import { RocketOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { modoTablePagination } from "@/components/biz/modo-pagination";
import { useAuth } from "@/components/auth-provider";
import { AtpTestLineDeriveModal } from "@/components/atp-test-lines/atp-test-line-derive-modal";
import { postJson, readApiError } from "@/lib/api";
import type {
  AtpAssetRunDetail,
  AtpAssetSummary,
  AtpAssetTestRunRequest,
  AtpAssetTestStage,
} from "@/types/auth";
import type {
  AtpTestLineDeriveRequest,
  AtpTestLineMatchedBy,
  AtpTestLineResolveResponse,
  AtpTestLineSourceKind,
  AtpTestLineSummary,
} from "@/types/atp-test-line";

const ALL_STAGES: AtpAssetTestStage[] = ["materialize", "geometry", "simulate"];

export type ParamsSource = "test-line" | "template" | "tower" | "line-tower";

const MATCHED_BY_LABEL: Record<AtpTestLineMatchedBy, { label: string; color: string }> = {
  bound: { label: "模型绑定", color: "purple" },
  geometry: { label: "几何维匹配", color: "blue" },
  degraded: { label: "降级匹配（仅电压+塔型）", color: "gold" },
  none: { label: "无匹配", color: "default" },
};

type LineOption = {
  id: string;
  name: string;
  code?: string | null;
  voltage_kv?: number | null;
};

type TowerOption = {
  id: string;
  tower_no: string;
  tower_type?: string | null;
  tower_model?: string | null;
  altitude_m?: number | null;
};

type AtpTestRunModalProps = {
  asset: AtpAssetSummary;
  open: boolean;
  onClose: () => void;
  onCreated: (run: AtpAssetRunDetail) => void;
};

function parseJsonObject(text: string): Record<string, unknown> | null {
  const trimmed = text.trim();
  if (!trimmed) return {};
  try {
    const parsed: unknown = JSON.parse(trimmed);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>;
    }
    return null;
  } catch {
    return null;
  }
}

export function AtpTestRunModal({ asset, open, onClose, onCreated }: AtpTestRunModalProps) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { fetchWithAuth } = useAuth();

  const [stages, setStages] = useState<AtpAssetTestStage[]>(ALL_STAGES);
  const [currentKa, setCurrentKa] = useState<number>(31);
  const [paramsSource, setParamsSource] = useState<ParamsSource>("test-line");
  const [allowIncomplete, setAllowIncomplete] = useState(false);
  const [towerKind, setTowerKind] = useState("");
  const [scene, setScene] = useState("");
  const [baseTowerText, setBaseTowerText] = useState("{}");
  const [profileText, setProfileText] = useState("{}");
  const [paramsRaw, setParamsRaw] = useState("");
  // 线路杆塔选择
  const [lines, setLines] = useState<LineOption[]>([]);
  const [lineId, setLineId] = useState<string | undefined>(undefined);
  const [towers, setTowers] = useState<TowerOption[]>([]);
  const [towersLoading, setTowersLoading] = useState(false);
  const [selectedTowerIds, setSelectedTowerIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  // 测试线路（单塔基准）
  const [resolveLoading, setResolveLoading] = useState(false);
  const [resolveInfo, setResolveInfo] = useState<AtpTestLineResolveResponse | null>(null);
  const [manualTestLineId, setManualTestLineId] = useState<string | undefined>(undefined);
  const [candidateLines, setCandidateLines] = useState<AtpTestLineSummary[]>([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [deriveOpen, setDeriveOpen] = useState(false);

  /** 当前实际会用的测试线路：手选优先，其次自动解析命中 */
  const activeTestLine = useMemo<AtpTestLineSummary | null>(() => {
    if (manualTestLineId) {
      return candidateLines.find((item) => item.id === manualTestLineId) ?? null;
    }
    return resolveInfo?.test_line ?? null;
  }, [manualTestLineId, candidateLines, resolveInfo]);

  /** 按资产维度调 resolve（模型绑定 → 几何维 → 降级） */
  const resolveTestLine = async (assetId: string) => {
    setResolveLoading(true);
    setResolveInfo(null);
    try {
      const response = await fetchWithAuth(
        `/api/v1/atp/test-lines/resolve?asset_id=${encodeURIComponent(assetId)}`,
      );
      if (!response.ok) throw new Error(await readApiError(response));
      setResolveInfo((await response.json()) as AtpTestLineResolveResponse);
    } catch {
      setResolveInfo({ test_line: null, matched_by: "none", hint: null });
    } finally {
      setResolveLoading(false);
    }
  };

  /** 手动挑选候选：按资产维度过滤，先按完整几何维，再放宽避雷线 */
  const loadCandidates = async (asset: AtpAssetSummary) => {
    setCandidatesLoading(true);
    try {
      const build = (withShieldWire: boolean) => {
        const params = new URLSearchParams();
        params.set("limit", "100");
        if (asset.voltage_level) params.set("voltage_level", asset.voltage_level);
        if (asset.tower_type) params.set("tower_type", asset.tower_type);
        if (withShieldWire && asset.shield_wire) params.set("shield_wire", asset.shield_wire);
        params.set("status", "enabled");
        return `/api/v1/atp/test-lines?${params.toString()}`;
      };
      const first = await fetchWithAuth(build(true));
      if (!first.ok) throw new Error(await readApiError(first));
      let data = (await first.json()) as { items: AtpTestLineSummary[] };
      if ((data.items ?? []).length === 0) {
        const relaxed = await fetchWithAuth(build(false));
        if (relaxed.ok) data = (await relaxed.json()) as { items: AtpTestLineSummary[] };
      }
      setCandidateLines(data.items ?? []);
    } catch {
      setCandidateLines([]);
    } finally {
      setCandidatesLoading(false);
    }
  };

  // 打开时重置并预填资产维度
  useEffect(() => {
    if (!open) return;
    setStages(ALL_STAGES);
    setCurrentKa(31);
    setParamsSource("test-line");
    setAllowIncomplete(false);
    setTowerKind(asset?.tower_type ?? "");
    setScene(asset?.scene_type ?? "");
    setBaseTowerText("{}");
    setProfileText("{}");
    setParamsRaw("");
    setLineId(undefined);
    setTowers([]);
    setSelectedTowerIds([]);
    setManualTestLineId(undefined);
    setCandidateLines([]);
    if (asset?.tower_type) setTowerKind(asset.tower_type);
    if (asset?.scene_type) setScene(asset.scene_type);
    if (asset?.id) void resolveTestLine(asset.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, asset]);

  // 加载线路列表（首次打开缓存）
  const linesLoaded = useMemo(() => lines.length > 0, [lines.length]);

  const handleLineChange = async (value: string) => {
    setLineId(value);
    setSelectedTowerIds([]);
    setTowers([]);
    if (!value) return;
    setTowersLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/lines/${value}/towers?limit=1000`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data: { items: TowerOption[] } = await response.json();
      setTowers(data.items ?? []);
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("加载杆塔失败"));
    } finally {
      setTowersLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (paramsSource === "test-line") {
      if (!activeTestLine) {
        message.warning(t("当前模型没有可用测试线路，请先派生或手动选择一条"));
        return;
      }
      const payload: AtpAssetTestRunRequest = {
        stages,
        tower_kind: towerKind.trim() || null,
        voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
        scene: scene.trim() || null,
        test_line_id: activeTestLine.id,
        params_raw: paramsRaw.trim() || null,
        current_ka: currentKa,
      };
      await submit(payload);
      return;
    }
    if (paramsSource === "tower") {
      const parsedBase = parseJsonObject(baseTowerText);
      if (parsedBase === null) {
        message.error(t("base_tower 不是合法 JSON 对象"));
        return;
      }
      const parsedProfile = parseJsonObject(profileText);
      if (parsedProfile === null) {
        message.error(t("profile 不是合法 JSON 对象"));
        return;
      }
      const payload: AtpAssetTestRunRequest = {
        stages,
        tower_kind: towerKind.trim() || null,
        voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
        scene: scene.trim() || null,
        base_tower: parsedBase,
        profile: parsedProfile,
        params_raw: paramsRaw.trim() || null,
        current_ka: currentKa,
      };
      await submit(payload);
      return;
    }
    if (paramsSource === "line-tower") {
      if (selectedTowerIds.length === 0) {
        message.warning(t("请先选择线路并勾选至少一根杆塔"));
        return;
      }
      const payload: AtpAssetTestRunRequest = {
        stages,
        tower_kind: towerKind.trim() || null,
        voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
        scene: scene.trim() || null,
        line_tower_id: selectedTowerIds[0],
        params_raw: paramsRaw.trim() || null,
        current_ka: currentKa,
      };
      await submit(payload);
      return;
    }
    // template
    const payload: AtpAssetTestRunRequest = {
      stages,
      tower_kind: towerKind.trim() || null,
      voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
      scene: scene.trim() || null,
      params_raw: paramsRaw.trim() || null,
      current_ka: currentKa,
      allow_incomplete_defaults: allowIncomplete,
    };
    await submit(payload);
  };

  const submit = async (payload: AtpAssetTestRunRequest) => {
    setSubmitting(true);
    try {
      const run = await postJson<AtpAssetRunDetail>(`/api/v1/atp/assets/${asset.id}/test-runs`, payload);
      message.success(t("测试已发起"));
      onCreated(run);
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : t("发起测试失败"));
    } finally {
      setSubmitting(false);
    }
  };

  /** 在测试弹窗里就地派生：落库后立刻重新解析，用户不用离开弹窗 */
  const handleDeriveCommit = async ({
    request,
    draft,
    code,
    name,
    sourceKind,
  }: {
    request: AtpTestLineDeriveRequest;
    draft: Record<string, unknown>;
    code: string;
    name: string;
    sourceKind: AtpTestLineSourceKind;
  }): Promise<boolean> => {
    const payload: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(draft)) {
      if (key.startsWith("_") || key === "circuits") continue;
      payload[key] = value;
    }
    if (Array.isArray(draft.circuits)) payload.circuits = draft.circuits;
    payload.code = code;
    payload.name = name;
    payload.source_kind = sourceKind;
    // 从模型入口派生：默认绑给这个模型（模型专用样本），避免污染共享基准
    payload.asset_id = request.asset_id ?? asset.id;
    if (request.source_tower_id) payload.source_tower_id = request.source_tower_id;

    const response = await fetchWithAuth("/api/v1/atp/test-lines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      message.error(await readApiError(response));
      return false;
    }
    message.success(t("测试线路已创建并绑定到该模型"));
    await resolveTestLine(asset.id);
    void loadCandidates(asset);
    return true;
  };

  return (
    <>
    <Modal
      title={`${t("发起测试")} · ${asset.name || asset.code}`}
      open={open}
      onCancel={onClose}
      width={760}
      footer={
        <Space style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
          <Button disabled={submitting} onClick={onClose}>
            {t("取消")}
          </Button>
          <Button type="primary" icon={<RocketOutlined />} loading={submitting} onClick={() => void handleSubmit()}>
            {t("确认测试")}
          </Button>
        </Space>
      }
    >
      <Space direction="vertical" size={12} style={{ width: "100%" }}>
        <Alert
          type="info"
          showIcon
          message={t("测试按 ① 物化 → ② 几何（DAT→LIB）→ ③ 单次 ATP 依次执行，依赖段自动补齐")}
        />

        <Row gutter={16}>
          <Col span={12}>
            <Form.Item label={t("测试段")} style={{ marginBottom: 8 }}>
              <Checkbox.Group
                value={stages}
                onChange={(values) => setStages(values as AtpAssetTestStage[])}
                options={[
                  { value: "materialize", label: t("① 物化") },
                  { value: "geometry", label: t("② 几何") },
                  { value: "simulate", label: t("③ 单次ATP") },
                ]}
              />
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label={t("固定雷电流")} style={{ marginBottom: 8 }}>
              <Space.Compact>
                <InputNumber
                  value={currentKa}
                  min={0.1}
                  onChange={(value) => setCurrentKa(typeof value === "number" ? value : 31)}
                  style={{ width: 100 }}
                />
                <Button disabled style={{ pointerEvents: "none" }}>
                  kA
                </Button>
              </Space.Compact>
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                {t("与 C# 侧必须同值")}
              </Typography.Text>
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item label={t("参数来源")} style={{ marginBottom: 8 }}>
              <Radio.Group
                value={paramsSource}
                onChange={(event) => setParamsSource(event.target.value as ParamsSource)}
                options={[
                  { value: "test-line", label: t("测试线路（单塔基准）") },
                  { value: "line-tower", label: t("从线路杆塔选择") },
                  { value: "tower", label: t("手工杆塔数据") },
                  { value: "template", label: t("参数模板默认值") },
                ]}
                optionType="button"
              />
            </Form.Item>
          </Col>
        </Row>

        {paramsSource === "test-line" ? (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              message={t("用同一条测试线路跑测试：输入逐字节一致，结果可直接与历史对比")}
              description={t("解析顺序：模型绑定 → 同几何维共享基准 → 降级（仅电压+塔型）")}
            />
            <Spin spinning={resolveLoading}>
              {activeTestLine ? (
                <div>
                  <Space size={6} wrap>
                    <Typography.Text strong>{activeTestLine.code}</Typography.Text>
                    <Tag color={MATCHED_BY_LABEL[manualTestLineId ? "geometry" : resolveInfo?.matched_by ?? "none"].color}>
                      {t(manualTestLineId ? "手动选择" : MATCHED_BY_LABEL[resolveInfo?.matched_by ?? "none"].label)}
                    </Tag>
                    {activeTestLine.asset_id ? (
                      <Tag color="purple">{t("模型专用")}</Tag>
                    ) : (
                      <Tag color="blue">{t("共享基准")}</Tag>
                    )}
                    <Tag color="geekblue">{activeTestLine.voltage_level} kV</Tag>
                    <Tag>{activeTestLine.tower_type}</Tag>
                    <Tag color={activeTestLine.shield_wire === "with" ? "cyan" : "default"}>
                      {activeTestLine.shield_wire === "with" ? t("双避雷线") : t("单避雷线")}
                    </Tag>
                  </Space>
                  <div style={{ marginTop: 4 }}>
                    <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                      {t("名称")}：{activeTestLine.name}
                      {activeTestLine.snapshot_hash
                        ? ` ・ ${t("快照")} ${activeTestLine.snapshot_hash.slice(0, 8)}`
                        : ""}
                      {activeTestLine.insulator_length_m != null
                        ? ` ・ ${t("串长")} ${activeTestLine.insulator_length_m} m`
                        : ""}
                      {activeTestLine.call_height_m != null ? ` ・ ${t("呼高")} ${activeTestLine.call_height_m} m` : ""}
                    </Typography.Text>
                  </div>
                  {!manualTestLineId && resolveInfo?.matched_by === "degraded" ? (
                    <Alert
                      type="warning"
                      showIcon
                      style={{ marginTop: 8 }}
                      message={t("这是降级匹配（只对上电压与塔型，避雷线/几何可能不一致）")}
                      description={t("建议为该模型派生一条准确样本，或手动选择更贴近的线路。")}
                    />
                  ) : null}
                </div>
              ) : (
                <Alert
                  type="warning"
                  showIcon
                  message={t("当前模型没有可用的测试线路")}
                  description={resolveInfo?.hint ?? t("可以先派生一条：按模型维度 + 历史成功运行派生最准。")}
                />
              )}
            </Spin>

            <Space wrap>
              <Button size="small" onClick={() => setDeriveOpen(true)}>
                {t("一键派生")}
              </Button>
              <Button
                size="small"
                loading={candidatesLoading}
                onClick={() => {
                  void loadCandidates(asset);
                }}
              >
                {t("加载候选线路")}
              </Button>
              <Select
                size="small"
                allowClear
                showSearch
                optionFilterProp="label"
                style={{ minWidth: 300 }}
                placeholder={t("或手动选择一条同几何维线路")}
                value={manualTestLineId}
                onChange={(value) => setManualTestLineId(value)}
                options={candidateLines.map((item) => ({
                  value: item.id,
                  label: `${item.code}｜${item.name}`,
                }))}
              />
            </Space>

            <Input
              value={paramsRaw}
              onChange={(event) => setParamsRaw(event.target.value)}
              placeholder={t("C# javaParams 原始串（可选，原样进 compare.json）")}
            />
          </Space>
        ) : paramsSource === "line-tower" ? (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Alert
              type="warning"
              showIcon
              message={t("按选中杆塔的真实台账数据测试（与「ATP 参数试算」同口径，后端按塔组装上下文）")}
            />
            <Form layout="vertical">
              <Form.Item label={t("线路")} style={{ marginBottom: 8 }}>
                <Select
                  showSearch
                  placeholder={t("选择线路")}
                  value={lineId}
                  onChange={(value) => void handleLineChange(String(value))}
                  optionFilterProp="label"
                  onOpenChange={async (visible) => {
                    if (visible && !linesLoaded) {
                      try {
                        const response = await fetchWithAuth("/api/v1/lines?limit=1000");
                        if (response.ok) {
                          const data: { items: LineOption[] } = await response.json();
                          setLines(data.items ?? []);
                        }
                      } catch {
                        // 忽略
                      }
                    }
                  }}
                  options={lines.map((line) => ({
                    value: line.id,
                    label: `${line.name}${line.voltage_kv ? `（${line.voltage_kv}kV）` : ""}`,
                  }))}
                />
              </Form.Item>
            </Form>
            <Spin spinning={towersLoading}>
              <Table
                rowKey="id"
                size="small"
                dataSource={towers}
                pagination={modoTablePagination({ pageSize: 8 })}
                locale={{ emptyText: lineId ? t("该线路暂无杆塔") : t("请先选择线路") }}
                rowSelection={{
                  type: "radio",
                  selectedRowKeys: selectedTowerIds,
                  onChange: (keys) => setSelectedTowerIds(keys.map(String)),
                }}
                columns={[
                  { title: t("塔号"), dataIndex: "tower_no", width: 110 },
                  { title: t("塔型"), dataIndex: "tower_type", width: 120, render: (value: string | null) => value || "-" },
                  { title: t("杆塔模型"), dataIndex: "tower_model", render: (value: string | null) => value || "-" },
                  {
                    title: t("海拔(m)"),
                    dataIndex: "altitude_m",
                    width: 90,
                    render: (value: number | null) => (value == null ? "-" : String(value)),
                  },
                ]}
              />
            </Spin>
          </Space>
        ) : (
          <Space direction="vertical" size={8} style={{ width: "100%" }}>
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item label={t("塔型")} style={{ marginBottom: 8 }}>
                  <Input
                    value={towerKind}
                    placeholder={t("如 d220maotou")}
                    onChange={(event) => setTowerKind(event.target.value)}
                  />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item label={t("场景")} style={{ marginBottom: 8 }}>
                  <Input
                    value={scene}
                    placeholder={t("如 fanji")}
                    onChange={(event) => setScene(event.target.value)}
                  />
                </Form.Item>
              </Col>
            </Row>
            {paramsSource === "tower" ? (
              <Row gutter={16}>
                <Col span={12}>
                  <Form.Item label={t("base_tower（JSON）")} style={{ marginBottom: 8 }}>
                    <Input.TextArea
                      rows={4}
                      value={baseTowerText}
                      onChange={(event) => setBaseTowerText(event.target.value)}
                      placeholder={`${t("如")} {"line_voltage_kv":220,"ground_resistance":7}`}
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label={t("profile（JSON）")} style={{ marginBottom: 8 }}>
                    <Input.TextArea
                      rows={4}
                      value={profileText}
                      onChange={(event) => setProfileText(event.target.value)}
                      placeholder={`${t("如")} {"insulator_length_mm":2491.5}`}
                    />
                  </Form.Item>
                </Col>
              </Row>
            ) : (
              <Space size={8}>
                <Typography.Text>{t("模板默认值不完整时仍继续")}</Typography.Text>
                <Switch checked={allowIncomplete} onChange={setAllowIncomplete} />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {t("默认关闭：缺默认值会直接报错并列出缺哪些变量")}
                </Typography.Text>
              </Space>
            )}
            <Input
              value={paramsRaw}
              onChange={(event) => setParamsRaw(event.target.value)}
              placeholder={t("C# javaParams 原始串（原样进 compare.json，供对拍）")}
            />
          </Space>
        )}
      </Space>
    </Modal>

    <AtpTestLineDeriveModal
      open={deriveOpen}
      canManage
      initialAssetId={asset.id}
      onClose={() => setDeriveOpen(false)}
      onCommit={handleDeriveCommit}
    />
    </>
  );
}
