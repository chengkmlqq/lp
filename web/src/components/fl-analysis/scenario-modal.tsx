"use client";
import { useI18n } from "@/lib/i18n";

import { Alert, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography } from "antd";
import type { FormInstance } from "antd";

import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatDateTime,
  formatJobType,
  formatRiskLevel,
  readObject,
  readString,
  riskColor,
  type ScenarioFormValues,
} from "./types";

type ScenarioModalProps = {
  open: boolean;
  selectedJob: FlAnalysisJobSummary | null;
  rows: FlAnalysisTowerResultSummary[];
  baseJobs: FlAnalysisJobSummary[];
  selectedTowerIds: string[];
  form: FormInstance<ScenarioFormValues>;
  submitting: boolean;
  onSelectedTowerIdsChange: (towerIds: string[]) => void;
  onSubmit: (values: ScenarioFormValues) => void;
  onCancel: () => void;
};

export function ScenarioModal({
  open,
  selectedJob,
  rows,
  baseJobs,
  selectedTowerIds,
  form,
  submitting,
  onSelectedTowerIdsChange,
  onSubmit,
  onCancel,
}: ScenarioModalProps) {
  const { t } = useI18n();
  return (
    <Modal
      title={selectedJob ? `加装避雷器复算 - ${selectedJob.job_name || selectedJob.line_name || selectedJob.line_code}` : "加装避雷器复算"}
      open={open}
      width={1080}
      confirmLoading={submitting}
      okText={t("创建并启动复算任务")}
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
          message={t("源端迁移口径：仅允许从措施推荐结果中继续选择仍为中高风险的杆塔，并复用一次已完成的普通/同跳计算链路，执行“补装避雷器后”的独立复算。")}
        />
        <Form<ScenarioFormValues>
          form={form}
          layout="vertical"
          onFinish={onSubmit}
        >
          <Form.Item
            name="job_name"
            label={t("任务名称")}
            rules={[{ required: true, message: t("请输入任务名称") }]}
          >
            <Input placeholder={t("加装避雷器复算任务名称")} />
          </Form.Item>
          <Form.Item
            name="base_job_id"
            label={t("复用计算任务")}
            rules={[{ required: true, message: t("请选择复用的普通计算或同跳计算任务") }]}
          >
            <Select
              placeholder={t("选择已成功完成的普通计算或同跳计算任务")}
              options={baseJobs.map((item) => ({
                value: item.id,
                label: `${item.job_name || item.line_name || item.line_code || item.id} / ${formatJobType(item.job_type)} / ${formatDateTime(item.finished_at)}`,
              }))}
            />
          </Form.Item>
        </Form>

        {baseJobs.length === 0 ? (
          <Alert
            type="warning"
            showIcon
            message={t("当前线路还没有可复用的普通计算或同跳计算成功任务。请先完成一次基线计算，再创建加装避雷器复算任务。")}
          />
        ) : null}

        {rows.length === 0 ? (
          <Empty description={t("当前措施任务没有仍需复算的中高风险杆塔")} />
        ) : (
          <>
            <Typography.Text type="secondary">
              已命中 {rows.length} 座仍为中高风险的杆塔。默认全选，可按需缩小复算范围。
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
                  title: t("预期风险"),
                  dataIndex: "risk_level",
                  width: 120,
                  render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value)}</Tag>,
                },
                {
                  title: t("高风险原因"),
                  key: "cause_analysis",
                  render: (_value, row) => readString(readObject(row.result_json), "cause_analysis"),
                },
                {
                  title: t("当前动作"),
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
