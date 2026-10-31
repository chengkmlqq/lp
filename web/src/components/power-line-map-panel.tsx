"use client";

import { SearchOutlined } from "@ant-design/icons";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Form, Input, Space, Spin, Typography } from "antd";
import Link from "next/link";
import { useMemo, useState } from "react";

import { useI18n } from "@/lib/i18n";
import { PowerLineCesiumMap } from "@/components/power-line-cesium-map";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { LineSummary, LineTowerListResponse } from "@/types/auth";

const TOWER_MAP_QUERY_LIMIT = 500;

type AppliedFilters = { keyword: string; towerType: string };

type PowerLineMapPanelProps = {
  lineId: string;
  accessToken: string;
};

export function PowerLineMapPanel({ lineId, accessToken }: PowerLineMapPanelProps) {
  const { t } = useI18n();
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  // 与后端 /lines/{id}/towers 契约一致：具备 line.read/line.manage 亦可读取杆塔
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage") || canLineRead;

  const [keyword, setKeyword] = useState("");
  const [towerType, setTowerType] = useState("");
  const [filters, setFilters] = useState<AppliedFilters>({ keyword: "", towerType: "" });

  const lineDetailQuery = useQuery({
    queryKey: ["line-detail-map", lineId],
    enabled: !!user && canLineRead,
    queryFn: async () => {
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineSummary;
    },
  });

  const mapTowersQuery = useQuery({
    queryKey: ["line-towers-map", lineId, filters.keyword, filters.towerType],
    enabled: !!user && canTowerRead && !!lineDetailQuery.data,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(TOWER_MAP_QUERY_LIMIT));
      params.set("offset", "0");
      if (filters.keyword.trim()) {
        params.set("keyword", filters.keyword.trim());
      }
      if (filters.towerType.trim()) {
        params.set("tower_type", filters.towerType.trim());
      }
      const query = params.toString();
      const response = await fetchWithAuth(`/api/v1/lines/${lineId}/towers${query ? `?${query}` : ""}`);
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineTowerListResponse;
    },
  });

  const towers = useMemo(() => mapTowersQuery.data?.items ?? [], [mapTowersQuery.data?.items]);
  const lineDetail = lineDetailQuery.data;

  const applyFilters = () => {
    setFilters({ keyword, towerType });
  };

  const resetFilters = () => {
    setKeyword("");
    setTowerType("");
    setFilters({ keyword: "", towerType: "" });
  };

  if (initializing) {
    return (
      <div className="flex min-h-[280px] items-center justify-center">
        <Spin />
      </div>
    );
  }
  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">{t("请先登录后再访问地图页面。")}</Typography.Text>
          <Button>
            <Link href="/">{t("返回首页")}</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  if (!canTowerRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">{t("你没有访问该页面的权限（需要 `tower.read` 或 `line.read`）。")}</Typography.Text>
          <Button>
            <Link href="/admin/power-lines">{t("返回线路列表")}</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col gap-3 p-6">
      {/* 顶部：与线路详情页一致的表单过滤（上下结构） */}
      <div className="admin-filter-bar">
        <Form layout="inline" className="flex flex-wrap items-center gap-2">
          <Form.Item label={t("关键词")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              value={keyword}
              allowClear
              onChange={(event) => setKeyword(event.target.value)}
              placeholder={t("按塔号/模型筛选")}
              onPressEnter={applyFilters}
            />
          </Form.Item>
          <Form.Item label={t("塔型")} className="admin-filter-keyword-item" style={{ marginBottom: 0 }}>
            <Input
              value={towerType}
              allowClear
              onChange={(event) => setTowerType(event.target.value)}
              placeholder={t("塔型编码（如 d500shangzi）")}
              onPressEnter={applyFilters}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button htmlType="button" icon={<SearchOutlined />} onClick={applyFilters} className="admin-search-btn">
              {t("查询")}
            </Button>
          </Form.Item>
          <Form.Item style={{ marginBottom: 0 }}>
            <Button onClick={resetFilters}>{t("重置")}</Button>
          </Form.Item>
          <Typography.Text type="secondary" className="text-xs">
            当前加载 {towers.length} 基（上限 {TOWER_MAP_QUERY_LIMIT}）
          </Typography.Text>
        </Form>
      </div>

      {/* 下方：地图高度自适应填满剩余空间 */}
      <div className="relative min-h-0 flex-1">
        <PowerLineCesiumMap
          lineCode={lineDetail?.code}
          lineName={lineDetail?.name}
          towers={towers}
          terrainDataset={null}
          accessToken={accessToken}
          exaggeration={1}
          loading={mapTowersQuery.isFetching || lineDetailQuery.isFetching}
          fillHeight
        />
      </div>
    </div>
  );
}
