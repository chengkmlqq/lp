"use client";

import { useParams } from "next/navigation";

import { WindFarmCalcDetailView } from "@/components/wind-farm-calc-detail-view";

export default function WindFarmCalcDetailPage() {
  const params = useParams();
  const jobId = String(params?.id ?? "");
  return <WindFarmCalcDetailView jobId={jobId} />;
}
