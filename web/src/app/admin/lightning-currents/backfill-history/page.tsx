"use client";

import Link from "next/link";
import { Button, Space, Typography } from "antd";

import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { Card } from "@/components/ui-antd";
import { LightningCurrentBackfillHistoryTable } from "@/components/lightning-current-backfill-history";

export default function AdminLightningCurrentsBackfillHistoryPage() {
  const { t } = useI18n();
  const { user, initializing, hasPermission } = useAuth();

  const canRead = hasPermission("lightning.read") || hasPermission("lightning.manage");

  if (initializing) {
    return (
      <AdminPageLoading minHeightClassName="min-h-[280px]"
      />
    );
  }

  if (!user) {
    return (
      <Card>
        <Space direction="vertical" size={12}>
          <Typography.Text type="secondary">
            请先登录后再访问回填记录页面。
          </Typography.Text>
          <Button>
            <Link href="/">{t("返回首页")}</Link>
          </Button>
        </Space>
      </Card>
    );
  }

  if (!canRead) {
    return (
      <div className="p-6">
        <Card>
          <Space direction="vertical" size={12}>
            <Typography.Text type="secondary">
              你没有访问该页面的权限（需要 `lightning.read`）。
            </Typography.Text>
            <Button>
              <Link href="/">{t("返回首页")}</Link>
            </Button>
          </Space>
        </Card>
      </div>
    );
  }

  return (
    <div className="p-6">
      <LightningCurrentBackfillHistoryTable />
    </div>
  );
}
