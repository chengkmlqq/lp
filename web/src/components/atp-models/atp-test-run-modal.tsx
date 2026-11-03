"use client";

// ATP 模型「测试参数」弹窗。
// 来源收敛（2026-11-03）：几何/工况唯一来源 = 测试线路（单塔基准）——
//   · 默认按资产维度自动解析（模型绑定 → 几何维 → 降级），也可手动挑候选；
//   · 没有线路就一键派生，派生完直接绑定该模型；
//   · 旧的 template（模板默认值）/ tower（手工 JSON）/ line-tower（线路杆塔选择）
//     入口已下线，后端对旧来源会显式 400 并给迁移提示。
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
  Row,
  Select,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { RocketOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
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

const MATCHED_BY_LABEL: Record<AtpTestLineMatchedBy, { label: string; color: string }> = {
  bound: { label: "模型绑定", color: "purple" },
  geometry: { label: "几何维匹配", color: "blue" },
  degraded: { label: "降级匹配（仅电压+塔型）", color: "gold" },
  none: { label: "无匹配", color: "default" },
};

type AtpTestRunModalProps = {
  asset: AtpAssetSummary;
  open: boolean;
  onClose: () => void;
  onCreated: (run: AtpAssetRunDetail) => void;
};

export function AtpTestRunModal({ asset, open, onClose, onCreated }: AtpTestRunModalProps) {
  const { t } = useI18n();
  const { message } = App.useApp();
  const { fetchWithAuth } = useAuth();

  const [stages, setStages] = useState<AtpAssetTestStage[]>(ALL_STAGES);
  const [currentKa, setCurrentKa] = useState<number>(31);
  const [scene, setScene] = useState("");
  const [paramsRaw, setParamsRaw] = useState("");
  const [submitting, setSubmitting] = useState(false);
  // 测试线路（单塔基准）：唯一几何/工况来源
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
    setScene(asset?.scene_type ?? "");
    setParamsRaw("");
    setManualTestLineId(undefined);
    setCandidateLines([]);
    if (asset?.id) void resolveTestLine(asset.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, asset]);

  const handleSubmit = async () => {
    if (!activeTestLine) {
      message.warning(t("当前模型没有可用测试线路，请先派生或手动选择一条"));
      return;
    }
    const payload: AtpAssetTestRunRequest = {
      stages,
      voltage_kv: asset.voltage_level ? Number(asset.voltage_level) : null,
      scene: scene.trim() || null,
      test_line_id: activeTestLine.id,
      params_raw: paramsRaw.trim() || null,
      current_ka: currentKa,
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
      width={720}
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
          <Col span={12}>
            <Form.Item label={t("场景")} style={{ marginBottom: 8 }}>
              <Input
                value={scene}
                placeholder={t("如 fanji")}
                onChange={(event) => setScene(event.target.value)}
              />
            </Form.Item>
          </Col>
          <Col span={24}>
            <Form.Item label={t("测试线路（几何与工况唯一来源）")} style={{ marginBottom: 8 }}>
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

              <Space wrap style={{ marginTop: 8 }}>
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
            </Form.Item>
          </Col>
          <Col span={24}>
            <Input
              value={paramsRaw}
              onChange={(event) => setParamsRaw(event.target.value)}
              placeholder={t("C# javaParams 原始串（可选，原样进 compare.json）")}
            />
          </Col>
        </Row>
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
