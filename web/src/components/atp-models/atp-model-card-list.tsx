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
  onActivate: (id: string) => void;
  onDeactivate: (id: string) => void;
  onPublish: (id: string) => void;
  onUnpublish: (id: string) => void;
  onRecheckFormat: (id: string) => void;
  recheckBusy: boolean;
  activeBusy: boolean;
  publishBusy: boolean;
  dimensionLabelMap?: {
    voltage_level?: Map<string, string>;
    tower_type?: Map<string, string>;
    scene_type?: Map<string, string>;
    arrester_config?: Map<string, string>;
  };
}

export function AtpModelCardList({ assets, canManage, canTest, deleteLoading, onView, onEdit, onDelete, onTest, onActivate, onDeactivate, onPublish, onUnpublish, onRecheckFormat, recheckBusy, activeBusy, publishBusy, dimensionLabelMap }: AtpModelCardListProps) {

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
          onActivate={onActivate}
          onDeactivate={onDeactivate}
          onPublish={onPublish}
          onUnpublish={onUnpublish}
          onRecheckFormat={onRecheckFormat}
          recheckBusy={recheckBusy}
          activeBusy={activeBusy}
          publishBusy={publishBusy}
          dimensionLabelMap={dimensionLabelMap}
        />
      ))}
    </div>
  );
}
