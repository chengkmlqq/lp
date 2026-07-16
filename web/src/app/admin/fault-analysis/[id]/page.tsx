"use client";

import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Space, Tag, Typography, Spin, Dropdown, message } from "antd";
import { ArrowLeftOutlined, DownloadOutlined } from "@ant-design/icons";
import { useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { Card } from "@/components/ui-antd";
import { readApiError } from "@/lib/api";
import type { FaultAnalysisDetail } from "@/components/fault-analysis/types";
import { exportToPDF, exportToWord } from "@/lib/export-utils";

const { Title, Text, Paragraph } = Typography;

export default function FaultAnalysisDetailPage() {
  const params = useParams();
  const router = useRouter();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const analysisId = params.id as string;
  const [exporting, setExporting] = useState(false);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  const detailQuery = useQuery({
    queryKey: ["/api/v1/fault-analysis/detail", analysisId],
    enabled: !!user && canRead && !!analysisId,
    queryFn: async () => {
      // 模拟详细报告数据
      const mockDetail: FaultAnalysisDetail & {
        fault_id: string;
        station: string;
        fault_datetime: string;
        sections: Array<{
          title: string;
          content: Array<{
            type: "text" | "subtitle" | "bullet" | "highlight" | "card";
            text: string;
            items?: string[];
          }>;
        }>;
      } = {
        id: analysisId,
        title: "220kV XX线路雷击故障分析",
        description: "2024年夏季雷电多发期故障分析",
        status: "completed",
        risk_level: "high",
        tower_count: 45,
        line_name: "北源线 220kV",
        fault_time: "2026-07-03 14:32:18",
        fault_type: "A相接地 · 绕击",
        confidence: 76.3,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        line_id: "line-123",
        analysis_type: "lightning",
        fault_id: "FA-2026-0703-001",
        station: "广东河源500kV上寨变",
        fault_datetime: "2026-07-03 14:32:18",
        sections: [
          {
            title: "一、故障初判（录波分析）",
            content: [
              {
                type: "text",
                text: "查询广东河源500kV上寨变录波数据，2026-07-03 14:32:18，220kV龙和线发生故障。",
              },
              {
                type: "text",
                text: "故障特征分析如下：",
              },
              {
                type: "bullet",
                text: "",
                items: [
                  "A相电流突增；",
                  "A相电压明显跌落；",
                  "零序电流及零序电压显著增大。",
                ],
              },
              {
                type: "text",
                text: "综合判定，本次故障类型为：A相接地故障。",
              },
              {
                type: "highlight",
                text: "计算故障阻抗：Zm = 37.04V / 1.3A × (1 + 0.52) = 43.3Ω",
              },
              {
                type: "text",
                text: "判定故障性质属于：高阻接地故障（≥500Ω）",
              },
              {
                type: "text",
                text: "综上分析，2026-07-03 14:32:18，广东河源500kV上寨变记录220kV龙和线出现A相接地故障，本次故障属于高阻接地故障，64ms后重合成功，为单相接地故障。",
              },
            ],
          },
          {
            title: "二、故障定位（雷电定位、录波测距、行波测距）",
            content: [
              {
                type: "text",
                text: "基于录波测距算法，故障点距离线路首端约 16.022 km，位于 35-36# 区段；",
              },
              {
                type: "text",
                text: "基于两端行波测距，故障点距离线路首端约 16.51 km，位于 33-34# 区段；",
              },
              {
                type: "text",
                text: "查询雷电定位系统，故障前后30秒线路5km范围内存在落雷记录，其中2026-07-03 14:32:18雷电流为20.3kA，距离33#-34#塔约180m。",
              },
            ],
          },
          {
            title: "三、故障原因分析",
            content: [
              {
                type: "subtitle",
                text: "① 故障区段线路台账参数",
              },
              {
                type: "text",
                text: "地形类型: 丘陵  |  海拔高度: 85m  |  杆塔型号: ZM1-42",
              },
              {
                type: "text",
                text: "绝缘子串长度: 2.4m  |  杆塔接地电阻设计值: 15Ω  |  杆塔接地电阻实测值: 18.5Ω",
              },
              {
                type: "text",
                text: "基于线路结构参数及实测接地电阻计算得到：",
              },
              {
                type: "bullet",
                text: "",
                items: ["反击耐雷水平: 28.5kA", "绕击耐雷水平: 12.3kA"],
              },
              {
                type: "text",
                text: "本次雷击电流幅值为 20.3kA。",
              },
              {
                type: "text",
                text: "绕击耐雷水平12.3kA < 20.3kA < 绕击上限电流，判定绕击概率较高，置信度50%",
              },
              {
                type: "subtitle",
                text: "② 分布式行波监测数据",
              },
              {
                type: "text",
                text: "查询分布式行波监测数据，杆塔 33#、34#装设分布式故障定位装置。",
              },
              {
                type: "text",
                text: "行波特征分析如下：",
              },
              {
                type: "bullet",
                text: "",
                items: [
                  "波尾时间: 28μs（≥20μs）",
                  "频谱特征: 中高频为主",
                  "波形结构: 单峰",
                ],
              },
              {
                type: "text",
                text: "判定为雷击故障",
              },
              {
                type: "text",
                text: "行波特征分析如下：",
              },
              {
                type: "bullet",
                text: "",
                items: ["主波前特征: 无反极性脉冲", "频谱特征: 高频为主"],
              },
              {
                type: "text",
                text: "判定为绕击",
              },
              {
                type: "subtitle",
                text: "③ 光学监控装置分析",
              },
              {
                type: "text",
                text: "65#安装有光学监控装置，故障时刻2026-07-03 14:32:18，65#识别到一起雷击记录。",
              },
              {
                type: "text",
                text: "根据图像识别结果，判定为 A相导线 接闪，判定本次故障为绕击，置信度80%。",
              },
              {
                type: "subtitle",
                text: "④ 综合融合判别",
              },
              {
                type: "text",
                text: "台账分析: 绕击（置信度: 50%）",
              },
              {
                type: "text",
                text: "行波分析: 绕击（置信度: 60%）",
              },
              {
                type: "text",
                text: "光学监测: 绕击（置信度: 80%）",
              },
              {
                type: "text",
                text: "三源一致（结论一致性高），一致性评分: 0.83",
              },
              {
                type: "text",
                text: "最终置信度: 绕击 76.3%、反击 12.1%、分叉雷 5.2%、非雷击 6.4%",
              },
            ],
          },
          {
            title: "四、最终判定结果",
            content: [
              {
                type: "card",
                text: "故障类型: A相接地故障\n故障定位: 位于 33-34# 区段，置信度 S=62.5%\n雷击类型: 绕击，置信度 S=76.3%，关键依据: 光学/行波/台账\n雷击类型冲突来源: 无",
              },
              {
                type: "card",
                text: "决策建议\n根据置信度 S=76.3% 做出决策：\n建议人工复核（S<0.9）",
              },
            ],
          },
        ],
      };
      return mockDetail;
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
            {/* 报告头部 */}
            <div className="border-b border-gray-200 pb-5 mb-6">
              <div className="flex items-start justify-between mb-5">
                <div className="flex items-center gap-3">
                  <Title level={3} className="mb-0">
                    {detail.fault_id} 故障分析报告
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
              </div>
              <Text type="secondary" className="text-sm">
                线路: {detail.line_name} | 录波记录厂站: {detail.station} | 故障时间:{" "}
                {detail.fault_datetime}
              </Text>
            </div>

            {/* 报告内容 */}
            <Space direction="vertical" size={24} className="w-full">
              {detail.sections?.map((section, sectionIndex) => (
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
                                line === "决策建议" ||
                                lineIndex === 0 && !line.includes(":");
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
