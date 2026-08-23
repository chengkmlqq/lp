import { Spin, Empty } from "antd";
import { AtpModelCard } from "./atp-model-card";
import type { AtpAssetSummary } from "@/types/auth";

interface AtpModelCardListProps {
  assets: AtpAssetSummary[];
  loading?: boolean;
  canManage: boolean;
  deleteLoading: boolean;
  onView: (id: string) => void;
  onDelete: (id: string) => void;
}

export function AtpModelCardList({ assets, loading, canManage, deleteLoading, onView, onDelete }: AtpModelCardListProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin size="large" />
      </div>
    );
  }

  if (assets.length === 0) {
    return (
      <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未找到符合筛选条件的 ATP 模型。" />
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {assets.map((item) => (
        <AtpModelCard
          key={item.id}
          asset={item}
          canManage={canManage}
          deleteLoading={deleteLoading}
          onView={onView}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
