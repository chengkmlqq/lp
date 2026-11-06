"use client";

/**
 * 测试线路派生弹窗（单弹窗两步走：选来源 → 干跑预览 → 确认落库）。
 *
 * 三种派生来源：
 * - 按模型（asset_id）：用模型维度 + 它的历史成功 run 派生，最准
 * - 按维度（电压/塔型/避雷线）：建「共享基准」，同一几何维所有模型共用
 * - 按真实杆塔（line_id + tower_id）：从台账里的真实杆塔派生，快照冻结后不随台账漂移
 *
 * 后端是「后写覆盖先写」的五级派生，所以结果里必然混有可信值与兜底值，
 * 必须逐字段标来源，并把 L5 内置兜底字段单独挑出来提醒复核。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Segmented,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import { useDimensionOptions } from "@/hooks/use-dimension-options";
import {
  SHIELD_WIRE_OPTIONS,
  SOURCE_TONE_COLOR,
  testLineSourceMeta,
  type AtpTestLineDeriveRequest,
  type AtpTestLineDeriveResponse,
  type AtpTestLineIssue,
  type AtpTestLineSourceKind,
} from "@/types/atp-test-line";
import type { AtpAssetSummary } from "@/types/auth";

const { Text } = Typography;

type DeriveSource = "asset" | "dimension" | "tower";

type DraftRow = {
  key: string;
  label: string;
  value: string;
  source: string;
};

type CircuitRow = {
  key: string;
  circuit: string;
  summary: string;
  source: string;
};

type LineOption = { id: string; code: string; name: string; voltage_kv: number | null };
type TowerOption = { id: string; seq_no: number; tower_no: string; tower_type: string | null };

/** 草稿字段 → 中文标签（未列出的字段直接显示原字段名，避免漏字段） */
const DRAFT_FIELD_LABEL: Record<string, string> = {
  voltage_level: "电压等级",
  tower_type: "塔型",
  shield_wire: "避雷线",
  scene_type: "场景",
  arrester_config: "避雷器组合",
  structure_kind: "结构类型",
  circuit_count: "回路数",
  span_small_m: "小档距(m)",
  span_large_m: "大档距(m)",
  ground_resistance_ohm: "接地电阻(Ω)",
  lightning_density: "雷暴日",
  altitude_m: "海拔(m)",
  terrain: "地形",
  slope_1: "坡度1",
  slope_2: "坡度2",
  tower_no: "杆塔号",
  tower_model: "杆塔型号",
  call_height_m: "呼高(m)",
  insulator_length_m: "绝缘子串长(m)",
  shield_wire_height_m: "避雷线高度(m)",
  shield_wire_left_mid_m: "避雷线左中距(m)",
  shield_wire_right_mid_m: "避雷线右中距(m)",
  protection_angle_left_deg: "左侧保护角(°)",
  protection_angle_right_deg: "右侧保护角(°)",
  angle_deg: "转角度(°)",
  phase_sequence_1: "I 回相序",
  phase_sequence_2: "II 回相序",
  phase_sequence_3: "III 回相序",
  phase_sequence_4: "IV 回相序",
  arrester_a: "A 相避雷器",
  arrester_b: "B 相避雷器",
  arrester_c: "C 相避雷器",
  current_ka: "雷电流(kA)",
  current_type: "雷电流波形",
  current_head_time_us: "波头时间(μs)",
  current_tail_time_us: "波尾时间(μs)",
};

