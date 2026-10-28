"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { App, Button, Progress, Space, Spin, Typography } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  DownOutlined,
  UpOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { useI18n } from "@/lib/i18n";
import { getApiBaseUrl } from "@/lib/api";
import type { TempUploadResponse } from "@/types/auth";
import type { FaultAnalysisTempFile } from "./types";
import type { PreviewKind, ValidationResult } from "./file-prevalidation";
import { validateFile } from "./file-prevalidation";

interface TempFileUploadProps {
  value?: FaultAnalysisTempFile[];
  onChange?: (value: FaultAnalysisTempFile[]) => void;
  /** 是否允许多文件（自动归类）；false 时单选替换 */
  multiple?: boolean;
  accept?: string;
  buttonLabel?: string;
  /** 文件大小上限（MB），选择时前端预校验（后端 validate_upload 仍为最终底线） */
  maxSizeMb?: number;
  /** 文件内容级预校验类型，指定后上传完成会自动解析并展示数据预览（LP-420） */
  previewKind?: PreviewKind;
  /** PDF 提取完成后的回调，传入 (item, response)。 */
  onPdfExtracted?: (item: FaultAnalysisTempFile, response: { ok: boolean; extracted: Record<string, unknown>; missing: string[]; ocr_used: boolean; raw_text_preview?: string }) => void;
  /** 渲染在选择文件按钮右侧的附加内容（如「下载模板」按钮） */
  trailing?: ReactNode;
}

function uploadToTemp(
  file: File,
  token: string | null,
  onProgress: (percent: number) => void,
  t: (s: string) => string,
): Promise<TempUploadResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${getApiBaseUrl()}/api/v1/fault-analysis/upload-temp`);
    xhr.withCredentials = true;
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.upload.onprogress = (event: ProgressEvent<EventTarget>) => {
      if (!event.lengthComputable || event.total <= 0) {
        return;
      }
      const percent = Math.min(99, Math.max(0, Math.round((event.loaded / event.total) * 100)));
      onProgress(percent);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(100);
        try {
          resolve(JSON.parse(xhr.responseText) as TempUploadResponse);
        } catch {
          reject(new Error(t("上传成功但响应解析失败，请重新选择文件")));
        }
        return;
      }
      let text = `HTTP ${xhr.status}`;
      try {
        const parsed = JSON.parse(xhr.responseText) as { detail?: string };
        if (parsed?.detail?.trim()) text = parsed.detail;
      } catch {
        // 忽略非 JSON 响应
      }
      reject(new Error(text));
    };
    xhr.onerror = () => reject(new Error(t("网络异常，上传失败")));
    xhr.onabort = () => reject(new Error(t("上传已取消")));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

function newUid(file: File): string {
  return `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const WAVE_FIELD_LABELS: Record<string, string> = {
  station: "故障时刻",
  fault_time: "故障时刻",
  line_name: "线路名称",
  fault_phase: "故障相",
  duration_ms: "故障持续时间",
  reclosing: "重合闸情况",
  phase_voltage: "故障相电压",
  phase_current: "故障相电流",
  zero_sequence_current: "零序电流",
  zero_sequence_compensation_k: "零序补偿系数K",
  line_length_km: "线路总长度L",
  sensitive_angle_deg: "线路正序灵敏角",
  positive_sequence_impedance_ohm: "线路正序阻抗定值",
};

const LIGHTNING_FIELD_LABELS: Record<string, string> = {
  event_id: "事件编号",
  line_name: "线路名称",
  fault_time: "故障时刻",
  query_result: "是否存在落雷记录",
  location_time: "雷电定位时刻",
  current_ka: "雷电流幅值",
  nearest_tower: "最近杆塔",
  distance_to_line_km: "雷击点距线路距离",
  distance_to_nearest_tower_m: "距最近杆塔距离",
  line_side_distances_km: "线路两侧距离",
  recording_distance_km: "录波测距",
  recording_nearest_tower: "录波测距最近杆塔",
  traveling_wave_distance_km: "行波测距",
  traveling_wave_nearest_tower: "行波测距最近杆塔",
  remarks: "备注",
};

const LEDGER_FIELD_LABELS: Record<string, string> = {
  "线路名称": "线路名称",
  "电压等级": "电压等级",
  "塔号": "塔号",
  "地形": "地形",
  "地闪密度": "地闪密度",
  "海拔m": "海拔",
  "杆塔模型": "杆塔模型",
  "塔形": "塔形",
  "直线或耐张杆塔": "直线或耐张杆塔",
  "绝缘子串长度mm": "绝缘子串长度",
  "接地电阻": "接地电阻",
  "反击耐雷水平kA": "反击耐雷水平",
  "绕击耐雷水平kA": "绕击耐雷水平",
  "雷击风险等级": "雷击风险等级",
  "经度": "经度",
  "纬度": "纬度",
};

