"use client";

import { useParams } from "next/navigation";

import { WindTurbineCalcDetailView } from "@/components/wind-turbine-calc-detail-view";

export default function WindTurbineCalcDetailPage() {
  const params = useParams<{ id: string }>();
  return <WindTurbineCalcDetailView jobId={params.id} />;
}
