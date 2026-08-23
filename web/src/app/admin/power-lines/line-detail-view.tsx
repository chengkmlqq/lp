"use client";

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
  Table,
  Tabs,
  Tag,
  Typography,
  Upload,
} from "antd";
import { CheckCircleOutlined, SearchOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { useAuth } from "@/components/auth-provider";
import { useToastFeedback } from "@/hooks/use-toast-feedback";
import { useTopicSubscription } from "@/hooks/use-topic-subscription";
import { getApiBaseUrl, readApiError } from "@/lib/api";
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
const TOWER_MAP_QUERY_LIMIT = 500;

type AdminPowerLinesDetailViewProps = {
  lineId: string;
  canTowerRead: boolean;
};

export function AdminPowerLinesDetailView({ lineId, canTowerRead }: AdminPowerLinesDetailViewProps) {
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();
  const queryClient = useQueryClient();
  const { message: messageApi } = App.useApp();

  const canTowerReadLocal = canTowerRead || hasPermission("tower.read") || hasPermission("tower.manage");
  const canTowerManage = hasPermission("tower.manage");

  const [lineError, setLineError] = useState("");
  const [lineDetail, setLineDetail] = useState<{ code: string; name: string } | null>(null);
  const [lineLoading, setLineLoading] = useState(true);
  const [towerKeyword, setTowerKeyword] = useState("");
  const [towerTypeFilter, setTowerTypeFilter] = useState("");
  const [towerPagination, setTowerPagination] = useState({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE });
  const [importModalOpen, setImportModalOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [tempFileId, setTempFileId] = useState<string | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState("");
  const [towerDetailDrawerOpen, setTowerDetailDrawerOpen] = useState(false);
  const [selectedTowerForDetail, setSelectedTowerForDetail] = useState<LineTowerSummary | null>(null);
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const [tableScrollY, setTableScrollY] = useState(180);

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
          setLineError(err instanceof Error ? err.message : "加载线路失败");
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
    if (towerKeyword.trim()) {
      params.set("keyword", towerKeyword.trim());
    }
    if (towerTypeFilter) {
      params.set("tower_type", towerTypeFilter);
    }
    const query = params.toString();
    return `/api/v1/lines/${lineId}/towers${query ? `?${query}` : ""}`;
  }, [lineId, towerKeyword, towerTypeFilter, towerPagination]);

  const towersQuery = useQuery({
    queryKey: [towerListPath],
    enabled: !!user && canTowerReadLocal && !lineLoading && !!lineDetail,
    queryFn: async () => {
      const response = await fetchWithAuth(towerListPath);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const towerDetailQuery = useQuery({
    queryKey: ["tower-detail", selectedTowerForDetail?.id],
    enabled: !!user && !!selectedTowerForDetail && towerDetailDrawerOpen && canTowerReadLocal,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/towers/${selectedTowerForDetail?.id}/detail`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as TowerDetailResponse;
    },
  });

  const towers = useMemo(() => towersQuery.data?.items ?? [], [towersQuery.data?.items]);

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

  useTopicSubscription("admin.power-lines", useCallback(() => {
    void refreshLines();
  }, [refreshLines]));

  useToastFeedback({
    errorMessage: towersQuery.error instanceof Error ? towersQuery.error.message : "",
    successMessage: "",
    clearError: () => {},
    clearSuccess: () => {},
  });

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
            setUploadError("上传成功但响应解析失败，请重新选择文件");
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
      xhr.onerror = () => setUploadError("网络异常，上传失败");
      xhr.onabort = () => setUploadError("上传已取消");

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

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const anchorHeight = anchor.getBoundingClientRect().height;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? 56;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? 64;
    const nextHeight = Math.floor(anchorHeight - headerHeight - paginationHeight - 8);
    const clampedHeight = Math.max(180, nextHeight);
    setTableScrollY((previous) => (Math.abs(previous - clampedHeight) <= 1 ? previous : clampedHeight));
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    window.requestAnimationFrame(updateTableScrollY);
  }, [towers.length, towersQuery.isFetching, updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const onViewportChange = () => {
      window.requestAnimationFrame(updateTableScrollY);
    };
    window.addEventListener("resize", onViewportChange);
    return () => window.removeEventListener("resize", onViewportChange);
  }, [updateTableScrollY]);

  useEffect(() => {
    if (typeof window === "undefined" || typeof ResizeObserver === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(updateTableScrollY);
    });
    resizeObserver.observe(anchor);
    return () => resizeObserver.disconnect();
  }, [updateTableScrollY]);

  const importMutation = useMutation({
    mutationFn: async () => {
      if (!canTowerManage) {
        throw new Error("缺少 tower.manage 权限");
      }
      if (!tempFileId) {
        throw new Error("文件尚未上传完成，请等待上传后再确认导入");
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
      messageApi.error(candidate instanceof Error ? candidate.message : "导入失败");
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
      messageApi.success("导出成功");
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "导出失败");
    },
  });

  const towerColumns: ColumnsType<LineTowerSummary> = [
    { title: "序号", dataIndex: "seq_no", width: 80 },
    {
      title: "塔号",
      dataIndex: "tower_no",
      width: 120,
      render: (value: string) => <Typography.Text code>{value}</Typography.Text>,
    },
    { title: "模型", dataIndex: "tower_model", width: 180, render: (value: string | null) => value || "-" },
    { title: "塔型", dataIndex: "tower_type", width: 100, render: (value: string | null) => value || "-" },
    {
      title: "坐标",
      key: "geo",
      width: 200,
      render: (_: unknown, row) =>
        row.longitude !== null && row.latitude !== null
          ? `${row.longitude.toFixed(6)}, ${row.latitude.toFixed(6)}`
          : "-",
    },
    { title: "接地电阻", dataIndex: "ground_resistance_ohm", width: 100, render: (value: number | null) => value ?? "-" },
    { title: "地闪密度", dataIndex: "lightning_density", width: 100, render: (value: number | null) => value ?? "-" },
    {
      title: "风险等级",
      dataIndex: "risk_level",
      width: 100,
      render: (value: string | null) => {
        if (!value) return "-";
        const riskLevel = value.trim();
        let color = "default";
        if (riskLevel === "1") {
          color = "green";
        } else if (riskLevel === "2") {
          color = "orange";
        } else if (riskLevel === "3") {
          color = "red";
        }
        return <Tag color={color}>{value}</Tag>;
      },
    },
    {
      title: "操作",
      key: "actions",
      width: 120,
      fixed: "right" as const,
      render: (_: unknown, row) => (
        <Space size="small">
          {canTowerReadLocal && (
            <Button size="small" onClick={() => openTowerDetailDrawer(row)}>
              详情
            </Button>
          )}
        </Space>
      ),
    },
  ];

  if (initializing || lineLoading) {
    return <AdminPageLoading tip="加载中..." minHeightClassName="min-h-[280px]" />;
  }

  if (lineError || !lineDetail) {
    return (
      <div className="flex flex-1 flex-col p-4">
        <Card size="small" className="admin-power-line-detail-meta">
          <Space direction="vertical" size={12}>
            <Typography.Text type="danger">{lineError || "加载线路失败"}</Typography.Text>
          </Space>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col p-4">

      <div className="admin-filter-bar mt-3">
        <Form layout="inline" className="flex flex-wrap items-center gap-2">
          <Form.Item label="关键词" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              value={towerKeyword}
              allowClear
              onChange={(event) => setTowerKeyword(event.target.value)}
              placeholder="按塔号/模型筛选"
            />
          </Form.Item>
          <Form.Item label="塔型" className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Select
              value={towerTypeFilter}
              options={[...TOWER_TYPE_OPTIONS]}
              onChange={(value) => setTowerTypeFilter(value)}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              htmlType="button"
              icon={<SearchOutlined />}
              onClick={() =>
                setTowerPagination({ current: 1, pageSize: TOWER_TABLE_DEFAULT_PAGE_SIZE })
              }
              className="admin-search-btn"
            >
              查询
            </Button>
          </Form.Item>
          {canTowerManage && (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button onClick={openImportModal}>导入 CSV</Button>
            </Form.Item>
          )}
          {canTowerRead && (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
                导出 CSV
              </Button>
            </Form.Item>
          )}
        </Form>
      </div>

      <div
        ref={tableScrollAnchorRef}
        className="admin-power-line-detail-table-anchor"
        style={{ "--admin-power-line-detail-table-body-min-height": `${tableScrollY}px` } as CSSProperties}
      >
        <Table<LineTowerSummary>
          rowKey={(row) => row.id}
          columns={towerColumns}
          dataSource={towers}
          loading={towersQuery.isFetching}
          pagination={{
            current: towerPagination.current,
            pageSize: towerPagination.pageSize,
            total: towersQuery.data?.total ?? 0,
            showSizeChanger: true,
            showTotal: (total) => `共 ${total} 条`,
            hideOnSinglePage: false,
            onChange: (page, pageSize) => {
              setTowerPagination({ current: page, pageSize });
            },
          }}
          scroll={{ x: 1400, y: tableScrollY }}
        />
      </div>

      <Modal
        title="导入杆塔数据"
        open={importModalOpen}
        onCancel={() => {
          if (importMutation.isPending) return;
          closeImportModal();
        }}
        footer={null}
        width={520}
        destroyOnClose
      >
        <div style={{ marginBottom: 16 }}>
          <Form layout="vertical">
            <Form.Item label="数据文件" required>
              <Upload.Dragger
                accept=".csv,text/csv"
                showUploadList={false}
                beforeUpload={(file) => {
                  const maxMB = 50;
                  const allowedExts = ["csv"];
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
                      <Typography.Text type="warning">上传中…</Typography.Text>
                    )}
                  </>
                ) : (
                  <>
                    <p className="ant-upload-hint" style={{ color: "#999", marginTop: 8 }}>
                      点击或拖拽文件到此区域上传
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
        <div style={{ textAlign: "right", borderTop: "1px solid #f0f0f0", paddingTop: 16 }}>
          <Button
            type="primary"
            disabled={!tempFileId}
            loading={importMutation.isPending}
            onClick={() => importMutation.mutate()}
          >
            确认导入
          </Button>
        </div>
      </Modal>

      <Drawer
        title={selectedTowerForDetail ? `杆塔详情 - ${selectedTowerForDetail.tower_no}` : "杆塔详情"}
        open={towerDetailDrawerOpen}
        width={720}
        onClose={closeTowerDetailDrawer}
        destroyOnClose
      >
        {towerDetailQuery.isPending ? (
          <div className="flex items-center justify-center py-16">
            <Typography.Text type="secondary">加载中...</Typography.Text>
          </div>
        ) : towerDetailQuery.isError ? (
          <Alert
            showIcon
            type="error"
            message="加载杆塔详情失败"
            description={towerDetailQuery.error instanceof Error ? towerDetailQuery.error.message : "未知错误"}
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
                    label: "基本信息",
                    children: (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="塔号">{tower.tower_no}</Descriptions.Item>
                        <Descriptions.Item label="序号">{tower.seq_no}</Descriptions.Item>
                        <Descriptions.Item label="杆塔模型">{tower.tower_model ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="塔型">{tower.tower_type ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="线路电压等级">{tower.voltage_kv != null ? `${tower.voltage_kv} kV` : "-"}</Descriptions.Item>
                        <Descriptions.Item label="风险等级">{tower.risk_level ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="经度">{tower.longitude != null ? tower.longitude : "-"}</Descriptions.Item>
                        <Descriptions.Item label="纬度">{tower.latitude != null ? tower.latitude : "-"}</Descriptions.Item>
                        <Descriptions.Item label="海拔(m)">{tower.altitude_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="地形">{tower.terrain ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="接地电阻(Ω)">{tower.ground_resistance_ohm ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="地闪密度">{tower.lightning_density ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="小号侧档距(m)">{tower.span_small_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="大号侧档距(m)">{tower.span_large_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="地面倾角1">{tower.slope_1 ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="地面倾角2">{tower.slope_2 ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="直线/耐张">{tower.structure_kind ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="绝缘子串长度(mm)">{tower.insulator_length_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="杆塔呼高(m)">{tower.call_height_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="避雷线高度(m)">{tower.shield_wire_height_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="左避雷线中距(m)">{tower.lightning_wire_left_mid_distance_m ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="右避雷线中距(m)">{tower.lightning_wire_right_mid_distance_m ?? "-"}</Descriptions.Item>
                      </Descriptions>
                    ),
                  },
                  {
                    key: "circuits",
                    label: "回路几何",
                    children: detail.circuits.length === 0 ? (
                      <Empty description="暂无回路数据" />
                    ) : (
                      <Table<TowerCircuitSummary>
                        rowKey={(row) => String(row.circuit_no)}
                        dataSource={detail.circuits}
                        size="small"
                        pagination={false}
                        columns={[
                          { title: "回路编号", dataIndex: "circuit_no", width: 80 },
                          { title: "相序", dataIndex: "phase_sequence", render: (value: string | null) => value || "-" },
                          { title: "上相中距(m)", dataIndex: "spacing_upper_m", render: (value: number | null) => value ?? "-" },
                          { title: "中相中距(m)", dataIndex: "spacing_middle_m", render: (value: number | null) => value ?? "-" },
                          { title: "下相中距(m)", dataIndex: "spacing_lower_m", render: (value: number | null) => value ?? "-" },
                          { title: "上相高度(m)", dataIndex: "height_upper_m", render: (value: number | null) => value ?? "-" },
                          { title: "中相高度(m)", dataIndex: "height_middle_m", render: (value: number | null) => value ?? "-" },
                          { title: "下相高度(m)", dataIndex: "height_lower_m", render: (value: number | null) => value ?? "-" },
                        ]}
                      />
                    ),
                  },
                  {
                    key: "lightning",
                    label: "防雷参数",
                    children: detail.lightning_result ? (
                      <Descriptions bordered size="small" column={2}>
                        <Descriptions.Item label="反击耐雷水平(kA)">{detail.lightning_result.counterstroke_withstand_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="反击跳闸率">{detail.lightning_result.counterstroke_trip_rate ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="绕击耐雷水平(kA)">{detail.lightning_result.shielding_withstand_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="绕击跳闸率">{detail.lightning_result.shielding_trip_rate ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="电角度(°)">{detail.lightning_result.angle_deg ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="风险等级">{detail.lightning_result.risk_level ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="雷电流幅值 a(kA)">{detail.lightning_result.current_a_ka ?? "-"}</Descriptions.Item>
                        <Descriptions.Item label="雷电流幅值 b(kA)">{detail.lightning_result.current_b_ka ?? "-"}</Descriptions.Item>
                      </Descriptions>
                    ) : (
                      <Empty description="暂无防雷参数" />
                    ),
                  },
                  {
                    key: "analysis",
                    label: "分析建议",
                    children: (
                      <Space direction="vertical" size={16} className="w-full">
                        <Descriptions bordered size="small" column={1}>
                          <Descriptions.Item label="原因分析">{detail.analysis?.cause_analysis ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="措施推荐">{detail.analysis?.mitigation_recommendation ?? "-"}</Descriptions.Item>
                        </Descriptions>
                        <Descriptions bordered size="small" column={3}>
                          <Descriptions.Item label="直线/耐张">{tower.structure_kind ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="绕击/反击模式">{tower.stroke_mode ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="雷电流波形">{tower.current_type ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="雷电流幅值 a">{tower.current_a ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="雷电流幅值 b">{tower.current_b ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="绝缘子串长度(mm)">{tower.insulator_length_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="杆塔呼高(m)">{tower.call_height_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="避雷线高度(m)">{tower.shield_wire_height_m ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="左保护角(°)">{tower.protection_angle_left_deg ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="右保护角(°)">{tower.protection_angle_right_deg ?? "-"}</Descriptions.Item>
                          <Descriptions.Item label="A相避雷器">{detail.arrester?.A ? "是" : "否"}</Descriptions.Item>
                          <Descriptions.Item label="B相避雷器">{detail.arrester?.B ? "是" : "否"}</Descriptions.Item>
                          <Descriptions.Item label="C相避雷器">{detail.arrester?.C ? "是" : "否"}</Descriptions.Item>
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
