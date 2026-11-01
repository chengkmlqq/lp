"use client";

/**
 * ATP 测试线路管理页（单塔基准）。
 *
 * 测试线路 = 一根"标准杆塔"的完整几何 + 参数输入，供 ATP 模型测试时复用。
 * 同一几何维（电压 × 塔型 × 避雷线）只允许一条共享基准；模型也可以绑定专用样本。
 *
 * 页面结构：筛选栏 → 列表（分页钉底）→ 编辑抽屉 / 派生弹窗 / 装配预览 / 引用清单。
 */
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  App,
  AutoComplete,
  Button,
  Empty,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
} from "antd";
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  PlusOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { ModoActionGroup } from "@/components/biz/modo-action-group";
import { modoTablePagination } from "@/components/biz/modo-pagination";
import { useAuth } from "@/components/auth-provider";
import { AtpTestLineDeriveModal } from "@/components/atp-test-lines/atp-test-line-derive-modal";
import { AtpTestLineEditor } from "@/components/atp-test-lines/atp-test-line-editor";
import { AtpTestLinePreviewModal } from "@/components/atp-test-lines/atp-test-line-preview-modal";
import { useDimensionOptions } from "@/hooks/use-dimension-options";
import { readApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import {
  SHIELD_WIRE_OPTIONS,
  TEST_LINE_SOURCE_KIND_LABEL,
  TEST_LINE_STATUS_META,
  type AtpTestLineDeriveRequest,
  type AtpTestLineDetail,
  type AtpTestLineSourceKind,
  type AtpTestLineStatus,
  type AtpTestLineSummary,
  type AtpTestLineUsageResponse,
} from "@/types/atp-test-line";

const { Text } = Typography;

const TABLE_MIN_SCROLL_Y = 180;

type Filters = {
  keyword: string;
  voltage_level?: string;
  tower_type?: string;
  shield_wire?: string;
  status?: AtpTestLineStatus;
};

const EMPTY_FILTERS: Filters = { keyword: "" };

function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return Number.isInteger(value) ? String(value) : value.toFixed(digits);
}

