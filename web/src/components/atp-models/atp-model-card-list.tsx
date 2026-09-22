import { AtpModelCard } from "./atp-model-card";
import type { AtpAssetSummary } from "@/types/auth";

interface AtpModelCardListProps {
  assets: AtpAssetSummary[];
  canManage: boolean;
  canTest: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onEdit: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  onTest: (asset: AtpAssetSummary) => void;
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

export function AtpModelCardList({ assets, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, dimensionLabelMap }: AtpModelCardListProps) {

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {assets.map((item) => (
        <AtpModelCard
          key={item.id}
          asset={item}
          canManage={canManage}
          canTest={canTest}
          deleteLoading={deleteLoading}
          onView={onView}
          onEdit={onEdit}
          onDelete={onDelete}
          onTest={onTest}
          dimensionLabelMap={dimensionLabelMap}
        />
      ))}
    </div>
  );
}
