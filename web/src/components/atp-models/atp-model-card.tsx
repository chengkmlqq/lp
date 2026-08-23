"use client";

import { Button, Modal, Typography } from "antd";
import { EyeOutlined, DeleteOutlined } from "@ant-design/icons";
import { useCallback } from "react";
import { useRouter } from "next/navigation";

import type { AtpAssetSummary } from "@/types/auth";

const { Text } = Typography;

interface AtpModelCardProps {
  asset: AtpAssetSummary;
  canManage: boolean;
  deleteLoading: boolean;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
  /** 维度 code → 中文名 的映射（塔型/场景/避雷器组合等） */
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

function formatDimension(
  value: string | null,
  map: Map<string, string> | undefined,
): string {
  if (!value) return "-";
  return map?.get(value) ?? value;
}

export function AtpModelCard({ asset, canManage, deleteLoading, onView, onDelete, dimensionLabelMap }: AtpModelCardProps) {
  const router = useRouter();
  const rowBusy = deleteLoading;

  const handleView = useCallback(() => {
    router.push(`/admin/atp-models/${asset.id}`);
  }, [router, asset.id]);

  const handleDelete = useCallback(() => {
    Modal.confirm({
      title: "删除模型",
      content: "这会同时删除其文件与运行记录。",
      okText: "删除",
      cancelText: "取消",
      okButtonProps: { danger: true, loading: deleteLoading },
      onOk: () => onDelete(asset.id),
    });
  }, [deleteLoading, onDelete, asset.id]);

  return (
    <div
      className="admin-atp-models-card"
      onClick={handleView}
      style={{
        height: "100%",
        cursor: "pointer",
        border: "1px solid color-mix(in srgb, var(--fquiz-theme-primary) 26%, var(--ant-color-border-secondary))",
        background:
          "linear-gradient(180deg, color-mix(in srgb, var(--fquiz-theme-bg-container) 96%, var(--fquiz-theme-primary) 4%) 0%, var(--fquiz-theme-bg-container) 100%)",
        boxShadow: "0 8px 18px color-mix(in srgb, var(--fquiz-theme-text-primary) 8%, transparent)",
      }}
    >
      <div
        className="admin-atp-models-card-title"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "10px 12px",
          borderBottom: "1px solid color-mix(in srgb, var(--fquiz-theme-primary) 18%, var(--ant-color-border-secondary))",
          background: "color-mix(in srgb, var(--fquiz-theme-primary) 6%, transparent)",
          minHeight: 44,
        }}
      >
        <Text strong ellipsis={{ tooltip: asset.name }} style={{ flex: 1 }}>
          {asset.name}
        </Text>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10, padding: "12px" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <Text type="secondary" style={{ width: 64, flexShrink: 0 }}>
            电压等级
          </Text>
          <Text ellipsis>{formatDimension(asset.voltage_level, dimensionLabelMap?.voltage_level)}</Text>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <Text type="secondary" style={{ width: 64, flexShrink: 0 }}>
            塔型
          </Text>
          <Text ellipsis>{formatDimension(asset.tower_type, dimensionLabelMap?.tower_type)}</Text>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <Text type="secondary" style={{ width: 64, flexShrink: 0 }}>
            场景
          </Text>
          <Text ellipsis>{formatDimension(asset.scene_type, dimensionLabelMap?.scene_type)}</Text>
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <Text type="secondary" style={{ width: 64, flexShrink: 0 }}>
            避雷器组合
          </Text>
          <Text ellipsis>{formatDimension(asset.arrester_config, dimensionLabelMap?.arrester_config)}</Text>
        </div>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "flex-end",
          gap: 8,
          padding: "10px 12px",
          borderTop: "1px solid color-mix(in srgb, var(--fquiz-theme-primary) 18%, var(--ant-color-border-secondary))",
        }}
      >
        <Button
          size="small"
          icon={<EyeOutlined />}
          onClick={(event) => {
            event.stopPropagation();
            onView(asset.id);
          }}
        >
          详情
        </Button>
        <Button
          danger
          size="small"
          disabled={!canManage || rowBusy}
          loading={deleteLoading}
          onClick={(event) => {
            event.stopPropagation();
            handleDelete();
          }}
        >
          删除
        </Button>
      </div>
    </div>
  );
}
