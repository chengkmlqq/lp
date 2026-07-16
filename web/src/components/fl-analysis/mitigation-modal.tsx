"use client";

import { Alert, Checkbox, Empty, Form, Input, Modal, Space, Table, Tag, Typography } from "antd";
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
  type MitigationFormValues,
} from "./types";

type MitigationModalProps = {
  open: boolean;
  selectedJob: FlAnalysisJobSummary | null;
  rows: FlAnalysisTowerResultSummary[];
  selectedTowerIds: string[];
  form: FormInstance<MitigationFormValues>;
  submitting: boolean;
  onSelectedTowerIdsChange: (towerIds: string[]) => void;
  onSubmit: (values: MitigationFormValues) => void;
  onCancel: () => void;
};

export function MitigationModal({
  open,
  selectedJob,
  rows,
  selectedTowerIds,
  form,
  submitting,
  onSelectedTowerIdsChange,
  onSubmit,
  onCancel,
}: MitigationModalProps) {
  return (
    <Modal
      title={selectedJob ? `措施推荐 - ${selectedJob.job_name || selectedJob.line_name || selectedJob.line_code}` : "措施推荐"}
      open={open}
      width={1080}
      confirmLoading={submitting}
      okText="创建并启动措施任务"
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
          message="源端迁移口径：仅允许从已有风险结果中选择高风险杆塔，生成措施推荐任务。"
        />
        <Form<MitigationFormValues>
          form={form}
          layout="vertical"
          onFinish={onSubmit}
          initialValues={{ non_construction: false }}
        >
          <Form.Item
            name="job_name"
            label="任务名称"
            rules={[{ required: true, message: "请输入任务名称" }]}
          >
            <Input placeholder="措施推荐任务名称" />
          </Form.Item>
          <Form.Item name="non_construction" valuePropName="checked">
            <Checkbox>按“非建线”模式生成措施推荐</Checkbox>
          </Form.Item>
        </Form>

        {rows.length === 0 ? (
          <Empty description="当前风险任务没有中高风险杆塔，无法生成措施推荐任务" />
        ) : (
          <>
            <Typography.Text type="secondary">
              已命中 {rows.length} 座中高风险杆塔。默认全选，可按需缩小推荐范围。
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
                { title: "杆塔号", dataIndex: "tower_no", width: 120 },
                {
                  title: "风险等级",
                  dataIndex: "risk_level",
                  width: 120,
                  render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value)}</Tag>,
                },
                {
                  title: "高风险原因",
                  key: "cause_analysis",
                  render: (_value, row) => readString(readObject(row.result_json), "cause_analysis"),
                },
                {
                  title: "当前建议",
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
