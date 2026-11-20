"use client";

import { useParams } from "next/navigation";

import { WindLightningDensityDetailView } from "@/components/wind-lightning-density-detail-view";

export default function WindLightningDensityDetailPage() {
  const params = useParams();
  const batchId = String(params?.id ?? "");
  return <WindLightningDensityDetailView batchId={batchId} />;
}
