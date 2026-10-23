import { useI18n } from "@/lib/i18n";
import { Spin, Empty } from "antd";
import { AnalysisCard } from "./analysis-card";
import type { FaultAnalysis } from "./types";

interface AnalysisCardListProps {
  analyses: FaultAnalysis[];
  selectedId: string | null;
  loading?: boolean;
  onView?: (id: string) => void;
  onDelete?: (id: string) => void;
  onLog?: (id: string) => void;
}

export function AnalysisCardList({ analyses, selectedId, loading, onView, onDelete, onLog }: AnalysisCardListProps) {
  const { t } = useI18n();
  if (analyses.length === 0) {
    // 无数据可展示时（首载/空结果）：全区域居中加载指示；
    // 有数据时保留现有卡片，查询/刷新期间不清空已有卡片，仅叠加 loading 遮罩，接口返回后再更新
    if (loading) {
      return (
        <div className="flex w-full flex-1 items-center justify-center">
          <Spin />
        </div>
      );
    }
    return (
      <Empty
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={t("暂无故障分析记录")}
      />
    );
  }

  return (
    <Spin spinning={loading}>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        {analyses.map((analysis) => (
          <AnalysisCard
            key={analysis.id}
            analysis={analysis}
            selected={analysis.id === selectedId}
            onView={() => onView?.(analysis.id)}
            onDelete={() => onDelete?.(analysis.id)}
            onLog={() => onLog?.(analysis.id)}
          />
        ))}
      </div>
    </Spin>
  );
}
