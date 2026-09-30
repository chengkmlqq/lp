"use client";

/**
 * 防雷改造 - 新建措施推荐任务弹窗（2026-09-30 页面重构）。
 *
 * 参照 fl-analysis 的「新建任务/MitigationModal」形态：
 * 选择前置防雷计算任务(normal/tongtiao) → 自动加载其中高风险杆塔 →
 * 勾选杆塔 + 填任务名 + 非建线选项 → 创建并启动措施推荐(mitigation)任务。
 * 任务列表进度通过 WebSocket 主题回调由页面刷新。
 */

import { Alert, Checkbox, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import type { FormInstance } from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type {
  FlAnalysisJobSummary,
  FlAnalysisTowerResultSummary,
} from "@/types/auth";

import {
  formatJobType,
  formatRiskLevel,
  readObject,
  readString,
  riskColor,
} from "./types";

type RetrofitCreateModalProps = {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
};

function isHighRisk(riskLevel: string | null | undefined): boolean {
  if (!riskLevel) {
    return false;
  }
  if (riskLevel === "high") {
    return true;
  }
  const numeric = Number(riskLevel);
  return Number.isFinite(numeric) && numeric > 2;
}

type RetrofitFormValues = {
  job_name: string;
  non_construction: boolean;
};

export function RetrofitCreateModal({ open, onClose, onCreated }: RetrofitCreateModalProps) {
  const { user, fetchWithAuth } = useAuth();
  const [form] = Form.useForm<RetrofitFormValues>();
  const [baseJobs, setBaseJobs] = useState<FlAnalysisJobSummary[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [selectedBaseJobId, setSelectedBaseJobId] = useState<string>("");
  const [rows, setRows] = useState<FlAnalysisTowerResultSummary[]>([]);
  const [loadingRows, setLoadingRows] = useState(false);
  const [selectedTowerIds, setSelectedTowerIds] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const loadBaseJobs = useCallback(async () => {
    if (!user) {
      return;
    }
    setLoadingJobs(true);
    try {
      const response = await fetchWithAuth("/api/v1/fl-analysis/jobs?limit=200");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as { items: FlAnalysisJobSummary[] };
      // 前置任务：普通计算 / 同跳计算（有结果可作为风险来源）
      setBaseJobs(
        (data.items ?? []).filter(
          (job) => job.job_type === "normal" || job.job_type === "tongtiao",
        ),
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "前置任务加载失败");
    } finally {
      setLoadingJobs(false);
    }
  }, [user, fetchWithAuth]);

  // 打开弹窗：重置表单 + 加载前置任务
  useEffect(() => {
    if (!open) {
      return;
    }
    form.resetFields();
    form.setFieldsValue({ job_name: "", non_construction: false });
    setSelectedBaseJobId("");
    setRows([]);
    setSelectedTowerIds([]);
    setErrorMessage("");
    void loadBaseJobs();
  }, [open, form, loadBaseJobs]);

  // 选择前置任务 → 加载其杆塔结果，默认勾选中高风险塔
  const handleBaseJobChange = async (jobId: string) => {
    setSelectedBaseJobId(jobId);
    setSelectedTowerIds([]);
    if (!jobId) {
      setRows([]);
      return;
    }
    setLoadingRows(true);
    setErrorMessage("");
    try {
      const response = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${jobId}/results?limit=200`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const data = (await response.json()) as { items: FlAnalysisTowerResultSummary[] };
      const items = data.items ?? [];
      setRows(items);
      // 参照旧页面：高风险塔默认勾选（risk_level∈{high,3,4}）
      setSelectedTowerIds(
        items.filter((row) => isHighRisk(row.risk_level)).map((row) => row.tower_id),
      );
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "杆塔结果加载失败");
    } finally {
      setLoadingRows(false);
    }
  };

  const submit = async () => {
    const values = form.getFieldsValue();
    const baseJob = baseJobs.find((job) => job.id === selectedBaseJobId);
    if (!baseJob) {
      setErrorMessage("请选择前置防雷计算任务");
      return;
    }
    if (selectedTowerIds.length === 0) {
      setErrorMessage("请至少勾选一个杆塔");
      return;
    }
    setSubmitting(true);
    setErrorMessage("");
    try {
      const nonConstruction = Boolean(values.non_construction);
      const payload = {
        line_id: baseJob.line_id,
        job_name:
          values.job_name?.trim() ||
          `${baseJob.job_name || baseJob.line_name || baseJob.line_code || "防雷任务"}-措施推荐`,
        job_type: "mitigation",
        execution_options_json: {
          non_construction: nonConstruction,
          source_job_id: baseJob.id,
          selected_tower_ids: selectedTowerIds,
        },
      };
      const createResponse = await fetchWithAuth("/api/v1/fl-analysis/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!createResponse.ok) {
        throw new Error(await readApiError(createResponse));
      }
      const created = (await createResponse.json()) as { job: FlAnalysisJobSummary };
      const startResponse = await fetchWithAuth(`/api/v1/fl-analysis/jobs/${created.job.id}/start`, {
        method: "POST",
      });
      if (!startResponse.ok) {
        throw new Error(await readApiError(startResponse));
      }
      message.success(`措施推荐任务已创建并启动：${created.job.job_name || created.job.id}`);
      onCreated();
      onClose();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "措施推荐任务创建失败");
    } finally {
      setSubmitting(false);
    }
  };

  const selectedBaseJob = baseJobs.find((job) => job.id === selectedBaseJobId) ?? null;

  return (
    <Modal
      title="新建改造（措施推荐）任务"
      open={open}
      width={1080}
      confirmLoading={submitting}
      okText="创建并启动改造任务"
      onCancel={() => {
        if (submitting) {
          return;
        }
        onClose();
      }}
      onOk={() => {
        void submit();
      }}
    >
      <Space direction="vertical" size={16} className="flex w-full">
        <Alert
          type="info"
          showIcon
          message="基于已完成的风险计算（普通/同跳）任务，为其中高风险杆塔生成改造措施推荐。"
        />
        {errorMessage ? (
          <Alert type="error" showIcon message={errorMessage} />
        ) : null}
        <Form<RetrofitFormValues> form={form} layout="vertical" initialValues={{ non_construction: false }}>
          <Form.Item label="前置防雷计算任务" required>
            <Select
              value={selectedBaseJobId}
              onChange={(next) => {
                void handleBaseJobChange(next);
              }}
              loading={loadingJobs}
              placeholder="选择已完成的风险计算任务"
              showSearch
              optionFilterProp="label"
              options={baseJobs.map((job) => ({
                value: job.id,
                label: `${job.job_name || job.line_name || job.line_code || "-"}（${formatJobType(job.job_type)}）`,
              }))}
            />
          </Form.Item>
          <Form.Item
            name="job_name"
            label="任务名称"
            rules={[{ required: true, message: "请输入任务名称" }]}
          >
            <Input placeholder="措施推荐任务名称" />
          </Form.Item>
          <Form.Item name="non_construction" valuePropName="checked">
            <Checkbox>按“非建线”模式生成措施推荐（线路未建成规划阶段，可优化保护角）</Checkbox>
          </Form.Item>
        </Form>

        {selectedBaseJob ? (
          <Alert
            type="success"
            showIcon
            message="已选择前置任务"
            description={`${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "-"} / 杆塔总数：${selectedBaseJob.total_tower_count}`}
          />
        ) : null}

        {!selectedBaseJobId ? (
          <Empty description="请先选择前置防雷计算任务" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : rows.length === 0 ? (
          <Empty description="该任务暂无杆塔结果" image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : (
          <>
            <Typography.Text type="secondary">
              已命中 {rows.length} 座杆塔，其中高风险 {rows.filter((row) => isHighRisk(row.risk_level)).length} 座（默认选中，可按需调整）。
            </Typography.Text>
            <Table<FlAnalysisTowerResultSummary>
              rowKey="tower_id"
              size="small"
              loading={loadingRows}
              pagination={{ pageSize: 8, showSizeChanger: false, hideOnSinglePage: false }}
              rowSelection={{
                selectedRowKeys: selectedTowerIds,
                onChange: (keys) => {
                  setSelectedTowerIds(keys.map((item) => String(item)));
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