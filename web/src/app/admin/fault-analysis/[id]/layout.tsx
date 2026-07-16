"use client";

import { AuthProvider } from "@/components/auth-provider";
import type { ReactNode } from "react";

export default function FaultAnalysisDetailLayout({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      {children}
    </AuthProvider>
  );
}
