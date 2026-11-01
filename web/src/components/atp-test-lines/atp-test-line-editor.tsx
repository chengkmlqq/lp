"use client";

/**
 * 测试线路编辑抽屉（新建 / 编辑共用）。
 *
 * 四组表单：维度信息 → 杆塔几何（含回路几何）→ 线路环境 → 测试参数。
 * 每个可派生字段右侧挂一枚来源 Tag：
 * - 绿色/青色/靛蓝 = 来自真实台账（历史运行 / 参数模板 / 杆塔库），可信
 * - 金色/橙色 = 来自维度配置或内置档位参考，**需要人工复核**
 * - 灰色 = 手填或未标注
 *
 * 单位约定：绝缘子串长等长度字段一律**米**（后端兼容历史毫米值，但新数据不写毫米）。
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Col,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
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
  STRUCTURE_KIND_OPTIONS,
  TEST_LINE_STATUS_META,
  testLineSourceMeta,
  type AtpTestLineCircuit,
  type AtpTestLineDetail,
  type AtpTestLineStatus,
} from "@/types/atp-test-line";

const { Text } = Typography;

type FormValues = Record<string, string | number | null | undefined>;

type CircuitRow = AtpTestLineCircuit & { key: string };

export type AtpTestLineEditorProps = {
  open: boolean;
  mode: "create" | "edit";
  /** 编辑时的完整详情（含 derive_rules_json 来源标注） */
  detail?: AtpTestLineDetail | null;
  /** 新建时由派生带过来的草稿 + 来源 */
  draft?: Record<string, unknown> | null;
  draftSources?: Record<string, string>;
  /** 新建时预设的维度/绑定（派生入参透传） */
  presetAssetId?: string | null;
  presetSourceKind?: "derived" | "manual" | "from_tower" | "from_asset_run";
  canManage: boolean;
  onClose: () => void;
  onSaved: (detail: AtpTestLineDetail) => void;
};

const DEFAULT_VALUES: FormValues = {
  voltage_level: "",
  tower_type: "",
  shield_wire: "with",
  scene_type: null,
  arrester_config: null,
  structure_kind: null,
  circuit_count: 1,
  span_small_m: null,
  span_large_m: null,
  ground_resistance_ohm: null,
  lightning_density: null,
  altitude_m: null,
  terrain: null,
  slope_1: null,
  slope_2: null,
  tower_no: null,
  tower_model: null,
  call_height_m: null,
  insulator_length_m: null,
  shield_wire_height_m: null,
  shield_wire_left_mid_m: null,
  shield_wire_right_mid_m: null,
  protection_angle_left_deg: null,
  protection_angle_right_deg: null,
  angle_deg: null,
  phase_sequence_1: null,
  phase_sequence_2: null,
  phase_sequence_3: null,
  phase_sequence_4: null,
  arrester_a: null,
  arrester_b: null,
  arrester_c: null,
  current_ka: 31,
  current_type: null,
  current_head_time_us: null,
  current_tail_time_us: null,
};

/** 空字符串 → null（避免把 "" 当数字/代码写库） */
function normalizeValue(value: unknown): unknown {
  if (value === "" || value === undefined) return null;
  return value;
}

function buildCircuitRows(count: number, source: AtpTestLineCircuit[] | undefined): CircuitRow[] {
  const byNo = new Map<number, AtpTestLineCircuit>();
  for (const circuit of source ?? []) {
    byNo.set(circuit.circuit_no, circuit);
  }
  return Array.from({ length: Math.max(1, Math.min(4, count)) }, (_, index) => {
    const circuitNo = index + 1;
    const existing = byNo.get(circuitNo);
    return {
      key: `circuit-${circuitNo}`,
      circuit_no: circuitNo,
      phase_sequence: existing?.phase_sequence ?? null,
      spacing_upper_m: existing?.spacing_upper_m ?? null,
      spacing_middle_m: existing?.spacing_middle_m ?? null,
      spacing_lower_m: existing?.spacing_lower_m ?? null,
      height_upper_m: existing?.height_upper_m ?? null,
      height_middle_m: existing?.height_middle_m ?? null,
      height_lower_m: existing?.height_lower_m ?? null,
    };
  });
}

