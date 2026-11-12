import { AtpModelCard } from "./atp-model-card";
import type { AtpAssetSummary } from "@/types/auth";

interface AtpModelCardListProps {
  assets: AtpAssetSummary[];
  canManage: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  publishBusy: boolean;
}

export function AtpModelCardList({ assets, canManage, deleteLoading, onView, onEdit, onDelete, onPublish, onUnpublish, publishBusy }: AtpModelCardListProps) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {assets.map((item) => (
        <AtpModelCard
          key={item.id}
          asset={item}
          canManage={canManage}
          deleteLoading={deleteLoading}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
          publishBusy={publishBusy}
        />
      ))}
    </div>
  );
}
