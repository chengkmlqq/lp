"use client";

import { App } from "antd";
import { useEffect, useRef } from "react";
import { formatErrorMessage, type ApiError } from "@/lib/api";
import { useI18n } from "@/lib/i18n";

type ToastFeedbackOptions = {
  errorTitle?: string;
  successTitle?: string;
  errorMessage: ApiError | string | null;
  successMessage?: string;
  clearError?: () => void;
  clearSuccess?: () => void;
};

export function useToastFeedback({
  errorTitle: errorTitleOpt,
  successTitle: successTitleOpt,
  errorMessage,
  successMessage,
  clearError,
  clearSuccess,
}: ToastFeedbackOptions) {
  const { message } = App.useApp();
  const { t } = useI18n();
  const errorTitle = errorTitleOpt ?? t("操作失败");
  const successTitle = successTitleOpt ?? t("操作成功");
  const lastErrorRef = useRef("");
  const lastSuccessRef = useRef("");

  useEffect(() => {
    const renderedError = formatErrorMessage(errorMessage);
    if (!renderedError) {
      lastErrorRef.current = "";
      return;
    }
    if (renderedError === lastErrorRef.current) {
      return;
    }
    lastErrorRef.current = renderedError;
    // 多行文本（上传预检报告等）读不完 3 秒：按长度延长停留时间，上限 9 秒
    const duration = renderedError.length > 120 ? 9 : renderedError.length > 40 ? 5 : 3;
    message.error(`${errorTitle}：${renderedError}`, duration);
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
    message.success(successTitleOpt == null ? successMessage : `${successTitle}：${successMessage}`);
    clearSuccess?.();
  }, [clearSuccess, message, successMessage, successTitle]);
}
