"use client";

import { App } from "antd";
import { useEffect, useRef } from "react";

type ToastFeedbackOptions = {
  errorTitle?: string;
  successTitle?: string;
  errorMessage: string;
  successMessage?: string;
  clearError?: () => void;
  clearSuccess?: () => void;
};

export function useToastFeedback({
  errorTitle = "操作失败",
  successTitle = "操作成功",
  errorMessage,
  successMessage,
  clearError,
  clearSuccess,
}: ToastFeedbackOptions) {
  const { message } = App.useApp();
  const lastErrorRef = useRef("");
  const lastSuccessRef = useRef("");

  useEffect(() => {
    if (!errorMessage) {
      lastErrorRef.current = "";
      return;
    }
    if (!errorMessage || errorMessage === lastErrorRef.current) {
      return;
    }
    lastErrorRef.current = errorMessage;
    message.error(`${errorTitle}：${errorMessage}`);
    clearError?.();
  }, [clearError, errorMessage, errorTitle, message]);

  useEffect(() => {
    if (!successMessage) {
      lastSuccessRef.current = "";
      return;
    }
    if (!successMessage || successMessage === lastSuccessRef.current) {
      return;
    }
    lastSuccessRef.current = successMessage;
    message.success(successTitle === "操作成功" ? successMessage : `${successTitle}：${successMessage}`);
    clearSuccess?.();
  }, [clearSuccess, message, successMessage, successTitle]);
}
