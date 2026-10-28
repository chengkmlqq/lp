"use client";
import { useI18n } from "@/lib/i18n";

import { Alert, Empty, Form, Input, Modal, Space, Table, Tag, Typography } from "antd";
import type { FormInstance } from "antd";

import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatRiskLevel,
  readObject,
  readString,
  riskColor,
  type ReportFormValues,
} from "./types";

type ReportModalProps = {
  open: boolean;
  selectedJob: FlAnalysisJobSummary | null;
  rows: FlAnalysisTowerResultSummary[];
  selectedTowerIds: string[];
  form: FormInstance<ReportFormValues>;
  submitting: boolean;
  onSelectedTowerIdsChange: (towerIds: string[]) => void;
  onSubmit: (values: ReportFormValues) => void;
  onCancel: () => void;
};

export function ReportModal({
  open,
  selectedJob,
  rows,
  selectedTowerIds,
  form,
  submitting,
  onSelectedTowerIdsChange,
  onSubmit,
  onCancel,
}: ReportModalProps) {
  const { t } = useI18n();
  return (
    <Modal
      title={selectedJob ? `${t("报告生成")} - ${selectedJob.job_name || selectedJob.line_name || selectedJob.line_code}` : t("报告生成")}
      open={open}
      width={1080}
      confirmLoading={submitting}
      okText={t("创建并启动报告任务")}
      onCancel={() => {
        if (submitting) {
          return;
        }
        onCancel();
      }}
      onOk={() => {
        form.submit();
      }}
    >
      <Space direction="vertical" size={16} className="flex w-full">
        <Alert
          type="info"
          showIcon
          message={t("源端迁移口径：报告任务挂靠在已完成的风险评估或措施推荐结果上，并允许按杆塔缩小纳入报告的范围；若已存在关联的加装避雷器复算任务，报告会自动并入“采取措施后的计算结果表”。")}
        />
        <Form<ReportFormValues>
          form={form}
          layout="vertical"
          onFinish={onSubmit}
        >
          <Form.Item
            name="job_name"
            label={t("任务名称")}
            rules={[{ required: true, message: t("请输入任务名称") }]}
          >
            <Input placeholder={t("报告任务名称")} />
          </Form.Item>
        </Form>

        {rows.length === 0 ? (
          <Empty description={t("当前任务没有可纳入报告的杆塔结果")} />
        ) : (
          <>
            <Typography.Text type="secondary">
              已命中 {rows.length} 座可纳入报告的杆塔。默认全选，可按需缩小报告范围。
            </Typography.Text>
            <Table<FlAnalysisTowerResultSummary>
              rowKey="tower_id"
              size="small"
              pagination={{ pageSize: 8, showSizeChanger: false, hideOnSinglePage: false }}
              rowSelection={{
                selectedRowKeys: selectedTowerIds,
                onChange: (keys) => {
                  onSelectedTowerIdsChange(keys.map((item) => String(item)));
                },
              }}
              columns={[
                { title: t("杆塔号"), dataIndex: "tower_no", width: 120 },
                {
                  title: t("风险等级"),
                  dataIndex: "risk_level",
                  width: 120,
                  render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>,
                },
                {
                  title: t("高风险原因"),
                  key: "cause_analysis",
                  render: (_value, row) => readString(readObject(row.result_json), "cause_analysis"),
                },
                {
                  title: t("措施建议"),
                  key: "mitigation_recommendation",
                  render: (_value, row) => readString(readObject(row.result_json), "mitigation_recommendation"),
                },
              ]}
              dataSource={rows}
              scroll={{ x: 1000 }}
            />
          </>
        )}
      </Space>
    </Modal>
  );
}
