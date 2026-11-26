"use client";

/**
 * 基础数据包「导出」页（交付人员用）。
 *
 * LP-130：布局对齐线路管理页 —— ModoTabs（任务列表 Tab + 可关闭详情 Tab）+
 * 筛选栏 + 卡片/列表视图切换，导出表单收进右上角「导出数据包」弹窗。
 *
 * 端点（LP-14 既有）：
 *   POST /admin/platform-data/export        异步导出
 *   GET  /admin/platform-data/jobs          历史任务列表
 *   GET  /admin/platform-data/jobs/{id}     任务详情
 *   GET  /admin/platform-data/jobs/{id}/download  重新下载产物
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
} from "react";
import { Alert, App, Button, Checkbox, Form, Modal, Select, Typography } from "antd";
import { DownloadOutlined } from "@ant-design/icons";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { ModoTabs } from "@/components/biz/modo-tabs";
import { readApiError } from "@/lib/api";
import type { DimensionItemListResponse } from "@/types/dimension";
import {
  CATEGORY_OPTIONS,
  EMPTY_EXPORT_DIMENSION_OPTIONS,
  EXPORT_DIMENSION_TYPE_CODES,
  PlatformDataJobDetailPane,
  flattenDimensionTypes,
  type DimensionOption,
  type ExportDimensionField,
  type ExportDimensionOptions,
  type JobSummary,
} from "../shared";
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

export default function PlatformDataExportPage() {
  const { t, lang } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message } = App.useApp();

  const canManage = hasPermission("platform_data.manage");

  // ── Tab 状态：列表 Tab + 可关闭的任务详情 Tab ────────────────────
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

  // ── 导出弹窗表单 ─────────────────────────────────────────────────
  const [exportOpen, setExportOpen] = useState(false);
  const [exportCategories, setExportCategories] = useState<string[]>([]);
  const [exportLayout, setExportLayout] = useState<"bundle" | "atp_tree">("bundle");
  const [filterVoltage, setFilterVoltage] = useState<string[]>([]);
  const [filterTower, setFilterTower] = useState<string[]>([]);
  const [filterScene, setFilterScene] = useState<string[]>([]);
  const [dimensionOptions, setDimensionOptions] = useState<ExportDimensionOptions>(EMPTY_EXPORT_DIMENSION_OPTIONS);
  const [exportLoading, setExportLoading] = useState(false);

  const atpModelsSelected = exportCategories.includes("atp_models");

  // 类别选项的 label 是中文原文，经 t() 渲染后按当前语言字母排序。
  const categoryOptions = useMemo(
    () =>
      CATEGORY_OPTIONS.map((option) => ({ ...option, label: t(option.label) })).sort((a, b) =>
        a.label.localeCompare(b.label, lang === "en" ? "en" : "zh-CN"),
      ),
    [t, lang],
  );

  // 仅在勾选「ATP 模型」类别时按需加载维度选项（types/tree + 每维度一次 dimensions）
  const dimensionOptionsLoadedRef = useRef(false);
  useEffect(() => {
    if (!atpModelsSelected || !canManage || dimensionOptionsLoadedRef.current) return;
    dimensionOptionsLoadedRef.current = true;
    void (async () => {
      try {
        const treeResponse = await fetchWithAuth("/api/v1/dimensions/types/tree");
        if (!treeResponse.ok) return;
        const types = (await treeResponse.json()) as import("@/types/auth").DimensionTypeTreeItem[];
        const flatTypes = flattenDimensionTypes(types);
        const fields = Object.keys(EXPORT_DIMENSION_TYPE_CODES) as ExportDimensionField[];
        const loaded = await Promise.all(
          fields.map(async (field): Promise<[ExportDimensionField, DimensionOption[]]> => {
            const typeId = flatTypes.find((item) => item.code === EXPORT_DIMENSION_TYPE_CODES[field])?.id;
            if (!typeId) return [field, []];
            const params = new URLSearchParams();
            params.set("type_id", typeId);
            params.set("enabled", "true");
            params.set("limit", "200");
            const response = await fetchWithAuth(`/api/v1/dimensions?${params.toString()}`);
            if (!response.ok) return [field, []];
            const data = (await response.json()) as DimensionItemListResponse;
            const options = (data.items ?? [])
              .map((item) => ({ label: item.name, value: item.code }))
              .sort((a, b) => t(a.label).localeCompare(t(b.label), lang === "en" ? "en" : "zh-CN"));
            return [field, options];
          }),
        );
        setDimensionOptions(Object.fromEntries(loaded) as ExportDimensionOptions);
      } catch {
        /* 维度选项加载失败不阻断导出，下拉保持空选项 */
      }
    })();
  }, [atpModelsSelected, canManage, fetchWithAuth, t, lang]);

  const resetExportForm = () => {
    setExportCategories([]);
    setExportLayout("bundle");
    setFilterVoltage([]);
    setFilterTower([]);
    setFilterScene([]);
  };

  const openExportModal = () => {
    resetExportForm();
    setExportOpen(true);
  };

  // ── 提交导出 ─────────────────────────────────────────────────────
  const handleExport = async () => {
    if (exportCategories.length === 0) {
      message.warning(t("请至少勾选一个导出类别"));
      return;
    }
    const filters: Record<string, string[]> = {};
    if (atpModelsSelected) {
      if (filterVoltage.length) filters.voltage_level = filterVoltage;
      if (filterTower.length) filters.tower_type = filterTower;
      if (filterScene.length) filters.scene = filterScene;
    }
    const effectiveLayout = atpModelsSelected ? exportLayout : "bundle";
    setExportLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/admin/platform-data/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categories: exportCategories, filters, layout: effectiveLayout }),
      });
      if (!response.ok) throw new Error(await readApiError(response));
      message.success(t("已创建导出任务，正在打包…"));
      setExportOpen(false);
      resetExportForm();
      jobsPanelRef.current?.reload({ resetPage: true });
    } catch (caught) {
      // 失败留在弹窗内提示，不关闭弹窗
      message.error(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setExportLoading(false);
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
          <Button type="primary" icon={<DownloadOutlined />} onClick={openExportModal}>
            {t("导出数据包")}
          </Button>
        }
        items={[
          {
            key: LIST_TAB_KEY,
            label: t("数据导出"),
            closable: false,
            children: (
              <div className="modo-page-card admin-platform-data-list-pane">
                <PlatformDataJobsPanel
                  ref={jobsPanelRef}
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
        title={t("导出数据包")}
        open={exportOpen}
        forceRender
        width={640}
        okText={t("导出")}
        cancelText={t("取消")}
        confirmLoading={exportLoading}
        onCancel={() => {
          if (exportLoading) return;
          setExportOpen(false);
        }}
        onOk={() => void handleExport()}
      >
        <Form layout="vertical">
          <Form.Item label={t("类别")} required>
            <Checkbox.Group
              options={categoryOptions}
              value={exportCategories}
              onChange={(values) => setExportCategories(values as string[])}
            />
          </Form.Item>
          {atpModelsSelected ? (
            <>
              <Form.Item label={t("ATP 格式")}>
                <Select
                  value={exportLayout}
                  onChange={(value) => setExportLayout(value as "bundle" | "atp_tree")}
                  options={[
                    { value: "bundle", label: t("平台数据包") },
                    { value: "atp_tree", label: t("ATP 目录树（C#）") },
                  ]}
                />
              </Form.Item>
              <Form.Item label={t("电压")}>
                <Select
                  mode="multiple"
                  allowClear
                  placeholder={t("请选择电压等级")}
                  value={filterVoltage}
                  onChange={(values) => setFilterVoltage(values ?? [])}
                  options={dimensionOptions.voltage_level}
                  maxTagCount="responsive"
                />
              </Form.Item>
              <Form.Item label={t("塔型")}>
                <Select
                  mode="multiple"
                  allowClear
                  placeholder={t("请选择塔型")}
                  value={filterTower}
                  onChange={(values) => setFilterTower(values ?? [])}
                  options={dimensionOptions.tower_type}
                  maxTagCount="responsive"
                />
              </Form.Item>
              <Form.Item label={t("场景")}>
                <Select
                  mode="multiple"
                  allowClear
                  placeholder={t("请选择场景")}
                  value={filterScene}
                  onChange={(values) => setFilterScene(values ?? [])}
                  options={dimensionOptions.scene}
                  maxTagCount="responsive"
                />
              </Form.Item>
              {exportLayout === "atp_tree" ? (
                <div style={{ color: "var(--gray-9)", fontSize: 12 }}>
                  {t("ATP 目录树按 电压/塔型/场景/措施 导出激活版本，包内 $INCLUDE 已重写为 D:\\ATP 下的绝对路径；解压到 D:\\ATP 后可直接供 C# 程序使用。")}
                </div>
              ) : null}
            </>
          ) : null}
          <div style={{ marginTop: 12, color: "var(--gray-9)", fontSize: 12 }}>
            {t("导出为异步任务，提交后可在任务列表查看进度与包大小。")}
          </div>
        </Form>
      </Modal>
    </div>
  );
}
