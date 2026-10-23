"use client";

import { useMemo, useState, useEffect } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Button, Card, Space, Typography } from "antd";
import Link from "next/link";

import { useI18n } from "@/lib/i18n";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { PowerLineMapPanel } from "@/components/power-line-map-panel";
import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";
import type { LineSummary, LineTowerListResponse, LineTowerSummary } from "@/types/auth";

const TOWER_MAP_QUERY_LIMIT = 500;
const MAP_HEADER_ESTIMATED_HEIGHT = 220;

export default function AdminPowerLineMapPage() {
  const { t } = useI18n();
  const { lineId } = useParams<{ lineId: string }>();
  const { user, initializing, fetchWithAuth, hasPermission, getAccessToken } = useAuth();

  const canLineRead = hasPermission("line.read") || hasPermission("line.manage");
  // 与后端 /lines/{id}/towers 契约一致：具备 line.read/line.manage 亦可读取杆塔
  const canTowerRead = hasPermission("tower.read") || hasPermission("tower.manage") || canLineRead;

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
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
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
    <div className="flex h-full min-h-0 flex-1 flex-col">
      <div className="relative min-h-0 flex-1">
        <PowerLineMapPanel lineId={lineId} accessToken={getAccessToken() ?? ""} />
      </div>
    </div>
  );
}
