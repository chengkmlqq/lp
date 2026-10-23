"use client";

import { useEffect, useState } from "react";
import { Form, Spin, Alert, message } from "antd";
import { useQuery, useMutation } from "@tanstack/react-query";
import { useI18n } from "@/lib/i18n";
import { useAuth } from "@/components/auth-provider";
import { CreateAnalysisFormAdvanced } from "@/components/fault-analysis/create-analysis-form-advanced";
import { readApiError } from "@/lib/api";
import type { LineListResponse } from "@/types/auth";
import type { FaultAnalysisDetail } from "@/types/auth";
import type { CreateFaultAnalysisFormValues } from "./types";

interface CreateAnalysisFormTabProps {
  mode: "create" | "edit";
  /** 编辑模式对应的分析 id */
  editId?: string;
  /** 提交请求（新建或更新），由页面注入，负责构建 body / multipart */
  submitRequest: (values: CreateFaultAnalysisFormValues) => Promise<unknown>;
  onSuccess: () => void;
  onError: (error: unknown) => void;
  /** 提交状态变更回调（页面据此在提交中禁止关闭 Modal） */
  onSubmittingChange?: (submitting: boolean) => void;
  /** 编辑详情加载失败时回调（用于关闭对应 Modal） */
  onLoadError?: () => void;
  /** Modal 打开状态（弹窗重开时表单复位到第一步） */
  open?: boolean;
}

/** Modal 弹窗内自持表单实例、线路数据与提交状态的新建/编辑分步表单容器（LP-546）。 */
export function CreateAnalysisFormTab({
  mode,
  editId,
  submitRequest,
  onSuccess,
  onError,
  onSubmittingChange,
  onLoadError,
  open,
}: CreateAnalysisFormTabProps) {
  const { t } = useI18n();
  const { user, fetchWithAuth, hasPermission } = useAuth();
  const [form] = Form.useForm<CreateFaultAnalysisFormValues>();
  const [loading, setLoading] = useState(mode === "edit");
  const [loadError, setLoadError] = useState<string | null>(null);

  const canRead = hasPermission("line.read") || hasPermission("line.manage");

  // Tab 内容为静态快照，线路列表需在组件内部自取（与 AnalysisDetailView 自持数据一致）。
  const linesQuery = useQuery({
    queryKey: ["/api/v1/lines"],
    enabled: !!user && canRead,
    queryFn: async () => {
      const response = await fetchWithAuth("/api/v1/lines");
      if (!response.ok) {
        throw new Error(await readApiError(response));
      }
      return (await response.json()) as LineListResponse;
    },
  });

  const mutation = useMutation({
    mutationFn: submitRequest,
    onSuccess,
    onError,
  });

  // 新建模式：弹窗每次打开时清空上次填写的数据（任务名称/故障信息/已选文件等），
  // 避免上次内容残留到下一次新建。
  useEffect(() => {
    if (mode === "create" && open) {
      form.resetFields();
    }
  }, [open, mode, form]);

  // 新建模式：线路加载完成后默认选中第一条线路（参照防雷计算任务新建表单）。
  // 编辑模式由详情预填 line_id，不在此干预。open 变化触发重跑，配合上方 resetFields
  // 保证每次重开都回到「默认选第一条线路」的干净初始态。
  useEffect(() => {
    if (mode !== "create") {
      return;
    }
    const firstLine = linesQuery.data?.items[0];
    if (firstLine && !form.getFieldValue("line_id")) {
      form.setFieldsValue({ line_id: firstLine.id });
    }
  }, [form, linesQuery.data?.items, mode, open]);

  useEffect(() => {
    onSubmittingChange?.(mutation.isPending);
  }, [mutation.isPending, onSubmittingChange]);

  useEffect(() => {
    if (mode !== "edit" || !editId) {
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const response = await fetchWithAuth(`/api/v1/fault-analysis/${editId}`);
        if (!response.ok) {
          throw new Error(await readApiError(response));
        }
        const detail: FaultAnalysisDetail = await response.json();
        if (cancelled) {
          return;
        }
        form.setFieldsValue({
          title: detail.title ?? undefined,
          line_id: detail.line_id ?? "",
          station_name: detail.station ?? undefined,
          fault_time: detail.fault_time ?? undefined,
          fault_line_name: detail.line_name ?? undefined,
          fault_phase: detail.fault_phase ?? undefined,
          fault_duration: detail.fault_duration_ms ?? undefined,
          reclosure_status: detail.reclosure_status ?? undefined,
          fault_voltage: detail.fault_voltage_v ?? undefined,
          fault_current: detail.fault_current_a ?? undefined,
          max_zero_current: detail.max_zero_current_a ?? undefined,
          zero_compensation: detail.zero_compensation ?? undefined,
          fault_resistance: detail.fault_resistance_ohm ?? undefined,
          line_length: detail.line_length_km ?? undefined,
          line_angle: detail.line_angle_deg ?? undefined,
          line_impedance: detail.line_impedance_ohm ?? undefined,
          lightning_current: detail.lightning_current_ka?.toString() ?? undefined,
          lightning_longitude: detail.lightning_longitude ?? undefined,
          lightning_latitude: detail.lightning_latitude ?? undefined,
          wave_distance: detail.wave_distance_km ?? undefined,
          traveling_wave_distance: detail.traveling_wave_distance_km ?? undefined,
          optical_position: detail.optical_position ?? undefined,
          optical_device_location: detail.optical_device_location ?? undefined,
        });
      } catch (error) {
        if (cancelled) {
          return;
        }
        const messageText = error instanceof Error ? error.message : "加载故障分析详情失败";
        setLoadError(messageText);
        message.error(messageText);
        onLoadError?.();
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode, editId, form, fetchWithAuth, onLoadError]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Spin size="large" />
      </div>
    );
  }

  if (loadError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("加载失败")}
        description={loadError}
      />
    );
  }

  return (
    <div className="admin-fault-analysis-form-tab-pane">
      <CreateAnalysisFormAdvanced
        form={form}
        lines={linesQuery.data?.items ?? []}
        linesLoading={linesQuery.isLoading}
        submitText={mode === "edit" ? "保存修改" : "提交分析"}
        submitting={mutation.isPending}
        open={open}
        onSubmit={(values) => mutation.mutate(values)}
      />
    </div>
  );
}
