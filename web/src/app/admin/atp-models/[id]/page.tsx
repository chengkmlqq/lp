"use client";

import { useParams } from "next/navigation";

import { AtpModelDetailTab } from "@/components/atp-models/atp-model-detail-tab";

/**
 * ATP 模型独立详情页（2026-11-07）：与模型列表页内打开的「模型详情」Tab 共用
 * AtpModelDetailTab（概览带 + 基本信息/文件列表 分区），登录与权限校验也在组件内完成，
 * 避免两处详情样式各自漂移。
 */
function ATPAssetDetailPage() {
  const params = useParams();
  const assetId = params.id as string;

  return <AtpModelDetailTab assetId={assetId} />;
}

export default ATPAssetDetailPage;
