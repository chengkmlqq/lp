"use client";

/**
 * 基础数据包「导入」页（部署人员用）。
 *
 * 只保留导入组件：上传 ZIP 或复用历史导出 → 异步导入。
 * 不展示导出表单与任务列表；任务状态请到「任务监控」页查看。
 *
 * 端点（LP-14 既有）：
 *   POST /admin/platform-data/import        异步导入
 *   GET  /admin/platform-data/jobs?kind=export&status=success  复用来源
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, App, Button, Card, Form, Select, Typography, Upload, type UploadFile } from "antd";
import { InboxOutlined, UploadOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import { formatDateTime, type JobSummary } from "../shared";

const { Text } = Typography;

export default function PlatformDataImportPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message } = App.useApp();

  const canManage = hasPermission("platform_data.manage");

  const [importFile, setImportFile] = useState<File | null>(null);
  const [sourceJobId, setSourceJobId] = useState<string | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [reuseJobs, setReuseJobs] = useState<JobSummary[]>([]);
  const importSelectRef = useRef<{ focus: () => void } | null>(null);

  // 复用来源：已完成的历史导出任务
  const loadReuseJobs = useCallback(async () => {
    try {
      const response = await fetchWithAuth(
        `/api/v1/admin/platform-data/jobs?kind=export&status=success&limit=100&offset=0`,
      );
      if (!response.ok) return;
      const data = (await response.json()) as { items: JobSummary[] };
      setReuseJobs(data.items ?? []);
    } catch {
      /* 复用来源加载失败不应阻断主流程 */
    }
  }, [fetchWithAuth]);

  useEffect(() => {
    if (!canManage) return;
    void loadReuseJobs();
  }, [canManage, loadReuseJobs]);

  const handleImport = async () => {
    if (!importFile && !sourceJobId) {
      message.warning(t("请上传数据包 ZIP，或选择复用某次历史导出"));
      return;
    }
    setImportLoading(true);
    try {
      const formData = new FormData();
      if (importFile) formData.append("file", importFile);
      if (sourceJobId) formData.append("source_job_id", sourceJobId);
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("已创建导入任务，正在写入…可在「任务监控」页查看结果"));
      setImportFile(null);
      setSourceJobId(null);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setImportLoading(false);
    }
  };

  if (!initializing && !canManage) {
    return (
      <div className="modo-page-card">
        <Alert
          type="warning"
          showIcon
          message={t("无访问权限")}
          description={
            <Text type="secondary">
              {!user
                ? t("请先登录后再访问基础数据包工具。")
                : t("当前账号无 platform_data.manage 权限，菜单与接口均不可用。")}
            </Text>
          }
        />
      </div>
    );
  }

  return (
    <div className="modo-page-card">
      <Card size="small" title={t("导入数据包")}>
        <div className="admin-filter-bar">
          <Form layout="inline">
            <Form.Item label={t("上传包")} style={{ marginBottom: 0 }}>
              <Upload
                maxCount={1}
                beforeUpload={(file) => {
                  setImportFile(file as unknown as File);
                  return false;
                }}
                onRemove={() => setImportFile(null)}
                fileList={
                  importFile
                    ? ([{ uid: "-1", name: importFile.name, status: "done" }] as UploadFile[])
                    : []
                }
              >
                <Button icon={<UploadOutlined />}>{t("选择 ZIP")}</Button>
              </Upload>
            </Form.Item>
            <Form.Item label={t("复用历史导出")} style={{ marginBottom: 0 }}>
              <Select
                ref={importSelectRef as never}
                allowClear
                style={{ width: 260 }}
                placeholder={t("或选择某次已完成导出任务")}
                value={sourceJobId}
                onChange={(value) => setSourceJobId(value ?? null)}
                options={reuseJobs.map((j) => ({
                  value: j.id,
                  label: `${j.id.slice(0, 8)} · ${formatDateTime(j.finish_date)}`,
                }))}
              />
            </Form.Item>
            <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
              <Button
                type="primary"
                icon={<InboxOutlined />}
                loading={importLoading}
                onClick={() => void handleImport()}
              >
                {t("导入数据包")}
              </Button>
            </Form.Item>
          </Form>
        </div>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t("导入为异步任务，提交后请到「任务监控」页查看执行结果。")}
          </Text>
        </div>
      </Card>
    </div>
  );
}
