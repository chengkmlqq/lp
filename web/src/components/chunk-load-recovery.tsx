"use client";

import { useEffect } from "react";

import {
  reloadOnceOnChunkError,
} from "@/lib/chunk-error";

export function ChunkLoadRecovery() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      const caught = event.error ?? event.message;
      if (reloadOnceOnChunkError(caught)) {
        event.preventDefault();
      }
    };

    const onUnhandledRejection = (event: PromiseRejectionEvent) => {
      if (reloadOnceOnChunkError(event.reason)) {
        event.preventDefault();
      }
    };

    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onUnhandledRejection);

    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onUnhandledRejection);
    };
  }, []);

  return null;
}
