"use client";

import { Alert, Button, Empty, Input, Segmented, Select, Space, Spin, Table, Tooltip, Typography } from "antd";
import { AppstoreOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState, Fragment } from "react";
import type { ColumnsType } from "antd/es/table";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { AtpAssetSummary } from "@/types/auth";
import { resolveFormatMeta } from "./atp-model-format-tag";

/** 列表接口单页上限 200（后端 Query le=200），全量分页抓取 */
const PAGE_LIMIT = 200;
const MAX_FETCH = 2000;

type StatusFilter = "all" | "active" | "inactive";
type FormatFilter = "all" | "insert" | "legacy" | "unknown";

interface AtpModelOverviewTabProps {
  /** 点清单行「详情」时切到该模型的详情 Tab（父页传入） */
  onOpenDetail?: (asset: AtpAssetSummary) => void;
}

function dateOnly(value: string | null | undefined): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** 「生效」口径：生效开关打开 + 资产可用 + 未下线（三者缺一都不能被仿真定位） */
function isEffective(asset: AtpAssetSummary): boolean {
  return Boolean(asset.is_active) && asset.status === "enabled" && asset.is_published !== false;
}

/** 形态分档：新版 insert / 旧版 legacy / 待检测（没有预检报告）/ 其他 */
function formatKind(asset: AtpAssetSummary): FormatFilter {
  if (!asset.format_check?.model_format) return "unknown";
  if (asset.model_format === "insert") return "insert";
  if (asset.model_format === "legacy") return "legacy";
  return "unknown";
}

function dimKey(asset: AtpAssetSummary, field: "voltage" | "tower" | "scene" | "arrester"): string {
  if (field === "voltage") return asset.voltage_level || "-";
  if (field === "tower") return asset.tower_type || "-";
  if (field === "scene") return asset.scene_type || "-";
  return asset.arrester_config || "-";
}

function dimLabel(asset: AtpAssetSummary, field: "voltage" | "tower" | "scene" | "arrester"): string {
  if (field === "voltage") return asset.voltage_level_label || asset.voltage_level || "-";
  if (field === "tower") return asset.tower_type_label || asset.tower_type || "-";
  if (field === "scene") return asset.scene_type_label || asset.scene_type || "-";
  return asset.arrester_config_label || asset.arrester_config || "-";
}

/**
 * ATP 模型总览（2026-11-07 重做）。
 *
 * 旧版是一个 ECharts 树：只有各层节点计数，看不出「具体有哪些资产 / 哪个版本在生效 /
 * 哪些是旧版、哪些还没判定形态」，而这三件事恰恰是选型与清理时最常问的。
 *
 * 新版按「读数 → 覆盖 → 清单」三层展开：
 * - 概览带：资产总数 / 生效中 / 未启用 / 新版 / 旧版 / 待检测 六个读数，一眼看家底；
 * - 覆盖矩阵：电压 × 塔型 的资产分布，格子里的数字是资产数（角标为其中新版数），
 *   点击格子即筛选下方清单——空白的格子就是当前缺口；
 * - 资产清单：每行一个模型，带版本、生效状态、形态、测试结论，可按场景/避雷器/状态/
 *   形态/关键字筛，点「详情」直接跳到该模型的详情 Tab。
 */
