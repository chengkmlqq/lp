"use client";

import { useMemo, useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Space, Typography } from "antd";
import { ArrowLeftOutlined } from "@ant-design/icons";
import Link from "next/link";

import { AdminPageLoading } from "@/components/admin-page-loading";
import { PowerLineCesiumMap } from "@/components/power-line-cesium-map";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { LineSummary, LineTowerListResponse, LineTowerSummary } from "@/types/auth";

const TOWER_MAP_QUERY_LIMIT = 500;
const MAP_HEADER_ESTIMATED_HEIGHT = 220;

export default function AdminPowerLineMapPage({ params }: { params: { lineId: string } }) {
  const { user, initializing, fetchWithAuth, hasPermission } = useAuth();
  const lineId = params.lineId;

  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage");

  const [mapHeight, setMapHeight] = useState(560);

  useEffect(() => {
    const updateHeight = () => {
      setMapHeight(Math.max(480, Math.floor((window.innerHeight ?? 800) - MAP_HEADER_ESTIMATED_HEIGHT)));
    };
    updateHeight();
    window.addEventListener("resize", updateHeight);
    return () => {
      window.removeEventListener("resize", updateHeight);
    };
  }, []);

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
    queryKey: ["line-towers-map", lineId],
    enabled: !!user && canTowerRead && !!lineDetailQuery.data,
    queryFn: async () => {
      const params = new URLSearchParams();
      params.set("limit", String(TOWER_MAP_QUERY_LIMIT));
      params.set("offset", "0");
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

  if (initializing) {
    return <AdminPageLoading tip="初始化中..." minHeightClassName="min-h-[280px]" />;
  }
  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">请先登录后再访问地图页面。</Typography.Text>
          <Button>
            <Link href="/">返回首页</Link>
          </Button>
        </Space>
      </Card>
    );
  }
  if (!canTowerRead) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">你没有访问该页面的权限（需要 `tower.read`）。</Typography.Text>
          <Button>
            <Link href="/admin/power-lines">返回线路列表</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="mb-3 flex items-center gap-3">
        <Button size="small" icon={<ArrowLeftOutlined />}>
          <Link href="/admin/power-lines">返回线路列表</Link>
        </Button>
        <Typography.Text strong>线路走向预览</Typography.Text>
      </div>

      <div className="relative min-h-0 flex-1">
        <PowerLineCesiumMap
          lineCode={lineDetail?.code}
          lineName={lineDetail?.name}
          towers={towers}
          terrainDataset={null}
          accessToken=""
          exaggeration={1}
          loading={mapTowersQuery.isFetching || lineDetailQuery.isFetching}
          height={mapHeight}
        />
      </div>
    </div>
  );
}
