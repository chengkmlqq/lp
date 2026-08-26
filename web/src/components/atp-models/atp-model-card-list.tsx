import { AtpModelCard } from "./atp-model-card";
import type { AtpAssetSummary } from "@/types/auth";

interface AtpModelCardListProps {
  assets: AtpAssetSummary[];
  canManage: boolean;
  deleteLoading: boolean;
  onView: (asset: AtpAssetSummary) => void;
  onDelete: (id: string) => void;
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

export function AtpModelCardList({ assets, canManage, deleteLoading, onView, onDelete, dimensionLabelMap }: AtpModelCardListProps) {

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {assets.map((item) => (
        <AtpModelCard
          key={item.id}
          asset={item}
          canManage={canManage}
          deleteLoading={deleteLoading}
          onView={onView}
          onDelete={onDelete}
          dimensionLabelMap={dimensionLabelMap}
        />
      ))}
    </div>
  );
}