export function AtpModelOverviewTab({ onOpenDetail }: AtpModelOverviewTabProps = {}) {
  const { t } = useI18n();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  const [matrixPick, setMatrixPick] = useState<{ voltage: string; tower: string } | null>(null);
  const [sceneFilter, setSceneFilter] = useState<string>("all");
  const [arresterFilter, setArresterFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [formatFilter, setFormatFilter] = useState<FormatFilter>("all");
  const [keyword, setKeyword] = useState("");

  const assetsQuery = useQuery({
    queryKey: ["atp-assets-overview-all"],
    enabled: Boolean(user && canRead),
    queryFn: async () => {
      const collected: AtpAssetSummary[] = [];
      let offset = 0;
      let total = Number.POSITIVE_INFINITY;
      while (collected.length < total && offset < MAX_FETCH) {
        const response = await fetchWithAuth(`/api/v1/atp/assets?limit=${PAGE_LIMIT}&offset=${offset}`);
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const page = (await response.json()) as { items?: AtpAssetSummary[]; total?: number };
        const items = page.items ?? [];
        if (typeof page.total === "number") total = page.total;
        collected.push(...items);
        if (items.length === 0) break;
        offset += items.length;
      }
      return collected;
    },
  });

  const assets = useMemo(() => assetsQuery.data ?? [], [assetsQuery.data]);

  // 场景 / 避雷器 选项：从数据里取，按资产数降序
  const sceneOptions = useMemo(() => {
    const map = new Map<string, { key: string; label: string; count: number }>();
    assets.forEach((asset) => {
      const key = dimKey(asset, "scene");
      const entry = map.get(key) ?? { key, label: dimLabel(asset, "scene"), count: 0 };
      entry.count += 1;
      map.set(key, entry);
    });
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [assets]);

  const arresterOptions = useMemo(() => {
    const map = new Map<string, { key: string; label: string; count: number }>();
    assets.forEach((asset) => {
      const key = dimKey(asset, "arrester");
      const entry = map.get(key) ?? { key, label: dimLabel(asset, "arrester"), count: 0 };
      entry.count += 1;
      map.set(key, entry);
    });
    return [...map.values()].sort((a, b) => b.count - a.count);
  }, [assets]);

  const stats = useMemo(() => {
    let active = 0;
    let insert = 0;
    let legacy = 0;
    let unknown = 0;
    assets.forEach((asset) => {
      if (isEffective(asset)) active += 1;
      const kind = formatKind(asset);
      if (kind === "insert") insert += 1;
      else if (kind === "legacy") legacy += 1;
      else unknown += 1;
    });
    return { total: assets.length, active, inactive: assets.length - active, insert, legacy, unknown };
  }, [assets]);

  // 矩阵：口径 = 除「矩阵自身筛选」外的全部筛选条件，点格子即钻取
  const matrixSource = useMemo(
    () =>
      assets.filter((asset) => {
        if (sceneFilter !== "all" && dimKey(asset, "scene") !== sceneFilter) return false;
        if (arresterFilter !== "all" && dimKey(asset, "arrester") !== arresterFilter) return false;
        if (statusFilter === "active" && !isEffective(asset)) return false;
        if (statusFilter === "inactive" && isEffective(asset)) return false;
        if (formatFilter !== "all" && formatKind(asset) !== formatFilter) return false;
        const kw = keyword.trim().toLowerCase();
        if (kw && !`${asset.name} ${asset.code}`.toLowerCase().includes(kw)) return false;
        return true;
      }),
    [assets, sceneFilter, arresterFilter, statusFilter, formatFilter, keyword],
  );

  const matrix = useMemo(() => {
    const towers = new Map<string, { key: string; label: string; count: number }>();
    const voltages = new Map<string, { key: string; label: string; count: number }>();
    const cells = new Map<string, { count: number; insert: number }>();
    matrixSource.forEach((asset) => {
      const vKey = dimKey(asset, "voltage");
      const tKey = dimKey(asset, "tower");
      const v = voltages.get(vKey) ?? { key: vKey, label: dimLabel(asset, "voltage"), count: 0 };
      v.count += 1;
      voltages.set(vKey, v);
      const tw = towers.get(tKey) ?? { key: tKey, label: dimLabel(asset, "tower"), count: 0 };
      tw.count += 1;
      towers.set(tKey, tw);
      const cellKey = `${vKey}|${tKey}`;
      const cell = cells.get(cellKey) ?? { count: 0, insert: 0 };
      cell.count += 1;
      if (formatKind(asset) === "insert") cell.insert += 1;
      cells.set(cellKey, cell);
    });
    const voltageList = [...voltages.values()].sort(
      (a, b) => (parseFloat(b.label) || 0) - (parseFloat(a.label) || 0),
    );
    const towerList = [...towers.values()].sort((a, b) => b.count - a.count);
    const maxCount = Math.max(1, ...[...cells.values()].map((cell) => cell.count));
    return { voltageList, towerList, cells, maxCount };
  }, [matrixSource]);

  const rows = useMemo(() => {
    const filtered = matrixSource.filter((asset) => {
      if (matrixPick) {
        if (dimKey(asset, "voltage") !== matrixPick.voltage) return false;
        if (dimKey(asset, "tower") !== matrixPick.tower) return false;
      }
      return true;
    });
    return [...filtered].sort((a, b) => {
      const byVoltage = (parseFloat(b.voltage_level_label || b.voltage_level || "0") || 0)
        - (parseFloat(a.voltage_level_label || a.voltage_level || "0") || 0);
      if (byVoltage !== 0) return byVoltage;
      const byTower = (a.tower_type_label || a.tower_type || "").localeCompare(b.tower_type_label || b.tower_type || "");
      if (byTower !== 0) return byTower;
      const byScene = (a.scene_type_label || a.scene_type || "").localeCompare(b.scene_type_label || b.scene_type || "");
      if (byScene !== 0) return byScene;
      return (a.arrester_config_label || a.arrester_config || "").localeCompare(
        b.arrester_config_label || b.arrester_config || "",
      );
    });
  }, [matrixSource, matrixPick]);

  const columns: ColumnsType<AtpAssetSummary> = [
    {
      title: t("模型"),
      key: "model",
      render: (_value, asset) => (
        <div className="admin-atp-models-overview-model">
          <span className="admin-atp-models-overview-model-name" title={asset.name}>
            {asset.name || asset.code}
          </span>
          <span className="admin-atp-models-overview-model-code">{asset.code}</span>
        </div>
      ),
    },
    {
      title: t("维度组合"),
      key: "dimensions",
      render: (_value, asset) => (
        <span className="admin-atp-models-overview-dims">
          {[
            dimLabel(asset, "voltage"),
            dimLabel(asset, "tower"),
            dimLabel(asset, "scene"),
            dimLabel(asset, "arrester"),
            asset.shield_wire === "without" ? t("无避雷线") : t("有避雷线"),
          ].join(" · ")}
        </span>
      ),
    },
    {
      title: t("版本"),
      dataIndex: "version",
      key: "version",
      width: 90,
      render: (value: string) => value || "-",
    },
    {
      title: t("生效状态"),
      key: "effective",
      width: 110,
      render: (_value, asset) =>
        isEffective(asset) ? (
          <span className="admin-atp-models-state-chip is-published">{t("生效中")}</span>
        ) : (
          <Tooltip
            title={
              asset.status !== "enabled"
                ? t("资产已停用/归档")
                : asset.is_published === false
                  ? t("版本已下线（不参与仿真定位）")
                  : t("生效开关已关闭")
            }
          >
            <span className="admin-atp-models-state-chip is-muted">{t("未启用")}</span>
          </Tooltip>
        ),
    },
    {
      title: t("形态"),
      key: "format",
      width: 110,
      render: (_value, asset) => {
        const meta = resolveFormatMeta(asset);
        return (
          <Tooltip title={t(meta.hint)}>
            <span className="admin-atp-models-overview-format" style={{ color: meta.color, background: meta.background }}>
              {t(meta.short)}
            </span>
          </Tooltip>
        );
      },
    },
    {
      title: t("更新时间"),
      dataIndex: "update_date",
      key: "update_date",
      width: 120,
      render: (value: string) => dateOnly(value),
    },
    ...(onOpenDetail
      ? [
          {
            title: t("操作"),
            key: "operation",
            width: 80,
            align: "right" as const,
            render: (_value: unknown, asset: AtpAssetSummary) => (
              <Button type="link" size="small" style={{ padding: 0 }} onClick={() => onOpenDetail(asset)}>
                {t("详情")}
              </Button>
            ),
          },
        ]
      : []),
  ];

  const matrixFilterActive = Boolean(matrixPick);
  const filterActive =
    statusFilter !== "all" || formatFilter !== "all" || sceneFilter !== "all" || arresterFilter !== "all" || keyword.trim() !== "";

  const resetFilters = () => {
    setMatrixPick(null);
    setSceneFilter("all");
    setArresterFilter("all");
    setStatusFilter("all");
    setFormatFilter("all");
    setKeyword("");
  };

  if (assetsQuery.isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <Spin />
      </div>
    );
  }

  if (assetsQuery.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("总览数据加载失败")}
        description={String(assetsQuery.error instanceof Error ? assetsQuery.error.message : assetsQuery.error)}
      />
    );
  }

  if (assets.length === 0) {
    return <Empty description={t("暂无模型数据")} image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return (
    <div className="admin-atp-models-overview">
      {/* 概览带：读数 + 刷新 */}
      <div className="admin-atp-models-detail-hero">
        <div className="admin-atp-models-detail-hero-head">
          <span className="admin-atp-models-card-tile admin-atp-models-detail-tile" aria-hidden>
            <AppstoreOutlined />
          </span>
          <div className="admin-atp-models-detail-headline">
            <div className="admin-atp-models-detail-name">
              <span className="admin-atp-models-detail-name-text">{t("ATP 模型总览")}</span>
            </div>
            <div className="admin-atp-models-detail-subline">
              <span>
                {t("全库 {n} 个资产，覆盖 {v} 个电压等级、{tw} 种塔型")
                  .replace("{n}", String(stats.total))
                  .replace("{v}", String(matrix.voltageList.length))
                  .replace("{tw}", String(matrix.towerList.length))}
              </span>
            </div>
          </div>
          <Tooltip title={t("刷新")}>
            <Button icon={<ReloadOutlined />} loading={assetsQuery.isFetching} onClick={() => assetsQuery.refetch()} />
          </Tooltip>
        </div>
        <div className="admin-atp-models-detail-stats">
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value">{stats.total}</span>
            <span className="admin-atp-models-detail-stat-label">{t("资产总数")}</span>
          </div>
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value is-success">{stats.active}</span>
            <span className="admin-atp-models-detail-stat-label">{t("生效中")}</span>
          </div>
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value is-muted">{stats.inactive}</span>
            <span className="admin-atp-models-detail-stat-label">{t("未启用")}</span>
          </div>
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value" style={{ color: "#b45309" }}>
              {stats.insert}
            </span>
            <span className="admin-atp-models-detail-stat-label">{t("新版（$INSERT）")}</span>
          </div>
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value" style={{ color: "#1d4ed8" }}>
              {stats.legacy}
            </span>
            <span className="admin-atp-models-detail-stat-label">{t("旧版（$INCLUDE）")}</span>
          </div>
          <div className="admin-atp-models-detail-stat">
            <span className="admin-atp-models-detail-stat-value is-muted">{stats.unknown}</span>
            <span className="admin-atp-models-detail-stat-label">{t("待检测")}</span>
          </div>
        </div>
      </div>

      {/* 覆盖矩阵：电压 × 塔型，点格子钻取 */}
      <div className="admin-atp-models-overview-block">
        <div className="admin-atp-models-overview-block-head">
          <span className="admin-atp-models-overview-block-title">{t("电压 × 塔型 覆盖")}</span>
          <span className="admin-atp-models-overview-block-note">
            {t("格子里是资产数，角标为其中新版数量；点击单元格筛选下方清单")}
          </span>
        </div>
        <div
          className="admin-atp-models-overview-matrix"
          style={{ gridTemplateColumns: `96px repeat(${matrix.towerList.length}, minmax(0, 1fr))` }}
        >
          <div className="admin-atp-models-overview-matrix-corner">{t("电压 / 塔型")}</div>
          {matrix.towerList.map((tower) => (
            <div key={`head-${tower.key}`} className="admin-atp-models-overview-matrix-colhead">
              {tower.label}
              <span className="admin-atp-models-overview-matrix-total">{tower.count}</span>
            </div>
          ))}
          {matrix.voltageList.map((voltage) => (
            <Fragment key={`row-${voltage.key}`}>
              <div className="admin-atp-models-overview-matrix-rowhead">
                {voltage.label}
                <span className="admin-atp-models-overview-matrix-total">{voltage.count}</span>
              </div>
              {matrix.towerList.map((tower) => {
                const cell = matrix.cells.get(`${voltage.key}|${tower.key}`);
                const count = cell?.count ?? 0;
                const selected =
                  matrixPick?.voltage === voltage.key && matrixPick?.tower === tower.key;
                const level = count === 0 ? 0 : Math.ceil((count / matrix.maxCount) * 3);
                return (
                  <Tooltip
                    key={`${voltage.key}-${tower.key}`}
                    title={
                      count === 0
                        ? `${voltage.label} ${tower.label}：${t("暂无资产")}`
                        : `${voltage.label} ${tower.label}：${count} ${t("个资产")}${cell?.insert ? ` · ${t("新版")} ${cell.insert}` : ""}`
                    }
                  >
                    <button
                      type="button"
                      className={`admin-atp-models-overview-cell is-level-${level}${selected ? " is-selected" : ""}`}
                      onClick={() => {
                        if (count === 0) return;
                        setMatrixPick(selected ? null : { voltage: voltage.key, tower: tower.key });
                      }}
                    >
                      <span className="admin-atp-models-overview-cell-count">{count === 0 ? "·" : count}</span>
                      {cell?.insert ? (
                        <span className="admin-atp-models-overview-cell-badge">{t("新")}{cell.insert}</span>
                      ) : null}
                    </button>
                  </Tooltip>
                );
              })}
            </Fragment>
          ))}
        </div>
      </div>

      {/* 资产清单 */}
      <div className="admin-atp-models-overview-block">
        <div className="admin-atp-models-overview-toolbar">
          <Space size={8} wrap>
            <Select
              size="small"
              value={sceneFilter}
              style={{ width: 120 }}
              onChange={setSceneFilter}
              options={[{ value: "all", label: t("全部场景") }, ...sceneOptions.map((o) => ({ value: o.key, label: `${o.label} (${o.count})` }))]}
            />
            <Select
              size="small"
              value={arresterFilter}
              style={{ width: 130 }}
              onChange={setArresterFilter}
              options={[{ value: "all", label: t("全部避雷器组合") }, ...arresterOptions.map((o) => ({ value: o.key, label: `${o.label} (${o.count})` }))]}
            />
            <Segmented
              size="small"
              value={statusFilter}
              onChange={(value) => setStatusFilter(value as StatusFilter)}
              options={[
                { value: "all", label: t("全部") },
                { value: "active", label: t("生效中") },
                { value: "inactive", label: t("未启用") },
              ]}
            />
            <Select
              size="small"
              value={formatFilter}
              style={{ width: 116 }}
              onChange={(value) => setFormatFilter(value as FormatFilter)}
              options={[
                { value: "all", label: t("全部形态") },
                { value: "insert", label: t("新版") },
                { value: "legacy", label: t("旧版") },
                { value: "unknown", label: t("待检测") },
              ]}
            />
            <Input
              size="small"
              allowClear
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              prefix={<SearchOutlined style={{ color: "var(--fquiz-theme-text-muted)" }} />}
              placeholder={t("搜索模型名称/编号")}
              style={{ width: 200 }}
            />
            {matrixFilterActive || filterActive ? (
              <Button size="small" type="link" onClick={resetFilters}>
                {t("清除筛选")}
              </Button>
            ) : null}
          </Space>
          <Typography.Text type="secondary" className="whitespace-nowrap text-xs">
            {t("共 {n} 个资产").replace("{n}", String(rows.length))}
            {matrixPick
              ? ` · ${matrix.voltageList.find((v) => v.key === matrixPick.voltage)?.label ?? matrixPick.voltage} ${
                  matrix.towerList.find((tw) => tw.key === matrixPick.tower)?.label ?? matrixPick.tower
                }`
              : ""}
          </Typography.Text>
        </div>
        <Table<AtpAssetSummary>
          rowKey="id"
          size="small"
          dataSource={rows}
          columns={columns}
          pagination={{
            pageSize: 20,
            showSizeChanger: false,
            showTotal: (total) => t("共 {n} 个资产").replace("{n}", String(total)),
          }}
          scroll={{ x: 880 }}
          locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={t("当前筛选下没有资产")} /> }}
        />
      </div>
    </div>
  );
}
