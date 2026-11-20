"use client";

import { useParams } from "next/navigation";

import { WindDataPrepDetailView } from "@/components/wind-data-prep-detail-view";

export default function WindDataPrepDetailPage() {
  const params = useParams();
  const batchId = String(params?.id ?? "");
  return <WindDataPrepDetailView batchId={batchId} />;
}