function labelOf(field: string): string {
  return DRAFT_FIELD_LABEL[field] ?? field;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** 草稿展平：主表字段 + 回路几何（circuits 走独立表格） */
function buildDraftRows(
  draft: Record<string, unknown>,
  sources: Record<string, string>,
): { main: DraftRow[]; circuits: CircuitRow[] } {
  const main: DraftRow[] = [];
  const circuits: CircuitRow[] = [];

  for (const [field, rawValue] of Object.entries(draft)) {
    if (field.startsWith("_")) continue;
    if (field === "circuits") {
      if (Array.isArray(rawValue)) {
        rawValue.forEach((item, index) => {
          const record = (item ?? {}) as Record<string, unknown>;
          const circuitNo = Number(record.circuit_no ?? index + 1);
          const parts = (["upper", "middle", "lower"] as const)
            .map((phase, phaseIndex) => {
              const spacing = record[`spacing_${phase}_m`];
              const height = record[`height_${phase}_m`];
              if (spacing == null && height == null) return null;
              const name = ["上", "中", "下"][phaseIndex];
              return `${name}相 中距 ${formatValue(spacing)} / 高 ${formatValue(height)}`;
            })
            .filter((text): text is string => Boolean(text));
          circuits.push({
            key: `circuit-${circuitNo}`,
            circuit: `${circuitNo} 回`,
            summary: parts.length > 0 ? parts.join("；") : "无几何数据",
            source: sources[`circuits[${circuitNo}]`] ?? sources.circuits ?? "manual",
          });
        });
      }
      continue;
    }
    main.push({
      key: field,
      label: labelOf(field),
      value: formatValue(rawValue),
      source: sources[field] ?? "",
    });
  }
  return { main, circuits };
}

function SourceTag({ source }: { source: string }) {
  const { t } = useI18n();
  if (!source) return <Tag>{t("未标注")}</Tag>;
  const meta = testLineSourceMeta(source);
  return (
    <Tag color={SOURCE_TONE_COLOR[meta.tone]} title={source}>
      {t(meta.label)}
    </Tag>
  );
}

function IssueBlock({ issues, type }: { issues: AtpTestLineIssue[]; type: "error" | "warning" }) {
  const { t } = useI18n();
  if (issues.length === 0) return null;
  return (
    <Alert
      type={type}
      showIcon
      style={{ marginBottom: 12 }}
      message={type === "error" ? `${t("几何阻断")}：${issues.length} ${t("项")}` : `${t("提示")}：${issues.length} ${t("项")}`}
      description={
        <ul style={{ margin: 0, paddingLeft: 18 }}>
          {issues.map((issue, index) => (
            <li key={`${issue.field}-${index}`}>
              <Text strong>{t(labelOf(issue.field))}</Text>：{issue.reason}
            </li>
          ))}
        </ul>
      }
    />
  );
}

export type AtpTestLineDeriveModalProps = {
  open: boolean;
  /** 从某模型「无可用测试线路」跳过来时预设 */
  initialAssetId?: string | null;
  /** 从列表筛选条件带过来的维度初值（只填空字段，不锁值） */
  initialDimension?: { voltage_level?: string; tower_type?: string; shield_wire?: string } | null;
  canManage: boolean;
  onClose: () => void;
  /** 确认落库；返回 true 关闭弹窗 */
  onCommit: (payload: {
    request: AtpTestLineDeriveRequest;
    draft: Record<string, unknown>;
    code: string;
    name: string;
    sourceKind: AtpTestLineSourceKind;
  }) => Promise<boolean>;
};

export function AtpTestLineDeriveModal({
  open,
  initialAssetId,
  initialDimension,
  canManage,
  onClose,
  onCommit,
}: AtpTestLineDeriveModalProps) {
  const { t } = useI18n();
  const { fetchWithAuth } = useAuth();
  const { message } = App.useApp();
  const [form] = Form.useForm<Record<string, string | undefined>>();

  const [mode, setMode] = useState<DeriveSource>(initialAssetId ? "asset" : "dimension");
  const [assets, setAssets] = useState<AtpAssetSummary[]>([]);
  const [lines, setLines] = useState<LineOption[]>([]);
  const [towers, setTowers] = useState<TowerOption[]>([]);
  const [loadingTowers, setLoadingTowers] = useState(false);

  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<AtpTestLineDeriveResponse | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [lastRequest, setLastRequest] = useState<AtpTestLineDeriveRequest | null>(null);
  const [codeInput, setCodeInput] = useState("");
  const [nameInput, setNameInput] = useState("");

  const { optionMap } = useDimensionOptions({
    voltage_level: "voltage_level",
    tower_type: "tower_type",
    scene_type: "scenario",
    arrester_config: "arrester_combination",
  });

  // 打开时重置
  useEffect(() => {
    if (!open) return;
    setResult(null);
    setLoadError(null);
    setLastRequest(null);
    setCodeInput("");
    setNameInput("");
    setTowers([]);
    const nextMode: DeriveSource = initialAssetId ? "asset" : "dimension";
    setMode(nextMode);
    form.resetFields();
    const preset: Record<string, string> = { shield_wire: "with" };
    if (initialAssetId) preset.asset_id = initialAssetId;
    if (initialDimension?.voltage_level) preset.voltage_level = initialDimension.voltage_level;
    if (initialDimension?.tower_type) preset.tower_type = initialDimension.tower_type;
    if (initialDimension?.shield_wire) preset.shield_wire = initialDimension.shield_wire;
    form.setFieldsValue(preset);
  }, [open, initialAssetId, initialDimension, form]);

  // 懒加载下拉数据（只在对应 tab 首次出现时拉）
  useEffect(() => {
    if (!open) return;
    if (mode === "asset" && assets.length === 0) {
      void (async () => {
        try {
          const response = await fetchWithAuth("/api/v1/atp/assets?limit=200&offset=0");
          if (!response.ok) return;
          const data = (await response.json()) as { items?: AtpAssetSummary[] };
          setAssets(data.items ?? []);
        } catch {
          /* 下拉拉不到就退化为手填维度 */
        }
      })();
    }
    if (mode === "tower" && lines.length === 0) {
      void (async () => {
        try {
          const response = await fetchWithAuth("/api/v1/lines?limit=200&offset=0");
          if (!response.ok) return;
          const data = (await response.json()) as { items?: LineOption[] };
          setLines(data.items ?? []);
        } catch {
          /* 同上 */
        }
      })();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mode]);

  const loadTowers = useCallback(
    async (lineId: string) => {
      setLoadingTowers(true);
      try {
        const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers?limit=500&offset=0`);
        if (!response.ok) {
          setTowers([]);
          return;
        }
        const data = (await response.json()) as { items?: TowerOption[] };
        setTowers(data.items ?? []);
      } catch {
        setTowers([]);
      } finally {
        setLoadingTowers(false);
      }
    },
    [fetchWithAuth],
  );

  const runDerive = async (request: AtpTestLineDeriveRequest) => {
    setLoading(true);
    setLoadError(null);
    setResult(null);
    try {
      const response = await fetchWithAuth("/api/v1/atp/test-lines:derive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as AtpTestLineDeriveResponse;
      setResult(data);
      setLastRequest(request);
      setCodeInput(data.suggested_code ?? "");
      const draftName = typeof data.draft.name === "string" ? data.draft.name : "";
      const voltage = formatValue(data.draft.voltage_level);
      const towerType = formatValue(data.draft.tower_type);
      setNameInput(draftName || `测试线路 ${voltage}kV ${towerType}`.trim());
    } catch (error) {
      setResult(null);
      setLoadError(error instanceof Error ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  };

  const handleDerive = async () => {
    let values: Record<string, string | undefined>;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }
    const request: AtpTestLineDeriveRequest = {};
    if (mode === "asset") {
      request.asset_id = values.asset_id;
    } else if (mode === "dimension") {
      request.voltage_level = values.voltage_level;
      request.tower_type = values.tower_type;
      request.shield_wire = values.shield_wire;
      if (values.scene_type) request.scene_type = values.scene_type;
      if (values.arrester_config) request.arrester_config = values.arrester_config;
    } else {
      request.source_tower_id = values.tower_id;
    }
    await runDerive(request);
  };

  const draftRows = useMemo(
    () => (result ? buildDraftRows(result.draft, result.sources) : { main: [], circuits: [] }),
    [result],
  );

  const fallbackFields = useMemo(() => {
    if (!result) return [] as string[];
    return Object.entries(result.sources)
      .filter(([, source]) => source === "L5:builtin")
      .map(([field]) => labelOf(field));
  }, [result]);

  const hasBlockers = (result?.blockers.length ?? 0) > 0;
  const canSubmit =
    canManage && Boolean(result) && !hasBlockers && !saving && codeInput.trim().length > 0;

  const handleCommit = async () => {
    if (!result || !lastRequest) return;
    setSaving(true);
    try {
      const sourceKind: AtpTestLineSourceKind =
        lastRequest.source_tower_id ? "from_tower" : lastRequest.asset_id ? "from_asset_run" : "derived";
      const ok = await onCommit({
        request: lastRequest,
        draft: result.draft,
        code: codeInput.trim(),
        name: nameInput.trim() || codeInput.trim(),
        sourceKind,
      });
      if (ok) {
        message.success(t("测试线路已创建"));
        onClose();
      }
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<DraftRow> = [
    { title: t("字段"), dataIndex: "label", width: 170, render: (value: string) => <Text strong>{t(value)}</Text> },
    { title: t("派生值"), dataIndex: "value", ellipsis: true },
    {
      title: t("来源"),
      dataIndex: "source",
      width: 110,
      render: (value: string) => <SourceTag source={value} />,
    },
  ];

  return (
    <Modal
      open={open}
      title={t("派生测试线路（单塔基准）")}
      width={920}
      onCancel={onClose}
      destroyOnHidden
      maskClosable={false}
      footer={
        <Space>
          <Button onClick={onClose}>{t("取消")}</Button>
          <Button type="primary" loading={saving} disabled={!canSubmit} onClick={() => void handleCommit()}>
            {t("确认并保存")}
          </Button>
        </Space>
      }
    >
      <Segmented
        value={mode}
        onChange={(value) => setMode(value as DeriveSource)}
        options={[
          { label: t("按模型派生"), value: "asset" },
          { label: t("按维度派生（共享基准）"), value: "dimension" },
          { label: t("按真实杆塔派生"), value: "tower" },
        ]}
        style={{ marginBottom: 12 }}
      />

      <Form form={form} layout="vertical" initialValues={{ shield_wire: "with" }}>
        {mode === "asset" ? (
          <Row gutter={12}>
            <Col span={16}>
              <Form.Item
                name="asset_id"
                label={t("ATP 模型")}
                rules={[{ required: true, message: t("请选择模型") }]}
                tooltip={t("用该模型的维度 + 历史成功 run 派生，命中率最高")}
              >
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder={t("按代码/名称搜索")}
                  options={assets.map((asset) => ({
                    value: asset.id,
                    label: `${asset.code}｜${asset.name}`,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
        ) : mode === "dimension" ? (
          <>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="voltage_level" label={t("电压等级(kV)")} rules={[{ required: true, message: t("必填") }]}>
                  <AutoComplete allowClear placeholder="500" options={optionMap.voltage_level ?? []} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="tower_type" label={t("塔型")} rules={[{ required: true, message: t("必填") }]}>
                  <AutoComplete allowClear placeholder="guxing" options={optionMap.tower_type ?? []} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="shield_wire" label={t("避雷线")} rules={[{ required: true, message: t("必填") }]}>
                  <Select options={SHIELD_WIRE_OPTIONS.map((o) => ({ value: o.value, label: t(o.label) }))} />
                </Form.Item>
              </Col>
            </Row>
            <Row gutter={12}>
              <Col span={8}>
                <Form.Item name="scene_type" label={t("场景（可选）")} tooltip={t("只影响参数规则，不改变几何")}>
                  <AutoComplete allowClear placeholder={t("不限")} options={optionMap.scene_type ?? []} />
                </Form.Item>
              </Col>
              <Col span={8}>
                <Form.Item name="arrester_config" label={t("避雷器组合（可选）")} tooltip={t("只影响参数规则，不改变几何")}>
                  <AutoComplete allowClear placeholder={t("不限")} options={optionMap.arrester_config ?? []} />
                </Form.Item>
              </Col>
            </Row>
          </>
        ) : (
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item name="line_id" label={t("线路")} rules={[{ required: true, message: t("请选择线路") }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  placeholder={t("按名称搜索")}
                  onChange={(value: string) => {
                    form.setFieldsValue({ tower_id: undefined });
                    void loadTowers(value);
                  }}
                  options={lines.map((line) => ({
                    value: line.id,
                    label: `${line.name}${line.voltage_kv ? `（${line.voltage_kv}kV）` : ""}`,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="tower_id" label={t("杆塔")} rules={[{ required: true, message: t("请选择杆塔") }]}>
                <Select
                  showSearch
                  optionFilterProp="label"
                  loading={loadingTowers}
                  placeholder={t("先选线路")}
                  options={towers.map((tower) => ({
                    value: tower.id,
                    label: `#${tower.seq_no} ${tower.tower_no}${tower.tower_type ? `｜${tower.tower_type}` : ""}`,
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
        )}

        <Space style={{ marginBottom: 12 }}>
          <Button type="primary" ghost loading={loading} onClick={() => void handleDerive()}>
            {result ? t("重新派生") : t("开始派生")}
          </Button>
          <Text type="secondary">{t("派生是干跑，不会写库；确认后才创建。")}</Text>
        </Space>
      </Form>

      {loading ? (
        <div style={{ padding: 40, display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
          <Spin />
          <Text type="secondary">{t("正在按五级来源派生…")}</Text>
        </div>
      ) : loadError ? (
        <Alert type="error" showIcon message={t("派生失败")} description={loadError} />
      ) : !result ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("选择来源后点击「开始派生」")} />
      ) : (
        <div style={{ maxHeight: "52vh", overflowY: "auto", paddingRight: 4 }}>
          <IssueBlock issues={result.blockers} type="error" />
          <IssueBlock issues={result.warnings} type="warning" />

          {fallbackFields.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("以下字段用了内置兜底值，请对照图纸复核")}
              description={
                <Space size={[4, 4]} wrap>
                  {fallbackFields.map((field) => (
                    <Tag key={field} color={SOURCE_TONE_COLOR.builtin}>
                      {field}
                    </Tag>
                  ))}
                </Space>
              }
            />
          ) : null}

          {result.not_consumed.length > 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("以下字段有值但仿真管线不消费")}
              description={result.not_consumed.join("、")}
            />
          ) : null}

          <Row gutter={12} style={{ marginBottom: 8 }}>
            <Col span={10}>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                {t("代码")}
              </Text>
              <Input value={codeInput} onChange={(event) => setCodeInput(event.currentTarget.value)} />
            </Col>
            <Col span={14}>
              <Text type="secondary" style={{ display: "block", marginBottom: 4 }}>
                {t("名称")}
              </Text>
              <Input value={nameInput} onChange={(event) => setNameInput(event.currentTarget.value)} />
            </Col>
          </Row>

          <Table<DraftRow>
            rowKey="key"
            size="small"
            bordered
            columns={columns}
            dataSource={draftRows.main}
            pagination={false}
            scroll={{ y: 240 }}
          />

          {draftRows.circuits.length > 0 ? (
            <>
              <Text strong style={{ display: "block", margin: "12px 0 8px" }}>
                {t("回路几何")}
              </Text>
              <Table<CircuitRow>
                rowKey="key"
                size="small"
                bordered
                pagination={false}
                dataSource={draftRows.circuits}
                columns={[
                  { title: t("回路"), dataIndex: "circuit", width: 80 },
                  { title: t("上/中/下相中距与相高"), dataIndex: "summary" },
                  {
                    title: t("来源"),
                    dataIndex: "source",
                    width: 110,
                    render: (value: string) => <SourceTag source={value} />,
                  },
                ]}
              />
            </>
          ) : null}

          {hasBlockers ? (
            <Text type="danger" style={{ display: "block", marginTop: 12 }}>
              {t("存在几何阻断项，补齐后重新派生才能保存。可切到「按真实杆塔派生」拿到完整几何。")}
            </Text>
          ) : null}
        </div>
      )}
    </Modal>
  );
}

export default AtpTestLineDeriveModal;
