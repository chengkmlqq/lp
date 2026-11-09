"use client";

/**
 * 测试集管理页面（独立页面，双 Tab）。
 *
 * - 防雷测试（默认）：防雷计算/防雷改造测试用例集合，批量发起真实
 *   fl_analysis 任务并在页内查看（任务打 test_run_case_id 标记，
 *   防雷计算/改造页面默认不展示）。
 * - ATP 模型回归：既有 ATP 资产回归测试（AtpTestSetTab），功能保持不变。
 *
 * 布局参照其它管理页：无侧栏分隔，直接渲染 Tab + 列表 + 抽屉。
 */
import { useState } from "react";
import { useAuth } from "@/components/auth-provider";
import { AtpTestSetTab } from "@/components/atp-models/atp-test-set-tab";
import { FlTestSetTab } from "@/components/fl-test-sets/fl-test-set-tab";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useI18n } from "@/lib/i18n";
import { Card, Empty, Tabs, Typography } from "antd";

export default function AtpTestSetsPage() {
  const { user, initializing, hasPermission } = useAuth();
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState("fl");

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  const canReadFl =
    hasPermission("line.read") || hasPermission("line.manage") || hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");
  const canReadAtp = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  if (!user || (!canReadFl && !canReadAtp)) {
    return (
      <Card>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Typography.Text type="secondary">
              {!user
                ? t("请先登录后再访问测试集管理。")
                : t("当前账号无测试集模块权限（需要 line/atp/fl 相关权限）。")}
            </Typography.Text>
          }
        />
      </Card>
    );
  }

  return (
    <div className="modo-page-card">
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          ...(canReadFl
            ? [
                {
                  key: "fl",
                  label: t("防雷测试"),
                  children: <FlTestSetTab />,
                },
              ]
            : []),
          ...(canReadAtp
            ? [
                {
                  key: "atp",
                  label: t("ATP 模型回归"),
                  children: <AtpTestSetTab />,
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
