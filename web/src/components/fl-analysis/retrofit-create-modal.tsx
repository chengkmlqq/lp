"use client";

/**
 * 防雷改造 - 新建措施推荐任务弹窗（2026-09-30 页面重构；2026-10-01 表单收窄 + 前置任务下拉全量展示）。
 *
 * 参照 fl-analysis 的「新建任务/MitigationModal」形态：
 * 选择前置防雷计算任务(normal/tongtiao) → 自动加载其中高风险杆塔 →
 * 勾选杆塔 + 填任务名 + 非建线选项 → 创建并启动措施推荐(mitigation)任务。
 * 任务列表进度通过 WebSocket 主题回调由页面刷新。
 *
 * 2026-10-01 调整：
 * - Modal 宽度 1080 → 880（表单收窄）
 * - 任务名称移到表单第一项
 * - 前置任务下拉：展示全部已完成(normal/tongtiao)任务，无中高风险杆塔的
 *   置灰 + 标注「无中高风险杆塔」（参照 lightning-distribution 线路选择模式），
 *   有中高风险的显示计数；判断依据 result_summary_json.risk_counts{high,medium}（后端结果汇总已有）
 * - 「非建线模式」Checkbox → Select（否/是）
 */

import { Alert, Empty, Form, Input, Modal, Select, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";

import { useI18n } from "@/lib/i18n";
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

/** 从任务结果汇总读中高风险杆塔数（risk_counts.high + medium）。 */
function readRiskCounts(job: FlAnalysisJobSummary): { high: number; medium: number } {
  const summary = readObject(job.result_summary_json);
  const counts = readObject(summary.risk_counts);
  return {
    high: Number(counts.high ?? 0),
    medium: Number(counts.medium ?? 0),
  };
}

type RetrofitFormValues = {
  job_name: string;
  non_construction: boolean;
};

export function RetrofitCreateModal({ open, onClose, onCreated }: RetrofitCreateModalProps) {
  const { t } = useI18n();
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

  // 前置任务：分页拉全已完成的普通计算 / 同跳计算（有结果可作为风险来源）
  const loadBaseJobs = useCallback(async () => {
    if (!user) {
      return;
    }
    setLoadingJobs(true);
    try {
      const jobs: FlAnalysisJobSummary[] = [];
      let offset = 0;
      for (;;) {
        const response = await fetchWithAuth(
          `/api/v1/fl-analysis/jobs?limit=200&offset=${offset}&job_types=normal,tongtiao&status=success`,
        );
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const data = (await response.json()) as { items: FlAnalysisJobSummary[] };
        const pageItems = data.items ?? [];
        jobs.push(...pageItems);
        if (pageItems.length < 200) {
          break;
        }
        offset += 200;
      }
      setBaseJobs(jobs);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : t("前置任务加载失败"));
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
      setErrorMessage(error instanceof Error ? error.message : t("杆塔结果加载失败"));
    } finally {
      setLoadingRows(false);
    }
  };

  const submit = async () => {
    const values = form.getFieldsValue();
    const baseJob = baseJobs.find((job) => job.id === selectedBaseJobId);
    if (!baseJob) {
      setErrorMessage(t("请选择前置防雷计算任务"));
      return;
    }
    if (selectedTowerIds.length === 0) {
      setErrorMessage(t("请至少勾选一个杆塔"));
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
          `${baseJob.job_name || baseJob.line_name || baseJob.line_code || t("防雷任务")}-${t("措施推荐")}`,
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
      setErrorMessage(error instanceof Error ? error.message : t("措施推荐任务创建失败"));
    } finally {
      setSubmitting(false);
    }
  };

  const selectedBaseJob = baseJobs.find((job) => job.id === selectedBaseJobId) ?? null;

  // 下拉选项：全部前置任务都在，无中高风险杆塔的置灰 + 标注提示
  const baseJobOptions = baseJobs.map((job) => {
    const { high, medium } = readRiskCounts(job);
    const hasRisk = high + medium > 0;
    const name = `${job.job_name || job.line_name || job.line_code || "-"}（${formatJobType(job.job_type, false, t)}）`;
    return {
      value: job.id,
      label: (
        <Space size={6} style={{ width: "100%", justifyContent: "space-between" }}>
          <span>{name}</span>
          {hasRisk ? (
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>
              {high + medium} 座中高风险塔
            </Typography.Text>
          ) : (
            <Tag color="warning" style={{ marginInlineEnd: 0 }}>
              无中高风险杆塔
            </Tag>
          )}
        </Space>
      ),
      disabled: !hasRisk,
    };
  });

  return (
    <Modal
      title={t("新建改造（措施推荐）任务")}
      open={open}
      width={880}
      confirmLoading={submitting}
      okText={t("创建并启动改造任务")}
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
          message={t("基于已完成的风险计算（普通/同跳）任务，为其中高风险杆塔生成改造措施推荐。")}
        />
        {errorMessage ? (
          <Alert type="error" showIcon message={errorMessage} />
        ) : null}
        <Form<RetrofitFormValues> form={form} layout="vertical" initialValues={{ non_construction: false }}>
          <Form.Item
            name="job_name"
            label={t("任务名称")}
            rules={[{ required: true, message: t("请输入任务名称") }]}
          >
            <Input placeholder={t("措施推荐任务名称")} />
          </Form.Item>
          <Form.Item label={t("前置防雷计算任务")} required>
            <Select
              value={selectedBaseJobId}
              onChange={(next) => {
                void handleBaseJobChange(next);
              }}
              loading={loadingJobs}
              placeholder={t("选择已完成的风险计算任务")}
              showSearch
              optionFilterProp="label"
              options={baseJobOptions}
            />
          </Form.Item>
          <Form.Item name="non_construction" label={t("非建线模式")}>
            <Select
              options={[
                { value: false, label: t("否（建线）") },
                { value: true, label: t("是（非建线）") },
              ]}
            />
          </Form.Item>
        </Form>

        {selectedBaseJob ? (
          <Alert
            type="success"
            showIcon
            message={t("已选择前置任务")}
            description={`${selectedBaseJob.job_name || selectedBaseJob.line_name || selectedBaseJob.line_code || "-"} / ${t("杆塔总数")}：${selectedBaseJob.total_tower_count}`}
          />
        ) : null}

        {!selectedBaseJobId ? (
          <Empty description={t("请先选择前置防雷计算任务")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
        ) : rows.length === 0 ? (
          <Empty description={t("该任务暂无杆塔结果")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
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
                { title: t("杆塔号"), dataIndex: "tower_no", width: 110 },
                {
                  title: t("风险等级"),
                  dataIndex: "risk_level",
                  width: 110,
                  render: (value: string | null) => <Tag color={riskColor(value)}>{formatRiskLevel(value, t)}</Tag>,
                },
                {
                  title: t("高风险原因"),
                  key: "cause_analysis",
                  render: (_value, row) => readString(readObject(row.result_json), "cause_analysis"),
                },
                {
                  title: t("当前建议"),
                  key: "mitigation_recommendation",
                  render: (_value, row) => readString(readObject(row.result_json), "mitigation_recommendation"),
                },
              ]}
              dataSource={rows}
              scroll={{ x: 760 }}
            />
          </>
        )}
      </Space>
    </Modal>
  );
}