export default function AtpTestLinesPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission, fetchWithAuth } = useAuth();
  const { message, modal } = App.useApp();

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canManage = hasPermission("atp.manage");

  const [rows, setRows] = useState<AtpTestLineSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);

  const [keywordInput, setKeywordInput] = useState("");
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [pagination, setPagination] = useState({ current: 1, pageSize: 20 });
  const [tableScrollY, setTableScrollY] = useState(TABLE_MIN_SCROLL_Y);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<"create" | "edit">("create");
  const [editingDetail, setEditingDetail] = useState<AtpTestLineDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const [deriveOpen, setDeriveOpen] = useState(false);
  const [deriveInitial, setDeriveInitial] = useState<{
    voltage_level?: string;
    tower_type?: string;
    shield_wire?: string;
  } | null>(null);

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<AtpTestLineSummary | null>(null);

  const [usageOpen, setUsageOpen] = useState(false);
  const [usageData, setUsageData] = useState<AtpTestLineUsageResponse | null>(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageTarget, setUsageTarget] = useState<AtpTestLineSummary | null>(null);

  const { optionMap } = useDimensionOptions({
    voltage_level: "voltage_level",
    tower_type: "tower_type",
  });

  // 表格高度自适应视口（口径与其它管理页一致：锚点底边推导）
  useEffect(() => {
    if (typeof window === "undefined") return;
    const measure = () => {
      const anchor = tableScrollAnchorRef.current;
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const available = window.innerHeight - rect.top - 190;
      setTableScrollY(Math.max(TABLE_MIN_SCROLL_Y, Math.floor(available)));
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const loadList = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const { current, pageSize } = pagination;
      const params = new URLSearchParams();
      params.set("limit", String(pageSize));
      params.set("offset", String((current - 1) * pageSize));
      if (filters.keyword.trim()) params.set("keyword", filters.keyword.trim());
      if (filters.voltage_level) params.set("voltage_level", filters.voltage_level);
      if (filters.tower_type) params.set("tower_type", filters.tower_type);
      if (filters.shield_wire) params.set("shield_wire", filters.shield_wire);
      if (filters.status) params.set("status", filters.status);
      const response = await fetchWithAuth(`/api/v1/atp/test-lines?${params.toString()}`);
      if (!response.ok) throw new Error(await readApiError(response));
      const data = (await response.json()) as { items: AtpTestLineSummary[]; total: number };
      setRows(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (error) {
      setListError(error instanceof Error ? error.message : String(error));
      setRows([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [fetchWithAuth, filters, pagination]);

  useEffect(() => {
    if (!canRead) return;
    void loadList();
  }, [canRead, loadList]);

  const openEditor = async (row?: AtpTestLineSummary) => {
    if (!row) {
      setEditorMode("create");
      setEditingDetail(null);
      setEditorOpen(true);
      return;
    }
    setDetailLoading(true);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/test-lines/${row.id}`);
      if (!response.ok) throw new Error(await readApiError(response));
      setEditingDetail((await response.json()) as AtpTestLineDetail);
      setEditorMode("edit");
      setEditorOpen(true);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setDetailLoading(false);
    }
  };

  const handleDelete = (row: AtpTestLineSummary) => {
    modal.confirm({
      title: `${t("删除测试线路")}：${row.code}`,
      content: t("删除后引用它的模型/用例会退回按维度自动反查。此操作不可撤销。"),
      okButtonProps: { danger: true },
      okText: t("删除"),
      cancelText: t("取消"),
      onOk: async () => {
        const response = await fetchWithAuth(`/api/v1/atp/test-lines/${row.id}`, { method: "DELETE" });
        if (!response.ok) {
          message.error(await readApiError(response));
          return;
        }
        message.success(t("已删除"));
        void loadList();
      },
    });
  };

  const handleClone = async (row: AtpTestLineSummary) => {
    const response = await fetchWithAuth(`/api/v1/atp/test-lines/${row.id}/clone`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: `${row.name}${t("（副本）")}` }),
    });
    if (!response.ok) {
      message.error(await readApiError(response));
      return;
    }
    message.success(t("已复制"));
    void loadList();
  };

  const openUsage = async (row: AtpTestLineSummary) => {
    setUsageTarget(row);
    setUsageOpen(true);
    setUsageLoading(true);
    setUsageData(null);
    try {
      const response = await fetchWithAuth(`/api/v1/atp/test-lines/${row.id}/usage`);
      if (!response.ok) throw new Error(await readApiError(response));
      setUsageData((await response.json()) as AtpTestLineUsageResponse);
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setUsageLoading(false);
    }
  };

  /** 派生确认：草稿 + 代码/名称 + 归属一次性落库 */
  const handleDeriveCommit = async ({
    request,
    draft,
    code,
    name,
    sourceKind,
  }: {
    request: AtpTestLineDeriveRequest;
    draft: Record<string, unknown>;
    code: string;
    name: string;
    sourceKind: AtpTestLineSourceKind;
  }): Promise<boolean> => {
    const payload: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(draft)) {
      if (key.startsWith("_") || key === "circuits") continue;
      payload[key] = value;
    }
    if (Array.isArray(draft.circuits)) payload.circuits = draft.circuits;
    payload.code = code;
    payload.name = name;
    payload.source_kind = sourceKind;
    if (request.asset_id) payload.asset_id = request.asset_id;
    if (request.source_tower_id) payload.source_tower_id = request.source_tower_id;

    const response = await fetchWithAuth("/api/v1/atp/test-lines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      message.error(await readApiError(response));
      return false;
    }
    void loadList();
    return true;
  };

  const columns: ColumnsType<AtpTestLineSummary> = [
    {
      title: t("代码 / 名称"),
      dataIndex: "code",
      width: 250,
      fixed: "left",
      render: (_: unknown, row) => (
        <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <Space size={6} wrap>
            <Text strong>{row.code}</Text>
            {row.asset_id ? (
              <Tooltip title={t("模型专用样本：只给该模型用")}>
                <Tag color="purple">{row.asset_code ?? t("专用")}</Tag>
              </Tooltip>
            ) : (
              <Tag color="blue">{t("共享基准")}</Tag>
            )}
          </Space>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {row.name}
          </Text>
        </div>
      ),
    },
    {
      title: t("几何维"),
      key: "geometry",
      width: 230,
      render: (_: unknown, row) => (
        <Space size={4} wrap>
          <Tag color="geekblue">{row.voltage_level} kV</Tag>
          <Tag>{row.tower_type}</Tag>
          <Tag color={row.shield_wire === "with" ? "cyan" : "default"}>
            {row.shield_wire === "with" ? t("双避雷线") : t("单避雷线")}
          </Tag>
          {row.circuit_count > 1 ? <Tag>{row.circuit_count} 回</Tag> : null}
        </Space>
      ),
    },
    {
      title: t("场景 / 避雷器"),
      key: "tags",
      width: 170,
      render: (_: unknown, row) =>
        row.scene_type || row.arrester_config ? (
          <Space size={4} wrap>
            {row.scene_type ? <Tag>{row.scene_type}</Tag> : null}
            {row.arrester_config ? <Tag>{row.arrester_config}</Tag> : null}
          </Space>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("关键几何"),
      key: "geometryKey",
      width: 210,
      render: (_: unknown, row) => (
        <div style={{ fontSize: 12, lineHeight: 1.6 }}>
          <div>
            {t("呼高")} {formatNumber(row.call_height_m)} m ・ {t("串长")} {formatNumber(row.insulator_length_m)} m
          </div>
          <div>
            {t("档距")} {formatNumber(row.span_small_m, 0)}~{formatNumber(row.span_large_m, 0)} m
          </div>
        </div>
      ),
    },
    {
      title: t("雷电流"),
      dataIndex: "current_ka",
      width: 100,
      render: (value: number) => `${formatNumber(value, 1)} kA`,
    },
    {
      title: t("来源"),
      dataIndex: "source_kind",
      width: 120,
      render: (value: AtpTestLineSourceKind) => <Tag>{t(TEST_LINE_SOURCE_KIND_LABEL[value] ?? value)}</Tag>,
    },
    {
      title: t("状态"),
      dataIndex: "status",
      width: 90,
      render: (value: AtpTestLineStatus) => {
        const meta = TEST_LINE_STATUS_META[value];
        return <Tag color={meta?.color}>{t(meta?.label ?? value)}</Tag>;
      },
    },
    {
      title: t("快照"),
      dataIndex: "snapshot_hash",
      width: 110,
      render: (value: string | null) =>
        value ? (
          <Tooltip title={value}>
            <Text code style={{ fontSize: 11 }}>
              {value.slice(0, 8)}
            </Text>
          </Tooltip>
        ) : (
          <Text type="secondary">—</Text>
        ),
    },
    {
      title: t("使用"),
      dataIndex: "used_count",
      width: 70,
      render: (value: number) => <Text type="secondary">{value}</Text>,
    },
    {
      title: t("操作"),
      key: "actions",
      width: 150,
      fixed: "right",
      render: (_: unknown, row) => (
        <ModoActionGroup
          maxCount={2}
          actions={[
            {
              key: "edit",
              label: t("编辑"),
              icon: <EditOutlined />,
              visible: canManage,
              onClick: () => void openEditor(row),
            },
            {
              key: "preview",
              label: t("预览"),
              icon: <EyeOutlined />,
              onClick: () => {
                setPreviewTarget(row);
                setPreviewOpen(true);
              },
            },
            {
              key: "usage",
              label: t("引用"),
              onClick: () => void openUsage(row),
            },
            {
              key: "clone",
              label: t("复制"),
              icon: <CopyOutlined />,
              visible: canManage,
              onClick: () => void handleClone(row),
            },
            {
              key: "delete",
              label: t("删除"),
              icon: <DeleteOutlined />,
              danger: true,
              visible: canManage,
              onClick: () => handleDelete(row),
            },
          ]}
        />
      ),
    },
  ];

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (!user || !canRead) {
    return (
      <div className="modo-page-card">
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Text type="secondary">
              {!user
                ? t("请先登录后再访问测试线路管理。")
                : t("当前账号无 ATP 模块权限（需要 atp.read/atp.run/atp.manage）。")}
            </Text>
          }
        />
      </div>
    );
  }

  const hasFilter = Boolean(
    filters.keyword || filters.voltage_level || filters.tower_type || filters.shield_wire || filters.status,
  );

  return (
    <div className="modo-page-card">
      <div className="admin-filter-bar">
        <Form layout="inline">
          <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              allowClear
              value={keywordInput}
              placeholder={t("代码/名称/说明")}
              onChange={(event) => setKeywordInput(event.currentTarget.value)}
              onPressEnter={() => {
                setFilters((prev) => ({ ...prev, keyword: keywordInput }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            />
          </Form.Item>

          <Form.Item label={t("电压")} style={{ marginBottom: 0 }}>
            <AutoComplete
              allowClear
              style={{ width: 100 }}
              placeholder={t("全部")}
              value={filters.voltage_level}
              options={optionMap.voltage_level ?? []}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, voltage_level: value || undefined }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            />
          </Form.Item>

          <Form.Item label={t("塔型")} style={{ marginBottom: 0 }}>
            <AutoComplete
              allowClear
              style={{ width: 120 }}
              placeholder={t("全部")}
              value={filters.tower_type}
              options={optionMap.tower_type ?? []}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, tower_type: value || undefined }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            />
          </Form.Item>

          <Form.Item label={t("避雷线")} style={{ marginBottom: 0 }}>
            <Select
              allowClear
              style={{ width: 118 }}
              placeholder={t("全部")}
              value={filters.shield_wire}
              options={SHIELD_WIRE_OPTIONS.map((o) => ({ value: o.value, label: t(o.label) }))}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, shield_wire: value }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            />
          </Form.Item>

          <Form.Item label={t("状态")} style={{ marginBottom: 0 }}>
            <Select
              allowClear
              style={{ width: 100 }}
              placeholder={t("全部")}
              value={filters.status}
              options={(Object.keys(TEST_LINE_STATUS_META) as AtpTestLineStatus[]).map((key) => ({
                value: key,
                label: t(TEST_LINE_STATUS_META[key].label),
              }))}
              onChange={(value) => {
                setFilters((prev) => ({ ...prev, status: value }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            />
          </Form.Item>

          <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
            <Button
              type="primary"
              htmlType="button"
              icon={<SearchOutlined />}
              loading={loading}
              className="admin-search-btn"
              onClick={() => {
                setFilters((prev) => ({ ...prev, keyword: keywordInput }));
                setPagination((prev) => ({ ...prev, current: 1 }));
              }}
            >
              {t("查询")}
            </Button>
          </Form.Item>

          {hasFilter ? (
            <Form.Item style={{ marginBottom: 0, marginRight: 8 }}>
              <Button
                htmlType="button"
                onClick={() => {
                  setKeywordInput("");
                  setFilters(EMPTY_FILTERS);
                  setPagination((prev) => ({ ...prev, current: 1 }));
                }}
              >
                {t("清除筛选")}
              </Button>
            </Form.Item>
          ) : null}

          <Form.Item style={{ marginBottom: 0, marginInlineStart: "auto" }}>
            <Space>
              <Button htmlType="button" icon={<PlusOutlined />} onClick={() => void openEditor()}>
                {t("手工新建")}
              </Button>
              <Button
                type="primary"
                htmlType="button"
                disabled={!canManage}
                onClick={() => {
                  setDeriveInitial(
                    filters.voltage_level || filters.tower_type || filters.shield_wire
                      ? {
                          voltage_level: filters.voltage_level,
                          tower_type: filters.tower_type,
                          shield_wire: filters.shield_wire,
                        }
                      : null,
                  );
                  setDeriveOpen(true);
                }}
              >
                {t("派生")}
              </Button>
            </Space>
          </Form.Item>
        </Form>
      </div>

      {listError ? (
        <Alert type="error" showIcon style={{ marginBottom: 12 }} message={t("加载失败")} description={listError} />
      ) : null}

      <div ref={tableScrollAnchorRef} className="flex min-h-0 flex-1 flex-col">
        <Table<AtpTestLineSummary>
          rowKey="id"
          size="small"
          loading={loading || detailLoading}
          dataSource={rows}
          columns={columns}
          tableLayout="fixed"
          scroll={{ x: 1500, y: tableScrollY }}
          pagination={modoTablePagination({
            current: pagination.current,
            pageSize: pagination.pageSize,
            total: Math.max(total, 1),
            onChange: (page, pageSize) => setPagination({ current: page, pageSize }),
          })}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={
                  <Space direction="vertical" size={4}>
                    <Text type="secondary">{t("还没有测试线路。")}</Text>
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      {t("建议从「派生」开始：按真实杆塔或按模型派生，几何一次填全。")}
                    </Text>
                  </Space>
                }
              />
            ),
          }}
        />
      </div>

      <AtpTestLineEditor
        open={editorOpen}
        mode={editorMode}
        detail={editingDetail}
        presetSourceKind="manual"
        canManage={canManage}
        onClose={() => setEditorOpen(false)}
        onSaved={() => void loadList()}
      />

      <AtpTestLineDeriveModal
        open={deriveOpen}
        canManage={canManage}
        initialDimension={deriveInitial}
        onClose={() => setDeriveOpen(false)}
        onCommit={handleDeriveCommit}
      />

      <AtpTestLinePreviewModal
        open={previewOpen}
        testLineId={previewTarget?.id ?? null}
        testLineCode={previewTarget?.code ?? null}
        onClose={() => setPreviewOpen(false)}
      />

      <Modal
        open={usageOpen}
        title={`${t("引用清单")}${usageTarget ? `：${usageTarget.code}` : ""}`}
        width={560}
        onCancel={() => setUsageOpen(false)}
        destroyOnHidden
        footer={<Button onClick={() => setUsageOpen(false)}>{t("关闭")}</Button>}
      >
        {usageLoading ? (
          <div style={{ padding: 24, textAlign: "center" }}>
            <Text type="secondary">{t("加载中…")}</Text>
          </div>
        ) : !usageData || usageData.items.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("暂无引用")} />
        ) : (
          <Table
            rowKey={(item) => `${item.kind}-${item.id}`}
            size="small"
            pagination={false}
            dataSource={usageData.items}
            columns={[
              {
                title: t("类型"),
                dataIndex: "kind",
                width: 110,
                render: (value: string) => <Tag>{value === "asset" ? t("模型绑定") : t("测试集用例")}</Tag>,
              },
              { title: t("代码"), dataIndex: "code", width: 150 },
              { title: t("名称"), dataIndex: "name" },
            ]}
          />
        )}
      </Modal>
    </div>
  );
}
