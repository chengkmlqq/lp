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
  Pagination,
  Progress,
  Row,
  Col,
  Select,
  Space,
  Spin,
  Table,
  Typography,
  Upload,
  Dropdown,
  type MenuProps,
} from "antd";
import { ApartmentOutlined, CheckCircleOutlined, InboxOutlined, SearchOutlined, MoreOutlined } from "@ant-design/icons";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";

import { useI18n } from "@/lib/i18n";
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

const TOWER_TABLE_DEFAULT_PAGE_SIZE = 20;
const TOWER_MAP_QUERY_LIMIT = 500;

type AdminPowerLinesDetailViewProps = {
  lineId: string;
  canTowerRead: boolean;
};

export function AdminPowerLinesDetailView({ lineId, canTowerRead }: AdminPowerLinesDetailViewProps) {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();
  const queryClient = useQueryClient();
  const { message: messageApi } = App.useApp();

  // 与后端 /lines/{id}/towers 契约一致：具备 line.read/line.manage 亦可读取杆塔列表
  const canTowerReadLocal =
    canTowerRead ||
    hasPermission("tower.read") ||
    hasPermission("tower.manage") ||
    hasPermission("line.read") ||
    hasPermission("line.manage");
  const canTowerManage = hasPermission("tower.manage");

  const [lineError, setLineError] = useState("");
  const [lineDetail, setLineDetail] = useState<{ code: string; name: string } | null>(null);
  const [lineLoading, setLineLoading] = useState(true);
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
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editingTower, setEditingTower] = useState<LineTowerSummary | null>(null);
  const [towerForm, setTowerForm] = useState<{
    tower_no?: string;
    tower_model?: string;
    tower_type?: string;
    longitude?: number | null;
    latitude?: number | null;
    altitude_m?: number | null;
    ground_resistance_ohm?: number | null;
    lightning_density?: number | null;
    risk_level?: string;
    span_small_m?: number | null;
    span_large_m?: number | null;
    slope_1?: number | null;
    slope_2?: number | null;
  }>({});
  const tableScrollAnchorRef = useRef<HTMLDivElement | null>(null);
  const towerDetailScrollRef = useRef<HTMLDivElement | null>(null);
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
    enabled: !!user && canTowerReadLocal && !lineLoading && !!lineDetail,
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

  const openEditTowerModal = useCallback((item: LineTowerSummary) => {
    setEditingTower(item);
    setTowerForm({
      tower_no: item.tower_no ?? "",
      tower_model: item.tower_model ?? "",
      tower_type: item.tower_type ?? "",
      longitude: item.longitude,
      latitude: item.latitude,
      altitude_m: item.altitude_m,
      ground_resistance_ohm: item.ground_resistance_ohm,
      lightning_density: item.lightning_density,
      risk_level: item.risk_level ?? "",
      span_small_m: item.span_small_m,
      span_large_m: item.span_large_m,
      slope_1: item.slope_1,
      slope_2: item.slope_2,
    });
    setEditModalOpen(true);
  }, []);

  const setFormValue = useCallback(
    (key: keyof typeof towerForm, value: string | number | null) => {
      setTowerForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const updateTowerMutation = useMutation({
    mutationFn: async () => {
      if (!editingTower) {
        throw new Error("未选择待编辑杆塔");
      }
      if (!canTowerManage) {
        throw new Error("缺少 tower.manage 权限");
      }
      const payload: Record<string, unknown> = {};
      if (towerForm.tower_no !== undefined) payload.tower_no = towerForm.tower_no;
      if (towerForm.tower_model !== undefined) payload.tower_model = towerForm.tower_model || null;
      if (towerForm.tower_type !== undefined) payload.tower_type = towerForm.tower_type || null;
      if (towerForm.longitude !== undefined) payload.longitude = towerForm.longitude;
      if (towerForm.latitude !== undefined) payload.latitude = towerForm.latitude;
      if (towerForm.altitude_m !== undefined) payload.altitude_m = towerForm.altitude_m;
      if (towerForm.ground_resistance_ohm !== undefined) payload.ground_resistance_ohm = towerForm.ground_resistance_ohm;
      if (towerForm.lightning_density !== undefined) payload.lightning_density = towerForm.lightning_density;
      if (towerForm.risk_level !== undefined) payload.risk_level = towerForm.risk_level || null;
      if (towerForm.span_small_m !== undefined) payload.span_small_m = towerForm.span_small_m;
      if (towerForm.span_large_m !== undefined) payload.span_large_m = towerForm.span_large_m;
      if (towerForm.slope_1 !== undefined) payload.slope_1 = towerForm.slope_1;
      if (towerForm.slope_2 !== undefined) payload.slope_2 = towerForm.slope_2;

      const response = await fetchWithAuth(`/api/v1/lines/towers/${editingTower.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return response.json();
    },
    onSuccess: async () => {
      messageApi.success("杆塔已更新");
      setEditModalOpen(false);
      setEditingTower(null);
      await refreshTowers();
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "更新失败");
    },
  });

  const deleteTowerMutation = useMutation({
    mutationFn: async (item: LineTowerSummary) => {
      if (!canTowerManage) {
        throw new Error("缺少 tower.manage 权限");
      }
      const response = await fetchWithAuth(`/api/v1/lines/towers/${item.id}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return response.json();
    },
    onSuccess: async () => {
      messageApi.success("杆塔已删除");
      await refreshTowers();
    },
    onError: (candidate) => {
      messageApi.error(candidate instanceof Error ? candidate.message : "删除失败");
    },
  });

  const updateTableScrollY = useCallback(() => {
    if (typeof window === "undefined") {
      return;
    }
    const anchor = tableScrollAnchorRef.current;
    if (!anchor) {
      return;
    }
    // 表体高度推导（2026-09-12 修复）：
    // 1) 不用 anchor 自身高度反推（会被表体 min-height 撑大 → 正反馈，翻页逐次 +12px）
    // 2) 不用 window.innerHeight（漏掉 tab 面板边界与根容器 padding → 详情页整体溢出 18px，
    //    出现「始终存在」的纵向滚动条）
    // 3) 以可视滚动容器（tab 面板）padding-box 底边为界，再扣除根容器底部 padding
    const anchorTop = anchor.getBoundingClientRect().top;
    const pane = anchor.closest<HTMLElement>(".ant-tabs-tabpane") ?? document.documentElement;
    const parent = anchor.parentElement;
    const paneRect = pane.getBoundingClientRect();
    const panePadBottom = Number.parseFloat(getComputedStyle(pane).paddingBottom) || 0;
    const parentPadBottom =
      parent && parent !== pane ? Number.parseFloat(getComputedStyle(parent).paddingBottom) || 0 : 0;
    const tableHeader = anchor.querySelector<HTMLElement>(".ant-table-header");
    const tablePagination = anchor.querySelector<HTMLElement>(".ant-table-pagination");
    const headerHeight = tableHeader?.getBoundingClientRect().height ?? 56;
    const paginationHeight = tablePagination?.getBoundingClientRect().height ?? 32;
    // 分页器上方 margin 16px + 4px 余量，确保容器内不产生滚动条
    const bottomLimit = paneRect.bottom - panePadBottom - parentPadBottom - 4;
    const available = bottomLimit - anchorTop;
    const nextHeight = Math.floor(available - headerHeight - paginationHeight - 16);
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
      width: 180,
      fixed: "right" as const,
      render: (_: unknown, row) => {
        const menuItems: MenuProps["items"] = [
          ...(canTowerManage
            ? [
                {
                  key: "delete",
                  label: t("删除"),
                  danger: true,
                  onClick: () => {
                    Modal.confirm({
                      title: t("确认删除该杆塔？"),
                      content: `将删除杆塔 ${row.tower_no}，此操作不可恢复。`,
                      okText: t("确认删除"),
                      cancelText: t("取消"),
                      okButtonProps: { danger: true },
                      onOk: () => deleteTowerMutation.mutate(row),
                    });
                  },
                },
              ]
            : []),
        ];

        return (
          <Space size="small">
            {canTowerReadLocal && (
              <Button size="small" onClick={() => openTowerDetailDrawer(row)}>
                详情
              </Button>
            )}
            {canTowerManage && (
              <Button size="small" onClick={() => openEditTowerModal(row)}>
                编辑
              </Button>
            )}
            {menuItems.length > 0 && (
              <Dropdown menu={{ items: menuItems }} trigger={["click"]}>
                <Button size="small" icon={<MoreOutlined />} />
              </Dropdown>
            )}
          </Space>
        );
      },
    },
  ];

  if (initializing || lineLoading) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  if (lineError || !lineDetail) {
    return (
      <div className="flex flex-1 flex-col p-6">
        <Card size="small" className="admin-power-line-detail-meta">
          <Space direction="vertical" size={12}>
            <Typography.Text type="danger">{lineError || "加载线路失败"}</Typography.Text>
          </Space>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col p-6">
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
            <Input
              value={towerTypeFilter}
              onChange={(event) => setTowerTypeFilter(event.target.value)}
              allowClear
              placeholder={t("塔型编码（如 d500shangzi）")}
              onPressEnter={handleSearch}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button
              htmlType="button"
              icon={<SearchOutlined />}
              onClick={handleSearch}
              className="admin-search-btn"
            >
              {t("查询")}
            </Button>
          </Form.Item>
          {canTowerManage && (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button onClick={openImportModal}>
                导入
              </Button>
            </Form.Item>
          )}
          {canTowerRead && (
            <Form.Item style={{ marginBottom: 0 }}>
              <Button onClick={() => exportMutation.mutate()} loading={exportMutation.isPending}>
                导出
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
            scroll={{ x: 1400, y: tableScrollY }}
          />
        )}
        {/* LP: 分页仅在表格有数据（total>0）时展示；空结果时不显示分页条 */}
        {(towersQuery.data?.total ?? 0) > 0 ? (
          <div className="admin-power-line-detail-pagination">
            <Pagination
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

      <Modal
        title={editingTower ? `编辑杆塔 - ${editingTower.tower_no}` : "编辑杆塔"}
        open={editModalOpen}
        onCancel={() => {
          if (updateTowerMutation.isPending) return;
          setEditModalOpen(false);
          setEditingTower(null);
        }}
        footer={null}
        width={720}
        destroyOnHidden
      >
        <Form layout="vertical">
          <Row gutter={12}>
            <Col xs={24} md={12}>
              <Form.Item label={t("塔号")} required>
                <Input value={towerForm.tower_no} onChange={(e) => setFormValue("tower_no", e.target.value)} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("塔型")}>
                <Input
                  value={towerForm.tower_type ?? ""}
                  allowClear
                  placeholder={t("塔型编码（如 d500shangzi/s500guxing）")}
                  onChange={(event) => setFormValue("tower_type", event.target.value)}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("模型")}>
                <Input value={towerForm.tower_model} onChange={(e) => setFormValue("tower_model", e.target.value)} />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("风险等级")}>
                <Select
                  value={towerForm.risk_level}
                  allowClear
                  options={[
                    { value: "1", label: "1" },
                    { value: "2", label: "2" },
                    { value: "3", label: "3" },
                  ]}
                  onChange={(value) => setFormValue("risk_level", value)}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("经度")}>
                <Input
                  type="number"
                  value={towerForm.longitude ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("longitude", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("纬度")}>
                <Input
                  type="number"
                  value={towerForm.latitude ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("latitude", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("海拔(m)")}>
                <Input
                  type="number"
                  value={towerForm.altitude_m ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("altitude_m", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("接地电阻(Ω)")}>
                <Input
                  type="number"
                  value={towerForm.ground_resistance_ohm ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("ground_resistance_ohm", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("地闪密度")}>
                <Input
                  type="number"
                  value={towerForm.lightning_density ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("lightning_density", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("小号侧档距(m)")}>
                <Input
                  type="number"
                  value={towerForm.span_small_m ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("span_small_m", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("大号侧档距(m)")}>
                <Input
                  type="number"
                  value={towerForm.span_large_m ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("span_large_m", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("地面倾角1")}>
                <Input
                  type="number"
                  value={towerForm.slope_1 ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("slope_1", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
            <Col xs={24} md={12}>
              <Form.Item label={t("地面倾角2")}>
                <Input
                  type="number"
                  value={towerForm.slope_2 ?? ""}
                  onChange={(e) => {
                    const value = e.target.value.trim() === "" ? null : Number(e.target.value);
                    setFormValue("slope_2", Number.isNaN(value as number) ? null : value);
                  }}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
        <div style={{ textAlign: "right", borderTop: "1px solid var(--ant-color-border-secondary)", paddingTop: 16 }}>
          <Space>
            <Button
              onClick={() => {
                setEditModalOpen(false);
                setEditingTower(null);
              }}
            >
              取消
            </Button>
            <Button
              type="primary"
              loading={updateTowerMutation.isPending}
              onClick={() => updateTowerMutation.mutate()}
            >
              保存
            </Button>
          </Space>
        </div>
      </Modal>

      <Drawer
        title={selectedTowerForDetail ? `杆塔详情 - ${selectedTowerForDetail.tower_no}` : "杆塔详情"}
        open={towerDetailDrawerOpen}
        width={880}
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
            description={towerDetailQuery.error instanceof Error ? towerDetailQuery.error.message : "未知错误"}
          />
        ) : towerDetailQuery.data ? (
          (() => {
            const detail = towerDetailQuery.data;
            const tower = detail.tower;
            return (
              (() => {
                const towerDetailSections = [
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
                ];

                return (
                  <div ref={towerDetailScrollRef} className="admin-tower-detail-content">
                      {towerDetailSections.map((section) => (
                        <section key={section.key} id={`tower-detail-${section.key}`} className="admin-tower-detail-section">
                          <Typography.Title level={5} style={{ margin: 0 }}>
                            {section.label}
                          </Typography.Title>
                          <div className="mt-3">{section.children}</div>
                        </section>
                      ))}
                  </div>
                );
              })()
            );
          })()
        ) : null}
      </Drawer>
    </div>
  );
}
