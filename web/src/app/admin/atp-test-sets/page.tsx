"use client";

/**
 * ATP 测试集管理（独立页面）。
 *
 * 测试集 = 一组 ATP 模型的仿真测试用例（普通计算/同跳计算）。用途：
 * ATP 模型更新或程序逻辑更新后，一键批量回归仿真测试，并与上次执行对比。
 *
 * 布局参照其它管理页：无侧栏分隔，直接渲染测试集列表 + 用例管理抽屉 + 执行结果抽屉。
 */
import { useAuth } from "@/components/auth-provider";
import { AtpTestSetTab } from "@/components/atp-models/atp-test-set-tab";
import { AdminPageLoading } from "@/components/admin-page-loading";
import { useI18n } from "@/lib/i18n";
import { Card, Empty, Typography } from "antd";

export default function AtpTestSetsPage() {
  const { user, initializing, hasPermission } = useAuth();
  const { t } = useI18n();

  if (initializing) {
    return <AdminPageLoading minHeightClassName="min-h-[280px]" />;
  }

  const canRead = hasPermission("atp.read") || hasPermission("atp.run") || hasPermission("atp.manage");

  if (!user || !canRead) {
    return (
      <Card>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={
            <Typography.Text type="secondary">
              {!user
                ? t("请先登录后再访问测试集管理。")
                : t("当前账号无 ATP 模块权限（需要 atp.read/atp.run/atp.manage）。")}
            </Typography.Text>
          }
        />
      </Card>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <AtpTestSetTab />
    </div>
  );
}
