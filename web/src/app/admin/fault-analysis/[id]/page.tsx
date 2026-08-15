"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Space, Tag, Typography, Spin, Dropdown, message } from "antd";
import { ArrowLeftOutlined, DownloadOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { readApiError } from "@/lib/api";
import type { FaultAnalysisDetail } from "@/types/auth";
import { exportToPDF, exportToWord } from "@/lib/export-utils";

const { Title, Text, Paragraph } = Typography;

interface ReportSectionItem {
  type: "text" | "subtitle" | "bullet" | "highlight" | "card";
  text: string;
  items?: string[];
}

interface ReportSection {
  title: string;
  content: ReportSectionItem[];
}

function buildSections(detail: FaultAnalysisDetail): { sections: ReportSection[]; station: string; fault_datetime: string; fault_id: string } {
  const storedSections = (detail.result_json?.sections as ReportSection[] | undefined);
  if (storedSections && storedSections.length > 0) {
    return {
      sections: storedSections,
      station: detail.station ?? "",
      fault_datetime: detail.fault_time ?? "",
      fault_id: `FA-${detail.id?.slice(0, 12) ?? ""}`,
    };
  }

  const sections: ReportSection[] = [];
  const station = detail.station ?? "";
  const faultDatetime = detail.fault_time ?? "";
  const faultId = `FA-${detail.id?.slice(0, 12) ?? ""}`;

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

  const electrical: ReportSectionItem[] = [];
  if (detail.fault_voltage_v != null) {
    electrical.push({ type: "text", text: `故障相电压: ${detail.fault_voltage_v} V` });
  }
  if (detail.fault_current_a != null) {
    electrical.push({ type: "text", text: `故障相电流: ${detail.fault_current_a} A` });
  }
  if (detail.line_length_km != null) {
    electrical.push({ type: "text", text: `线路总长度: ${detail.line_length_km} km` });
  }
  if (electrical.length > 0) {
    sections.push({ title: "二、电气参数", content: electrical });
  }

  const location: ReportSectionItem[] = [];
  if (detail.lightning_current_ka != null) {
    location.push({ type: "text", text: `雷电流幅值: ${detail.lightning_current_ka} kA` });
  }
  if (detail.wave_distance_km != null) {
    location.push({ type: "text", text: `录波测距: ${detail.wave_distance_km} km` });
  }
  if (detail.traveling_wave_distance_km != null) {
    location.push({ type: "text", text: `行波测距: ${detail.traveling_wave_distance_km} km` });
  }
  if (location.length > 0) {
    sections.push({ title: "三、雷电定位与测距", content: location });
  }

  const conclusion: ReportSectionItem[] = [];
  if (detail.confidence != null) {
    conclusion.push({ type: "text", text: `综合置信度: ${detail.confidence}%` });
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

export default function FaultAnalysisDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const analysisId = params.id as string;
  const [exporting, setExporting] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);

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
  });

  const handleExport = async (format: "pdf" | "word") => {
    if (!detail) return;

    setExporting(true);
    try {
      if (format === "pdf") {
        await exportToPDF(detail as any, "export-content");
        message.success("PDF导出成功");
      } else {
        await exportToWord(detail as any);
        message.success("Word文档导出成功");
      }
    } catch (error) {
      console.error("导出失败", error);
      message.error("导出失败，请重试");
    } finally {
      setExporting(false);
    }
  };

  const handleDownloadReport = async () => {
    if (!detail) return;
    setDownloadingReport(true);
    try {
      const response = await fetchWithAuth(`/api/v1/fault-analysis/${analysisId}/report`);
      if (!response.ok) {
        const errMsg = await readApiError(response).catch(() => "请求失败");
        throw new Error(errMsg);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `fault_analysis_${analysisId}_report.docx`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success("Word报告下载成功");
    } catch (error) {
      console.error("下载报告失败", error);
      message.error(error instanceof Error ? error.message : "下载失败，请重试");
    } finally {
      setDownloadingReport(false);
    }
  };

  if (!initializing && !user) {
    return (
      <div className="p-6">
        <Alert type="warning" showIcon message="请先登录后查看故障分析详情。" />
      </div>
    );
  }

  if (!initializing && !canRead) {
    return (
      <div className="p-6">
        <Alert
          type="error"
          showIcon
          message="当前账号缺少线路读取权限，无法查看故障分析详情。"
        />
      </div>
    );
  }

  if (detailQuery.isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spin size="large" />
      </div>
    );
  }

  if (detailQuery.error) {
    return (
      <div className="p-6">
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
      </div>
    );
  }

  const detail = detailQuery.data;

  if (!detail) {
    return (
      <div className="p-6">
        <Alert type="info" showIcon message="未找到该故障分析记录" />
      </div>
    );
  }

  const { sections, station, fault_datetime, fault_id } = buildSections(detail);

  return (
    <div className="min-h-screen bg-gray-50 py-6">
      <div className="max-w-5xl mx-auto px-6">
        <div className="mb-6">
          <Button
            icon={<ArrowLeftOutlined />}
            onClick={() => router.back()}
            className="mb-4"
          >
            返回列表
          </Button>
        </div>

        <Card>
          <div id="export-content">
            <div className="border-b border-gray-200 pb-5 mb-6">
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-3">
                  <Title level={3} className="mb-0">
                    {fault_id} 故障分析报告
                  </Title>
                  <Tag color="orange">待复核</Tag>
                </div>
                <Dropdown
                  menu={{
                    items: [
                      {
                        key: "pdf",
                        label: "导出为 PDF",
                        onClick: () => handleExport("pdf"),
                      },
                      {
                        key: "word",
                        label: "导出为 Word",
                        onClick: () => handleExport("word"),
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
                <Button
                  icon={<DownloadOutlined />}
                  loading={downloadingReport}
                  disabled={!detail.result_json?.diagnosis}
                  onClick={handleDownloadReport}
                >
                  下载 Word 报告
                </Button>
              </div>
              <Text type="secondary" className="text-sm">
                线路: {detail.line_name ?? "-"} | 录波记录厂站: {station} | 故障时间:{" "}
                {fault_datetime}
              </Text>
            </div>

            <Space direction="vertical" size={24} className="w-full">
              {sections.map((section, sectionIndex) => (
                <div key={sectionIndex}>
                  <div className="fault-analysis-step-header px-5 py-3 rounded-md mb-4">
                    <Text className="font-semibold text-base">
                      {section.title}
                    </Text>
                  </div>
                  <Space direction="vertical" size={12} className="w-full">
                    {section.content.map((item, itemIndex) => {
                      if (item.type === "subtitle") {
                        return (
                          <Text key={itemIndex} strong className="text-sm">
                            {item.text}
                          </Text>
                        );
                      }
                      if (item.type === "bullet") {
                        return (
                          <div key={itemIndex} className="ml-2">
                            {item.items?.map((bullet, bulletIndex) => (
                              <Paragraph
                                key={bulletIndex}
                                className="text-sm mb-2 text-gray-700"
                              >
                                • {bullet}
                              </Paragraph>
                            ))}
                          </div>
                        );
                      }
                      if (item.type === "highlight") {
                        return (
                          <Text
                            key={itemIndex}
                            className="text-sm text-orange-600 font-medium"
                          >
                            {item.text}
                          </Text>
                        );
                      }
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
                      return (
                        <Paragraph key={itemIndex} className="text-sm text-gray-700">
                          {item.text}
                        </Paragraph>
                      );
                    })}
                  </Space>
                </div>
              ))}
            </Space>
          </div>
        </Card>
      </div>
    </div>
  );
}