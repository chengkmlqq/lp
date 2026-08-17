"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Descriptions, Space, Typography, Spin, Dropdown, Table, message } from "antd";
import { DownloadOutlined } from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { readApiError } from "@/lib/api";
import type { FaultAnalysisDetail } from "@/types/auth";

const { Title, Text, Paragraph } = Typography;

interface AnalysisDetailViewProps {
  analysisId: string;
  /** 唯一标识，用作导出容器 DOM id 前缀（多开详情 Tab 时避免重复 id） */
  tabKey: string;
}

interface ReportSectionItem {
  type: "text" | "subtitle" | "bullet" | "highlight" | "card" | "table";
  text: string;
  items?: string[];
  title?: string;
  layout?: "grid" | "key_value";
  columns?: string[];
  rows?: string[][];
}

interface ReportSection {
  title: string;
  content: ReportSectionItem[];
}

/** Build report sections from a FaultAnalysisDetail returned by the API. */
function buildSections(detail: FaultAnalysisDetail): { sections: ReportSection[]; station: string; fault_datetime: string; fault_id: string } {
  // If the backend already stored structured sections, use them.
  const storedSections = (detail.result_json?.sections as ReportSection[] | undefined);
  if (storedSections && storedSections.length > 0) {
    return {
      sections: storedSections,
      station: detail.station ?? "",
      fault_datetime: detail.fault_time ?? "",
      fault_id: `FA-${detail.id?.slice(0, 12) ?? ""}`,
    };
  }

  // Otherwise build a lightweight report from the available scalar fields.
  const sections: ReportSection[] = [];
  const station = detail.station ?? "";
  const faultDatetime = detail.fault_time ?? "";
  const faultId = `FA-${detail.id?.slice(0, 12) ?? ""}`;

  // Section 1: fault basics
  const basics: ReportSectionItem[] = [];
  if (station || faultDatetime) {
    basics.push({
      type: "text",
      text: `故障录波记录厂站: ${station}，故障时刻: ${faultDatetime}`,
    });
  }
  if (detail.fault_type) {
    basics.push({ type: "text", text: `故障类型: ${detail.fault_type}` });
  }
  if (detail.fault_phase) {
    basics.push({ type: "text", text: `故障相: ${detail.fault_phase}` });
  }
  if (detail.fault_duration_ms != null) {
    basics.push({ type: "text", text: `故障持续时间: ${detail.fault_duration_ms} ms` });
  }
  if (detail.reclosure_status) {
    basics.push({ type: "text", text: `重合闸情况: ${detail.reclosure_status}` });
  }
  if (basics.length > 0) {
    sections.push({ title: "一、故障基本信息", content: basics });
  }

  // Section 2: electrical parameters
  const electrical: ReportSectionItem[] = [];
  if (detail.fault_voltage_v != null) {
    electrical.push({ type: "text", text: `故障相电压: ${detail.fault_voltage_v} V` });
  }
  if (detail.fault_current_a != null) {
    electrical.push({ type: "text", text: `故障相电流: ${detail.fault_current_a} A` });
  }
  if (detail.max_zero_current_a != null) {
    electrical.push({ type: "text", text: `最大零序电流: ${detail.max_zero_current_a} A` });
  }
  if (detail.zero_compensation != null) {
    electrical.push({ type: "text", text: `零序补偿系数K: ${detail.zero_compensation}` });
  }
  if (detail.fault_resistance_ohm != null) {
    electrical.push({ type: "text", text: `故障电阻: ${detail.fault_resistance_ohm} Ω` });
  }
  if (detail.line_length_km != null) {
    electrical.push({ type: "text", text: `线路总长度: ${detail.line_length_km} km` });
  }
  if (electrical.length > 0) {
    sections.push({ title: "二、电气参数", content: electrical });
  }

  // Section 3: lightning & location
  const location: ReportSectionItem[] = [];
  if (detail.lightning_current_ka != null) {
    location.push({ type: "text", text: `雷电流幅值: ${detail.lightning_current_ka} kA` });
  }
  if (detail.lightning_longitude != null && detail.lightning_latitude != null) {
    location.push({ type: "text", text: `雷电定位: 经度 ${detail.lightning_longitude}°, 纬度 ${detail.lightning_latitude}°` });
  }
  if (detail.wave_distance_km != null) {
    location.push({ type: "text", text: `录波测距: ${detail.wave_distance_km} km` });
  }
  if (detail.traveling_wave_distance_km != null) {
    location.push({ type: "text", text: `行波测距: ${detail.traveling_wave_distance_km} km` });
  }
  if (detail.optical_position) {
    location.push({ type: "text", text: `光学接闪位置: ${detail.optical_position}` });
  }
  if (detail.optical_device_location) {
    location.push({ type: "text", text: `光学设备安装位置: ${detail.optical_device_location}` });
  }
  if (location.length > 0) {
    sections.push({ title: "三、雷电定位与测距", content: location });
  }

  // Section 4: conclusion
  const conclusion: ReportSectionItem[] = [];
  if (detail.confidence != null) {
    conclusion.push({
      type: "text",
      text: `综合置信度: ${detail.confidence}%`,
    });
  }
  if (detail.risk_level) {
    const riskMap: Record<string, string> = { high: "高风险", medium: "中风险", low: "低风险" };
    conclusion.push({ type: "text", text: `风险等级: ${riskMap[detail.risk_level] ?? detail.risk_level}` });
  }
  conclusion.push({
    type: "card",
    text: detail.confidence != null && detail.confidence >= 90
      ? "综合判定: 高置信度，可直接采纳分析结论。"
      : detail.confidence != null && detail.confidence >= 70
        ? `综合判定: 置信度 S=${detail.confidence}%，建议人工复核后再做决策。`
        : "综合判定: 置信度较低，建议结合现场情况综合分析。",
  });
  if (conclusion.length > 0) {
    sections.push({ title: "四、综合判定", content: conclusion });
  }

  return { sections, station, fault_datetime: faultDatetime, fault_id: faultId };
}