export function AtpTestLineEditor({
  open,
  mode,
  detail,
  draft,
  draftSources,
  presetAssetId,
  presetSourceKind,
  canManage,
  onClose,
  onSaved,
}: AtpTestLineEditorProps) {
  const { t } = useI18n();
  const { fetchWithAuth } = useAuth();
  const { message } = App.useApp();
  const [form] = Form.useForm<FormValues>();

  const [circuits, setCircuits] = useState<CircuitRow[]>(buildCircuitRows(1, undefined));
  const [saving, setSaving] = useState(false);
  const [errorText, setErrorText] = useState<string | null>(null);
  const [blockers, setBlockers] = useState<{ field: string; reason: string }[]>([]);

  const { optionMap } = useDimensionOptions({
    voltage_level: "voltage_level",
    tower_type: "tower_type",
    scene_type: "scenario",
    arrester_config: "arrester_combination",
  });

  /** 编辑时来源标注来自 detail.derive_rules_json；新建时来自派生草稿 */
  const sources = useMemo<Record<string, string>>(() => {
    if (mode === "edit") return detail?.derive_rules_json ?? {};
    return draftSources ?? {};
  }, [mode, detail, draftSources]);

  // 打开时灌值（编辑取详情，新建取草稿 / 默认值）
  useEffect(() => {
    if (!open) return;
    setErrorText(null);
    setBlockers([]);
    if (mode === "edit" && detail) {
      // 只灌标量字段：circuits 走独立 state，derive_rules_json / snapshot_json 是对象
      const { circuits: _circuits, derive_rules_json: _rules, snapshot_json: _snapshot, ...scalarFields } = detail;
      void _circuits;
      void _rules;
      void _snapshot;
      form.setFieldsValue({ ...DEFAULT_VALUES, ...scalarFields } as unknown as FormValues);
      setCircuits(buildCircuitRows(detail.circuit_count, detail.circuits));
      return;
    }
    const merged: FormValues = { ...DEFAULT_VALUES };
    for (const [key, value] of Object.entries(draft ?? {})) {
      if (key === "circuits" || key.startsWith("_")) continue;
      merged[key] = value as string | number | null;
    }
    form.setFieldsValue(merged);
    const draftCircuits = Array.isArray(draft?.circuits)
      ? (draft?.circuits as AtpTestLineCircuit[])
      : undefined;
    const count = Number(merged.circuit_count ?? 1) || 1;
    setCircuits(buildCircuitRows(count, draftCircuits));
  }, [open, mode, detail, draft, form]);

  const sourceTag = useCallback(
    (field: string) => {
      const source = sources[field];
      if (!source) return null;
      const meta = testLineSourceMeta(source);
      return (
        <Tooltip title={`${t("派生来源")}：${source}`}>
          <Tag color={SOURCE_TONE_COLOR[meta.tone]} style={{ marginInlineStart: 6, fontWeight: 400 }}>
            {t(meta.label)}
          </Tag>
        </Tooltip>
      );
    },
    [sources, t],
  );

  /** 带来源标注的 Form.Item label */
  const labelWithSource = useCallback(
    (field: string, text: string) => (
      <span>
        {t(text)}
        {sourceTag(field)}
      </span>
    ),
    [sourceTag, t],
  );

  const handleCircuitCountChange = (value: number | null) => {
    const count = Math.max(1, Math.min(4, Number(value) || 1));
    setCircuits((prev) => {
      if (prev.length === count) return prev;
      if (prev.length > count) return prev.slice(0, count);
      const extra = buildCircuitRows(count, undefined).slice(prev.length);
      return [...prev, ...extra];
    });
  };

  const updateCircuit = (circuitNo: number, patch: Partial<AtpTestLineCircuit>) => {
    setCircuits((prev) =>
      prev.map((row) => (row.circuit_no === circuitNo ? { ...row, ...patch } : row)),
    );
  };

  const handleSubmit = async () => {
    setErrorText(null);
    setBlockers([]);
    let values: FormValues;
    try {
      values = await form.validateFields();
    } catch {
      return;
    }

    const payload: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(values)) {
      payload[key] = normalizeValue(value);
    }
    payload.code = normalizeValue(values.code);
    payload.name = normalizeValue(values.name);
    payload.description = typeof values.description === "string" ? values.description : "";
    payload.circuits = circuits.map((row) => ({
      circuit_no: row.circuit_no,
      phase_sequence: row.phase_sequence || null,
      spacing_upper_m: row.spacing_upper_m ?? null,
      spacing_middle_m: row.spacing_middle_m ?? null,
      spacing_lower_m: row.spacing_lower_m ?? null,
      height_upper_m: row.height_upper_m ?? null,
      height_middle_m: row.height_middle_m ?? null,
      height_lower_m: row.height_lower_m ?? null,
    }));

    setSaving(true);
    try {
      const isEdit = mode === "edit" && detail;
      // 编辑不允许改归属（asset_id）：改归属等于换身份，应该走「复制」而不是「编辑」
      delete payload.asset_id;
      if (!isEdit) {
        payload.asset_id = presetAssetId ?? null;
        payload.status = (values.status as AtpTestLineStatus) ?? "enabled";
        payload.source_kind = presetSourceKind ?? "manual";
      }
      const response = await fetchWithAuth(
        isEdit ? `/api/v1/atp/test-lines/${detail!.id}` : "/api/v1/atp/test-lines",
        {
          method: isEdit ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        },
      );
      if (!response.ok) {
        const raw = await readApiError(response);
        // 后端几何校验失败时 detail 是 {message, blockers}，尝试抽出阻断项逐条显示
        try {
          const parsed = JSON.parse(raw) as { detail?: { blockers?: { field: string; reason: string }[]; message?: string } };
          const list = parsed.detail?.blockers;
          if (Array.isArray(list) && list.length > 0) {
            setBlockers(list);
            setErrorText(parsed.detail?.message ?? t("几何校验未通过"));
            setSaving(false);
            return;
          }
        } catch {
          /* raw 不是 JSON，直接展示 */
        }
        setErrorText(raw);
        setSaving(false);
        return;
      }
      const saved = (await response.json()) as AtpTestLineDetail;
      message.success(mode === "edit" ? t("测试线路已更新（快照已重算）") : t("测试线路已创建"));
      onSaved(saved);
      onClose();
    } catch (error) {
      setErrorText(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };

  const circuitColumns: ColumnsType<CircuitRow> = [
    {
      title: t("回路"),
      dataIndex: "circuit_no",
      width: 64,
      render: (value: number) => <Text strong>{value} 回</Text>,
    },
    ...(
      [
        ["spacing_upper_m", "上相中距(m)"],
        ["spacing_middle_m", "中相中距(m)"],
        ["spacing_lower_m", "下相中距(m)"],
        ["height_upper_m", "上相高(m)"],
        ["height_middle_m", "中相高(m)"],
        ["height_lower_m", "下相高(m)"],
      ] as const
    ).map(([field, label]) => ({
      title: t(label),
      dataIndex: field,
      width: 120,
      render: (_: unknown, row: CircuitRow) => (
        <InputNumber
          size="small"
          min={0}
          step={0.1}
          style={{ width: "100%" }}
          value={row[field] ?? null}
          onChange={(value) => updateCircuit(row.circuit_no, { [field]: value } as Partial<AtpTestLineCircuit>)}
          disabled={!canManage}
        />
      ),
    })),
  ];

  const isEdit = mode === "edit" && Boolean(detail);

  return (
    <Drawer
      open={open}
      title={isEdit ? `${t("编辑测试线路")}：${detail?.code ?? ""}` : t("新建测试线路")}
      width={900}
      onClose={onClose}
      destroyOnHidden
      maskClosable={false}
      extra={
        <Space>
          <Button onClick={onClose}>{t("取消")}</Button>
          <Button type="primary" loading={saving} disabled={!canManage} onClick={() => void handleSubmit()}>
            {isEdit ? t("保存") : t("创建")}
          </Button>
        </Space>
      }
    >
      {!canManage ? (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={t("当前账号没有 atp.manage 权限，只能查看。")}
        />
      ) : null}

      {errorText ? (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 12 }}
          message={t("保存失败")}
          description={
            blockers.length > 0 ? (
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {blockers.map((item, index) => (
                  <li key={`${item.field}-${index}`}>
                    <Text strong>{item.field}</Text>：{item.reason}
                  </li>
                ))}
              </ul>
            ) : (
              errorText
            )
          }
        />
      ) : null}

      <Form form={form} layout="vertical" disabled={!canManage} initialValues={DEFAULT_VALUES}>
        {/* ── 1. 维度信息 ── */}
        <Divider orientation="start" style={{ marginTop: 0 }}>
          {t("维度信息")}
        </Divider>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="voltage_level"
              label={labelWithSource("voltage_level", "电压等级(kV)")}
              rules={[{ required: true, message: t("必填") }]}
            >
              <AutoComplete
                allowClear
                placeholder={t("如 500")}
                options={optionMap.voltage_level ?? []}
                filterOption={(input, option) =>
                  String(option?.label ?? option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                }
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="tower_type"
              label={labelWithSource("tower_type", "塔型")}
              rules={[{ required: true, message: t("必填") }]}
            >
              <AutoComplete
                allowClear
                placeholder={t("如 guxing")}
                options={optionMap.tower_type ?? []}
                filterOption={(input, option) =>
                  String(option?.label ?? option?.value ?? "").toLowerCase().includes(input.toLowerCase())
                }
              />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="shield_wire"
              label={labelWithSource("shield_wire", "避雷线")}
              rules={[{ required: true, message: t("必填") }]}
            >
              <Select options={SHIELD_WIRE_OPTIONS.map((o) => ({ value: o.value, label: t(o.label) }))} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="code" label={t("代码")} tooltip={t("留空按 电压-塔型-避雷线 自动生成")}>
              <Input placeholder={t("留空自动生成")} disabled={isEdit} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="name" label={t("名称")}>
              <Input placeholder={t("留空与代码相同")} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="status" label={t("状态")}>
              <Select
                options={(Object.keys(TEST_LINE_STATUS_META) as AtpTestLineStatus[]).map((key) => ({
                  value: key,
                  label: t(TEST_LINE_STATUS_META[key].label),
                }))}
              />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item name="scene_type" label={labelWithSource("scene_type", "场景")} tooltip={t("标签维，不影响杆塔几何")}>
              <AutoComplete allowClear placeholder={t("不限")} options={optionMap.scene_type ?? []} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item
              name="arrester_config"
              label={labelWithSource("arrester_config", "避雷器组合")}
              tooltip={t("标签维，不影响杆塔几何")}
            >
              <AutoComplete allowClear placeholder={t("不限")} options={optionMap.arrester_config ?? []} />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="structure_kind" label={labelWithSource("structure_kind", "结构类型")}>
              <Select allowClear placeholder={t("不限")} options={STRUCTURE_KIND_OPTIONS.map((o) => ({ value: o.value, label: t(o.label) }))} />
            </Form.Item>
          </Col>
        </Row>
        <Form.Item name="description" label={t("说明")}>
          <Input.TextArea rows={2} maxLength={4000} showCount />
        </Form.Item>

        {/* ── 2. 杆塔几何 ── */}
        <Divider orientation="start">{t("杆塔几何")}</Divider>
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item name="tower_no" label={labelWithSource("tower_no", "杆塔号")}>
              <Input />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="tower_model" label={labelWithSource("tower_model", "杆塔型号")}>
              <Input />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="circuit_count" label={labelWithSource("circuit_count", "回路数")}>
              <InputNumber min={1} max={4} style={{ width: "100%" }} onChange={handleCircuitCountChange} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="call_height_m" label={labelWithSource("call_height_m", "呼高(m)")}>
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={8}>
            <Form.Item
              name="insulator_length_m"
              label={labelWithSource("insulator_length_m", "绝缘子串长(m)")}
              tooltip={t("单位米；历史数据是毫米时后端会自动换算（>100 视为毫米）")}
            >
              <InputNumber min={0} step={0.01} style={{ width: "100%" }} placeholder="4.45" />
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="shield_wire_height_m" label={labelWithSource("shield_wire_height_m", "避雷线高度(m)")}>
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item
              name="shield_wire_left_mid_m"
              label={labelWithSource("shield_wire_left_mid_m", "左中距(m)")}
              rules={[{ required: true, message: t("几何必需") }]}
            >
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item
              name="shield_wire_right_mid_m"
              label={labelWithSource("shield_wire_right_mid_m", "右中距(m)")}
              rules={[{ required: true, message: t("几何必需") }]}
            >
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item name="protection_angle_left_deg" label={labelWithSource("protection_angle_left_deg", "左保护角(°)")}>
              <InputNumber step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="protection_angle_right_deg" label={labelWithSource("protection_angle_right_deg", "右保护角(°)")}>
              <InputNumber step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="angle_deg" label={labelWithSource("angle_deg", "转角度(°)")}>
              <InputNumber step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>

        <Text strong style={{ display: "block", marginBottom: 8 }}>
          {t("回路几何（上/中/下相中距与相高）")}
        </Text>
        <Table<CircuitRow>
          rowKey="key"
          size="small"
          bordered
          columns={circuitColumns}
          dataSource={circuits}
          pagination={false}
          scroll={{ x: 780 }}
          style={{ marginBottom: 16 }}
        />

        <Row gutter={12}>
          {[1, 2, 3, 4].map((index) => (
            <Col span={6} key={`phase-sequence-${index}`}>
              <Form.Item name={`phase_sequence_${index}`} label={labelWithSource(`phase_sequence_${index}`, `${["I", "II", "III", "IV"][index - 1]} 回相序`)}>
                <Input placeholder="ABC" />
              </Form.Item>
            </Col>
          ))}
        </Row>

        {/* ── 3. 线路环境 ── */}
        <Divider orientation="start">{t("线路环境")}</Divider>
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item
              name="span_small_m"
              label={labelWithSource("span_small_m", "小档距(m)")}
              rules={[{ type: "number", max: 3000, min: 0.001, message: t("需在 (0, 3000] 米") }]}
            >
              <InputNumber min={0.001} max={3000} step={10} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="span_large_m"
              label={labelWithSource("span_large_m", "大档距(m)")}
              rules={[{ type: "number", max: 3000, min: 0.001, message: t("需在 (0, 3000] 米") }]}
            >
              <InputNumber min={0.001} max={3000} step={10} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="ground_resistance_ohm" label={labelWithSource("ground_resistance_ohm", "接地电阻(Ω)")}>
              <InputNumber min={0} step={0.5} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="lightning_density" label={labelWithSource("lightning_density", "雷暴日")}>
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item
              name="altitude_m"
              label={
                <span>
                  {labelWithSource("altitude_m", "海拔(m)")}
                  <Tag style={{ marginInlineStart: 6 }}>{t("不参与仿真")}</Tag>
                </span>
              }
            >
              <InputNumber min={0} step={10} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="terrain"
              label={
                <span>
                  {labelWithSource("terrain", "地形")}
                  <Tag style={{ marginInlineStart: 6 }}>{t("不参与仿真")}</Tag>
                </span>
              }
            >
              <Input />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="slope_1"
              label={
                <span>
                  {labelWithSource("slope_1", "坡度1")}
                  <Tag style={{ marginInlineStart: 6 }}>{t("不参与仿真")}</Tag>
                </span>
              }
            >
              <InputNumber step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item
              name="slope_2"
              label={
                <span>
                  {labelWithSource("slope_2", "坡度2")}
                  <Tag style={{ marginInlineStart: 6 }}>{t("不参与仿真")}</Tag>
                </span>
              }
            >
              <InputNumber step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>

        {/* ── 4. 测试参数 ── */}
        <Divider orientation="start">{t("测试参数")}</Divider>
        <Row gutter={12}>
          <Col span={6}>
            <Form.Item
              name="current_ka"
              label={labelWithSource("current_ka", "雷电流(kA)")}
              rules={[{ required: true, message: t("必填") }]}
            >
              <InputNumber min={0.001} step={1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="current_type" label={labelWithSource("current_type", "波形类型")}>
              <Input placeholder="2.6/50" />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="current_head_time_us" label={labelWithSource("current_head_time_us", "波头时间(μs)")}>
              <InputNumber min={0} step={0.1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name="current_tail_time_us" label={labelWithSource("current_tail_time_us", "波尾时间(μs)")}>
              <InputNumber min={0} step={1} style={{ width: "100%" }} />
            </Form.Item>
          </Col>
        </Row>
        <Row gutter={12}>
          {(["a", "b", "c"] as const).map((phase) => (
            <Col span={8} key={`arrester-${phase}`}>
              <Form.Item name={`arrester_${phase}`} label={labelWithSource(`arrester_${phase}`, `${phase.toUpperCase()} 相避雷器`)}>
                <Input placeholder={t("留空表示无避雷器")} />
              </Form.Item>
            </Col>
          ))}
        </Row>
      </Form>
    </Drawer>
  );
}

export default AtpTestLineEditor;
