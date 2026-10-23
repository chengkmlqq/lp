"use client";

// ATP 模型「测试参数」弹窗。
// 参数来源三种：
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
  Typography,
} from "antd";
import { RocketOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { postJson, readApiError } from "@/lib/api";
import type {
  AtpAssetRunDetail,
  AtpAssetSummary,
  AtpAssetTestRunRequest,
  AtpAssetTestStage,
} from "@/types/auth";

const ALL_STAGES: AtpAssetTestStage[] = ["materialize", "geometry", "simulate"];

export type ParamsSource = "template" | "tower" | "line-tower";

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

function parseJsonObject(text: string, label: string): Record<string, unknown> | null {
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
  const [dryRun, setDryRun] = useState(false);
  const [paramsSource, setParamsSource] = useState<ParamsSource>("template");
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

  // 打开时重置并预填资产维度
  useEffect(() => {
    if (!open) return;
    setStages(ALL_STAGES);
    setCurrentKa(31);
    setDryRun(false);
    setParamsSource("template");
    setAllowIncomplete(false);
    setTowerKind(asset?.tower_type ?? "");
    setScene(asset?.scene_type ?? "");
    setBaseTowerText("{}");
    setProfileText("{}");
    setParamsRaw("");
    setLineId(undefined);
    setTowers([]);
    setSelectedTowerIds([]);
    if (asset?.tower_type) setTowerKind(asset.tower_type);
    if (asset?.scene_type) setScene(asset.scene_type);
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
      message.error(error instanceof Error ? error.message : "加载杆塔失败");
    } finally {
      setTowersLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (paramsSource === "tower") {
      const parsedBase = parseJsonObject(baseTowerText, "base_tower");
      if (parsedBase === null) {
        message.error("base_tower 不是合法 JSON 对象");
        return;
      }
      const parsedProfile = parseJsonObject(profileText, "profile");
      if (parsedProfile === null) {
        message.error("profile 不是合法 JSON 对象");
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
        dry_run: dryRun,
      };
      await submit(payload);
      return;
    }
    if (paramsSource === "line-tower") {
      if (selectedTowerIds.length === 0) {
        message.warning("请先选择线路并勾选至少一根杆塔");
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
        dry_run: dryRun,
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
      dry_run: dryRun,
      allow_incomplete_defaults: allowIncomplete,
    };
    await submit(payload);
  };

  const submit = async (payload: AtpAssetTestRunRequest) => {
    setSubmitting(true);
    try {
      const run = await postJson<AtpAssetRunDetail>(`/api/v1/atp/assets/${asset.id}/test-runs`, payload);
      message.success(dryRun ? "已发起试跑（只列命令，不执行）" : "测试已发起");
      onCreated(run);
      onClose();
    } catch (error) {
      message.error(error instanceof Error ? error.message : "发起测试失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title={`发起测试 · ${asset.name || asset.code}`}
      open={open}
      onCancel={onClose}
      width={760}
      footer={
        <Space style={{ display: "flex", justifyContent: "flex-end", width: "100%" }}>
          <Button disabled={submitting} onClick={onClose}>
            取消
          </Button>
          <Button type="primary" icon={<RocketOutlined />} loading={submitting} onClick={() => void handleSubmit()}>
            确认测试
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
                与 C# 侧必须同值
              </Typography.Text>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label={t("试跑")} style={{ marginBottom: 8 }}>
              <Switch checked={dryRun} onChange={setDryRun} />
              <Typography.Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                只列命令不执行
              </Typography.Text>
            </Form.Item>
          </Col>
          <Col span={12}>
            <Form.Item label={t("参数来源")} style={{ marginBottom: 8 }}>
              <Radio.Group
                value={paramsSource}
                onChange={(event) => setParamsSource(event.target.value as ParamsSource)}
                options={[
                  { value: "template", label: t("参数模板默认值") },
                  { value: "tower", label: t("手工杆塔数据") },
                  { value: "line-tower", label: t("从线路杆塔选择") },
                ]}
                optionType="button"
              />
            </Form.Item>
          </Col>
        </Row>

        {paramsSource === "line-tower" ? (
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
                pagination={{ pageSize: 8, showSizeChanger: true, showTotal: (total) => `共 ${total} 座杆塔` }}
                locale={{ emptyText: lineId ? "该线路暂无杆塔" : "请先选择线路" }}
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
                  <Form.Item label="base_tower（JSON）" style={{ marginBottom: 8 }}>
                    <Input.TextArea
                      rows={4}
                      value={baseTowerText}
                      onChange={(event) => setBaseTowerText(event.target.value)}
                      placeholder='如 {"line_voltage_kv":220,"ground_resistance":7}'
                    />
                  </Form.Item>
                </Col>
                <Col span={12}>
                  <Form.Item label="profile（JSON）" style={{ marginBottom: 8 }}>
                    <Input.TextArea
                      rows={4}
                      value={profileText}
                      onChange={(event) => setProfileText(event.target.value)}
                      placeholder='如 {"insulator_length_mm":2491.5}'
                    />
                  </Form.Item>
                </Col>
              </Row>
            ) : (
              <Space size={8}>
                <Typography.Text>{t("模板默认值不完整时仍继续")}</Typography.Text>
                <Switch checked={allowIncomplete} onChange={setAllowIncomplete} />
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  默认关闭：缺默认值会直接报错并列出缺哪些变量
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
  );
}
