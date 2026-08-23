import { Spin, Empty } from "antd";
import { AnalysisCard } from "./analysis-card";
import type { FaultAnalysis } from "./types";

interface AnalysisCardListProps {
  analyses: FaultAnalysis[];
  selectedId: string | null;
  loading?: boolean;
  onView?: (id: string) => void;
  onProcess?: (id: string) => void;
  onArtifacts?: (id: string) => void;
  onEdit?: (id: string) => void;
  onDelete?: (id: string) => void;
}

export function AnalysisCardList({ analyses, selectedId, loading, onView, onProcess, onArtifacts, onEdit, onDelete }: AnalysisCardListProps) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin size="large" />
      </div>
    );
  }

  if (analyses.length === 0) {
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description="暂无故障分析记录"
      />
    );
  }

  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      {analyses.map((analysis) => (
        <AnalysisCard
          key={analysis.id}
          analysis={analysis}
          selected={analysis.id === selectedId}
          onView={() => onView?.(analysis.id)}
          onProcess={() => onProcess?.(analysis.id)}
          onArtifacts={() => onArtifacts?.(analysis.id)}
          onEdit={() => onEdit?.(analysis.id)}
          onDelete={() => onDelete?.(analysis.id)}
        />
      ))}
    </div>
  );
}
