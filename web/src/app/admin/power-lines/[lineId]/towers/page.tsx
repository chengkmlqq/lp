"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  App,
  Alert,
  Button,
  Card,
  Descriptions,
  Drawer,
  Empty,
  Form,
  Input,
  Modal,
  Progress,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Typography,
  Upload,
} from "antd";
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  InboxOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import Link from "next/link";

import { useI18n } from "@/lib/i18n";
import { ModoPagination } from "@/components/biz/modo-pagination";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { getApiBaseUrl, readApiError } from "@/lib/api";
import { RiskLevelTag } from "@/lib/risk-level";
import type {
  LineTowerImportResponse,
  LineTowerListResponse,
  LineTowerSummary,
  TempUploadResponse,
  TowerCircuitSummary,
  TowerDetailResponse,
} from "@/types/auth";

const TOWER_TYPE_OPTIONS = [
  { value: "", label: "全部塔型" },
  { value: "直线", label: "直线" },
  { value: "耐张", label: "耐张" },
] as const;
const TOWER_TABLE_DEFAULT_PAGE_SIZE = 20;

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }
  const parsed = value.includes("T") ? value.replace("T", " ").replace("Z", "") : value;
  return parsed.length >= 19 ? parsed.slice(0, 19) : parsed;
}

export default function AdminPowerLineTowersPage() {
  const { t } = useI18n();
  const { lineId } = useParams<{ lineId: string }>();
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();
  const queryClient = useQueryClient();
  const { message: messageApi } = App.useApp();

  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  // 与后端 /lines/{id}/towers 契约一致：具备 line.read/line.manage 亦可读取杆塔
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage") || canLineRead;
  const canTowerManage = hasPermission("tower.manage");

  const [lineDetail, setLineDetail] = useState<{ code: string; name: string } | null>(null);
  const [lineLoading, setLineLoading] = useState(true);
  const [lineError, setLineError] = useState("");
  const [towerKeyword, setTowerKeyword] = useState("");
  // 已生效的查询关键词：仅在点击「查询」/回车时同步，输入过程不触发接口请求
  const [appliedTowerKeyword, setAppliedTowerKeyword] = useState("");
  const [towerTypeFilter, setTowerTypeFilter] = useState("");
  const [towerPagination, setTowerPagination] = useState({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE });
  // 手动刷新计数：每次点击「查询」都自增并作为 queryKey 的一部分，强制走一次接口，
  // 即使关键词/塔型/分页均未变化、或目标结果此前已被 react-query 缓存，也不会被缓存短路。
  const [searchNonce, setSearchNonce] = useState(0);
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [towerDetailDrawerOpen, setTowerDetailDrawerOpen] = useState(false);
  const [selectedTowerForDetail, setSelectedTowerForDetail] = useState<LineTowerSummary | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchDetail = async () => {
      try {
        setLineLoading(true);
        const response = await fetchWithAuth(`/api/v1/lines/${lineId}`);
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const data = (await response.json()) as { code: string; name: string };
        if (!cancelled) {
          setLineDetail({ code: data.code, name: data.name });
          setLineError("");
        }
      } catch (err) {
        if (!cancelled) {
          setLineError(err instanceof Error ? err.message : t("加载线路失败"));
        }
      } finally {
        if (!cancelled) {
          setLineLoading(false);
        }
      }
    };

    void fetchDetail();
    return () => {
      cancelled = true;
    };
  }, [lineId, fetchWithAuth]);

  const towerListPath = useMemo(() => {
    const params = new URLSearchParams();
    params.set("limit", String(TOWER_TABLE_DEFAULT_PAGE_SIZE));
    params.set("offset", String((towerPagination.current - 1) * towerPagination.pageSize));
    if (appliedTowerKeyword.trim()) {
      params.set("keyword", appliedTowerKeyword.trim());
    }
    if (towerTypeFilter) {
      params.set("tower_type", towerTypeFilter);
    }
    const query = params.toString();
    return `/api/v1/lines/${lineId}/towers${query ? `?${query}` : ""}`;
  }, [lineId, appliedTowerKeyword, towerTypeFilter, towerPagination]);

  const towersQuery = useQuery({
    queryKey: [towerListPath, searchNonce],
    enabled: !!user && canTowerRead && !!lineDetail && !lineLoading,
    queryFn: async () => {
      const response = await fetchWithAuth(towerListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
    // 查询键随 searchNonce 变化：保留上一份数据作占位，避免点击查询/切页时表格闪空
    placeholderData: (previousData) => previousData,
  });

  const towerDetailQuery = useQuery({
    queryKey: ["tower-detail", selectedTowerForDetail?.id],
    enabled: !!user && !!selectedTowerForDetail && towerDetailDrawerOpen && canTowerRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/towers/${selectedTowerForDetail?.id}/detail`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerDetailResponse;
    },
  });

  const towers = useMemo(() => towersQuery.data?.items ?? [], [towersQuery.data?.items]);

  const handleSearch = () => {
    // 输入框当前值同步为「已生效」关键词后，与分页/nonce 一起构成新 queryKey：
    // 输入过程不查询，只有点「查询」/回车才把输入值落进请求路径。
    setAppliedTowerKeyword(towerKeyword.trim());
    // 每次点击「查询」都强制触发一次接口请求：searchNonce 作为 queryKey 的一部分自增，
    // 保证即便关键词/塔型/分页均未变化（目标 key 若已被 react-query 缓存会短路不发请求）
    // 也会产生新 key 重新拉取；同时回到第 1 页。
    setTowerPagination({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE });
    setSearchNonce((n) => n + 1);
  };

  const refreshLines = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].startsWith("/api/v1/lines"),
    });
  }, [queryClient]);

  const refreshTowers = useCallback(async () => {
    await queryClient.invalidateQueries({
      predicate: (query) =>
        Array.isArray(query.queryKey)
        && typeof query.queryKey[0] === "string"
        && query.queryKey[0].includes("/towers"),
    });
  }, [queryClient]);

  const handleTempUpload = useCallback(
    (file: File) => {
      setSelectedFile(file);
      setTempFileId(null);
      setUploadProgress(0);
      setUploadError("");

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${getApiBaseUrl()}/api/v1/uploads/temp`);
      xhr.withCredentials = true;
      const token = getAccessToken();
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }
      xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
        if (!event.lengthComputable || event.total <= 0) {
          return;
        }
        const percent = Math.min(99, Math.max(0, Math.round((event.loaded / event.total) * 100)));
        setUploadProgress(percent);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          setUploadProgress(100);
          try {
            const payload = JSON.parse(xhr.responseText) as TempUploadResponse;
            setTempFileId(payload.temp_file_id);
          } catch {
            setUploadError(t("上传成功但响应解析失败，请重新选择文件"));
          }
          return;
        }
        let message = `HTTP ${xhr.status}`;
        try {
          const parsed = JSON.parse(xhr.responseText) as { detail?: string };
          if (parsed?.detail?.trim()) message = parsed.detail;
        } catch {
          // ignore
        }
        setUploadError(message);
      };
      xhr.onerror = () => setUploadError(t("网络异常，上传失败"));
      xhr.onabort = () => setUploadError(t("上传已取消"));

      const formData = new FormData();
      formData.append("file", file);
      xhr.send(formData);
    },
    [getAccessToken],
  );

  const closeImportModal = useCallback(() => {
    setImportModalOpen(false);
    setSelectedFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
  }, []);

  const openImportModal = useCallback(() => {
    setSelectedFile(null);
    setTempFileId(null);
    setUploadProgress(0);
    setUploadError("");
    setImportModalOpen(true);
  }, []);

  const openTowerDetailDrawer = useCallback((item: LineTowerSummary) => {
    setSelectedTowerForDetail(item);
    setTowerDetailDrawerOpen(true);
  }, []);

  const closeTowerDetailDrawer = useCallback(() => {
    setTowerDetailDrawerOpen(false);
    setSelectedTowerForDetail(null);
  }, []);

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!canTowerManage) {
        throw new Error(t("缺少 tower.manage 权限"));
      }
      if (!tempFileId) {
        throw new Error(t("文件尚未上传完成，请等待上传后再确认导入"));
      }
      const formData = new FormData();
      formData.append("temp_file_id", tempFileId);
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerImportResponse;
    },
    onSuccess: async (result) => {
      messageApi.success(
        `导入完成：新增 ${result.imported_count} 条，更新 ${result.updated_count} 条，跳过 ${result.skipped_count} 条`,
      );
      closeImportModal();
      await refreshLines();
      await refreshTowers();
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : t("导入失败"));
    },
  });

  const exportMutation = useMutation({
    mutationFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers/export`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      const blob = await response.blob();
      const contentDisposition = response.headers.get("Content-Disposition") || "";
      const matched = contentDisposition.match(/filename="([^"]+)"/i);
      const filename = matched?.[1] ?? "towers_export.csv";
      return { blob, filename };
    },
    onSuccess: ({ blob, filename }) => {
      const url = window.URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      window.URL.revokeObjectURL(url);
      messageApi.success(t("导出成功"));
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : t("导出失败"));
    },
  });

  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: t("序号"), dataIndex: "seq_no", width: 80 },
    {
      title: t("塔号"),
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: t("模型"), dataIndex: "tower_model", width: 180, render: (value: string | null) => value || "-" },
    { title: t("塔型"), dataIndex: "tower_type", width: 100, render: (value: string | null) => value || "-" },
    {
      title: t("坐标"),
      key: "geo",
      width: 200,
      render: (_: unknown, row) =>
        row.longitude !== null && row.latitude !== null
          ? `${row.longitude.toFixed(6)}, ${row.latitude.toFixed(6)}`
          : "-",
    },
    { title: t("接地电阻"), dataIndex: "ground_resistance_ohm", width: 100, render: (value: number | null) => value ?? "-" },
    { title: t("地闪密度"), dataIndex: "lightning_density", width: 100, render: (value: number | null) => value ?? "-" },
    {
      title: t("风险等级"),
      dataIndex: "risk_level",
      width: 110,
      render: (value: string | null) => <RiskLevelTag value={value} />,
    },
    {
      title: t("操作"),
      key: "actions",
      width: 120,
      fixed: "right" as const,
      render: (_: unknown, row) => (
        <Space size="small">
          {canTowerRead && (
            <Button size="small" onClick={() => openTowerDetailDrawer(row)}>
              查看详情
            </Button>
          )}
        </Space>
      ),
    },
  ];

  if (initializing || lineLoading) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (lineError || !lineDetail) {
    return (
      <div className="modo-page-card">
        <Card size="small" className="admin-power-line-detail-meta">
          <Space direction="vertical" size={12}>
            <Typography.Text type="danger">{lineError || t("加载线路失败")}</Typography.Text>
          </Space>
        </Card>
      </div>
    );
  }

  return (
    <div className="modo-page-card">
      <div className="admin-power-line-detail-meta mb-3 flex items-center justify-between gap-3">
        <Space size={8} wrap>
          <Typography.Text strong>{t("线路杆塔")}</Typography.Text>
          <Typography.Text type="secondary">
            {lineDetail ? `${lineDetail.code} / ${lineDetail.name}` : ""}
          </Typography.Text>
        </Space>
        <Space size={8} wrap>
          <Button size="small" icon={<ArrowLeftOutlined />}>
            <Link href="/admin/power-lines">{t("返回线路列表")}</Link>
          </Button>
        </Space>
      </div>

      <div className="admin-filter-bar">
        <Form layout="inline" className="flex flex-wrap items-center gap-2">
          <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              value={towerKeyword}
              allowClear
              onChange={(event) => setTowerKeyword(event.target.value)}
              placeholder={t("按塔号/模型筛选")}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item label={t("塔型")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Select
              value={towerTypeFilter}
              options={TOWER_TYPE_OPTIONS.map((opt) => ({ ...opt, label: t(opt.label) }))}
              onChange={(value) => setTowerTypeFilter(value)}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginRight: 0 }}>
            <Button
              htmlType="button"
              icon={<SearchOutlined />}
              onClick={handleSearch}
              className="admin-search-btn"
            >
              {t("查询")}
            </Button>
          </Form.Item>
          <Form.Item style={{ marginBottom: 0, marginRight: 0 }}>
            <Space size={8}>
              {canTowerManage && (
                <Button onClick={openImportModal}>
                  {t("导入")}
                </Button>
              )}
              {canTowerRead && (
                <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
                  导出
                </Button>
              )}
            </Space>
          </Form.Item>
        </Form>
      </div>

      <div className="relative mt-3 flex min-h-0 flex-1 flex-col">
        {towers.length === 0 && towersQuery.isFetching ? (
          // 首载/空结果且请求进行中：整区垂直+水平居中加载指示；已有数据时保留 Table 并
          // 由 antd 内置 loading 遮罩覆盖，接口返回前不清空现有行
          <div className="flex w-full flex-1 items-center justify-center">
            <Spin />
          </div>
        ) : towers.length === 0 ? (
          // 空结果：不渲染表格，参考线路管理列表页空态（Empty 占位）
          <div className="flex w-full flex-1 items-center justify-center">
            <Empty description={t("暂无杆塔数据")} image={Empty.PRESENTED_IMAGE_SIMPLE} />
          </div>
        ) : (
          <Table<LineTowerSummary>
            rowKey={(row) => row.id}
            columns={towerColumns}
            dataSource={towers}
            loading={towersQuery.isFetching}
            pagination={false}
            scroll={{ x: 1400 }}
          />
        )}
        {/* LP: 分页仅在表格有数据（total>0）时展示；空结果时不显示分页条 */}
        {(towersQuery.data?.total ?? 0) > 0 ? (
          <div className="admin-power-line-detail-pagination">
            <ModoPagination
              current={towerPagination.current}
              pageSize={towerPagination.pageSize}
              total={towersQuery.data?.total ?? 0}
              showSizeChanger
              showTotal={(total) => `共 ${total} 条`}
              onChange={(page, pageSize) => {
                setTowerPagination({ current: page, pageSize });
              }}
            />
          </div>
        ) : null}
      </div>

      <Modal
        title={t("导入杆塔数据")}
        open={importModalOpen}
        onCancel={() => {
          if (importMutation.isPending) return;
          closeImportModal();
        }}
        footer={null}
        width={520}
        destroyOnHidden
      >
        <div style={{ marginBottom: 16 }}>
          <Form layout="vertical">
            <Form.Item label={t("数据文件")} required>
              <Upload.Dragger
                accept=".csv,text/csv,.xlsx"
                showUploadList={false}
                beforeUpload={(file) => {
                  const maxMB = 50;
                  const allowedExts = ["csv", "xlsx"];
                  const ext = file.name.split(".").pop()?.toLowerCase() || "";
                  if (file.size > maxMB * 1024 * 1024) {
                    messageApi.error(`文件大小超过 ${maxMB}MB 限制，请压缩后重新上传`);
                    return Upload.LIST_IGNORE;
                  }
                  if (!allowedExts.includes(ext)) {
                    messageApi.error(`不支持的文件格式，仅支持 .${allowedExts.join("/")}`);
                    return Upload.LIST_IGNORE;
                  }
                  return true;
                }}
                customRequest={({ file }) => handleTempUpload(file as File)}
                onRemove={() => {
                  setSelectedFile(null);
                  setTempFileId(null);
                  setUploadProgress(0);
                  setUploadError("");
                }}
              >
                {selectedFile ? (
                  <>
                    <p className="ant-upload-text">{selectedFile.name}</p>
                    {uploadProgress < 100 ? (
                      <Progress percent={uploadProgress} size="small" style={{ marginTop: 8 }} />
                    ) : tempFileId ? (
                      <Typography.Text type="success">
                        <CheckCircleOutlined /> 上传完成，可以确认导入
                      </Typography.Text>
                    ) : (
                      <Typography.Text type="warning">{t("上传中…")}</Typography.Text>
                    )}
                  </>
                ) : (
                  <>
                    <p className="ant-upload-drag-icon">
                      <InboxOutlined />
                    </p>
                    <p className="ant-upload-text">{t("点击或拖拽文件到此区域上传")}</p>
                    <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                      支持 .csv / .xlsx 格式，单文件不超过 50MB
                    </p>
                    <Typography.Text type="secondary">
                      选择文件后立即上传到临时存储，确认导入后开始解析。
                    </Typography.Text>
                  </>
                )}
                {uploadError && (
                  <Typography.Text type="danger" style={{ display: "block", marginTop: 8 }}>
                    {uploadError}
                  </Typography.Text>
                )}
              </Upload.Dragger>
            </Form.Item>
          </Form>
        </div>
        <div style={{ textAlign: "right", borderTop: "1px solid var(--ant-color-border-secondary)", paddingTop: 16 }}>
          <Button
            type="primary"
            disabled={!tempFileId}
            loading={importMutation.isPending}
            onClick={() => importMutation.mutate()}
          >
            {t("确认导入")}
          </Button>
        </div>
      </Modal>

      <Drawer
        title={selectedTowerForDetail ? `${t("杆塔详情")} - ${selectedTowerForDetail.tower_no}` : t("杆塔详情")}
        open={towerDetailDrawerOpen}
        width={720}
        onClose={closeTowerDetailDrawer}
        destroyOnHidden
      >
        {towerDetailQuery.isPending ? (
          <div className="flex items-center justify-center py-16">
            <Typography.Text type="secondary">{t("加载中...")}</Typography.Text>
          </div>
        ) : towerDetailQuery.isError ? (
          <Alert
            showIcon
            type="error"
            message={t("加载杆塔详情失败")}
            description={towerDetailQuery.error instanceof Error ? towerDetailQuery.error.message : t("未知错误")}
          />
        ) : towerDetailQuery.data ? (
          (() => {
            const detail = towerDetailQuery.data;
            const tower = detail.tower;
            return (
              <Tabs
                items={[
                  {
                    key: "basic",
                    label: t("基本信息"),
                    children: (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label={t("塔号")}>{tower.tower_no}</Descriptions.Item>
                        <Descriptions.Item label={t("序号")}>{tower.seq_no}</Descriptions.Item>
                        <Descriptions.Item label={t("杆塔模型")}>{tower.tower_model ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("塔型")}>{tower.tower_type ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("线路电压等级")}>{tower.voltage_kv != null ? `${tower.voltage_kv} kV` : "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("风险等级")}><RiskLevelTag value={tower.risk_level} /></Descriptions.Item>
                        <Descriptions.Item label={t("经度")}>{tower.longitude != null ? tower.longitude : "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("纬度")}>{tower.latitude != null ? tower.latitude : "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("海拔(m)")}>{tower.altitude_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("地形")}>{tower.terrain ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("接地电阻(Ω)")}>{tower.ground_resistance_ohm ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("地闪密度")}>{tower.lightning_density ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("小号侧档距(m)")}>{tower.span_small_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("大号侧档距(m)")}>{tower.span_large_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("地面倾角1")}>{tower.slope_1 ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("地面倾角2")}>{tower.slope_2 ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("直线/耐张")}>{tower.structure_kind ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("绝缘子串长度(mm)")}>{tower.insulator_length_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("杆塔呼高(m)")}>{tower.call_height_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("避雷线高度(m)")}>{tower.shield_wire_height_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("左避雷线中距(m)")}>{tower.lightning_wire_left_mid_distance_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("右避雷线中距(m)")}>{tower.lightning_wire_right_mid_distance_m ?? "-"}</Descriptions.Item>
                      </Descriptions>
                    ),
                  },
                  {
                    key: "circuits",
                    label: t("回路几何"),
                    children: detail.circuits.length === 0 ? (
                      <Empty description={t("暂无回路数据")} />
                    ) : (
                      <Table<TowerCircuitSummary>
                        rowKey={(row) => String(row.circuit_no)}
                        dataSource={detail.circuits}
                        size="small"
                        pagination={false}
                        columns={[
                          { title: t("回路编号"), dataIndex: "circuit_no", width: 80 },
                          { title: t("相序"), dataIndex: "phase_sequence", render: (value: string | null) => value || "-" },
                          { title: t("上相中距(m)"), dataIndex: "spacing_upper_m", render: (value: number | null) => value ?? "-" },
                          { title: t("中相中距(m)"), dataIndex: "spacing_middle_m", render: (value: number | null) => value ?? "-" },
                          { title: t("下相中距(m)"), dataIndex: "spacing_lower_m", render: (value: number | null) => value ?? "-" },
                          { title: t("上相高度(m)"), dataIndex: "height_upper_m", render: (value: number | null) => value ?? "-" },
                          { title: t("中相高度(m)"), dataIndex: "height_middle_m", render: (value: number | null) => value ?? "-" },
                          { title: t("下相高度(m)"), dataIndex: "height_lower_m", render: (value: number | null) => value ?? "-" },
                        ]}
                      />
                    ),
                  },
                  {
                    key: "lightning",
                    label: t("防雷参数"),
                    children: detail.lightning_result ? (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label={t("反击耐雷水平(kA)")}>{detail.lightning_result.counterstroke_withstand_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("反击跳闸率")}>{detail.lightning_result.counterstroke_trip_rate ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("绕击耐雷水平(kA)")}>{detail.lightning_result.shielding_withstand_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("绕击跳闸率")}>{detail.lightning_result.shielding_trip_rate ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("电角度(°)")}>{detail.lightning_result.angle_deg ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("风险等级")}><RiskLevelTag value={detail.lightning_result.risk_level} /></Descriptions.Item>
                        <Descriptions.Item label={t("雷电流幅值 a(kA)")}>{detail.lightning_result.current_a_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label={t("雷电流幅值 b(kA)")}>{detail.lightning_result.current_b_ka ?? "-"}</Descriptions.Item>
                      </Descriptions>
                    ) : (
                      <Empty description={t("暂无防雷参数")} />
                    ),
                  },
                  {
                    key: "analysis",
                    label: t("分析建议"),
                    children: (
                      <Space direction="vertical" size={16} className="w-full">
                        <Descriptions bordered size="small" column={1}>
                          <Descriptions.Item label={t("原因分析")}>{detail.analysis?.cause_analysis ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("措施推荐")}>{detail.analysis?.mitigation_recommendation ?? "-"}</Descriptions.Item>
                        </Descriptions>
                        <Descriptions bordered size="small" column={3}>
                          <Descriptions.Item label={t("直线/耐张")}>{tower.structure_kind ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("绕击/反击模式")}>{tower.stroke_mode ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("雷电流波形")}>{tower.current_type ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("雷电流幅值 a")}>{tower.current_a ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("雷电流幅值 b")}>{tower.current_b ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("绝缘子串长度(mm)")}>{tower.insulator_length_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("杆塔呼高(m)")}>{tower.call_height_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("避雷线高度(m)")}>{tower.shield_wire_height_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("左保护角(°)")}>{tower.protection_angle_left_deg ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("右保护角(°)")}>{tower.protection_angle_right_deg ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label={t("A相避雷器")}>{detail.arrester?.A ? "是" : "否"}</Descriptions.Item>
                          <Descriptions.Item label={t("B相避雷器")}>{detail.arrester?.B ? "是" : "否"}</Descriptions.Item>
                          <Descriptions.Item label={t("C相避雷器")}>{detail.arrester?.C ? "是" : "否"}</Descriptions.Item>
                        </Descriptions>
                      </Space>
                    ),
                  },
                ]}
              />
            );
          })()
        ) : null}
      </Drawer>
    </div>
  );
}
