"use client";

import { useCallback, useEffect, useRef } from "react";
import { Button, Progress, Space, Typography, message } from "antd";
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  UploadOutlined,
} from "@ant-design/icons";

import { useAuth } from "@/components/auth-provider";
import { getApiBaseUrl } from "@/lib/api";
import type { TempUploadResponse } from "@/types/auth";
import type { FaultAnalysisTempFile } from "./types";

interface TempFileUploadProps {
  value?: FaultAnalysisTempFile[];
  onChange?: (value: FaultAnalysisTempFile[]) => void;
  /** 是否允许多文件（自动归类）；false 时单选替换 */
  multiple?: boolean;
  accept?: string;
  buttonLabel?: string;
  /** 文件大小上限（MB），选择时前端预校验（后端 validate_upload 仍为最终底线） */
  maxSizeMb?: number;
}

function uploadToTemp(
  file: File,
  token: string | null,
  onProgress: (percent: number) => void,
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
          reject(new Error("上传成功但响应解析失败，请重新选择文件"));
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
    xhr.onerror = () => reject(new Error("网络异常，上传失败"));
    xhr.onabort = () => reject(new Error("上传已取消"));

    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

function newUid(file: File): string {
  return `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** 选择文件后立即上传到临时目录并展示进度条（LP-369，交互与地闪密度导入一致）。 */
export function TempFileUpload({
  value = [],
  onChange,
  multiple = false,
  accept,
  buttonLabel = "选择文件",
  maxSizeMb,
}: TempFileUploadProps) {
  const { getAccessToken } = useAuth();
  const inputRef = useRef<HTMLInputElement | null>(null);
  // 始终读取最新 value，避免并发上传时 onProgress 回调闭包读到陈旧值。
  const valueRef = useRef<FaultAnalysisTempFile[]>(value);
  const onChangeRef = useRef(onChange);
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

  const startUpload = useCallback(
    (file: File, item: FaultAnalysisTempFile) => {
      const token = getAccessToken();
      uploadToTemp(
        file,
        token,
        (percent) => {
          patchValue((items) =>
            items.map((it) => (it.uid === item.uid ? { ...it, percent } : it)),
          );
        },
      )
        .then((payload) => {
          patchValue((items) =>
            items.map((it) =>
              it.uid === item.uid
                ? { ...it, status: "done", percent: 100, temp_file_id: payload.temp_file_id }
                : it,
            ),
          );
        })
        .catch((error) => {
          const text = error instanceof Error ? error.message : "上传失败";
          patchValue((items) =>
            items.map((it) =>
              it.uid === item.uid ? { ...it, status: "error", error: text } : it,
            ),
          );
          message.error(`${file.name} 上传失败：${text}`);
        });
    },
    [getAccessToken, patchValue],
  );

  const buildPendingItem = useCallback(
    (file: File): FaultAnalysisTempFile | null => {
      if (maxSizeMb != null && file.size > maxSizeMb * 1024 * 1024) {
        message.error(`${file.name} 超过 ${maxSizeMb}MB 大小限制，请重新选择`);
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
      <Button size="small" icon={<UploadOutlined />} onClick={triggerPicker}>
        {buttonLabel}
      </Button>

      {value.length > 0 && (
        <div className="flex w-full flex-col gap-2">
          {value.map((item) => (
            <div
              key={item.uid}
              className="w-full rounded border border-gray-200 bg-white px-2 py-1"
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
                    <CheckCircleOutlined /> 上传完成
                  </Typography.Text>
                )}
                {item.status === "error" && (
                  <Typography.Text type="danger" style={{ fontSize: 12 }}>
                    <CloseCircleOutlined /> {item.error || "上传失败"}
                  </Typography.Text>
                )}
                <Button type="text" size="small" danger onClick={() => removeItem(item.uid)}>
                  移除
                </Button>
              </Space>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
