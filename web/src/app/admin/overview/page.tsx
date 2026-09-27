"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import type { ComponentType, RefAttributes } from "react";
import {
  Alert,
  Card,
  Col,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
  type CardProps,
} from "antd";

import { useAuth } from "@/components/auth-provider";
import { readApiError } from "@/lib/api";

const { Text, Title } = Typography;
const AntCard = Card as unknown as ComponentType<CardProps & RefAttributes<HTMLDivElement>>;

type AssetStatItem = {
  key: string;
  label: string;
  count: number;
  route: string | null;
};

type TaskStateBucket = {
  key: string;
  label: string;
  count: number;
};

type OverviewTasksSummary = {
  total: number;
  queue_pending_total: number;
  scheduled_tasks: number;
  state_buckets: TaskStateBucket[];
};

type SystemOverviewResponse = {
  generated_at: string;
  assets: AssetStatItem[];
  tasks: OverviewTasksSummary;
};

const OVERVIEW_QUERY_KEY = ["/api/v1/admin/overview"] as const;

const STATE_COLORS: Record<string, string> = {
  SUCCESS: "green",
  FAILURE: "red",
  STARTED: "processing",
  PENDING: "default",
  RECEIVED: "default",
  RETRY: "orange",
  REVOKED: "default",
};

export default function AdminOverviewPage() {
  const { fetchWithAuth } = useAuth();

  const overviewQuery = useQuery({
    queryKey: OVERVIEW_QUERY_KEY,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/admin/overview");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as SystemOverviewResponse;
    },
  });

  if (overviewQuery.isLoading) {
    return (
      <div className="flex min-h-[300px] items-center justify-center">
        <Spin size="large" />
      </div>
    );
  }

  if (overviewQuery.isError || !overviewQuery.data) {
    return (
      <Alert
        type="error"
        showIcon
        message="系统总览加载失败"
        description={overviewQuery.error instanceof Error ? overviewQuery.error.message : "请稍后重试"}
      />
    );
  }

  const { assets, tasks } = overviewQuery.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-baseline justify-between">
        <Title level={4} style={{ marginBottom: 0 }}>
          系统总览
        </Title>
        <Text type="secondary" style={{ fontSize: 12 }}>
          更新时间：{new Date(overviewQuery.data.generated_at).toLocaleString("zh-CN")}
        </Text>
      </div>

      <AntCard title="系统资产统计" size="small">
        <Row gutter={[16, 16]}>
          {assets.map((item) => {
            const card = (
              <Statistic
                title={item.label}
                value={item.count}
                valueStyle={{ fontSize: 22 }}
              />
            );
            return (
              <Col key={item.key} xs={12} sm={8} md={6} lg={4}>
                {item.route ? (
                  <Link
                    href={item.route}
                    className="block !text-inherit no-underline"
                    prefetch={false}
                  >
                    <div className="rounded-lg border border-solid border-[var(--ant-color-border-secondary)] p-3 transition-colors hover:bg-[var(--ant-color-fill-tertiary)]">
                      {card}
                    </div>
                  </Link>
                ) : (
                  <div className="rounded-lg border border-solid border-[var(--ant-color-border-secondary)] p-3">
                    {card}
                  </div>
                )}
              </Col>
            );
          })}
        </Row>
      </AntCard>

      <AntCard
        title="任务总览"
        size="small"
        extra={
          <Link href="/admin/task-monitor" prefetch={false}>
            前往任务监控
          </Link>
        }
      >
        <Row gutter={[16, 16]}>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="历史任务总数" value={tasks.total} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="队列积压任务数" value={tasks.queue_pending_total} />
          </Col>
          <Col xs={12} sm={8} md={4}>
            <Statistic title="定时任务数" value={tasks.scheduled_tasks} />
          </Col>
        </Row>

        <div className="mt-4">
          <Text type="secondary" style={{ display: "block", marginBottom: 8 }}>
            任务状态分布
          </Text>
          {tasks.state_buckets.length === 0 ? (
            <Text type="secondary">暂无任务历史记录</Text>
          ) : (
            <Space wrap size={[8, 8]}>
              {tasks.state_buckets.map((bucket) => (
                <Tag key={bucket.key} color={STATE_COLORS[bucket.key] ?? "default"}>
                  {bucket.label} · {bucket.count}
                </Tag>
              ))}
            </Space>
          )}
        </div>
      </AntCard>
    </div>
  );
}