export function AnalysisDetailView({ analysisId, tabKey }: AnalysisDetailViewProps) {
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const [exporting, setExporting] = useState(false);
  const exportElementId = `analysis-export-content-${tabKey}`;

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  const detailQuery = useQuery({
    queryKey: ["/api/v1/fault-analysis", analysisId],
    enabled: !!user && canRead && !!analysisId,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as FaultAnalysisDetail;
    },
    // 判别为异步任务（pending/processing 时），轮询详情直至完成/失败（LP-316）。
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "processing" ? 3000 : false;
    },
  });

  const handleExportMatlab = async () => {
    if (!detail) return;

    setExporting(true);
    try {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/export-matlab`);
      if (!response.ok) {
        const errMsg = await readApiError(response).catch(() => "请求失败");
        throw new Error(errMsg);
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") ?? "";
      let filename = "";
      const encodedMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i);
      if (encodedMatch) {
        filename = decodeURIComponent(encodedMatch[1]);
      } else {
        const plainMatch = disposition.match(/filename="?([^";]+)"?/i);
        filename = plainMatch ? plainMatch[1] : `fault_analysis_${analysisId}_matlab_outputs.zip`;
      }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success("MATLAB 引擎产物导出成功");
    } catch (error) {
      console.error("导出失败", error);
      message.error(error instanceof Error ? error.message : "导出失败，请重试");
    } finally {
      setExporting(false);
    }
  };

  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spin size="large" />
      </div>
    );
  }

  if (detailQuery.error) {
    return (
      <Alert
        type="error"
        showIcon
        message="加载失败"
        description={
          detailQuery.error instanceof Error
            ? detailQuery.error.message
            : "未知错误"
        }
      />
    );
  }

  const detail = detailQuery.data;

  if (!detail) {
    return <Alert type="info" showIcon message="未找到该故障分析记录" />;
  }

  const { sections, station, fault_datetime, fault_id } = buildSections(detail);

  return (
    <div className="flex flex-col gap-4 h-full">
      <Card className="flex-1 overflow-auto">
        <div id={exportElementId}>
          <div className="border-b border-gray-200 pb-5 mb-6">
            <div className="flex items-start justify-between mb-5">
              <Title level={3} className="mb-0">
                {fault_id} 故障分析报告
              </Title>
              <Dropdown
                menu={{
                  items: [
                    {
                      key: "matlab",
                      label: "导出引擎产物 (ZIP)",
                      onClick: handleExportMatlab,
                    },
                  ],
                }}
                placement="bottomRight"
                trigger={["click"]}
              >
                <Button
                  icon={<DownloadOutlined />}
                  loading={exporting}
                >
                  导出报告
                </Button>
              </Dropdown>
            </div>
            <Text type="secondary" className="text-sm">
              线路: {detail.line_name ?? "-"} | 录波记录厂站: {station} | 故障时间:{" "}
              {fault_datetime}
            </Text>
          </div>

          <Space direction="vertical" size={24} className="w-full">
            {sections.map((section, sectionIndex) => {
              const descriptionsItems = section.content.filter(
                (item) => item.type !== "table" && item.type !== "card"
              );
              const standaloneItems = section.content.filter(
                (item) => item.type === "table" || item.type === "card"
              );
              return (
                <div key={sectionIndex}>
                  <div
                    className="px-5 py-3 rounded-md mb-4"
                    style={{
                      background: 'var(--ant-color-primary)',
                      color: 'var(--accent-contrast)'
                    }}
                  >
                    <Text
                      className="font-semibold text-base"
                      style={{ color: 'var(--accent-contrast)' }}
                    >
                      {section.title}
                    </Text>
                  </div>
                  <Space direction="vertical" size={12} className="w-full">
                    {descriptionsItems.length > 0 && (
                      <Descriptions column={2} bordered size="small">
                        {descriptionsItems.map((item, itemIndex) => {
                          if (item.type === "subtitle") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                <Text strong className="text-sm">
                                  {item.text}
                                </Text>
                              </Descriptions.Item>
                            );
                          }
                          if (item.type === "highlight") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                <Text type="warning" className="text-sm">
                                  {item.text}
                                </Text>
                              </Descriptions.Item>
                            );
                          }
                          if (item.type === "bullet") {
                            return (
                              <Descriptions.Item key={itemIndex} label="" span={2}>
                                {item.items?.map((bullet, bulletIndex) => (
                                  <Paragraph
                                    key={bulletIndex}
                                    className="text-sm mb-2 text-gray-700"
                                  >
                                    • {bullet}
                                  </Paragraph>
                                ))}
                              </Descriptions.Item>
                            );
                          }
                          return (
                            <Descriptions.Item key={itemIndex} label="">
                              <Paragraph className="text-sm text-gray-700 mb-0">
                                {item.text}
                              </Paragraph>
                            </Descriptions.Item>
                          );
                        })}
                      </Descriptions>
                    )}
                    {standaloneItems.map((item, itemIndex) => {
                      if (item.type === "card") {
                        const lines = item.text.split("\n");
                        return (
                          <div
                            key={itemIndex}
                            className="bg-gray-50 border border-gray-200 rounded-lg p-5"
                          >
                            {lines.map((line, lineIndex) => {
                              const isHighlight =
                                line.includes("建议人工复核") ||
                                line.includes("雷击类型:");
                              const isTitle =
                                line === "综合判定" ||
                                (lineIndex === 0 && !line.includes(":"));
                              return (
                                <Paragraph
                                  key={lineIndex}
                                  className={`text-sm mb-2 ${
                                    isTitle
                                      ? "font-semibold text-gray-900"
                                      : isHighlight
                                      ? "text-orange-600 font-medium"
                                      : "text-gray-700"
                                  }`}
                                >
                                  {line}
                                </Paragraph>
                              );
                            })}
                          </div>
                        );
                      }
                      if (item.type === "table") {
                        const columns = item.columns ?? [];
                        const rawRows = item.rows ?? [];
                        let tableColumns = columns.map((col, index) => ({
                          title: col,
                          dataIndex: index,
                          key: `${index}-${col}`,
                        }));
                        let tableRows: Record<string, string>[] = [];
                        if (item.layout === "key_value" && columns.length >= 2) {
                          const pairHead = columns[0];
                          const valueHead = columns[1];
                          tableColumns = [
                            { title: pairHead, dataIndex: 0, key: "kv-key" },
                            { title: valueHead, dataIndex: 1, key: "kv-value" },
                          ];
                          rawRows.forEach((row, rowIndex) => {
                            for (let index = 0; index + 1 < row.length; index += 2) {
                              tableRows.push({
                                key: `r${rowIndex}-c${index}`,
                                0: row[index] ?? "",
                                1: row[index + 1] ?? "",
                              });
                            }
                          });
                        } else {
                          rawRows.forEach((row, rowIndex) => {
                            const record: Record<string, string> = { key: `r${rowIndex}` };
                            columns.forEach((_, index) => {
                              record[index] = row[index] ?? "";
                            });
                            tableRows.push(record);
                          });
                        }
                        return (
                          <div
                            key={itemIndex}
                            className="bg-white border border-gray-200 rounded-lg"
                            style={{ padding: 12, overflowY: "auto" }}
                          >
                            {item.title ? (
                              <Text strong className="text-sm block mb-2">
                                {item.title}
                              </Text>
                            ) : null}
                            <Table
                              size="small"
                              bordered
                              pagination={false}
                              columns={tableColumns}
                              dataSource={tableRows}
                            />
                          </div>
                        );
                      }
                      return null;
                    })}
                  </Space>
                </div>
              );
            })}
          </Space>
        </div>
      </Card>
    </div>
  );
}