/** 预览区：根据 previewKind 渲染校验摘要（LP-420） */
function PreviewPanel({
  kind,
  result,
}: {
  kind: PreviewKind;
  result: ValidationResult;
}) {
  const { t } = useI18n();
  const [expanded, setExpanded] = useState(false);

  const renderSummary = () => {
    if (kind === "optical_data") {
      const fmt = result.extra?.format as string | undefined;
      const kindText = result.extra?.kind === "video" ? t("视频") : t("图片");
      return <span>{t("媒体文件")}（{kindText}{fmt ? ` · .${fmt}` : ""}），{t("无需结构校验")}</span>;
    }
    if (kind === "traveling_wave") {
      const count = Number(result.extra?.sampleCount ?? result.extra?.rowCount ?? 0) || 0;
      const phases = result.fields.phaseCount;
      return <span>{t("采样点")} {count}，{t("识别相")} {String(phases ?? "-")}</span>;
    }
    if (kind === "ledger_data") {
      const matched = Object.values(result.fields).filter(Boolean).length;
      return <span>{t("识别到台账列")} {matched}/16</span>;
    }
    if (kind === "wave_data" || kind === "lightning_data") {
      const matched = Object.values(result.fields).filter(Boolean).length;
      const total = kind === "wave_data" ? Object.keys(WAVE_FIELD_LABELS).length : Object.keys(LIGHTNING_FIELD_LABELS).length;
      return <span>{t("识别到字段")} {matched}/{total}</span>;
    }
    return null;
  };

  const renderDetail = () => {
    if (kind === "optical_data") {
      return null;
    }
    if (kind === "traveling_wave") {
      const count = Number(result.extra?.sampleCount ?? result.extra?.rowCount ?? 0) || 0;
      const phases = result.fields;
      return (
        <div className="space-y-1">
          <div>{t("采样点数量")}：{count}</div>
          <div className="flex gap-3">
            {["A", "B", "C"].map((p) => {
              const key = `hasPhase${p}`;
              const hit = phases[key];
              return (
                <span key={p} className={hit ? "" : "text-yellow-600"}>
                  {p} {hit ? "✓" : "✗"}
                </span>
              );
            })}
          </div>
        </div>
      );
    }
    if (kind === "ledger_data") {
      const missing = Object.keys(LEDGER_FIELD_LABELS).filter((key) => !result.fields[key]);
      const matchedCount = Object.keys(LEDGER_FIELD_LABELS).length - missing.length;
      return (
        <div className="space-y-1">
          <div>{t("识别到")} {matchedCount}/16 {t("列")}</div>
          {missing.length > 0 && (
            <div className="text-yellow-600">{t("缺失列")}：{missing.map((key) => t(LEDGER_FIELD_LABELS[key])).join("、")}</div>
          )}
        </div>
      );
    }
    const labels = kind === "wave_data" ? WAVE_FIELD_LABELS : LIGHTNING_FIELD_LABELS;
    const shownKeys = Object.keys(labels);
    const matchedCount = shownKeys.filter((key) => result.fields[key]).length;
    return (
      <div className="space-y-1">
        <div>
          {t("识别到字段")} {matchedCount}/{shownKeys.length}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1">
          {shownKeys.map((key) => {
            const hit = result.fields[key];
            return (
              <span key={key} className={hit ? "" : "text-yellow-600"}>
                {t(labels[key])} {hit ? "✓" : "✗"}
              </span>
            );
          })}
        </div>
      </div>
    );
  };

  if (kind === "optical_data") {
    return (
      <div className="mt-1 rounded bg-[var(--gray-2)] px-2 py-1 text-xs text-[var(--ant-color-text-secondary)]">
        {renderSummary()}
      </div>
    );
  }

  return (
    <div className="mt-1 rounded bg-[var(--gray-2)] px-2 py-1 text-xs text-[var(--ant-color-text-secondary)]">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center justify-between text-left"
        onClick={() => setExpanded((v) => !v)}
      >
        <span>{renderSummary()}</span>
        {expanded ? <UpOutlined /> : <DownOutlined />}
      </button>
      {expanded && <div className="mt-1">{renderDetail()}</div>}
      {result.errors.length > 0 && (
        <div className="mt-1 text-red-600">
          {result.errors.map((e, i) => (
            <div key={i}>{t("格式错误")}：{e}</div>
          ))}
        </div>
      )}
      {result.warnings.length > 0 && (
        <div className="mt-1 text-yellow-600">
          {result.warnings.map((w, i) => (
            <div key={i}>{t("提示")}：{w}</div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 选择文件后立即上传到临时目录并展示进度条（LP-369，交互与地闪密度导入一致）。 */
export function TempFileUpload({
  value = [],
  onChange,
  multiple = false,
  accept,
  buttonLabel,
  maxSizeMb,
  previewKind,
  onPdfExtracted,
  trailing,
}: TempFileUploadProps) {
  const { message: messageApi } = App.useApp();
  const { getAccessToken } = useAuth();
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  // 始终读取最新 value，避免并发上传时 onProgress 回调闭包读到陈旧值。
  const valueRef = useRef<FaultAnalysisTempFile[]>(value);
  const onChangeRef = useRef(onChange);
  const fileMapRef = useRef<Map<string, File>>(new Map());
  useEffect(() => {
    valueRef.current = value;
  }, [value]);
  useEffect(() => {
    onChangeRef.current = onChange;
  }, [onChange]);

  const patchValue = useCallback(
    (updater: (items: FaultAnalysisTempFile[]) => FaultAnalysisTempFile[]) => {
      const next = updater(valueRef.current);
      valueRef.current = next;
      onChangeRef.current?.(next);
    },
    [],
  );

  // 录波数据文件（pdf/txt/csv/json/xlsx）上传后调用后端提取 13 个故障字段并回填表单
  const callWaveExtract = useCallback(
    async (uid: string, file: File) => {
      const token = getAccessToken();
      const formData = new FormData();
      formData.append("file", file);
      try {
        const response = await fetch(`${getApiBaseUrl()}/api/v1/fault-analysis/extract-wave`, {
          method: "POST",
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
          credentials: "include",
        });
        const data = (await response.json()) as {
          ok?: boolean;
          extracted?: Record<string, unknown>;
          missing?: string[];
          ocr_used?: boolean;
          raw_text_preview?: string;
          detail?: string;
          error?: string;
        };
        patchValue((items) =>
          items.map((it) =>
            it.uid === uid
              ? ({
                  ...it,
                  pdfExtracting: false,
                  pdfExtractError: response.ok ? null : t("提取失败"),
                  pdfExtractResponse: response.ok
                    ? {
                        ok: Boolean(data.ok),
                        extracted: data.extracted ?? {},
                        missing: Array.isArray(data.missing) ? data.missing : [],
                        ocr_used: Boolean(data.ocr_used),
                        raw_text_preview: data.raw_text_preview,
                      }
                    : null,
                } satisfies FaultAnalysisTempFile)
              : it,
          ),
        );
        if (response.ok) {
          onPdfExtracted?.(
            { uid, name: file.name, status: "done", percent: 100, temp_file_id: "" },
            {
              ok: Boolean(data.ok),
              extracted: data.extracted ?? {},
              missing: Array.isArray(data.missing) ? data.missing : [],
              ocr_used: Boolean(data.ocr_used),
              raw_text_preview: data.raw_text_preview,
            },
          );
        }
      } catch (error) {
        patchValue((items) =>
          items.map((it) =>
            it.uid === uid
              ? ({
                  ...it,
                  pdfExtracting: false,
                  pdfExtractError: error instanceof Error ? error.message : t("提取失败"),
                  pdfExtractResponse: null,
                } satisfies FaultAnalysisTempFile)
              : it,
          ),
        );
      }
    },
    [getAccessToken, onPdfExtracted, patchValue],
  );

  const startValidate = useCallback(
    async (uid: string, file: File) => {
      if (!previewKind) {
        return;
      }
      patchValue((items) =>
        items.map((it) => (it.uid === uid ? { ...it, previewing: true } : it)),
      );
      try {
        const result = await validateFile(file, previewKind, t);
        patchValue((items) =>
          items.map((it) => (it.uid === uid ? { ...it, preview: result, previewing: false } : it)),
        );
      } catch (error) {
        const text = error instanceof Error ? error.message : t("校验失败");
        patchValue((items) =>
          items.map((it) =>
            it.uid === uid
              ? {
                  ...it,
                  previewing: false,
                  preview: {
                    ok: false,
                    errors: [`${t("内容校验失败")}：${text}`],
                    warnings: [],
                    fields: {},
                  },
                }
              : it,
          ),
        );
      }
    },
    [patchValue, previewKind],
  );

  const startUpload = useCallback(
    (file: File, item: FaultAnalysisTempFile) => {
      const token = getAccessToken();
      // 录波数据任意格式（pdf/txt/csv/json/xlsx）上传后都走后端提取并回填表单；其余文件做内容预校验
      const shouldExtractWave = previewKind === "wave_data";
      fileMapRef.current.set(item.uid, file);
      uploadToTemp(
        file,
        token,
        (percent) => {
          patchValue((items) =>
            items.map((it) => (it.uid === item.uid ? { ...it, percent } : it)),
          );
        },
        t,
      )
        .then((payload) => {
          patchValue((items) =>
            items.map((it) =>
              it.uid === item.uid
                ? { ...it, status: "done", percent: 100, temp_file_id: payload.temp_file_id }
                : it,
            ),
          );
          if (shouldExtractWave) {
            patchValue((items) =>
              items.map((it) =>
                it.uid === item.uid ? { ...it, pdfExtracting: true } : it,
              ),
            );
            callWaveExtract(item.uid, file);
            return;
          }
          startValidate(item.uid, file);
        })
        .catch((error) => {
          const text = error instanceof Error ? error.message : t("上传失败");
          patchValue((items) =>
            items.map((it) =>
              it.uid === item.uid ? { ...it, status: "error", error: text } : it,
            ),
          );
          messageApi.error(`${file.name} ${t("上传失败")}：${text}`);
        });
    },
    [getAccessToken, patchValue, startValidate, callWaveExtract, previewKind],
  );

  const buildPendingItem = useCallback(
    (file: File): FaultAnalysisTempFile | null => {
      if (maxSizeMb != null && file.size > maxSizeMb * 1024 * 1024) {
        messageApi.error(`${file.name} ${t("超过")} ${maxSizeMb}MB ${t("大小限制，请重新选择")}`);
        return null;
      }
      return {
        uid: newUid(file),
        name: file.name,
        status: "uploading",
        percent: 0,
      };
    },
    [maxSizeMb],
  );

  const handleSelectFiles = useCallback(
    (files: File[]) => {
      const pairs = files
        .map((file) => ({ file, item: buildPendingItem(file) }))
        .filter((entry): entry is { file: File; item: FaultAnalysisTempFile } => entry.item !== null);
      if (pairs.length === 0) {
        return;
      }
      const pendingItems = pairs.map((entry) => entry.item);
      if (multiple) {
        patchValue((items) => [...items, ...pendingItems]);
      } else {
        patchValue(() => [pendingItems[pendingItems.length - 1]]);
      }
      for (const { file, item } of pairs) {
        startUpload(file, item);
      }
    },
    [buildPendingItem, multiple, patchValue, startUpload],
  );

  const removeItem = useCallback(
    (uid: string) => {
      fileMapRef.current.delete(uid);
      patchValue((items) => items.filter((it) => it.uid !== uid));
    },
    [patchValue],
  );

  const triggerPicker = useCallback(() => {
    inputRef.current?.click();
  }, []);

  return (
    <div className="flex flex-col items-center gap-2">
      <input
        ref={inputRef}
        type="file"
        hidden
        multiple={multiple}
        accept={accept}
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          handleSelectFiles(files);
          event.target.value = "";
        }}
      />
      <div className="flex items-center gap-2">
        <Button size="small" icon={<UploadOutlined />} onClick={triggerPicker}>
          {buttonLabel ?? t("选择文件")}
        </Button>
        {trailing}
      </div>

      {value.length > 0 && (
        <div className="flex w-full flex-col gap-2">
          {value.map((item) => (
            <div
              key={item.uid}
              className="w-full rounded border border-[var(--gray-6)] bg-[var(--ant-color-bg-container)] px-2 py-1"
            >
              <Space size={8} className="w-full">
                <Typography.Text ellipsis style={{ maxWidth: 170 }}>
                  {item.name}
                </Typography.Text>
                {item.status === "uploading" && (
                  <Progress percent={item.percent} size="small" style={{ flex: 1 }} />
                )}
                {item.status === "done" && (
                  <Typography.Text type="success" style={{ fontSize: 12 }}>
                    <CheckCircleOutlined /> {t("上传完成")}
                  </Typography.Text>
                )}
                {item.status === "error" && (
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    <CloseCircleOutlined /> {item.error || t("上传失败")}
                  </Typography.Text>
                )}
                <Button type="text" size="small" danger onClick={() => removeItem(item.uid)}>
                  {t("移除")}
                </Button>
              </Space>
              {item.status === "done" && previewKind && (
                <div className="mt-1">
                  {item.previewing && !item.preview ? (
                    <div className="flex items-center gap-2 rounded bg-[var(--gray-2)] px-2 py-1 text-xs text-[var(--ant-color-text-secondary)]">
                      <Spin size="small" /> {t("正在解析文件内容...")}
                    </div>
                  ) : item.preview ? (
                    <PreviewPanel kind={previewKind} result={item.preview} />
                  ) : null}
                </div>
              )}
              {item.pdfExtracting && (
                <div className="mt-1 flex items-center gap-2 rounded bg-[var(--ant-color-primary-bg)] px-2 py-1 text-xs text-[var(--ant-color-primary)]">
                  <Spin size="small" /> {t("正在识别并回填故障字段...")}
                </div>
              )}
              {item.pdfExtractError && (
                <div className="mt-1 rounded bg-red-50 px-2 py-1 text-xs text-red-600">
                  {t("识别失败")}：{item.pdfExtractError}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
