"use client";

/**
 * 测试线路装配预览弹窗。
 *
 * 展示"真实执行时到底会用什么输入"：`base_tower` + `profile` + 快照指纹。
 * 用途是让用户在跑仿真前确认几何是否真的齐了 —— 几何缺失是 ATP 生成失败的
 * 头号原因（避雷线中距为 0、四回几何重合、档距越界），所以这些值单独列在上层。
 */
import { useEffect, useState } from "react";
import { Alert, Button, Collapse, Descriptions, Empty, Modal, Spin, Table, Typography } from "antd";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { AtpTestLinePreviewResponse } from "@/types/atp-test-line";

const { Text } = Typography;

export type AtpTestLinePreviewModalProps = {
  open: boolean;
  testLineId: string | null;
  testLineCode?: string | null;
  onClose: () => void;
};

function pick(source: Record<string, unknown>, key: string): unknown {
  if (key in source) return source[key];
  return undefined;
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function AtpTestLinePreviewModal({
  open,
  testLineId,
  testLineCode,
  onClose,
}: AtpTestLinePreviewModalProps) {
  const { t } = useI18n();
  const { fetchWithAuth } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<AtpTestLinePreviewResponse | null>(null);

  useEffect(() => {
    if (!open || !testLineId) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const response = await fetchWithAuth(`/api/v1/atp/test-lines/${testLineId}/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        });
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const payload = (await response.json()) as AtpTestLinePreviewResponse;
        if (!cancelled) setData(payload);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [open, testLineId, fetchWithAuth]);

  const baseTower = data?.base_tower ?? {};
  const profile = data?.profile ?? {};
  // 几何层：base_tower.circuit_geometry_json = { "I": { phase_spacing_m:{...}, phase_height_m:{...} }, ... }
  const geometry = (pick(baseTower, "circuit_geometry_json") ?? {}) as Record<
    string,
    { phase_spacing_m?: Record<string, number | null>; phase_height_m?: Record<string, number | null> }
  >;
  const geometryEntries = Object.entries(geometry);
  // 避雷线中距存在 profile.extra_profile_json.lightning_wire 上（两路径同构）
  const extraProfile = (pick(profile, "extra_profile_json") ?? {}) as Record<string, unknown>;
  const lightningWire = (pick(extraProfile, "lightning_wire") ?? {}) as Record<string, unknown>;

  return (
    <Modal
      open={open}
      title={`${t("装配预览")}${testLineCode ? `：${testLineCode}` : ""}`}
      width={820}
      onCancel={onClose}
      destroyOnHidden
      footer={<Button onClick={onClose}>{t("关闭")}</Button>}
    >
      {loading ? (
        <div style={{ padding: 40, textAlign: "center" }}>
          <Spin />
        </div>
      ) : error ? (
        <Alert type="error" showIcon message={t("预览失败")} description={error} />
      ) : !data ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无预览")} />
      ) : (
        <div style={{ maxHeight: "64vh", overflowY: "auto" }}>
          {data.blockers.length > 0 ? (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("几何校验未通过（执行会失败）")}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {data.blockers.map((item, index) => (
                    <li key={`${item.field}-${index}`}>
                      <Text strong>{item.field}</Text>：{item.reason}
                    </li>
                  ))}
                </ul>
              }
            />
          ) : (
            <Alert
              type="success"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("几何校验通过")}
              description={
                <Text type="secondary">
                  {t("快照指纹")}：<Text code>{data.snapshot_hash.slice(0, 16)}…</Text>
                </Text>
              }
            />
          )}

          {data.warnings.length > 0 ? (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 12 }}
              message={`${data.warnings.length} ${t("项提示")}`}
              description={
                <ul style={{ margin: 0, paddingLeft: 18 }}>
                  {data.warnings.map((item, index) => (
                    <li key={`${item.field}-${index}`}>
                      <Text strong>{item.field}</Text>：{item.reason}
                    </li>
                  ))}
                </ul>
              }
            />
          ) : null}

          <Descriptions size="small" column={2} bordered style={{ marginBottom: 12 }}>
            <Descriptions.Item label={t("电压等级(kV)")}>{renderValue(pick(baseTower, "line_voltage_kv"))}</Descriptions.Item>
            <Descriptions.Item label={t("塔型")}>{renderValue(pick(baseTower, "tower_type"))}</Descriptions.Item>
            <Descriptions.Item label={t("杆塔号")}>{renderValue(pick(baseTower, "tower_no"))}</Descriptions.Item>
            <Descriptions.Item label={t("杆塔型号")}>{renderValue(pick(baseTower, "tower_model"))}</Descriptions.Item>
            <Descriptions.Item label={t("呼高(m)")}>{renderValue(pick(profile, "call_height_m"))}</Descriptions.Item>
            <Descriptions.Item label={t("绝缘子串长(m)")}>{renderValue(pick(profile, "insulator_length_m"))}</Descriptions.Item>
            <Descriptions.Item label={t("避雷线高度(m)")}>{renderValue(pick(profile, "shield_wire_height_m"))}</Descriptions.Item>
            <Descriptions.Item label={t("雷电流(A)")}>{renderValue(pick(profile, "current_a"))}</Descriptions.Item>
            <Descriptions.Item label={t("避雷线左中距(m)")}>
              {renderValue(pick(lightningWire, "left_mid_distance_m"))}
            </Descriptions.Item>
            <Descriptions.Item label={t("避雷线右中距(m)")}>
              {renderValue(pick(lightningWire, "right_mid_distance_m"))}
            </Descriptions.Item>
            <Descriptions.Item label={t("小档距(m)")}>{renderValue(pick(baseTower, "span_small_m"))}</Descriptions.Item>
            <Descriptions.Item label={t("大档距(m)")}>{renderValue(pick(baseTower, "span_large_m"))}</Descriptions.Item>
          </Descriptions>

          {geometryEntries.length > 0 ? (
            <div style={{ marginBottom: 12 }}>
              <Text strong style={{ display: "block", marginBottom: 6 }}>
                {t("回路几何（中距 / 相高，单位米）")}
              </Text>
              <Table
                rowKey="circuit"
                size="small"
                bordered
                pagination={false}
                dataSource={geometryEntries.map(([circuit, layer]) => ({
                  circuit,
                  upper: `${renderValue(layer.phase_spacing_m?.upper)} / ${renderValue(layer.phase_height_m?.upper)}`,
                  middle: `${renderValue(layer.phase_spacing_m?.middle)} / ${renderValue(layer.phase_height_m?.middle)}`,
                  lower: `${renderValue(layer.phase_spacing_m?.lower)} / ${renderValue(layer.phase_height_m?.lower)}`,
                }))}
                columns={[
                  { title: t("回路"), dataIndex: "circuit", width: 80 },
                  { title: t("上相"), dataIndex: "upper" },
                  { title: t("中相"), dataIndex: "middle" },
                  { title: t("下相"), dataIndex: "lower" },
                ]}
              />
            </div>
          ) : null}

          {data.not_consumed.length > 0 ? (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("以下字段不参与仿真")}
              description={data.not_consumed.join("、")}
            />
          ) : null}

          <Collapse
            size="small"
            items={[
              {
                key: "base_tower",
                label: t("base_tower（装配结果）"),
                children: (
                  <pre style={{ margin: 0, maxHeight: 240, overflow: "auto", fontSize: 12 }}>
                    {JSON.stringify(data.base_tower, null, 2)}
                  </pre>
                ),
              },
              {
                key: "profile",
                label: t("profile（杆塔参数）"),
                children: (
                  <pre style={{ margin: 0, maxHeight: 240, overflow: "auto", fontSize: 12 }}>
                    {JSON.stringify(data.profile, null, 2)}
                  </pre>
                ),
              },
            ]}
          />
        </div>
      )}
    </Modal>
  );
}

export default AtpTestLinePreviewModal;
