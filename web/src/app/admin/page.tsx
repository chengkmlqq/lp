"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function AdminEntryRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/overview");
  }, [router]);

  return null;
}
