"use client";

/**
 * 基础数据包「导入」页（部署人员用）。
 *
 * LP-130：布局对齐线路管理页 —— ModoTabs（导入任务列表 Tab + 可关闭详情 Tab）+
 * 筛选栏 + 卡片/列表视图切换，导入表单收进右上角「导入数据包」弹窗。
 *
 * 端点（LP-14 既有）：
 *   POST /admin/platform-data/import        异步导入
 *   GET  /admin/platform-data/jobs?kind=export&status=success  复用来源
 */
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { Alert, App, Button, Form, Modal, Select, Space, Typography, Upload, type UploadFile } from "antd";
import { InboxOutlined, MonitorOutlined, UploadOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { readApiError } from "@/lib/api";
import { PlatformDataJobDetailPane, formatDateTime, type JobSummary } from "../shared";
import { PlatformDataJobsPanel, type PlatformDataJobsPanelHandle } from "../jobs-panel";

const { Text } = Typography;

const LIST_TAB_KEY = "list";

type DetailTabItem = {
  key: string;
  label: string;
  closable: boolean;
  jobId: string;
  children: ReactNode;
};

export default function PlatformDataImportPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message } = App.useApp();

  const canManage = hasPermission("platform_data.manage");

  const [detailTabs, setDetailTabs] = useState<DetailTabItem[]>([]);
  const [activeTabKey, setActiveTabKey] = useState<string>(LIST_TAB_KEY);

  const handleTabsEdit = useCallback(
    (targetKey: ReactMouseEvent | ReactKeyboardEvent | string, action: "add" | "remove") => {
      if (action !== "remove") return;
      const key = String(targetKey);
      const removedIndex = detailTabs.findIndex((tab) => tab.key === key);
      const next = detailTabs.filter((tab) => tab.key !== key);
      setDetailTabs(next);
      if (activeTabKey === key) {
        setActiveTabKey(next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY);
      }
    },
    [detailTabs, activeTabKey],
  );

  const openDetail = useCallback(
    (job: JobSummary) => {
      const key = job.id;
      setDetailTabs((previous) => {
        if (previous.some((tab) => tab.key === key)) return previous;
        return [
          ...previous,
          {
            key,
            label: `${t("任务详情")} - ${job.id.slice(0, 8)}`,
            closable: true,
            jobId: job.id,
            children: <PlatformDataJobDetailPane jobId={job.id} />,
          },
        ];
      });
      setActiveTabKey(key);
    },
    [t],
  );

  const jobsPanelRef = useRef<PlatformDataJobsPanelHandle | null>(null);

  // 任务被删除后关闭它的详情 Tab（若正打开）
  const handleJobDeleted = useCallback(
    (jobId: string) => {
      const removedIndex = detailTabs.findIndex((tab) => tab.key === jobId);
      if (removedIndex < 0) return;
      const next = detailTabs.filter((tab) => tab.key !== jobId);
      setDetailTabs(next);
      if (activeTabKey === jobId) {
        setActiveTabKey(next[Math.max(0, removedIndex - 1)]?.key ?? next[0]?.key ?? LIST_TAB_KEY);
      }
    },
    [detailTabs, activeTabKey],
  );

  // ── 导入弹窗 ─────────────────────────────────────────────────────
  const [importOpen, setImportOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [sourceJobId, setSourceJobId] = useState<string | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [reuseJobs, setReuseJobs] = useState<JobSummary[]>([]);

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

  const resetImportForm = () => {
    setImportFile(null);
    setSourceJobId(null);
  };

  const openImportModal = () => {
    resetImportForm();
    setImportOpen(true);
  };

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
      setImportOpen(false);
      resetImportForm();
      jobsPanelRef.current?.reload({ resetPage: true });
      void loadReuseJobs();
    } catch (caught) {
      // 失败留在弹窗内提示，不关闭弹窗
      message.error(caught instanceof Error ? caught.message : String(caught));
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
    <div className="flex min-h-0 flex-1 flex-col">
      <ModoTabs
        type="editable-card"
        hideAdd
        className="modo-page-tabs"
        activeKey={activeTabKey}
        onChange={setActiveTabKey}
        onEdit={handleTabsEdit}
        tabBarExtraContent={
          <Space size={8}>
            <Link href="/admin/task-monitor">
              <Button icon={<MonitorOutlined />}>{t("任务监控")}</Button>
            </Link>
            <Button type="primary" icon={<InboxOutlined />} onClick={openImportModal}>
              {t("导入数据包")}
            </Button>
          </Space>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: t("导入任务列表"),
            closable: false,
            children: (
              <div className="modo-page-card admin-platform-data-list-pane">
                <PlatformDataJobsPanel
                  ref={jobsPanelRef}
                  fixedKind="import"
                  onOpenDetail={openDetail}
                  onJobDeleted={handleJobDeleted}
                />
              </div>
            ),
          },
          ...detailTabs,
        ]}
      />

      <Modal
        title={t("导入数据包")}
        open={importOpen}
        forceRender
        width={560}
        okText={t("导入")}
        cancelText={t("取消")}
        confirmLoading={importLoading}
        onCancel={() => {
          if (importLoading) return;
          setImportOpen(false);
        }}
        onOk={() => void handleImport()}
      >
        <Form layout="vertical">
          <Form.Item label={t("上传包")}>
            <Upload
              maxCount={1}
              beforeUpload={(file) => {
                setImportFile(file as unknown as File);
                return false;
              }}
              onRemove={() => setImportFile(null)}
              fileList={
                importFile ? ([{ uid: "-1", name: importFile.name, status: "done" }] as UploadFile[]) : []
              }
            >
              <Button icon={<UploadOutlined />}>{t("选择 ZIP")}</Button>
            </Upload>
          </Form.Item>
          <Form.Item label={t("复用历史导出")}>
            <Select
              allowClear
              style={{ width: "100%" }}
              placeholder={t("或选择某次已完成导出任务")}
              value={sourceJobId}
              onChange={(value) => setSourceJobId(value ?? null)}
              options={reuseJobs.map((job) => ({
                value: job.id,
                label: `${job.id.slice(0, 8)} · ${formatDateTime(job.finish_date)}`,
              }))}
            />
          </Form.Item>
          <div style={{ color: "var(--gray-9)", fontSize: 12 }}>
            {t("导入为异步任务，提交后请到「任务监控」页查看执行结果与各分类计数。")}
          </div>
        </Form>
      </Modal>
    </div>
  );
}
